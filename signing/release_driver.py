"""Adapter for the pinned AOSP signer: refresh Android 17 fs-verity metadata.

Run inside the matching AOSP Python executable, never with unverified tools.
Private key paths are supplied by the caller; this module creates no keys.
"""
from pathlib import Path, PurePosixPath
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import zipfile


def manifest_source(staging, partition, device_path):
    relative = PurePosixPath(device_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Unsafe fs-verity manifest path")
    prefix = partition.lower()
    parts = relative.parts
    if parts[0] == prefix:
        parts = parts[1:]
    elif parts[0] in {"system", "system_ext", "product", "vendor", "odm"}:
        raise ValueError("Cross-partition fs-verity manifest path")
    return Path(staging).joinpath(partition, *parts)


def replace_manifest_asset(original, destination, payload):
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(destination, "w") as out:
        names = source.namelist()
        if names.count("assets/build_manifest.pb") != 1:
            raise ValueError("Expected one fs-verity manifest asset")
        for info in source.infolist():
            if info.filename.upper().startswith("META-INF/"):
                continue
            data = payload if info.filename == "assets/build_manifest.pb" else source.read(info)
            out.writestr(info, data)


def clean_temps(paths, temp_root):
    root = Path(temp_root).resolve()
    checked = []
    for raw in paths:
        path = Path(os.path.abspath(raw))
        if path == root or not path.parent.resolve().is_relative_to(root):
            raise ValueError("Refusing to remove a non-temporary path")
        checked.append(path)
    for path in reversed(checked):
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def refresh_fsverity(staging, apk_keys, tools):
    # This generated protobuf module is provided by the same AOSP tool package.
    sys.path.insert(0, str(tools / "bin/fsverity_manifest_generator"))
    from fsverity_digests_pb2 import FSVerityDigests

    staging = Path(staging)
    report = {"manifests": [], "metadata_files": 0}
    for partition in ("SYSTEM", "SYSTEM_EXT"):
        directory = staging / partition / "etc/security/fsverity"
        for apk in sorted(directory.glob("BuildManifest*.apk")):
            with zipfile.ZipFile(apk) as archive:
                old = FSVerityDigests.FromString(archive.read("assets/build_manifest.pb"))
            pairs = []
            for device_path in sorted(old.digests):
                path = manifest_source(staging, partition, device_path)
                if not path.exists() and not path.is_symlink():
                    raise ValueError("Missing fs-verity input: " + device_path)
                if path == apk or "," in str(path) or "\n" in str(path):
                    raise ValueError("Invalid fs-verity input")
                pairs.append(str(path) + "," + device_path)
            key = apk_keys[apk.name]
            if key in ("PRESIGNED", "EXTERNAL"):
                raise ValueError("Cannot update a presigned BuildManifest")
            old_mode = stat.S_IMODE(apk.stat().st_mode)
            with tempfile.TemporaryDirectory(prefix="fsverity-refresh-") as tmp:
                tmp = Path(tmp)
                listing, manifest = tmp / "inputs.txt", tmp / "build_manifest.pb"
                listing.write_text("\n".join(pairs) + "\n")
                subprocess.run([
                    str(tools / "bin/fsverity_manifest_generator"),
                    "--fsverity-path", str(tools / "bin/fsverity"),
                    "--output", str(manifest), "@" + str(listing),
                ], check=True)
                unsigned, aligned, signed = tmp / "unsigned.apk", tmp / "aligned.apk", tmp / "signed.apk"
                replace_manifest_asset(apk, unsigned, manifest.read_bytes())
                subprocess.run([str(tools / "bin/zipalign"), "-f", "4", str(unsigned), str(aligned)], check=True)
                subprocess.run([
                    str(tools / "bin/apksigner"), "sign", "--key", key + ".pk8",
                    "--cert", key + ".x509.pem", "--min-sdk-version", "37",
                    "--v4-signing-enabled", "true", "--out", str(signed), str(aligned),
                ], check=True)
                idsig = Path(str(signed) + ".idsig")
                if not idsig.is_file():
                    raise ValueError("Missing regenerated v4 signature")
                os.replace(signed, apk)
                os.replace(idsig, str(apk) + ".idsig")
                apk.chmod(old_mode)
            report["manifests"].append({"path": str(apk.relative_to(staging)), "entries": len(pairs)})
    for metadata in sorted(staging.rglob("*.fsv_meta")):
        source = Path(str(metadata).removesuffix(".fsv_meta"))
        mode = stat.S_IMODE(metadata.lstat().st_mode)
        subprocess.run([
            str(tools / "bin/fsverity_metadata_generator"), "--fsverity-path", str(tools / "bin/fsverity"),
            "--signature", "none", "--hash-alg", "sha256", "--output", str(metadata), str(source),
        ], check=True)
        if not metadata.is_symlink():
            metadata.chmod(mode)
        report["metadata_files"] += 1
    return report


def main():
    import sign_target_files_apks as signer
    import common
    import apex_utils

    tools = Path(os.environ["OWNER_SIGNING_TOOLS"]).resolve()
    report_path = Path(os.environ["OWNER_SIGNING_REPORT"])
    report = {"complete": False}
    local = threading.local()
    original_dir, original_file = common.MakeTempDir, common.MakeTempFile

    def tracked(original):
        def create(*args, **kwargs):
            path = original(*args, **kwargs)
            if getattr(local, "paths", None) is not None:
                local.paths.append(path)
            return path
        return create

    common.MakeTempDir = tracked(original_dir)
    common.MakeTempFile = tracked(original_file)
    apex_utils.MakeTempFile = common.MakeTempFile
    original_entry = signer.ProcessTargetFileEntries

    def process_entry(*args, **kwargs):
        local.paths = []
        try:
            return original_entry(*args, **kwargs)
        finally:
            clean_temps(local.paths, tempfile.gettempdir())
            local.paths = None

    signer.ProcessTargetFileEntries = process_entry
    original_process = signer.ProcessTargetFiles

    def process_all(input_zip, output_dir, misc, apk_keys, *args):
        report["staging_directory"] = output_dir
        original_process(input_zip, output_dir, misc, apk_keys, *args)
        report["fsverity"] = refresh_fsverity(output_dir, apk_keys, tools)
        report_path.write_text(json.dumps(report, indent=2) + "\n")

    signer.ProcessTargetFiles = process_all
    try:
        signer.main(sys.argv[1:])
        report["complete"] = True
    finally:
        # Keep the signed tree for OTA generation without extracting a second copy.
        retained = report.get("staging_directory")
        common.OPTIONS.tempfiles[:] = [p for p in common.OPTIONS.tempfiles if p != retained]
        common.Cleanup()
        report_path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
