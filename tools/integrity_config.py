#!/usr/bin/env python3
"""Inspect or explicitly restore the owner's verified Integrity configuration."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "device/xiaomi/dash/configs/integrity/policy.json"
MAX_KEYBOX_BYTES = 128 * 1024
SETTING_KEYS = (
    "spoof_trickystore_target", "spoof_trickystore_patch",
    "spoof_pif_config", "spoof_gameprops_config", "spoof_trickystore_keybox",
)


class ApplySettingsError(RuntimeError):
    def __init__(self, restored, backup):
        self.restored = restored
        self.backup = backup
        super().__init__("Apply failed; " + ("previous settings restored" if restored else "rollback incomplete"))


def openssl(*args, data=None):
    result = subprocess.run(["openssl", *args], input=data, capture_output=True,
                            timeout=20, env={**os.environ, "LC_ALL": "C"})
    if result.returncode:
        # OpenSSL errors can include input-derived content. Never print key material.
        raise ValueError("Key/certificate validation failed")
    return result.stdout


def pem_text(value):
    # Keybox XML often indents every PEM line. Preserve its payload while
    # removing XML formatting that OpenSSL's PEM reader does not accept.
    return "\n".join(line.strip() for line in (value or "").splitlines() if line.strip()) + "\n"


def validate_keybox(data, policy, revocations, *, now=None, enforce_pin=True):
    if not data or len(data) > MAX_KEYBOX_BYTES:
        raise ValueError("Invalid keybox size")
    digest = hashlib.sha256(data).hexdigest()
    approved = digest == policy["approved_keybox_sha256"]
    if enforce_pin and not approved:
        raise ValueError("Keybox SHA256 changed; inspect and review the new file first")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("DTD and entities are forbidden")
    if not isinstance(revocations, dict) or not isinstance(revocations.get("entries"), dict):
        raise ValueError("Invalid revocation response")
    revoked = {key.lower().lstrip("0") for key in revocations["entries"]}
    timestamp = int(time.time() if now is None else now)
    try:
        root = ET.fromstring(data)
        boxes = root.findall("Keybox")
        if root.tag != "AndroidAttestation" or not 1 <= len(boxes) <= 4:
            raise ValueError("Invalid keybox structure")
        if int(root.findtext("NumberOfKeyboxes", "0")) != len(boxes):
            raise ValueError("Keybox count mismatch")
        results = []
        with tempfile.TemporaryDirectory(prefix="integrity-validation-") as directory:
            folder = Path(directory)
            for box in boxes:
                keys = box.findall("Key")
                if not 1 <= len(keys) <= 4:
                    raise ValueError("Invalid key count")
                for key in keys:
                    algorithm = key.get("algorithm")
                    if algorithm not in ("ecdsa", "rsa"):
                        raise ValueError("Unsupported key algorithm")
                    private = folder / "private.pem"
                    private.write_text(pem_text(key.findtext("PrivateKey", "")))
                    private.chmod(0o600)
                    openssl("ec" if algorithm == "ecdsa" else "rsa", "-in", str(private), "-check", "-noout")
                    chain = key.findall("./CertificateChain/Certificate")
                    if not 2 <= len(chain) <= 8:
                        raise ValueError("Invalid certificate chain length")
                    if int(key.findtext("./CertificateChain/NumberOfCertificates", "0")) != len(chain):
                        raise ValueError("Certificate count mismatch")
                    files = []
                    for index, cert in enumerate(chain):
                        path = folder / (str(index) + ".pem")
                        path.write_text(pem_text(cert.text))
                        files.append(path)
                        serial = openssl("x509", "-in", str(path), "-noout", "-serial").decode().strip().split("=", 1)[1]
                        if serial.lower().lstrip("0") in revoked:
                            raise ValueError("Certificate is present in Google's revocation list")
                    root_der = openssl("x509", "-in", str(files[-1]), "-outform", "DER")
                    if hashlib.sha256(root_der).hexdigest() not in policy["trusted_root_sha256"]:
                        raise ValueError("Unapproved attestation root")
                    private_pub = openssl("pkey", "-in", str(private), "-pubout", "-outform", "DER")
                    leaf_pub = openssl("pkey", "-pubin", "-outform", "DER", data=openssl("x509", "-in", str(files[0]), "-pubkey", "-noout"))
                    if private_pub != leaf_pub:
                        raise ValueError("Private key does not match leaf certificate")
                    intermediates = folder / "intermediates.pem"
                    intermediates.write_text("\n".join(p.read_text() for p in files[1:-1]))
                    args = ["verify", "-no-CAfile", "-no-CApath", "-no-CAstore", "-check_ss_sig", "-attime", str(timestamp), "-trusted", str(files[-1])]
                    if len(files) > 2:
                        args += ["-untrusted", str(intermediates)]
                    openssl(*args, str(files[0]))
                    expiry = openssl("x509", "-in", str(files[0]), "-noout", "-enddate").decode().strip().split("=", 1)[1]
                    results.append({"algorithm": algorithm, "certificate_count": len(chain), "leaf_expires": expiry})
        return {"sha256": digest, "approved": approved, "key_count": len(results), "chains": results}
    except (ET.ParseError, TypeError, IndexError):
        raise ValueError("Malformed keybox") from None


def apply_settings(adb, values, backup_dir):
    if set(values) != set(SETTING_KEYS):
        raise ValueError("Refusing to modify unrelated settings")
    backup_dir = Path(backup_dir).resolve()
    if any((parent / ".git").exists() for parent in (backup_dir, *backup_dir.parents)):
        raise ValueError("Private backups must stay outside Git checkouts")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir.chmod(0o700)
    previous = {key: adb.get(key) for key in SETTING_KEYS}
    backup = backup_dir / ("settings-before-" + str(time.time_ns()) + ".json")
    with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
        json.dump(previous, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    try:
        for key in SETTING_KEYS:
            adb.put(key, values[key])
        if any(adb.get(key) != values[key] for key in SETTING_KEYS):
            raise RuntimeError("Settings readback mismatch")
    except Exception:
        try:
            adb.put("spoof_trickystore_keybox", None)
            for key in SETTING_KEYS:
                adb.put(key, previous[key])
            if any(adb.get(key) != previous[key] for key in SETTING_KEYS):
                raise RuntimeError("Rollback readback mismatch")
        except Exception:
            raise ApplySettingsError(False, backup) from None
        raise ApplySettingsError(True, backup) from None
    return backup


class Adb:
    def __init__(self, serial):
        self.prefix = ["adb", "-s", serial, "shell", "-T", "sh"]

    def shell(self, command):
        result = subprocess.run(self.prefix, input=command + "\n", text=True,
                                capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError("ADB operation failed; private input suppressed")
        return result.stdout.strip()

    def get(self, key):
        value = self.shell("settings get secure " + shlex.quote(key))
        return None if value == "null" else value

    def put(self, key, value):
        if key not in SETTING_KEYS:
            raise ValueError("Unapproved setting")
        command = "settings delete secure " + key if value is None else "settings put secure " + key + " " + shlex.quote(value)
        self.shell(command)


def fetch(url, limit):
    if urlparse(url).scheme != "https":
        raise ValueError("HTTPS is required")
    with urlopen(Request(url, headers={"User-Agent": "infinity-dash-integrity", "Cache-Control": "no-cache"}), timeout=25) as response:
        if urlparse(response.geturl()).scheme != "https" or urlparse(response.geturl()).netloc != urlparse(url).netloc:
            raise ValueError("Unexpected download redirect")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Response exceeds size limit")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "apply"])
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--keybox-file", type=Path)
    parser.add_argument("--serial")
    parser.add_argument("--factory-product")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    if args.keybox_file:
        with args.keybox_file.open("rb") as source:
            data = source.read(MAX_KEYBOX_BYTES + 1)
    else:
        data = fetch(policy["keybox_url"], MAX_KEYBOX_BYTES)
    revocations = json.loads(fetch("https://android.googleapis.com/attestation/status?encrypted=0", 8 * 1024 * 1024))
    report = validate_keybox(data, policy, revocations, enforce_pin=args.action == "apply")
    print(json.dumps(report, indent=2), flush=True)
    if args.action == "inspect":
        return 0 if report["approved"] else 2
    if not args.serial or args.factory_product != policy["factory_attestation_product"]:
        raise ValueError("Apply requires a serial and the independently verified factory product")
    adb = Adb(args.serial)
    if adb.shell("getprop ro.product.device") != policy["device"] or adb.shell("getprop ro.product.model") != policy["model"]:
        raise ValueError("Unexpected device")
    if adb.shell("getprop ro.build.version.sdk") != str(policy["tested_sdk"]):
        raise ValueError("Untested Android SDK; review required")
    configs = {}
    for name in ("pif", "gameprops"):
        raw = args.policy.with_name(name + ".json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != policy[name + "_sha256"]:
            raise ValueError("Public configuration changed; review required")
        configs[name] = json.loads(raw)
    private = Path.home() / ".local/share/infinity-dash/integrity"
    if private.resolve().is_relative_to(ROOT):
        raise ValueError("Private backups must stay outside the repository")
    values = {
        "spoof_trickystore_target": "\n".join(policy["targets"]),
        "spoof_trickystore_patch": None,
        "spoof_pif_config": json.dumps(configs["pif"], separators=(",", ":")),
        "spoof_gameprops_config": json.dumps(configs["gameprops"], separators=(",", ":")),
        "spoof_trickystore_keybox": base64.b64encode(data).decode(),
    }
    apply_settings(adb, values, private)
    for package in ("com.google.android.gms", "com.android.vending"):
        adb.shell("am force-stop " + package)
    print("Configuration applied and read back. Check fresh Integrity and Play Store status.")
    return 0


def cli():
    try:
        return main()
    except ApplySettingsError as error:
        # Both fields are generated locally; no raw transport error or settings.
        print("ERROR:", str(error) + ". Private settings backup:", error.backup)
        if not error.restored:
            print("Reconnect ADB and restore the private backup before retrying.")
        return 1
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        # Do not echo input data, failed commands, XML or private keys.
        print("ERROR:", type(error).__name__, "— operation not completed")
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
