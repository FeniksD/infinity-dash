import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
import subprocess
import tracemalloc

spec = importlib.util.spec_from_file_location("guard", Path(__file__).resolve().parents[1] / "security/guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class SecurityGuardTests(unittest.TestCase):
    def test_changed_deleted_and_mode_changed_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "protected"
            p.write_text("trusted")
            expected = {str(p): guard.file_record(p)}
            self.assertEqual(guard.changed_files(expected), [])
            p.write_text("changed")
            self.assertTrue(guard.changed_files(expected))
            p.write_text("trusted")
            p.chmod(0o777)
            self.assertTrue(guard.changed_files(expected))
            p.unlink()
            self.assertTrue(guard.changed_files(expected))

    def test_only_expected_ip_key_and_method_are_accepted(self):
        good = "Accepted publickey for root from 1.2.3.4 port 345 ssh2: ED25519 SHA256:trusted"
        self.assertEqual(guard.unexpected_logins([good], "1.2.3.4", "SHA256:trusted"), [])
        for bad in (good.replace("1.2.3.4", "5.6.7.8"), good.replace("root", "attacker"), good.replace("publickey", "password"), good.replace("SHA256:trusted", "SHA256:other")):
            self.assertTrue(guard.unexpected_logins([bad], "1.2.3.4", "SHA256:trusted"))

    def test_port_parser_covers_ipv6_and_interface_scope(self):
        raw = 'tcp LISTEN 0 4096 [::]:22 [::]:*\nudp UNCONN 0 0 127.0.0.53%lo:53 0.0.0.0:*\n'
        self.assertEqual(guard.listeners(raw), ["tcp :: 22", "udp 127.0.0.53 53"])
        with self.assertRaises(ValueError):
            guard.listeners("unexpected output")

    def test_replacing_file_with_symlink_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.write_text("trusted")
            p = Path(tmp) / "protected"
            p.write_text("trusted")
            expected = {str(p): guard.file_record(p)}
            p.unlink()
            p.symlink_to(target)
            self.assertTrue(guard.changed_files(expected))

    def test_new_dropin_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "known.conf").write_text("safe")
            expected = {str(folder): guard.tree_members(folder)}
            (folder / "00-override.conf").write_text("unsafe")
            self.assertTrue(guard.changed_trees(expected))

    def test_fingerprint_prefix_is_not_enough(self):
        message = "Accepted publickey for root from 1.2.3.4 port 345 ssh2: ED25519 SHA256:trustedEVIL"
        self.assertTrue(guard.unexpected_logins([message], "1.2.3.4", "SHA256:trusted"))

    def test_verbose_key_offer_is_not_a_completed_login(self):
        message = "Accepted key ED25519 SHA256:trusted found at /root/.ssh/authorized_keys:1"
        self.assertEqual(guard.unexpected_logins([message], "1.2.3.4", "SHA256:trusted"), [])

    def test_pause_does_not_depend_on_mutable_passwd(self):
        with patch("pwd.getpwnam", side_effect=KeyError), patch.object(guard.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as command:
            guard.freeze_build_user()
        self.assertEqual(command.call_args.args[0], ["pkill", "-STOP", "-u", "1000"])

    def test_pause_failure_records_unhealthy_status_and_preserves_first_incident(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            with patch.object(guard.subprocess, "run", return_value=subprocess.CompletedProcess([], 2)):
                status = guard.finish(state, ["first incident"])
                first = (state / "incident.json").read_bytes()
                guard.finish(state, ["second incident"])
            self.assertFalse(status["ok"])
            self.assertFalse(status["build_pause_confirmed"])
            self.assertEqual(first, (state / "incident.json").read_bytes())
            self.assertFalse(json.loads((state / "status.json").read_text())["ok"])

    def test_large_inventory_hash_uses_bounded_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "large"
            with p.open("wb") as output:
                for _ in range(16):
                    output.write(b"x" * 1024 * 1024)
            tracemalloc.start()
            try:
                guard.file_record(p)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertLess(peak, 4 * 1024 * 1024)

    def test_new_listener_or_service_is_reported(self):
        baseline = {"files": {}, "allowed_ip": "1.2.3.4", "fingerprint": "SHA256:x", "listeners": ["tcp 0.0.0.0 22"], "services": ["ssh.service"]}
        errors = guard.inspect(baseline, [], 'tcp LISTEN 0 1 0.0.0.0:5900 0.0.0.0:*\n', "ssh.service loaded active running SSH\nvnc.service loaded active running VNC\n")
        self.assertTrue(any("5900" in x for x in errors))
        self.assertTrue(any("vnc.service" in x for x in errors))
