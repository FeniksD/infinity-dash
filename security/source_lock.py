#!/usr/bin/env python3
"""Snapshot and verify the immutable Android source tree, outside build outputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from itertools import islice
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

EXCLUDED_ROOTS = {".repo", ".infinity-dash-logs", "out"}
FORMAT = "infinity-source-lock-v1"


def paths(root):
    def walk(folder):
        with os.scandir(folder) as scan:
            entries = sorted(scan, key=lambda e: e.name)
        for entry in entries:
            if entry.name == ".git" or (folder == root and entry.name in EXCLUDED_ROOTS):
                continue
            path = Path(entry.path)
            yield path.relative_to(root).as_posix()
            if entry.is_dir(follow_symlinks=False):
                yield from walk(path)
    yield from walk(root)


def record(root, relative, image_links=None):
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or not parts.parts:
        raise ValueError("invalid source path")
    path = root / relative
    if not path.parent.resolve().is_relative_to(root):
        raise ValueError("source parent escapes tree: " + relative)
    st = path.lstat()
    result = {"path": relative, "mode": stat.S_IMODE(st.st_mode)}
    if stat.S_ISLNK(st.st_mode):
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            target = os.readlink(path)
            if (image_links or {}).get(relative) != target:
                raise ValueError("external symlink: " + relative)
            if resolved.exists() or resolved.is_symlink():
                raise ValueError("image link resolves to an existing host object: " + relative)
            for parent in resolved.parents:
                if parent.exists():
                    metadata = parent.stat()
                    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                        raise ValueError("image link has a mutable host ancestor: " + relative)
            result.update(kind="image-link", target=target)
            return result
        target_parts = resolved.relative_to(root).parts
        if ".git" in target_parts or (target_parts and target_parts[0] in EXCLUDED_ROOTS):
            raise ValueError("symlink into excluded source tree: " + relative)
        result.update(kind="link", target=os.readlink(path))
    elif stat.S_ISREG(st.st_mode):
        if st.st_nlink != 1:
            raise ValueError("hardlink alias: " + relative)
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(4 * 1024 * 1024):
                digest.update(chunk)
        result.update(kind="file", size=st.st_size, sha256=digest.hexdigest())
    elif stat.S_ISDIR(st.st_mode):
        result.update(kind="directory")
    else:
        raise ValueError("unsupported source type: " + relative)
    return result


def snapshot(root, manifest, image_links=None):
    root, manifest = root.resolve(), manifest.absolute()
    image_links = image_links or {}
    if manifest.resolve().is_relative_to(root):
        raise ValueError("source manifest must be outside the source tree")
    created = False
    try:
        with manifest.open("x") as output:
            created = True
            output.write(json.dumps({"format": FORMAT, "root": str(root), "image_links": image_links}) + "\n")
            count = 0
            for relative in paths(root):
                output.write(json.dumps(record(root, relative, image_links), sort_keys=True) + "\n")
                count += 1
            output.flush()
            os.fsync(output.fileno())
        return count
    except Exception:
        if created:
            manifest.unlink(missing_ok=True)
        raise


def verify(root, manifest, image_links=None, jobs=1, progress=False):
    if not 1 <= jobs <= 32:
        raise ValueError("verification jobs must be between 1 and 32")
    root = root.resolve()
    image_links = image_links or {}
    expected_paths = set()
    errors = []
    def check(expected):
        relative = expected["path"]
        try:
            if record(root, relative, image_links) != expected:
                return "source changed: " + relative
        except (OSError, ValueError) as exc:
            return "source unavailable/unsafe: " + relative + ": " + str(exc)
        return None

    with manifest.open() as source, ThreadPoolExecutor(max_workers=jobs) as pool:
        header = json.loads(next(source))
        if header != {"format": FORMAT, "root": str(root), "image_links": image_links}:
            return ["source manifest root/format mismatch"]
        next_progress = 100000
        while lines := list(islice(source, 256)):
            batch = [json.loads(line) for line in lines]
            for expected in batch:
                relative = expected["path"]
                if relative in expected_paths:
                    raise ValueError("duplicate source manifest path")
                expected_paths.add(relative)
            errors.extend(error for error in pool.map(check, batch) if error)
            if progress and len(expected_paths) >= next_progress:
                print("checked source entries:", len(expected_paths), flush=True)
                next_progress += 100000
    for relative in paths(root):
        if relative not in expected_paths:
            errors.append("unexpected source: " + relative)
    return errors


def mount_errors(root, mountinfo):
    root = root.resolve()
    entries = []
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) < 6:
            raise ValueError("invalid mountinfo")
        mountpoint = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4])
        entries.append((Path(mountpoint), set(fields[5].split(","))))
    errors = []
    matches = [options for path, options in entries if path == root]
    if not matches or "ro" not in matches[-1]:
        errors.append("source requires an exact read-only mount")
    for path, options in entries:
        if path != root and path.is_relative_to(root) and "ro" not in options:
            if path not in {root / ".infinity-dash-logs", root / "out"}:
                errors.append("unexpected writable source submount: " + str(path))
    return errors


def log_errors(root, logs):
    actual = (root / ".infinity-dash-logs").stat()
    expected = logs.stat()
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        return ["source log mount does not match the external log directory"]
    return []


def output_errors(root, output):
    actual = (root / "out").stat()
    expected = output.stat()
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        return ["source output mount does not match the external output directory"]
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "verify", "mount-check", "log-check", "output-check"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--logs", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    try:
        if args.source.is_symlink() or not args.source.is_dir():
            raise ValueError("source must be a real directory")
        errors = mount_errors(args.source, Path("/proc/self/mountinfo").read_text())
        if errors:
            raise ValueError("; ".join(errors))
        if args.command == "mount-check":
            print("read-only source mount verified")
            return 0
        if args.command == "log-check":
            if not args.logs:
                raise ValueError("--logs is required")
            errors = log_errors(args.source.resolve(), args.logs.resolve())
            if errors:
                raise ValueError("; ".join(errors))
            print("external log destination verified")
            return 0
        if args.command == "output-check":
            if not args.output:
                raise ValueError("--output is required")
            errors = output_errors(args.source.resolve(), args.output.resolve())
            if errors:
                raise ValueError("; ".join(errors))
            print("external output destination verified")
            return 0
        if not args.manifest:
            raise ValueError("--manifest is required")
        policy_path = Path(__file__).with_name("source-link-policy.json")
        image_links = json.loads(policy_path.read_text()) if policy_path.exists() else {}
        if args.command == "snapshot":
            count = snapshot(args.source, args.manifest, image_links)
            print("source snapshot completed:", count, "entries")
        else:
            errors = verify(args.source, args.manifest, image_links, jobs=args.jobs, progress=True)
            if errors:
                print("\n".join(errors[:20]))
                print("source verification failed:", len(errors), "differences")
                return 1
            print("all source files verified")
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print("ERROR:", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
