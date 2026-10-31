import importlib.util
from pathlib import Path
import tempfile
import subprocess
import unittest
import zipfile


DRIVER = Path(__file__).resolve().parents[1] / "signing" / "release_driver.py"


class ReleaseDriverTests(unittest.TestCase):
    def test_git_excludes_private_key_formats_but_keeps_public_certificates(self):
        root = DRIVER.parents[1]
        for name, ignored in (
            ("signing/accidental/avb.pem", True),
            ("signing/accidental/platform.pk8", True),
            ("signing/accidental/backup.passphrase", True),
            ("signing/public/platform.x509.pem", False),
        ):
            with self.subTest(name=name):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "-q", name], cwd=root,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                self.assertEqual(result.returncode, 0 if ignored else 1)

    def setUp(self):
        spec = importlib.util.spec_from_file_location("release_driver", DRIVER)
        self.driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.driver)

    def test_manifest_paths_stay_in_their_partition(self):
        root = Path("/stage")
        self.assertEqual(
            self.driver.manifest_source(root, "SYSTEM", "framework/a.jar"),
            root / "SYSTEM/framework/a.jar",
        )
        self.assertEqual(
            self.driver.manifest_source(root, "SYSTEM_EXT", "system_ext/app/a.apk"),
            root / "SYSTEM_EXT/app/a.apk",
        )
        for name in ("../secret", "/home/owner/keys", "system_ext/../../keys"):
            with self.assertRaises(ValueError):
                self.driver.manifest_source(root, "SYSTEM", name)

    def test_asset_replacement_keeps_resources_and_removes_stale_signatures(self):
        with tempfile.TemporaryDirectory() as tmp:
            before, after = Path(tmp) / "before.apk", Path(tmp) / "after.apk"
            with zipfile.ZipFile(before, "w") as z:
                z.writestr("AndroidManifest.xml", b"manifest")
                z.writestr("resources.arsc", b"resources")
                z.writestr("assets/build_manifest.pb", b"old digest list")
                z.writestr("META-INF/TESTKEY.RSA", b"stale signature")
                z.writestr("META-INF/MANIFEST.MF", b"stale hashes")
            self.driver.replace_manifest_asset(before, after, b"new digest list")
            with zipfile.ZipFile(after) as z:
                self.assertEqual(z.read("assets/build_manifest.pb"), b"new digest list")
                self.assertEqual(z.read("resources.arsc"), b"resources")
                self.assertEqual(z.read("AndroidManifest.xml"), b"manifest")
                self.assertFalse(any(n.startswith("META-INF/") for n in z.namelist()))

    def test_temp_cleanup_does_not_follow_symlinks_or_remove_outside_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scratch"
            root.mkdir()
            outside = Path(tmp) / "keys"
            outside.mkdir()
            secret = outside / "platform.pk8"
            secret.write_bytes(b"private")
            link = root / "link"
            link.symlink_to(outside, target_is_directory=True)
            self.driver.clean_temps([link], root)
            self.assertFalse(link.is_symlink())
            self.assertEqual(secret.read_bytes(), b"private")
            with self.assertRaises(ValueError):
                self.driver.clean_temps([secret], root)
            with self.assertRaises(ValueError):
                self.driver.clean_temps([root], root)


if __name__ == "__main__":
    unittest.main()
