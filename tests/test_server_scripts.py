from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ServerPreparationTests(unittest.TestCase):
    def test_default_prints_plan_without_creating_source_root(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "android"
            result = subprocess.run([sys.executable, str(ROOT / "tools/prepare_server.py"), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("repo init", result.stdout)
            self.assertIn("repo sync", result.stdout)
            self.assertFalse(target.exists())

    def test_sync_refuses_nonempty_foreign_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            marker = target / "my-file.txt"
            marker.write_text("keep me")
            result = subprocess.run([sys.executable, str(ROOT / "tools/prepare_server.py"), str(target), "--sync"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nonempty", result.stdout)
            self.assertEqual(marker.read_text(), "keep me")


if __name__ == "__main__":
    unittest.main()
