import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_server


class LockedRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.bundle = self.root / "bundle"
        self.device = self.source / "device/xiaomi/dash"
        self.platform = self.source / "platform/example"
        manifest = ET.Element("manifest")
        for path in (self.device, self.platform):
            path.mkdir(parents=True)
            self.git(path, "init", "-q")
            (path / "tracked.txt").write_text("base")
            if path == self.device:
                for name in ("AndroidProducts.mk", "BoardConfig.mk", "device.mk"):
                    (path / name).write_text("old")
            self.git(path, "add", ".")
            self.commit(path)
            ET.SubElement(manifest, "project", path=str(path.relative_to(self.source)), revision=self.git(path, "rev-parse", "HEAD").strip())
        self.manifest = self.root / "manifest.xml"
        ET.ElementTree(manifest).write(self.manifest)
        expected = self.bundle / "device/xiaomi/dash"
        expected.mkdir(parents=True)
        for name in ("AndroidProducts.mk", "BoardConfig.mk", "device.mk", "infinity_dash.mk"):
            (expected / name).write_text("new " + name)

    def git(self, path, *args):
        return subprocess.check_output(["git", "-C", str(path), *args], text=True)

    def commit(self, path):
        self.git(path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "test")

    def errors(self):
        return prepare_server.validate_locked_checkouts(self.bundle, self.source, self.manifest)

    def test_clean_locked_tree_is_accepted(self):
        self.assertEqual(self.errors(), [])

    def test_nonhardware_wrong_head_is_rejected(self):
        (self.platform / "tracked.txt").write_text("changed")
        self.git(self.platform, "add", ".")
        self.commit(self.platform)
        self.assertTrue(any("commit" in e and "platform/example" in e for e in self.errors()))

    def test_nonhardware_dirty_file_is_rejected(self):
        (self.platform / "tracked.txt").write_text("changed")
        self.assertTrue(any("dirty" in e and "platform/example" in e for e in self.errors()))

    def test_exact_reviewed_device_patch_is_accepted_on_retry(self):
        for file in (self.bundle / "device/xiaomi/dash").iterdir():
            shutil.copy2(file, self.device / file.name)
        self.assertEqual(self.errors(), [])

    def test_extra_device_change_is_rejected(self):
        for file in (self.bundle / "device/xiaomi/dash").iterdir():
            shutil.copy2(file, self.device / file.name)
        (self.device / "tracked.txt").write_text("other edit")
        self.assertTrue(any("dirty" in e for e in self.errors()))

    def test_staged_device_patch_requires_review(self):
        for file in (self.bundle / "device/xiaomi/dash").iterdir():
            shutil.copy2(file, self.device / file.name)
        self.git(self.device, "add", "AndroidProducts.mk")
        self.assertTrue(any("dirty" in e for e in self.errors()))
