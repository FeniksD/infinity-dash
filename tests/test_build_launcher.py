import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuildLauncherTests(unittest.TestCase):
    @unittest.skipIf(os.geteuid() == 0, "non-root rejection test")
    def test_non_root_cannot_launch_the_privileged_network_setup(self):
        result = subprocess.run(["bash", str(ROOT / "security/launch_build.sh")], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("root launcher", result.stdout + result.stderr)
