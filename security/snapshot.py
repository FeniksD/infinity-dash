#!/usr/bin/env python3
"""Capture a reviewed host state. Run manually, never from the checking timer."""
import argparse
import json
from pathlib import Path
import time
import guard

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--ip", required=True)
parser.add_argument("--fingerprint", required=True)
parser.add_argument("--source-root", type=Path)
parser.add_argument("--source-manifest", type=Path)
args = parser.parse_args()
if bool(args.source_root) != bool(args.source_manifest):
    parser.error("source root and source manifest must be provided together")
roots = [
    "/srv/infinity/infinity-dash-prep", "/etc/ssh/sshd_config.d", "/root/.ssh",
    "/etc/ufw", "/etc/systemd/system", "/etc/cron.d", "/etc/sudoers.d",
    "/var/spool/cron", "/usr/local/lib/infinity-guard",
]
files = ["/etc/ssh/sshd_config", "/etc/passwd", "/etc/group", "/etc/shadow", "/etc/sudoers", "/usr/sbin/sshd", "/usr/bin/git", "/usr/bin/python3.14", "/etc/pam.d/sshd"]
if args.source_manifest:
    files.append(str(args.source_manifest.resolve()))
trees = {}
for name in roots:
    root = Path(name)
    trees[name] = guard.tree_members(root)
    if root.exists():
        files.append(name)
        files.extend(str(root / part) for part in trees[name])
baseline = {
    "version": 1, "since": int(time.time()) - 3600, "allowed_ip": args.ip,
    "fingerprint": args.fingerprint,
    "files": {name: guard.file_record(name) for name in files}, "trees": trees,
    "listeners": guard.listeners(guard.run("ss", "-H", "-lntup")),
    "services": guard.services(guard.run("systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain")),
}
if args.source_root:
    baseline["source_lock"] = {"root": str(args.source_root.resolve()), "manifest": str(args.source_manifest.resolve())}
args.output.write_text(json.dumps(baseline, indent=2) + "\n")
args.output.chmod(0o600)
print("Reviewed host baseline written:", len(baseline["files"]), "paths")
