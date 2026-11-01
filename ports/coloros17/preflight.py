#!/usr/bin/env python3
"""Read-only validation gate for the pinned ColorOS17 extraction recipe."""
import argparse
import json
from pathlib import Path
import re

REPLACEMENT_OPERATIONS = {"REPLACE", "REPLACE_BZ", "REPLACE_XZ", "ZERO"}
PARTITION_NAME = re.compile(r"[a-z][a-z0-9_]*")


def validate(metadata, payload, profile):
    if not isinstance(profile, dict) or profile.get("schema_version") != 1:
        raise ValueError("Missing or unsupported ColorOS profile")
    if profile.get("rom_type") != "coloros" or profile.get("sdk") != 37:
        raise ValueError("Profile is not for ColorOS Android17")
    if profile.get("pipeline_adapter_ready") is not True:
        raise ValueError("ColorOS17 pipeline adapter is not reviewed; refusing preparation")
    for key, expected in {"use_stock_init": True, "add_vendor_stuff": False,
                          "allow_insecure_adb": False, "allow_permissive_selinux": False,
                          "allow_unreviewed_binary_patches": False}.items():
        if profile.get(key) is not expected:
            raise ValueError("Unsafe or unspecified profile option: " + key)
    if profile.get("debloat") != {}:
        raise ValueError("Initial preservation profile must not remove apps")
    if not isinstance(metadata, dict) or not isinstance(payload, dict):
        raise ValueError("Malformed donor metadata")
    for key, expected in {"product_name": profile.get("product"),
                          "version_name": profile.get("version"),
                          "post-sdk-level": "37", "android_version": "17",
                          "os_version": "V17.0.0"}.items():
        if not expected or metadata.get(key) != expected:
            raise ValueError("Donor identity/version mismatch: " + key)
    if payload.get("magic") != "CrAU" or payload.get("major_version") != 2:
        raise ValueError("Unsupported Android payload format")
    if payload.get("metadata_hash_matches") is not True:
        raise ValueError("Payload metadata hash has not been verified")
    required = profile.get("required_partitions")
    if (not isinstance(required, list) or not required or
            not all(isinstance(name, str) and PARTITION_NAME.fullmatch(name) for name in required) or
            len(required) != len(set(required)) or
            not {"system", "system_ext", "product"}.issubset(required)):
        raise ValueError("Incomplete or malformed required partition list")
    if any(name not in {"system", "system_ext", "product"} and not name.startswith("my_")
           for name in required):
        raise ValueError("Hardware/boot partition is outside the GSI extraction scope")
    parts = payload.get("partitions")
    if not isinstance(parts, list):
        raise ValueError("Missing partition manifest")
    by_name = {}
    for part in parts:
        if (not isinstance(part, dict) or not isinstance(part.get("name"), str) or
                not PARTITION_NAME.fullmatch(part["name"])):
            raise ValueError("Malformed partition entry")
        name = part["name"]
        if name in by_name:
            raise ValueError("Duplicate partition: " + name)
        by_name[name] = part
        if name.startswith("my_") and name not in required:
            raise ValueError("Unreviewed ColorOS partition: " + name)
    missing = set(required) - by_name.keys()
    if missing:
        raise ValueError("Missing required partitions: " + ", ".join(sorted(missing)))
    size = 0
    for name in required:
        part = by_name[name]
        if (part.get("old_partition_info_present") is not False or
                part.get("operations_with_source_extents") != 0):
            raise ValueError("Partition needs an older source image: " + name)
        operations = part.get("operations")
        if (not isinstance(operations, dict) or not operations or
                not set(operations).issubset(REPLACEMENT_OPERATIONS)):
            raise ValueError("Unsupported/source-dependent operation: " + name)
        if any(type(count) is not int or count <= 0 for count in operations.values()):
            raise ValueError("Invalid operation count: " + name)
        length = part.get("size")
        if type(length) is not int or length <= 0 or length % 512:
            raise ValueError("Invalid partition size: " + name)
        size += length
    return {"donor": metadata["version_name"], "sdk": 37,
            "partitions": list(required), "image_bytes": size,
            "self_contained_for_extraction": True, "phone_flash_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--payload-summary", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("profile.json"))
    args = parser.parse_args()
    try:
        report = validate(json.loads(args.metadata.read_text()),
                          json.loads(args.payload_summary.read_text()),
                          json.loads(args.profile.read_text()))
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print("ERROR:", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
