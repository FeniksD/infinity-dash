import importlib.util
import io
from pathlib import Path
import tarfile
import unittest
import tempfile
import json
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("monitor", Path(__file__).resolve().parents[1] / "security/local_monitor.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def archive(name, data, mode=0o644):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = mode
        tar.addfile(info, io.BytesIO(data))
    return output.getvalue()


class LocalMonitorTests(unittest.TestCase):
    def test_matching_server_bytes_pass(self):
        expected = monitor.members(archive("infinity-dash-prep/file", b"trusted"), "infinity-dash-prep/")
        actual = monitor.members(archive("./file", b"trusted"))
        self.assertEqual(expected, actual)

    def test_changed_or_extra_file_is_detected(self):
        expected = monitor.members(archive("file", b"trusted"))
        self.assertNotEqual(expected, monitor.members(archive("file", b"tampered")))
        self.assertNotEqual(expected, monitor.members(archive("extra", b"trusted")))

    def test_parent_path_is_rejected(self):
        with self.assertRaises(ValueError):
            monitor.members(archive("../file", b"trusted"))

    def test_sealed_expected_permissions_preserve_detection_of_write_access(self):
        expected = monitor.members(archive("infinity-dash-prep/file", b"trusted", 0o664), "infinity-dash-prep/", sealed=True)
        safe = monitor.members(archive("file", b"trusted", 0o644))
        writable = monitor.members(archive("file", b"trusted", 0o664))
        self.assertEqual(expected, safe)
        self.assertNotEqual(expected, writable)

    def test_existing_alarm_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"latched": True, "ok": False}))
            self.assertTrue(monitor.saved_latch(state))
            state.write_text("broken")
            self.assertTrue(monitor.saved_latch(state))

    def test_missing_initial_input_reports_alarm_and_attempts_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(host="root@example", archive=Path(tmp)/"missing", baseline=Path(tmp)/"baseline", state=Path(tmp)/"state.json")
            with patch.object(monitor, "ssh", return_value=b"") as ssh:
                status = monitor.cycle(args, False)
            self.assertFalse(status["ok"])
            self.assertTrue(status["latched"])
            self.assertTrue(status["build_pause_confirmed"])
            self.assertIn("pkill", ssh.call_args.args[1])
            self.assertTrue(args.state.is_file())
