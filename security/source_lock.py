#!/usr/bin/env python3
"""Snapshot and verify the immutable Android source tree, outside build outputs."""
import argparse
import hashlib
import json
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


def record(root, relative):
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
            raise ValueError("external symlink: " + relative)
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


def snapshot(root, manifest):
    root, manifest = root.resolve(), manifest.absolute()
    if manifest.resolve().is_relative_to(root):
        raise ValueError("source manifest must be outside the source tree")
    created = False
    try:
        with manifest.open("x") as output:
            created = True
            output.write(json.dumps({"format": FORMAT, "root": str(root)}) + "\n")
            count = 0
            for relative in paths(root):
                output.write(json.dumps(record(root, relative), sort_keys=True) + "\n")
                count += 1
            output.flush()
            os.fsync(output.fileno())
        return count
    except Exception:
        if created:
            manifest.unlink(missing_ok=True)
        raise


def verify(root, manifest):
    root = root.resolve()
    expected_paths = set()
    errors = []
    with manifest.open() as source:
        header = json.loads(next(source))
        if header != {"format": FORMAT, "root": str(root)}:
            return ["source manifest root/format mismatch"]
        for line in source:
            expected = json.loads(line)
            relative = expected["path"]
            if relative in expected_paths:
                raise ValueError("duplicate source manifest path")
            expected_paths.add(relative)
            try:
                if record(root, relative) != expected:
                    errors.append("source changed: " + relative)
            except (OSError, ValueError) as exc:
                errors.append("source unavailable/unsafe: " + relative + ": " + str(exc))
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
            if path != root / ".infinity-dash-logs":
                errors.append("unexpected writable source submount: " + str(path))
    return errors


def log_errors(root, logs):
    actual = (root / ".infinity-dash-logs").stat()
    expected = logs.stat()
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        return ["source log mount does not match the external log directory"]
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "verify", "mount-check", "log-check"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--logs", type=Path)
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
        if not args.manifest:
            raise ValueError("--manifest is required")
        if args.command == "snapshot":
            count = snapshot(args.source, args.manifest)
            print("source snapshot completed:", count, "entries")
        else:
            errors = verify(args.source, args.manifest)
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
