import hashlib
import base64
import importlib.util
import json
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools/integrity_config.py"


class IntegrityConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        def run(*args):
            return subprocess.check_output(["openssl", *args], cwd=cls.folder, stderr=subprocess.DEVNULL)
        run("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", "root.key")
        run("req", "-new", "-x509", "-key", "root.key", "-subj", "/CN=TestRoot", "-days", "2", "-out", "root.pem", "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        run("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", "leaf.key")
        run("req", "-new", "-key", "leaf.key", "-subj", "/CN=TestAttestation", "-out", "leaf.csr")
        run("x509", "-req", "-in", "leaf.csr", "-CA", "root.pem", "-CAkey", "root.key", "-CAcreateserial", "-days", "1", "-out", "leaf.pem")
        cls.root_hash = hashlib.sha256(run("x509", "-in", "root.pem", "-outform", "DER")).hexdigest()
        cls.serial = run("x509", "-in", "leaf.pem", "-noout", "-serial").decode().strip().split("=")[1].lower().lstrip("0")
        cls.xml = ("<AndroidAttestation><NumberOfKeyboxes>1</NumberOfKeyboxes><Keybox DeviceID='test'><Key algorithm='ecdsa'><PrivateKey>" + (cls.folder / "leaf.key").read_text() + "</PrivateKey><CertificateChain><NumberOfCertificates>2</NumberOfCertificates><Certificate>" + (cls.folder / "leaf.pem").read_text() + "</Certificate><Certificate>" + (cls.folder / "root.pem").read_text() + "</Certificate></CertificateChain></Key></Keybox></AndroidAttestation>").encode()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.assertTrue(MODULE.is_file(), "Integrity restore implementation is missing")
        spec = importlib.util.spec_from_file_location("integrity_config", MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.policy = {"approved_keybox_sha256": hashlib.sha256(self.xml).hexdigest(), "trusted_root_sha256": [self.root_hash]}

    def test_valid_chain_and_matching_private_key_pass_without_exposing_key(self):
        result = self.module.validate_keybox(self.xml, self.policy, {"entries": {}})
        self.assertTrue(result["approved"])
        self.assertEqual(result["key_count"], 1)
        self.assertNotIn("PRIVATE KEY", json.dumps(result))

    def test_changed_hash_is_rejected_but_can_be_inspected_without_applying(self):
        self.policy["approved_keybox_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.module.validate_keybox(self.xml, self.policy, {"entries": {}})
        self.assertFalse(self.module.validate_keybox(self.xml, self.policy, {"entries": {}}, enforce_pin=False)["approved"])

    def test_indented_pem_in_real_world_xml_is_accepted(self):
        root = ET.fromstring(self.xml)
        for node in [root.find("./Keybox/Key/PrivateKey"), *root.findall("./Keybox/Key/CertificateChain/Certificate")]:
            node.text = "\n" + "\n".join("                " + line for line in node.text.splitlines()) + "\n"
        data = ET.tostring(root)
        self.policy["approved_keybox_sha256"] = hashlib.sha256(data).hexdigest()
        self.assertTrue(self.module.validate_keybox(data, self.policy, {"entries": {}})["approved"])

    def test_revoked_certificate_is_rejected(self):
        with self.assertRaises(ValueError):
            self.module.validate_keybox(self.xml, self.policy, {"entries": {self.serial: {"status": "REVOKED"}}})

    def test_untrusted_root_is_rejected(self):
        self.policy["trusted_root_sha256"] = ["0" * 64]
        with self.assertRaises(ValueError):
            self.module.validate_keybox(self.xml, self.policy, {"entries": {}})

    def test_expired_chain_is_rejected(self):
        with self.assertRaises(ValueError):
            self.module.validate_keybox(self.xml, self.policy, {"entries": {}}, now=4070908800)

    def test_invalid_certificate_signature_is_rejected(self):
        pem = (self.folder / "leaf.pem").read_text()
        der = bytearray(base64.b64decode("".join(pem.splitlines()[1:-1])))
        der[-1] ^= 1
        encoded = base64.b64encode(der).decode()
        broken = "-----BEGIN CERTIFICATE-----\n" + "\n".join(encoded[i:i+64] for i in range(0, len(encoded), 64)) + "\n-----END CERTIFICATE-----\n"
        data = self.xml.replace(pem.encode(), broken.encode())
        self.policy["approved_keybox_sha256"] = hashlib.sha256(data).hexdigest()
        with self.assertRaises(ValueError):
            self.module.validate_keybox(data, self.policy, {"entries": {}})

    def test_mismatched_private_key_is_rejected(self):
        xml = self.xml.replace((self.folder / "leaf.key").read_bytes(), (self.folder / "root.key").read_bytes())
        self.policy["approved_keybox_sha256"] = hashlib.sha256(xml).hexdigest()
        with self.assertRaises(ValueError):
            self.module.validate_keybox(xml, self.policy, {"entries": {}})

    def test_external_entities_and_oversized_input_are_rejected(self):
        for data in (b'<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + self.xml, b"x" * (self.module.MAX_KEYBOX_BYTES + 1)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                self.module.validate_keybox(data, self.policy, {"entries": {}}, enforce_pin=False)

    def test_apply_backs_up_privately_and_rolls_back_a_failed_write(self):
        class FakeAdb:
            def __init__(self):
                self.values = {k: "old-" + k for k in self_keys}
                self.original = dict(self.values)
                self.failed = False
            def get(self, key):
                return self.values[key]
            def put(self, key, value):
                if key == "spoof_pif_config" and value == "new" and not self.failed:
                    self.failed = True
                    raise RuntimeError("simulated write failure")
                self.values[key] = value
        self_keys = self.module.SETTING_KEYS
        adb = FakeAdb()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self.module.apply_settings(adb, {k: "new" for k in self_keys}, Path(tmp))
            self.assertEqual(adb.values, adb.original)
            backups = list(Path(tmp).glob("settings-before-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)

    def test_apply_refuses_unrelated_settings_before_reading_device(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            self.module.apply_settings(None, {"screen_brightness": "0"}, Path(tmp))

    def test_failed_rollback_retains_private_backup_and_explicit_status(self):
        class DisconnectedAdb:
            def get(self, key):
                return "old-private-value"
            def put(self, key, value):
                raise RuntimeError("private raw transport error")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(self.module.ApplySettingsError) as raised:
                self.module.apply_settings(DisconnectedAdb(), {k: "new" for k in self.module.SETTING_KEYS}, Path(tmp))
            self.assertFalse(raised.exception.restored)
            self.assertTrue(raised.exception.backup.is_file())
            self.assertEqual(json.loads(raised.exception.backup.read_text())[self.module.SETTING_KEYS[0]], "old-private-value")

    def test_cli_reports_safe_rollback_status_and_backup_location(self):
        for restored, expected in ((False, "rollback incomplete"), (True, "previous settings restored")):
            with self.subTest(restored=restored):
                output = io.StringIO()
                error = self.module.ApplySettingsError(restored, Path("/private/settings-before-123.json"))
                with patch.object(self.module, "main", side_effect=error), redirect_stdout(output):
                    self.assertEqual(self.module.cli(), 1)
                self.assertIn(expected, output.getvalue())
                self.assertIn("/private/settings-before-123.json", output.getvalue())
                self.assertNotIn("private raw transport error", output.getvalue())

    def test_private_backup_cannot_be_written_inside_a_git_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            with self.assertRaises(ValueError):
                self.module.apply_settings(None, {k: "new" for k in self.module.SETTING_KEYS}, root / "private")
            self.assertFalse((root / "private").exists())

    def test_device_bundle_contains_public_configuration_only(self):
        folder = ROOT / "device/xiaomi/dash/configs/integrity"
        for name in ("policy.json", "pif.json", "gameprops.json"):
            content = (folder / name).read_text()
            json.loads(content)
            self.assertNotIn("PRIVATE KEY", content)
            self.assertNotIn("<Keybox", content)
            self.assertIn("configs/integrity/" + name, (ROOT / "device/xiaomi/dash/infinity_dash.mk").read_text())

    def test_git_ignores_private_xml_and_settings_backups(self):
        for name in ("accidental/keybox.xml", "accidental/settings-before-1.json"):
            result = subprocess.run(["git", "check-ignore", "--no-index", "-q", name], cwd=ROOT)
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
