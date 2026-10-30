from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PARSER = (ROOT / "tests/fixtures/infinity-lunch.sh").read_text()
STUBS = r'''
function _lunch_meat() {
    echo "parsed-product=<$1> release=<$2> variant=<$3>"
    case "$3" in eng|user|userdebug) ;; *) return 29 ;; esac
    export TARGET_PRODUCT="$1" TARGET_RELEASE="$2" TARGET_BUILD_VARIANT="$3"
}
function _lunch_store_leftovers() { :; }
function m() { echo "compile-started"; }
'''


class BuildWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        (self.bundle / "scripts").mkdir(parents=True)
        (self.bundle / "tools").mkdir()
        shutil.copy2(ROOT / "scripts/build-server.sh", self.bundle / "scripts/build-server.sh")
        # Source validation has its own integration tests; isolate shell orchestration here.
        (self.bundle / "tools/preflight.py").write_text("pass\n")
        self.source = self.root / "android"
        (self.source / "build/make/core").mkdir(parents=True)
        (self.source / "build/make/core/build_id.mk").write_text("BUILD_ID := CP2A.000000.001\n")
        (self.source / "build/envsetup.sh").write_text(PARSER + STUBS)

    def run_wrapper(self):
        return subprocess.run(
            ["bash", str(self.bundle / "scripts/build-server.sh"), str(self.source)],
            capture_output=True, text=True,
        )

    def test_wrapper_supplies_valid_tuple_to_actual_upstream_lunch_parser(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("parsed-product=<infinity_dash> release=<cp2a> variant=<userdebug>", result.stdout)
        self.assertIn("compile-started", result.stdout)

    def test_setup_failure_is_logged_and_exit_status_preserved(self):
        (self.source / "build/envsetup.sh").write_text('echo "setup-failure"\nreturn 17\n')
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        logs = list((self.source / ".infinity-dash-logs").glob("build-*.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("setup-failure", logs[0].read_text())

    def test_unexpected_release_is_rejected_before_compile(self):
        (self.source / "build/make/core/build_id.mk").write_text("BUILD_ID := XX2A.000000.001\n")
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected lunch configuration", result.stdout + result.stderr)
        self.assertNotIn("compile-started", result.stdout)

    def test_common_choice_matches_actual_upstream_parser(self):
        choice = (ROOT / "device/xiaomi/dash/AndroidProducts.mk").read_text().split("COMMON_LUNCH_CHOICES :=", 1)[1]
        choice = choice.replace("\\", "").strip()
        script = PARSER + STUBS + '\nlunch "$1"\n'
        result = subprocess.run(["bash", "-e", "-c", script, "test", choice], cwd=self.source, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("variant=<userdebug>", result.stdout)


if __name__ == "__main__":
    unittest.main()
