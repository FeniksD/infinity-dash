#!/usr/bin/env python3
"""Show or execute the source-only server setup; never flashes a device."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from apply_device import apply_device
from apply_platform import apply_platform, matches_platform_patch, platform_specs
from preflight import SHA, validate_bundle, validate_checkouts


def locked_manifest(bundle):
    path = bundle / "build/source-manifest.xml"
    data = path.read_bytes()
    root = ET.fromstring(data)
    if root.findall("include") or root.findall("submanifest"):
        raise ValueError("locked manifest must not include other manifests")
    for remote in root.findall("remote"):
        url = urlparse(remote.get("fetch", ""))
        if url.scheme not in ("https", "ssh") or not url.hostname:
            raise ValueError("locked remotes must use absolute HTTPS/SSH URLs")
        if url.password or (url.username and not (url.scheme == "ssh" and url.username == "git")):
            raise ValueError("embedded credentials are not allowed in locked remotes")
    projects = {}
    for project in root.findall("project"):
        relative = project.get("path", project.get("name", ""))
        if not relative or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts or relative in projects:
            raise ValueError("invalid or duplicate locked project path")
        revision = project.get("revision", "")
        if not SHA.fullmatch(revision):
            raise ValueError("locked project is not pinned: " + relative)
        projects[relative] = revision
    if not projects:
        raise ValueError("empty locked manifest")
    lock = json.loads((bundle / "sources/dependencies.json").read_text())
    for dependency in lock["projects"]:
        if projects.get(dependency["path"]) != dependency["commit"]:
            raise ValueError("locked hardware dependency mismatch: " + dependency["path"])
    return path, hashlib.sha256(data).hexdigest()


def project_revisions(manifest):
    return {p.get("path", p.get("name")): p.get("revision") for p in ET.parse(manifest).getroot().findall("project")}


def validate_locked_checkouts(bundle, source, manifest):
    errors = []
    prepared_names = {"AndroidProducts.mk", "BoardConfig.mk", "device.mk", "infinity_dash.mk"}
    platform_patches = {spec["path"]: spec for spec in platform_specs(bundle)}
    for relative, revision in project_revisions(manifest).items():
        path = source / relative
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel", "HEAD"], capture_output=True, text=True)
        lines = head.stdout.splitlines()
        if head.returncode or len(lines) != 2 or Path(lines[0]).resolve() != path.resolve() or lines[1] != revision:
            errors.append("locked checkout commit mismatch: " + relative)
            continue
        status = subprocess.run(["git", "-C", str(path), "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching"], capture_output=True, text=True)
        if status.returncode:
            errors.append("cannot inspect locked checkout: " + relative)
            continue
        entries = [entry for entry in status.stdout.split("\0") if entry]
        if not entries:
            continue
        valid_patch = relative == "device/xiaomi/dash" and all(
            (entry[:2] == " M" and entry[3:] in prepared_names - {"infinity_dash.mk"})
            or (entry[:2] == "??" and entry[3:] == "infinity_dash.mk")
            for entry in entries
        )
        if valid_patch:
            for name in prepared_names:
                actual, expected = path / name, bundle / relative / name
                if not actual.is_file() or actual.read_bytes() != expected.read_bytes():
                    valid_patch = False
                    break
        if relative in platform_patches:
            valid_patch = matches_platform_patch(bundle, path, platform_patches[relative], entries)
        if not valid_patch:
            errors.append("dirty locked checkout: " + relative)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--bundle-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sync", action="store_true", help="actually initialize and download Android sources")
    parser.add_argument("--locked", action="store_true", help="restore all projects from the saved resolved manifest")
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
    preparation = dict(platform)
    if args.locked:
        try:
            manifest, digest = locked_manifest(bundle)
        except (OSError, ValueError, ET.ParseError) as exc:
            print("ERROR:", exc)
            return 1
        preparation["resolved_manifest_sha256"] = digest
        commands[0] = ["repo", "init", "--standalone-manifest", "-u", manifest.as_uri(), "--git-lfs", "--depth=1"]
    if not args.sync:
        print("Source root:", source)
        print(shlex.join(commands[0]))
        if not args.locked:
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
        if known != preparation:
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
    marker.write_text(json.dumps(preparation, indent=2) + "\n")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        subprocess.run(commands[0], cwd=source, env=env, check=True)
        manifests = source / ".repo/local_manifests"
        if args.locked:
            if manifests.exists() and list(manifests.glob("*.xml")):
                raise ValueError("locked restore refuses additional local manifests")
        else:
            manifests.mkdir(exist_ok=True)
            target = manifests / "dash.xml"
            content = (bundle / "local_manifests/dash.xml").read_bytes()
            if target.exists() and target.read_bytes() != content:
                raise ValueError("existing local manifest differs; refusing to overwrite")
            target.write_bytes(content)
        subprocess.run(commands[1], cwd=source, env=env, check=True)
        errors = validate_locked_checkouts(bundle, source, manifest) if args.locked else validate_checkouts(bundle, source)
        if errors:
            raise ValueError("; ".join(errors))
        print(apply_device(bundle, source))
        for message in apply_platform(bundle, source):
            print(message)
        errors = validate_checkouts(bundle, source, prepared=True)
        if errors:
            raise ValueError("; ".join(errors))
        logs = source / ".infinity-dash-logs"
        logs.mkdir(exist_ok=True)
        subprocess.run(["repo", "manifest", "-r", "-o", str(logs / "resolved-manifest.xml")], cwd=source, check=True)
        if args.locked and project_revisions(manifest) != project_revisions(logs / "resolved-manifest.xml"):
            raise ValueError("resolved checkout differs from the complete locked manifest")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("ERROR:", exc)
        return 1
    print("Sources prepared. Compilation has not been run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
