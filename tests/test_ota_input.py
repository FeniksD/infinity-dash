import importlib.util
from pathlib import Path
import tempfile
import unittest


DRIVER = Path(__file__).resolve().parents[1] / "signing" / "ota_input.py"


class OtaInputTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DRIVER.is_file(), "OTA input preparation helper is missing")
        spec = importlib.util.spec_from_file_location("ota_input", DRIVER)
        self.driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.driver)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scratch"
        (self.root / "META").mkdir(parents=True)
        (self.root / "IMAGES").mkdir()
        self.manifest = self.root / "META/ab_partitions.txt"
        self.manifest.write_text("boot\nsystem\nlk\n")
        self.manifest.chmod(0o444)
        self.original = Path(self.tmp.name) / "signed-image"
        self.original.write_bytes(b"unchanged signed image")
        for name in ("boot", "system", "lk"):
            (self.root / "IMAGES" / (name + ".img")).symlink_to(self.original)

    def test_readonly_metadata_becomes_writable_and_firmware_links_are_removed(self):
        self.driver.prepare_partial_ota_input(self.root, ["boot", "system"])
        self.assertEqual(self.manifest.read_text(), "boot\nsystem\n")
        self.assertTrue(self.manifest.stat().st_mode & 0o200)
        self.assertFalse((self.root / "IMAGES/lk.img").is_symlink())
        self.assertEqual(self.original.read_bytes(), b"unchanged signed image")

    def test_metadata_symlink_is_rejected_before_any_change(self):
        (self.root / "META/foreign").symlink_to(self.original)
        with self.assertRaises(ValueError):
            self.driver.prepare_partial_ota_input(self.root, ["boot", "system"])
        self.assertEqual(self.manifest.read_text(), "boot\nsystem\nlk\n")
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o444)

    def test_regular_excluded_image_is_not_deleted(self):
        image = self.root / "IMAGES/lk.img"
        image.unlink()
        image.write_bytes(b"not a disposable link")
        with self.assertRaises(ValueError):
            self.driver.prepare_partial_ota_input(self.root, ["boot", "system"])
        self.assertEqual(image.read_bytes(), b"not a disposable link")
        self.assertEqual(self.manifest.read_text(), "boot\nsystem\nlk\n")

    def test_invalid_partition_lists_are_rejected(self):
        for names in ([], ["boot", "boot"], ["../lk"], ["unknown"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.driver.prepare_partial_ota_input(self.root, names)


if __name__ == "__main__":
    unittest.main()
