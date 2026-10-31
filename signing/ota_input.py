"""Prepare a disposable, image-symlink target-files directory for a partial OTA."""
import argparse
import json
import os
from pathlib import Path
import re
import stat


def complete_partition_versions(partitions, existing, release_timestamp):
    """Fill omitted partial-update versions from the target release timestamp."""
    if not partitions or len(set(partitions)) != len(partitions):
        raise ValueError("Expected a nonempty unique partition list")
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in partitions):
        raise ValueError("Invalid partition name")
    timestamp = str(release_timestamp)
    if not timestamp.isdecimal() or int(timestamp) <= 0:
        raise ValueError("Invalid target release timestamp")
    if set(existing) - set(partitions):
        raise ValueError("Version refers to an excluded partition")
    result = {}
    for name in partitions:
        value = str(existing.get(name) or timestamp)
        if not value.isdecimal() or int(value) <= 0:
            raise ValueError("Invalid partition version")
        result[name] = value
    return result


def prepare_partial_ota_input(root, partitions):
    root = Path(root)
    if not partitions or len(set(partitions)) != len(partitions):
        raise ValueError("Expected a nonempty unique partition list")
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in partitions):
        raise ValueError("Invalid partition name")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Expected a disposable target-files directory")
    metadata = root / "META"
    if metadata.is_symlink() or not metadata.is_dir():
        raise ValueError("Expected a real META directory")
    paths = list(metadata.rglob("*"))
    if any(p.is_symlink() or p.stat().st_uid != os.geteuid() for p in paths):
        raise ValueError("Metadata must be owned regular files or directories")
    manifest = metadata / "ab_partitions.txt"
    if not manifest.is_file() or not set(partitions) <= set(manifest.read_text().split()):
        raise ValueError("Requested partitions are absent from the input manifest")
    discard = []
    images = set()
    for name in ("IMAGES", "RADIO", "PREBUILT_IMAGES"):
        directory = root / name
        if directory.is_symlink():
            raise ValueError("Image directory must not be a symlink")
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if path.suffix not in (".img", ".map"):
                continue
            if path.stem not in partitions:
                if not path.is_symlink():
                    raise ValueError("Refusing to discard a real image file")
                discard.append(path)
            elif path.suffix == ".img" and path.is_file():
                images.add(path.stem)
    if images != set(partitions):
        raise ValueError("Missing selected partition images")
    # AOSP WriteBytesToInputFile silently ignores EACCES on 0444 metadata.
    # Only relax the disposable copy; signed inputs retain their original modes.
    for path in paths:
        if path.is_file():
            path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
    manifest.write_text("\n".join(partitions) + "\n")
    for path in discard:
        path.unlink()
    if manifest.read_text().split() != list(partitions):
        raise ValueError("Partition manifest write did not persist")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_directory", type=Path)
    parser.add_argument("--partitions", type=Path, required=True)
    args = parser.parse_args()
    prepare_partial_ota_input(
        args.input_directory, json.loads(args.partitions.read_text())["partitions"]
    )
