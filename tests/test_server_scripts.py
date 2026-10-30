from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil

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

    def test_locked_plan_uses_exact_resolved_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "android"
            result = subprocess.run([sys.executable, str(ROOT / "tools/prepare_server.py"), str(target), "--locked"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("--standalone-manifest", result.stdout)
            self.assertIn("source-manifest.xml", result.stdout)
            self.assertNotIn("Install pinned local_manifests", result.stdout)
            self.assertFalse(target.exists())

    def test_locked_plan_rejects_moving_project_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / "bundle"
            bundle.mkdir()
            for name in ("sources", "local_manifests", "device", "build", "patches", "source_overrides"):
                shutil.copytree(ROOT / name, bundle / name)
            manifest = bundle / "build/source-manifest.xml"
            text = manifest.read_text()
            import xml.etree.ElementTree as ET
            tree = ET.fromstring(text)
            tree.find("project").set("revision", "main")
            manifest.write_text(ET.tostring(tree, encoding="unicode"))
            result = subprocess.run([sys.executable, str(ROOT / "tools/prepare_server.py"), str(Path(folder)/"android"), "--bundle-root", str(bundle), "--locked"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not pinned", result.stdout)

    def test_locked_plan_rejects_relative_remote(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / "bundle"
            bundle.mkdir()
            for name in ("sources", "local_manifests", "device", "build", "patches", "source_overrides"):
                shutil.copytree(ROOT / name, bundle / name)
            import xml.etree.ElementTree as ET
            path = bundle / "build/source-manifest.xml"
            tree = ET.parse(path)
            tree.getroot().find("remote").set("fetch", "..")
            tree.write(path)
            result = subprocess.run([sys.executable, str(ROOT / "tools/prepare_server.py"), str(Path(folder)/"android"), "--bundle-root", str(bundle), "--locked"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("absolute", result.stdout)


if __name__ == "__main__":
    unittest.main()
