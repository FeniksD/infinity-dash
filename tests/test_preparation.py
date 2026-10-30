"""Offline checks for the build handoff, not a substitute for an Android build."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class PreparationTests(unittest.TestCase):
    def run_check(self, root=ROOT):
        return subprocess.run(
            [sys.executable, str(ROOT / "tools/preflight.py"), "--bundle-root", str(root)],
            capture_output=True, text=True,
        )

    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for folder in ("sources", "local_manifests", "device", "patches", "source_overrides"):
            source = ROOT / folder
            if source.exists():
                shutil.copytree(source, root / folder)
        return root

    def test_offline_preflight_accepts_complete_bundle(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("offline preparation passed", result.stdout)

    def test_rejects_duplicate_dependency_paths(self):
        root = self.fixture()
        path = root / "sources/dependencies.json"
        self.assertTrue(path.exists(), "dependency lock is missing")
        data = json.loads(path.read_text())
        data["projects"].append(data["projects"][0])
        path.write_text(json.dumps(data))
        result = self.run_check(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate dependency path", result.stdout)

    def test_rejects_unpinned_manifest_revision(self):
        root = self.fixture()
        path = root / "local_manifests/dash.xml"
        self.assertTrue(path.exists(), "local manifest is missing")
        tree = ET.parse(path)
        tree.getroot().find("project").set("revision", "cnb")
        tree.write(path)
        result = self.run_check(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not pinned", result.stdout)

    def test_rejects_private_signing_key_dependency(self):
        root = self.fixture()
        path = root / "sources/dependencies.json"
        self.assertTrue(path.exists(), "dependency lock is missing")
        data = json.loads(path.read_text())
        data["projects"].append({"path": "vendor/evolution-priv/keys", "repository": "private/keys", "commit": "a" * 40})
        path.write_text(json.dumps(data))
        result = self.run_check(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private signing", result.stdout)

    def test_device_is_ported_and_preserves_hardware_identity(self):
        path = ROOT / "device/xiaomi/dash/infinity_dash.mk"
        self.assertTrue(path.exists(), "Infinity product is not prepared")
        product = path.read_text()
        self.assertIn("PRODUCT_NAME := infinity_dash", product)
        self.assertIn("PRODUCT_MODEL := 2602BPC18G", product)
        self.assertIn("vendor/infinity/config/common_full_phone.mk", product)
        self.assertNotIn("evolution.mk", product)
        device = (ROOT / "device/xiaomi/dash/device.mk").read_text()
        self.assertNotIn("WITH_GMS", device)
        self.assertIn("FILESYSTEM_TYPE_vendor=erofs", device)
        board = (ROOT / "device/xiaomi/dash/BoardConfig.mk").read_text()
        self.assertNotIn("vendor/lineage/config/", board)
        self.assertIn("BOARD_BOOTIMAGE_PARTITION_SIZE := 67108864", board)
        self.assertIn("BOARD_SUPER_PARTITION_SIZE := 9126805504", board)

    def test_source_check_rejects_missing_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(ROOT / "tools/preflight.py"), "--source-root", folder], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing checkout", result.stdout)


if __name__ == "__main__":
    unittest.main()
