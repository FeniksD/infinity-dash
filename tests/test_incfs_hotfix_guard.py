"""Exercise the real boot guard without a phone or production shared library."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "hotfixes/incfs-lifetime/post-fs-data.sh"
BASE_SHA = "03fdc0558874b1396558aa2a424d322895837bb8458b469d44a6a77c5d8b4df7"
FIXED_SHA = "50dd2f5660ebe8a82c2c2ab99431961ad5b4f70c84f732ff7ef838034486b1cf"


class IncfsHotfixGuardTests(unittest.TestCase):
    def test_only_matching_device_base_and_payload_are_mounted(self):
        for case in ("matching", "different_base", "corrupt_payload", "missing_base",
                     "missing_payload", "other_device", "other_sdk"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / "system/lib64").mkdir(parents=True)
                (root / "bin").mkdir()
                baseline = root / "original.so"
                payload = root / "system/lib64/service.incremental.so"
                if case != "missing_base":
                    baseline.write_bytes(b"different" if case == "different_base" else b"original")
                if case != "missing_payload":
                    payload.write_bytes(b"corrupt" if case == "corrupt_payload" else b"fixed")
                getprop = root / "bin/getprop"
                getprop.write_text(
                    '#!/bin/sh\ncase "$1" in\n'
                    'ro.product.device) echo ' + ("other" if case == "other_device" else "dash") + ';;\n'
                    'ro.build.version.sdk) echo ' + ("36" if case == "other_sdk" else "37") + ';;\nesac\n'
                )
                getprop.chmod(0o755)
                source = GUARD.read_text()
                self.assertEqual(source.count(BASE_SHA), 1)
                self.assertEqual(source.count(FIXED_SHA), 1)
                source = source.replace(BASE_SHA, hashlib.sha256(b"original").hexdigest())
                source = source.replace(FIXED_SHA, hashlib.sha256(b"fixed").hexdigest())
                source = source.replace("/system/lib64/service.incremental.so 2>", str(baseline) + " 2>")
                script = root / "post-fs-data.sh"
                script.write_text(source)
                result = subprocess.run(
                    ["sh", str(script)], capture_output=True, text=True, timeout=5,
                    env={**os.environ, "PATH": str(root / "bin") + ":" + os.environ["PATH"]},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                disabled = case != "matching"
                self.assertEqual((root / "skip_mount").exists(), disabled)
                self.assertEqual((root / "disable").exists(), disabled)
                self.assertEqual((root / "disabled-reason.txt").exists(), disabled)
                # Guard decisions must not modify the base or supplied library.
                if baseline.exists():
                    self.assertEqual(baseline.read_bytes(), b"different" if case == "different_base" else b"original")
                if payload.exists():
                    self.assertEqual(payload.read_bytes(), b"corrupt" if case == "corrupt_payload" else b"fixed")
