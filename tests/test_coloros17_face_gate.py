import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ports/coloros17/face"


class FaceOperationGateTests(unittest.TestCase):
    def test_callback_lifetime_contract(self):
        self.assertIsNotNone(shutil.which("javac"), "JDK required for face gate tests")
        self.assertIsNotNone(shutil.which("java"), "JRE required for face gate tests")
        with tempfile.TemporaryDirectory() as folder:
            compile_result = subprocess.run(
                ["javac", "-Xlint:all", "-d", folder,
                 str(SOURCE / "FaceOperationGate.java"),
                 str(SOURCE / "FaceOperationGateTest.java")],
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(compile_result.returncode, 0,
                             compile_result.stdout + compile_result.stderr)
            result = subprocess.run(
                ["java", "-cp", folder,
                 "com.android.server.biometrics.sensors.face.dash.FaceOperationGateTest"],
                text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
