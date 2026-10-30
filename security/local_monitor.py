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
    ], timeout=45, stderr=subprocess.PIPE)


def transient_transport_failure(exc):
    if not isinstance(exc, subprocess.CalledProcessError) or exc.returncode != 255:
        return False
    detail = (exc.stderr or b"").decode(errors="replace").lower()
    if any(text in detail for text in ("host key verification failed", "remote host identification", "permission denied")):
        return False
    if "timeout, server " in detail and "not responding" in detail:
        return True
    return any(text in detail for text in (
        "network is unreachable", "no route to host", "connection timed out",
        "connection reset by peer", "connection closed by", "broken pipe",
    ))


def verify_once(args, expected, expected_baseline):
    remote = members(ssh(args.host, "tar -C /srv/infinity/infinity-dash-prep -cf - ."))
    if remote != expected:
        return ["remote preparation differs from local archive"]
    if ssh(args.host, "cat /root/infinity-security/baseline.json") != expected_baseline:
        return ["remote baseline differs from local copy"]
    health = json.loads(ssh(args.host, "cat /var/lib/infinity-guard/status.json"))
    if not health.get("ok") or abs(time.time() - health.get("time", 0)) > 180:
        return ["server guard is unhealthy or stale"]
    return []


def saved_latch(path):
    if not path.exists():
        return False
    try:
        state = json.loads(path.read_text())
        if not isinstance(state, dict):
            return True
        return bool(state.get("latched") or not state.get("ok", False))
    except (ValueError, OSError):
        return True


def cycle(args, latched):
    errors = []
    try:
        expected = members(args.archive.read_bytes(), "infinity-dash-prep/", sealed=True)
        expected_baseline = args.baseline.read_bytes()
        for attempt, delay in enumerate((0, 3, 7, 10)):
            if delay:
                time.sleep(delay)
            try:
                errors = verify_once(args, expected, expected_baseline)
                break
            except subprocess.CalledProcessError as exc:
                if latched or attempt == 3 or not transient_transport_failure(exc):
                    raise
                print(json.dumps({"transport_retry": attempt + 1, "reason": (exc.stderr or b"").decode(errors="replace").strip()[:300]}), flush=True)
    except Exception as exc:
        detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            detail += ": " + exc.stderr.decode(errors="replace").strip()[:300]
        errors.append("verification unavailable: " + detail)
    if latched:
        try:
            previous_state = json.loads(args.state.read_text())
            if not isinstance(previous_state, dict):
                raise ValueError("invalid saved incident")
            previous = previous_state.get("errors", [])
            if not isinstance(previous, list) or not all(isinstance(error, str) for error in previous):
                raise ValueError("invalid saved incident")
            errors = previous + [error for error in errors if error not in previous]
        except (OSError, ValueError):
            errors.insert(0, "previous incident details unavailable")
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
