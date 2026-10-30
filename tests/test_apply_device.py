import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = """diff --git a/config.mk b/config.mk
index 3367afd..3e75765 100644
--- a/config.mk
+++ b/config.mk
@@ -1 +1 @@
-old
+new
"""


class ApplyDeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "android"
        self.device = self.source / "device/xiaomi/dash"
        self.device.mkdir(parents=True)
        (self.device / "config.mk").write_text("old\n")
        self.git("init", "-q")
        self.git("add", "config.mk")
        self.git("-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-qm", "baseline")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.bundle = self.root / "bundle"
        (self.bundle / "sources").mkdir(parents=True)
        (self.bundle / "patches").mkdir()
        (self.bundle / "sources/dependencies.json").write_text(json.dumps({"projects": [{"path": "device/xiaomi/dash", "commit": self.head}]}))
        (self.bundle / "patches/0001-infinity-dash.patch").write_text(PATCH)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.device), *args], text=True)

    def apply(self):
        return subprocess.run([sys.executable, str(ROOT / "tools/apply_device.py"), "--bundle-root", str(self.bundle), "--source-root", str(self.source)], capture_output=True, text=True)

    def test_applies_once_and_second_run_does_not_change_files(self):
        first = self.apply()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual((self.device / "config.mk").read_text(), "new\n")
        second = self.apply()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("already applied", second.stdout)

    def test_refuses_wrong_upstream_commit(self):
        path = self.bundle / "sources/dependencies.json"
        path.write_text(json.dumps({"projects": [{"path": "device/xiaomi/dash", "commit": "a" * 40}]}))
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upstream commit", result.stdout)
        self.assertEqual((self.device / "config.mk").read_text(), "old\n")

    def test_refuses_existing_uncommitted_change(self):
        (self.device / "config.mk").write_text("user edit\n")
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uncommitted", result.stdout)
        self.assertEqual((self.device / "config.mk").read_text(), "user edit\n")


if __name__ == "__main__":
    unittest.main()
