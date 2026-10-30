#!/usr/bin/env python3
"""Independently compare the remote preparation bytes with a local archive."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import time


def members(data, prefix="", sealed=False):
    result = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for entry in archive:
            name = entry.name
            while name.startswith("./"):
                name = name[2:]
            if prefix:
                if name == prefix.rstrip("/"):
                    continue
                if not name.startswith(prefix):
                    raise ValueError("unexpected archive prefix")
                name = name[len(prefix):]
            if name in ("", "."):
                continue
            if name.startswith("/") or ".." in PurePosixPath(name).parts or name in result:
                raise ValueError("unsafe or duplicate archive path")
            mode = entry.mode & ~0o022 if sealed else entry.mode
            if entry.isfile():
                digest = hashlib.sha256(archive.extractfile(entry).read()).hexdigest()
                result[name] = ("file", mode, digest)
            elif entry.isdir():
                result[name.rstrip("/")] = ("dir", mode, None)
            elif entry.issym():
                result[name] = ("link", mode, entry.linkname)
            else:
                raise ValueError("unexpected archive member type")
    return result


def ssh(host, command):
    return subprocess.check_output([
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ForwardAgent=no", "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
        host, command,
    ], timeout=45)


def saved_latch(path):
    if not path.exists():
        return False
    try:
        state = json.loads(path.read_text())
        return bool(state.get("latched") or not state.get("ok", False))
    except (ValueError, OSError):
        return True


def cycle(args, latched):
    errors = []
    try:
        expected = members(args.archive.read_bytes(), "infinity-dash-prep/", sealed=True)
        expected_baseline = args.baseline.read_bytes()
        remote = members(ssh(args.host, "tar -C /srv/infinity/infinity-dash-prep -cf - ."))
        if remote != expected:
            errors.append("remote preparation differs from local archive")
        if ssh(args.host, "cat /root/infinity-security/baseline.json") != expected_baseline:
            errors.append("remote baseline differs from local copy")
        health = json.loads(ssh(args.host, "cat /var/lib/infinity-guard/status.json"))
        if not health.get("ok") or abs(time.time() - health.get("time", 0)) > 180:
            errors.append("server guard is unhealthy or stale")
    except Exception as exc:
        errors.append("verification unavailable: " + str(exc))
    stopped = False
    if errors or latched:
        latched = True
        try:
            ssh(args.host, "pkill -STOP -u 1000; test $? -le 1")
            stopped = True
        except Exception:
            pass
    state = {"time": int(time.time()), "ok": not errors and not latched, "errors": errors, "latched": latched, "build_pause_confirmed": stopped}
    args.state.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.state.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(args.state)
    print(json.dumps(state), flush=True)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.host.startswith("-") or args.interval < 10:
        parser.error("invalid host or interval")
    latched = saved_latch(args.state)
    while True:
        state = cycle(args, latched)
        latched = state["latched"]
        if args.once:
            return 0 if state["ok"] else 3
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
