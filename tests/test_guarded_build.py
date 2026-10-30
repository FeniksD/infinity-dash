from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GuardedBuildTests(unittest.TestCase):
    def exercise(self, build_status=0, post_fail=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name in ("source", "security", "bundle/scripts"):
            (root / name).mkdir(parents=True)
        (root / "sources.jsonl").write_text("{}\n")
        script = (ROOT / "security/build_guarded.sh").read_text().replace("/srv/infinity/infinity-dash-prep", str(root / "bundle"))
        (root / "security/build_guarded.sh").write_text(script)
        (root / "security/source_lock.py").write_text('''import os, pathlib, sys
p = pathlib.Path(os.environ["TRACE"])
old = p.read_text() if p.exists() else ""
with p.open("a") as f: f.write(sys.argv[1]+"\\n")
if sys.argv[1] == "verify" and "verify" in old and os.environ.get("POST_FAIL") == "1": sys.exit(11)
''')
        (root / "bundle/scripts/build-server.sh").write_text('printf "build:%s\\n" "$OUT_DIR" >> "$TRACE"\nexit "$BUILD_STATUS"\n')
        env = dict(os.environ, TRACE=str(root / "trace"), BUILD_STATUS=str(build_status), POST_FAIL=str(int(post_fail)))
        result = subprocess.run(["bash", str(root / "security/build_guarded.sh"), str(root / "source"), str(root / "sources.jsonl"), str(root / "out"), str(root / "logs")], env=env, capture_output=True, text=True)
        return result, (root / "trace").read_text().splitlines(), root

    @unittest.skipIf(os.geteuid() == 0, "requires a non-root builder")
    def test_success_orders_both_checks_and_passes_external_output(self):
        result, trace, root = self.exercise()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(trace, ["verify", "log-check", "build:" + str(root / "out"), "verify"])

    @unittest.skipIf(os.geteuid() == 0, "requires a non-root builder")
    def test_failed_build_still_checks_sources_and_preserves_exit_status(self):
        result, trace, root = self.exercise(build_status=7)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(trace[-1], "verify")

    @unittest.skipIf(os.geteuid() == 0, "requires a non-root builder")
    def test_failed_postcheck_rejects_successful_build(self):
        result, trace, root = self.exercise(post_fail=True)
        self.assertEqual(result.returncode, 11)
        self.assertEqual(trace[-1], "verify")

    def test_unsealed_tree_is_rejected_before_compilation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            manifest = root / "sources.jsonl"
            manifest.write_text("{}\n")
            result = subprocess.run(["bash", str(ROOT / "security/build_guarded.sh"), str(source), str(manifest), str(root / "out"), str(root / "logs")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("read-only", result.stdout + result.stderr)
            self.assertFalse((root / "out").exists())

    def test_output_inside_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            manifest = root / "sources.jsonl"
            manifest.write_text("{}\n")
            result = subprocess.run(["bash", str(ROOT / "security/build_guarded.sh"), str(source), str(manifest), str(source / "out"), str(root / "logs")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside", result.stdout + result.stderr)
