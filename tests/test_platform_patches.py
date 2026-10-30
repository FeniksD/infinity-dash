import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from apply_platform import apply_platform
from preflight import validate_checkouts

PATCH = """diff --git a/config.mk b/config.mk
--- a/config.mk
+++ b/config.mk
@@ -1 +1 @@
-old
+new
"""


class PlatformPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "android"
        self.checkout = self.source / "vendor/infinity"
        self.checkout.mkdir(parents=True)
        for name in ("config.mk", "other.mk"):
            (self.checkout / name).write_text("old\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
        self.bundle = self.root / "bundle"
        (self.bundle / "sources").mkdir(parents=True)
        (self.bundle / "sources/dependencies.json").write_text('{"projects": []}')
        (self.bundle / "patches").mkdir()
        (self.bundle / "patches/test.patch").write_text(PATCH)
        (self.bundle / "expected.mk").write_text("new\n")
        (self.bundle / "sources/platform-patches.json").write_text(json.dumps({"patches":[{"path":"vendor/infinity", "commit":self.git("rev-parse", "HEAD").strip(), "patch":"patches/test.patch", "files":{"config.mk":"expected.mk"}}]}))

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.checkout), *args], text=True)

    def test_platform_patch_applies_and_is_idempotent(self):
        apply_platform(self.bundle, self.source)
        self.assertEqual((self.checkout / "config.mk").read_text(), "new\n")
        apply_platform(self.bundle, self.source)

    def test_patched_checkout_with_other_edit_is_rejected(self):
        apply_platform(self.bundle, self.source)
        (self.checkout / "other.mk").write_text("unexpected\n")
        with self.assertRaises(ValueError):
            apply_platform(self.bundle, self.source)

    def test_fresh_checkout_is_valid_before_patch_and_prepared_check_is_strict(self):
        self.assertEqual(validate_checkouts(self.bundle, self.source), [])
        self.assertTrue(validate_checkouts(self.bundle, self.source, prepared=True))
        apply_platform(self.bundle, self.source)
        self.assertEqual(validate_checkouts(self.bundle, self.source, prepared=True), [])

    def test_unlisted_patch_target_is_rejected_without_modification(self):
        extra = PATCH.replace('config.mk', 'other.mk')
        (self.bundle / 'patches/test.patch').write_text(PATCH + extra)
        with self.assertRaises(ValueError):
            apply_platform(self.bundle, self.source)
        self.assertEqual((self.checkout / 'config.mk').read_text(), 'old\n')
        self.assertEqual((self.checkout / 'other.mk').read_text(), 'old\n')

    def test_executable_mode_change_is_not_an_exact_patch(self):
        apply_platform(self.bundle, self.source)
        (self.checkout / 'config.mk').chmod(0o755)
        self.assertTrue(validate_checkouts(self.bundle, self.source, prepared=True))
        with self.assertRaises(ValueError):
            apply_platform(self.bundle, self.source)
