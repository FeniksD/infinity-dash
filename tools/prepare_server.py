#!/usr/bin/env python3
"""Show or execute the source-only server setup; never flashes a device."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from apply_device import apply_device
from preflight import validate_bundle, validate_checkouts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--bundle-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sync", action="store_true", help="actually initialize and download Android sources")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--min-free-gib", type=int, default=400)
    args = parser.parse_args()
    bundle, source = args.bundle_root.resolve(), args.source_root.resolve()
    if args.jobs < 1 or args.min_free_gib < 1:
        print("ERROR: jobs and minimum free space must be positive")
        return 1
    errors = validate_bundle(bundle)
    if errors:
        print("\n".join("ERROR: " + e for e in errors))
        return 1
    platform = json.loads((bundle / "sources/platform.json").read_text())
    commands = [
        ["repo", "init", "-u", platform["url"], "-b", platform["commit"], "--git-lfs", "--depth=1"],
        ["repo", "sync", "-c", "--no-clone-bundle", "--no-tags", f"-j{args.jobs}"],
    ]
    if not args.sync:
        print("Source root:", source)
        print(shlex.join(commands[0]))
        print("Install pinned local_manifests/dash.xml into .repo/local_manifests/")
        print(shlex.join(commands[1]))
        print("Verify dependency commits and apply the reviewed device patch.")
        print("Plan only. Add --sync on the build server to execute; no files changed.")
        return 0
    marker = source / ".infinity-dash-preparation.json"
    if source.exists() and any(source.iterdir()):
        try:
            known = json.loads(marker.read_text())
        except (OSError, ValueError):
            print("ERROR: nonempty source directory is not owned by this preparation")
            return 1
        if known != platform:
            print("ERROR: nonempty source directory belongs to a different preparation revision")
            return 1
    if source == bundle or source in bundle.parents or bundle in source.parents:
        print("ERROR: source and bundle directories must be separate")
        return 1
    ancestor = source
    while not ancestor.exists():
        ancestor = ancestor.parent
    available = shutil.disk_usage(ancestor).free // (1024 ** 3)
    if available < args.min_free_gib:
        print(f"ERROR: {available} GiB free; at least {args.min_free_gib} GiB required before sync")
        return 1
    for name in ("repo", "git", "git-lfs"):
        if not shutil.which(name):
            print("ERROR: missing build-host tool:", name)
            return 1
    source.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(platform, indent=2) + "\n")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        subprocess.run(commands[0], cwd=source, env=env, check=True)
        manifests = source / ".repo/local_manifests"
        manifests.mkdir(exist_ok=True)
        target = manifests / "dash.xml"
        content = (bundle / "local_manifests/dash.xml").read_bytes()
        if target.exists() and target.read_bytes() != content:
            raise ValueError("existing local manifest differs; refusing to overwrite")
        target.write_bytes(content)
        subprocess.run(commands[1], cwd=source, env=env, check=True)
        errors = validate_checkouts(bundle, source)
        if errors:
            raise ValueError("; ".join(errors))
        print(apply_device(bundle, source))
        logs = source / ".infinity-dash-logs"
        logs.mkdir(exist_ok=True)
        subprocess.run(["repo", "manifest", "-r", "-o", str(logs / "resolved-manifest.xml")], cwd=source, check=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("ERROR:", exc)
        return 1
    print("Sources prepared. Compilation has not been run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
