#!/usr/bin/env python3
"""Apply explicitly pinned platform patches without discarding other changes."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from apply_device import apply_checkout_patch


def platform_specs(bundle):
    config = bundle / "sources/platform-patches.json"
    if not config.exists():
        return []
    specs = json.loads(config.read_text())["patches"]
    for spec in specs:
        paths = [spec["path"], spec["patch"], *spec["files"].keys(), *spec["files"].values()]
        if any(not p or PurePosixPath(p).is_absolute() or ".." in PurePosixPath(p).parts for p in paths):
            raise ValueError("unsafe platform patch path")
        if not re.fullmatch(r"[0-9a-f]{40}", spec["commit"]):
            raise ValueError("platform patch commit is not pinned")
        for relative in [spec["patch"], *spec["files"].values()]:
            target = (bundle / relative).resolve()
            if not target.is_relative_to(bundle.resolve()) or not target.is_file():
                raise ValueError("platform patch input missing or outside bundle")
    return specs


def matches_platform_patch(bundle, checkout, spec, entries):
    if not all(entry[:2] in (" M", "??") and entry[3:] in spec["files"] for entry in entries):
        return False
    for path, reference in spec["files"].items():
        actual = checkout / path
        if not actual.is_file() or actual.read_bytes() != (bundle / reference).read_bytes():
            return False
        if bool(actual.stat().st_mode & 0o111) != bool((bundle / reference).stat().st_mode & 0o111):
            return False
    return True


def apply_platform(bundle, source):
    messages = []
    for spec in platform_specs(bundle):
        checkout = (source / spec["path"]).resolve()
        if not checkout.is_relative_to(source.resolve()) or not checkout.is_dir():
            raise ValueError("platform checkout missing or outside source")
        patch_path = (bundle / spec["patch"]).resolve()
        changes = subprocess.run(["git", "-C", str(checkout), "apply", "--numstat", "-z", str(patch_path)], capture_output=True, text=True, check=True)
        targets = {entry.split("\t", 2)[-1] for entry in changes.stdout.split("\0") if entry}
        if targets != set(spec["files"]):
            raise ValueError("platform patch targets differ from the approved file list")
        status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching"], capture_output=True, text=True, check=True)
        entries = [x for x in status.stdout.split("\0") if x]
        if entries and not matches_platform_patch(bundle, checkout, spec, entries):
            raise ValueError("unexpected platform checkout changes: " + spec["path"])
        result = apply_checkout_patch(checkout, spec["commit"], patch_path)
        status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching"], capture_output=True, text=True, check=True)
        entries = [x for x in status.stdout.split("\0") if x]
        if not matches_platform_patch(bundle, checkout, spec, entries):
            raise ValueError("platform patch result differs from reviewed files")
        messages.append(spec["path"] + ": " + result)
    return messages


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    for message in apply_platform(args.bundle_root.resolve(), args.source_root.resolve()):
        print(message)
