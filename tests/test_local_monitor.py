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
    def inputs(self, tmp):
        root=Path(tmp)
        args=SimpleNamespace(host='root@example',archive=root/'prep.tar',baseline=root/'baseline.json',state=root/'state.json')
        args.archive.write_bytes(archive('infinity-dash-prep/file',b'trusted'))
        args.baseline.write_bytes(b'baseline')
        replies=[archive('./file',b'trusted'),b'baseline',json.dumps({'ok':True,'time':monitor.time.time()}).encode()]
        return args,replies

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

    def test_brief_network_loss_retries_complete_verification_without_pausing(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,replies=self.inputs(tmp)
            failure=monitor.subprocess.CalledProcessError(255,['ssh'],stderr=b'Network is unreachable')
            with patch.object(monitor,'ssh',side_effect=[failure]+replies) as ssh, patch.object(monitor.time,'sleep') as sleep:
                status=monitor.cycle(args,False)
            self.assertTrue(status['ok'])
            self.assertFalse(status['latched'])
            self.assertTrue(sleep.called)
            self.assertFalse(any('pkill' in call.args[1] for call in ssh.call_args_list))

    def test_brief_server_keepalive_timeout_retries_without_pausing(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,replies=self.inputs(tmp)
            failure=monitor.subprocess.CalledProcessError(255,['ssh'],stderr=b'Timeout, server 94.237.81.2 not responding.')
            with patch.object(monitor,'ssh',side_effect=[failure]+replies),patch.object(monitor.time,'sleep'):
                status=monitor.cycle(args,False)
            self.assertTrue(status['ok'])
            self.assertFalse(status['latched'])

    def test_persistent_network_loss_pauses_and_requires_manual_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,replies=self.inputs(tmp)
            def offline(host,command):
                if 'pkill' in command: return b''
                raise monitor.subprocess.CalledProcessError(255,['ssh'],stderr=b'Connection timed out')
            with patch.object(monitor,'ssh',side_effect=offline),patch.object(monitor.time,'sleep') as sleep:
                failed=monitor.cycle(args,False)
            self.assertTrue(failed['latched'])
            self.assertTrue(failed['build_pause_confirmed'])
            self.assertLessEqual(sum(call.args[0] for call in sleep.call_args_list),20)
            self.assertLessEqual(sleep.call_count,3)
            with patch.object(monitor,'ssh',side_effect=replies+[b'']):
                still_stopped=monitor.cycle(args,True)
            self.assertFalse(still_stopped['ok'])
            self.assertTrue(still_stopped['build_pause_confirmed'])
            self.assertEqual(failed['errors'],still_stopped['errors'])

    def test_tampering_is_not_treated_as_a_transient_network_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,replies=self.inputs(tmp)
            with patch.object(monitor,'ssh',side_effect=[archive('./file',b'tampered')]+replies[1:]+[b'']),patch.object(monitor.time,'sleep') as sleep:
                status=monitor.cycle(args,False)
            self.assertTrue(status['latched'])
            sleep.assert_not_called()

    def test_host_key_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,_=self.inputs(tmp)
            error=monitor.subprocess.CalledProcessError(255,['ssh'],stderr=b'Host key verification failed.')
            with patch.object(monitor,'ssh',side_effect=[error,b'']),patch.object(monitor.time,'sleep') as sleep:
                status=monitor.cycle(args,False)
            self.assertTrue(status['latched'])
            sleep.assert_not_called()

    def test_retry_that_observes_tampering_stops_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,_=self.inputs(tmp)
            failure=monitor.subprocess.CalledProcessError(255,['ssh'],stderr=b'Network is unreachable')
            with patch.object(monitor,'ssh',side_effect=[failure,archive('./file',b'tampered'),b'']),patch.object(monitor.time,'sleep') as sleep:
                status=monitor.cycle(args,False)
            self.assertTrue(status['build_pause_confirmed'])
            self.assertIn('remote preparation differs from local archive',status['errors'])
            self.assertEqual(sleep.call_count,1)

    def test_baseline_and_guard_failures_are_not_retried(self):
        for fault in ('baseline','stale_guard'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                args,replies=self.inputs(tmp)
                if fault=='baseline': replies=[replies[0],b'changed']
                else: replies[2]=json.dumps({'ok':True,'time':0}).encode()
                with patch.object(monitor,'ssh',side_effect=replies+[b'']),patch.object(monitor.time,'sleep') as sleep:
                    status=monitor.cycle(args,False)
                self.assertTrue(status['build_pause_confirmed'])
                sleep.assert_not_called()

    def test_invalid_state_shapes_remain_latched_and_attempt_pause(self):
        for content in ('[]','null','false','0','"text"'):
            with self.subTest(content=content),tempfile.TemporaryDirectory() as tmp:
                args,replies=self.inputs(tmp)
                args.state.write_text(content)
                self.assertTrue(monitor.saved_latch(args.state))
                with patch.object(monitor,'ssh',side_effect=replies+[b'']):
                    status=monitor.cycle(args,True)
                self.assertTrue(status['latched'])
                self.assertTrue(status['build_pause_confirmed'])
                self.assertIn('previous incident details unavailable',status['errors'])
