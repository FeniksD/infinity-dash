#!/usr/bin/env python3
"""Validate the portable preparation bundle without syncing/building Android."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from apply_platform import platform_specs

SHA = re.compile(r"[0-9a-f]{40}")


def validate_checkouts(bundle: Path, source: Path, prepared: bool = False) -> list[str]:
    errors = []
    lock = json.loads((bundle / "sources/dependencies.json").read_text())
    for project in lock["projects"]:
        path = source / project["path"]
        if not path.is_dir():
            errors.append(f"missing checkout: {project['path']}")
            continue
        result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
        if result.returncode or result.stdout.strip() != project["commit"]:
            errors.append(f"checkout commit mismatch: {project['path']}")
    for spec in platform_specs(bundle):
        path = source / spec["path"]
        result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
        if result.returncode or result.stdout.strip() != spec["commit"]:
            errors.append("platform checkout commit mismatch: " + spec["path"])
        if prepared:
            for relative, reference in spec["files"].items():
                actual = path / relative
                if not actual.is_file() or actual.read_bytes() != (bundle / reference).read_bytes():
                    errors.append("platform override mismatch: " + relative)
                elif bool(actual.stat().st_mode & 0o111) != bool((bundle / reference).stat().st_mode & 0o111):
                    errors.append("platform override mode mismatch: " + relative)
    return errors


def validate_bundle(root: Path) -> list[str]:
    errors = []
    try:
        platform_specs(root)
    except (OSError, ValueError, KeyError) as exc:
        errors.append(str(exc))
    try:
        lock = json.loads((root / "sources/dependencies.json").read_text())
        platform = json.loads((root / "sources/platform.json").read_text())
        base = json.loads((root / "sources/base-manifest-projects.json").read_text())
        manifest = ET.parse(root / "local_manifests/dash.xml").getroot()
    except (OSError, ValueError, ET.ParseError) as exc:
        return [str(exc)]
    if not SHA.fullmatch(platform.get("commit", "")):
        errors.append("platform manifest is not pinned")
    if platform.get("android") != 17 or platform.get("release_config") != "cp2a":
        errors.append("unexpected Android/release configuration")
    projects = lock.get("projects", [])
    by_path = {}
    for project in projects:
        path = project.get("path", "")
        parts = PurePosixPath(path).parts
        if not parts or path.startswith("/") or ".." in parts:
            errors.append(f"invalid dependency path: {path}")
        if path in by_path:
            errors.append(f"duplicate dependency path: {path}")
        by_path[path] = project
        if "keys" in parts or "-priv" in path or "-priv" in project.get("repository", ""):
            errors.append(f"private signing dependency: {path}")
        if not SHA.fullmatch(project.get("commit", "")):
            errors.append(f"dependency is not pinned: {path}")
    seen = set()
    removals = {x.get("name") for x in manifest.findall("remove-project")}
    for project in manifest.findall("project"):
        path = project.get("path", "")
        if path in seen:
            errors.append(f"duplicate manifest path: {path}")
        seen.add(path)
        expected = by_path.get(path)
        if not SHA.fullmatch(project.get("revision", "")):
            errors.append(f"manifest revision is not pinned: {path}")
        if expected is None or project.get("name") != expected.get("repository") or project.get("revision") != expected.get("commit"):
            errors.append(f"manifest differs from dependency lock: {path}")
        if path in base and base[path] not in removals:
            errors.append(f"base project not removed before replacement: {path}")
    if seen != set(by_path):
        errors.append("manifest and dependency lock contain different paths")
    device = root / "device/xiaomi/dash"
    try:
        product = (device / "infinity_dash.mk").read_text()
        registry = (device / "AndroidProducts.mk").read_text()
        board = (device / "BoardConfig.mk").read_text()
        config = (device / "device.mk").read_text()
    except OSError as exc:
        return errors + [str(exc)]
    for required in ("PRODUCT_NAME := infinity_dash", "PRODUCT_DEVICE := dash", "PRODUCT_MODEL := 2602BPC18G", "vendor/infinity/config/common_full_phone.mk"):
        if required not in product:
            errors.append(f"product missing: {required}")
    if "infinity_dash.mk" not in registry:
        errors.append("Infinity product is not registered")
    if "evolution.mk" in product or "vendor/lineage/config/" in product + board:
        errors.append("active product still inherits the other ROM configuration")
    if "WITH_GMS" in config:
        errors.append("device filesystem still uses WITH_GMS instead of WITH_GAPPS")
    if "FILESYSTEM_TYPE_vendor=erofs" not in config:
        errors.append("vendor postinstall filesystem is not declared")
    try:
        integrity = device / "configs/integrity"
        policy = json.loads((integrity / "policy.json").read_text())
        for name in ("pif", "gameprops"):
            raw = (integrity / (name + ".json")).read_bytes()
            json.loads(raw)
            if hashlib.sha256(raw).hexdigest() != policy[name + "_sha256"]:
                errors.append("integrity configuration hash mismatch: " + name)
    except (OSError, ValueError, KeyError) as exc:
        errors.append("invalid integrity configuration: " + str(exc))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    errors = validate_bundle(args.bundle_root.resolve())
    if args.source_root and not errors:
        errors += validate_checkouts(args.bundle_root.resolve(), args.source_root.resolve(), prepared=True)
        for name in ("AndroidProducts.mk", "BoardConfig.mk", "device.mk", "infinity_dash.mk",
                     "configs/integrity/pif.json", "configs/integrity/gameprops.json",
                     "configs/integrity/policy.json"):
            actual = args.source_root / "device/xiaomi/dash" / name
            expected = args.bundle_root / "device/xiaomi/dash" / name
            if not actual.is_file() or actual.read_bytes() != expected.read_bytes():
                errors.append(f"prepared device file mismatch: {name}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("offline preparation passed")
    print("Not verified here: Android compilation, binary ABI/VINTF, device boot and hardware.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
