#!/usr/bin/env python3
"""Apply the reviewed device patch only to the pinned, clean upstream checkout."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def apply_device(bundle: Path, source: Path) -> str:
    source = source.resolve()
    device = (source / "device/xiaomi/dash").resolve()
    if not device.is_relative_to(source) or not device.is_dir():
        raise ValueError("device checkout is missing or outside source root")
    projects = json.loads((bundle / "sources/dependencies.json").read_text())["projects"]
    expected = next(p["commit"] for p in projects if p["path"] == "device/xiaomi/dash")
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("invalid upstream commit")
    patch = (bundle / "patches/0001-infinity-dash.patch").resolve()

    def git(*args):
        return subprocess.run(["git", "-C", str(device), *args], capture_output=True, text=True)

    head = git("rev-parse", "HEAD")
    top = git("rev-parse", "--show-toplevel")
    if head.returncode or head.stdout.strip() != expected or Path(top.stdout.strip()).resolve() != device:
        raise ValueError("upstream commit does not match the pinned device checkout")
    if git("apply", "--reverse", "--check", str(patch)).returncode == 0:
        return "device patch already applied"
    if git("status", "--porcelain").stdout.strip():
        raise ValueError("device checkout has uncommitted changes; refusing to overwrite")
    checked = git("apply", "--check", str(patch))
    if checked.returncode:
        raise ValueError("patch check failed: " + checked.stderr.strip())
    applied = git("apply", str(patch))
    if applied.returncode:
        raise ValueError("patch application failed: " + applied.stderr.strip())
    return "device patch applied"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(apply_device(args.bundle_root.resolve(), args.source_root))
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print("ERROR:", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
