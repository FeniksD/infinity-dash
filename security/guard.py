#!/usr/bin/env python3
"""Root-run build-host tripwire. Detects changes; cannot attest a compromised kernel."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

# Pinned at deployment, independent of mutable /etc/passwd.
BUILD_UID = 1000


def run(*args):
    return subprocess.check_output(args, text=True, timeout=45)


def file_record(path):
    p = Path(path)
    st = p.lstat()
    kind = "link" if stat.S_ISLNK(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else "other"
    digest = None
    if kind == "file":
        with p.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {"sha256": digest, "mode": st.st_mode & 0o7777, "uid": st.st_uid, "kind": kind, "link": os.readlink(p) if kind == "link" else None}


def tree_members(path):
    root = Path(path)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def changed_trees(expected):
    return ["protected directory membership changed: " + path for path, members in expected.items() if tree_members(path) != members]


def changed_files(expected):
    errors = []
    for path, record in expected.items():
        try:
            if file_record(path) != record:
                errors.append("protected file changed: " + path)
        except OSError as exc:
            errors.append("protected file unavailable: " + path + ": " + str(exc))
    return errors


def unexpected_logins(messages, allowed_ip, fingerprint, additional_logins=()):
    # Additional identities must not widen the original root login policy.
    rules = []
    for rule in additional_logins:
        if rule["user"] == "root":
            raise ValueError("additional login rules cannot override root policy")
        rules.append((rule["user"], rule["fingerprint"],
                      [ipaddress.ip_network(cidr) for cidr in rule["source_cidrs"]]))
    errors = []
    for message in messages:
        if not message.startswith("Accepted ") or message.startswith("Accepted key "):
            continue
        match = re.search(r"Accepted (\S+) for (\S+) from (\S+) ", message)
        accepted = bool(match and match.group(1, 2, 3) == ("publickey", "root", allowed_ip)
                        and fingerprint in message.split())
        if match and match.group(1) == "publickey":
            source = ipaddress.ip_address(match.group(3))
            accepted = accepted or any(
                match.group(2) == user and key in message.split()
                and any(source in network for network in networks)
                for user, key, networks in rules)
        if not accepted:
            errors.append("unexpected login: " + message)
    return errors


def listeners(raw):
    result = set()
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 6:
            raise ValueError("unrecognized ss output")
        protocol, address = fields[0], fields[4]
        host, port = address.rsplit(":", 1)
        host = host.strip("[]").split("%", 1)[0]
        if host != "*":
            ipaddress.ip_address(host)
        result.add(protocol + " " + host + " " + port)
    return sorted(result)


def services(raw):
    return sorted(x.split()[0] for x in raw.splitlines() if x.split() and x.split()[0] != "infinity-guard.service")


def inspect(baseline, journal, socket_output, service_output):
    errors = changed_files(baseline["files"])
    errors += changed_trees(baseline.get("trees", {}))
    errors += unexpected_logins(journal, baseline["allowed_ip"], baseline["fingerprint"], baseline.get("additional_logins", ()))
    extra_ports = set(listeners(socket_output)) - set(baseline["listeners"])
    errors += ["unexpected listener: " + x for x in sorted(extra_ports)]
    extra_services = set(services(service_output)) - set(baseline["services"])
    errors += ["unexpected service: " + x for x in sorted(extra_services)]
    return errors


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def freeze_build_user():
    result = subprocess.run(["pkill", "-STOP", "-u", str(BUILD_UID)], check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError("pkill failed with status " + str(result.returncode))


def finish(state_dir, errors):
    incident = state_dir / "incident.json"
    status = {"time": int(time.time()), "ok": not errors and not incident.exists(), "errors": list(errors)}
    if errors and not incident.exists():
        write_json(incident, status)
    if incident.exists():
        status["ok"] = False
        status["incident_latched"] = True
        try:
            freeze_build_user()
            status["build_pause_confirmed"] = True
        except Exception as exc:
            status["build_pause_confirmed"] = False
            status["errors"].append("pause failed: " + str(exc))
    write_json(state_dir / "status.json", status)
    print(json.dumps(status))
    return status


def check(baseline_path, state_dir):
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    baseline = json.loads(baseline_path.read_text())
    cursor_path = state_dir / "cursor"
    command = ["journalctl", "-u", "ssh", "-o", "json", "--no-pager"]
    if cursor_path.exists():
        command += ["--after-cursor", cursor_path.read_text().strip()]
    else:
        command += ["--since", "@" + str(baseline["since"])]
    records = [json.loads(x) for x in run(*command).splitlines() if x.strip()]
    errors = inspect(baseline, [x.get("MESSAGE", "") for x in records], run("ss", "-H", "-lntup"), run("systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"))
    if "source_lock" in baseline:
        from source_lock import log_errors, mount_errors, output_errors
        source = baseline["source_lock"]
        root = Path(source["root"])
        errors += mount_errors(root, Path("/proc/self/mountinfo").read_text())
        if "output" in source:
            errors += output_errors(root, Path(source["output"]))
        if "logs" in source:
            errors += log_errors(root, Path(source["logs"]))
    if not run("ufw", "status").startswith("Status: active\n"):
        errors.append("firewall is inactive")
    if records:
        cursor_path.write_text(records[-1]["__CURSOR"] + "\n")
    status = finish(state_dir, errors)
    return 0 if status["ok"] else 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("this host guard must run as root")
    try:
        return check(args.baseline, args.state_dir)
    except Exception as exc:
        args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        finish(args.state_dir, ["guard failure: " + str(exc)])
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
