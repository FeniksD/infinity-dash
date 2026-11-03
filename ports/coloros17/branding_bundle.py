"""Install only the reviewed port credits and Settings overlay."""
import copy
import hashlib
import json
from pathlib import Path

from . import compat
from .build_image import validate_tree

HERE = Path(__file__).resolve().parent


def _load_manifest():
    return json.loads((HERE / "branding-bundle.json").read_text())


def _make_plan(tree, records, contents, artifact_dir):
    tree = compat._canonical_host(tree, exists=True)
    artifacts = compat._canonical_host(artifact_dir, exists=True)
    if artifacts == tree or tree in artifacts.parents:
        raise ValueError("branding inputs must be outside the canonical tree")
    validate_tree(tree, records, contents)
    spec = _load_manifest()
    allowed = {"/system/etc/feniksd-port-info.txt", "/system/system_ext/overlay/FeniksDAboutOverlay.apk"}
    if spec.get("schema_version") != 1 or {f["path"] for f in spec["files"]} != allowed or len(spec["files"]) != 2:
        raise ValueError("unreviewed branding targets")
    settings, _ = compat._read_regular(tree / "system/system_ext/priv-app/Settings/Settings.apk")
    if hashlib.sha256(settings).hexdigest() != spec["settings_apk_sha256"]:
        raise ValueError("branding overlay targets another Settings APK")
    template = records[spec["metadata_template"]]
    if (template["kind"] != "file" or template["uid"] != 0 or template["gid"] != 0
            or template["mode"] != 0o100644 or set(template["xattrs"]) != {"security.selinux"}
            or bytes.fromhex(template["xattrs"]["security.selinux"]).rstrip(b"\0") != b"u:object_r:system_file:s0"):
        raise ValueError("invalid branding metadata template")
    _, host = compat._read_regular(tree / spec["metadata_template"][1:])
    host = dict(host, mode=0o644)
    final_records, final_contents = copy.deepcopy(records), copy.deepcopy(contents)
    changes, writes = [], []
    for item in spec["files"]:
        name = item.get("source", item.get("artifact"))
        if name not in {"PORT_INFO.txt", "FeniksDAboutOverlay.apk"}:
            raise ValueError("unexpected branding input")
        data, _ = compat._read_regular((HERE if "source" in item else artifacts) / name)
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("branding input hash mismatch")
        path, identity = item["path"], compat._identity(data)
        if records.get(str(Path(path).parent), {}).get("kind") != "dir":
            raise ValueError("branding parent must already exist")
        exists = path in records
        action = "add"
        if exists:
            previous, previous_host = compat._read_regular(tree / path[1:])
            previous_identity = compat._identity(previous)
            if (not compat._same_synthetic_record(records, path, "file", len(previous), template)
                    or contents.get(path) != previous_identity):
                raise ValueError("unknown existing branding file")
            if previous == data:
                action = "unchanged"
            elif (path == "/system/system_ext/overlay/FeniksDAboutOverlay.apk"
                    and previous_identity in item.get("replaces", [])):
                action = "replace"
                final_records[path]["size"] = len(data)
                final_contents[path] = identity
                writes.append({"kind": "file", "path": path, "data": data,
                               "before": previous, "host": previous_host})
            else:
                raise ValueError("unknown existing branding file")
        else:
            final_records[path] = compat._synthetic_record("file", compat._new_inode(final_records), len(data), template)
            final_contents[path] = identity
            writes.append({"kind": "file", "path": path, "data": data, "before": None, "host": host})
        changes.append({"path": path, "action": action,
                        "before": {"record": copy.deepcopy(records[path]), "content": copy.deepcopy(contents[path])} if exists else None,
                        "after": {"record": copy.deepcopy(final_records[path]), "content": identity}})
    report = {"status": "planned" if writes else "already_applied", "bundle_id": spec["bundle_id"],
              "canonical_tree": str(tree), "changes": changes,
              "writes": [{"path": w["path"], **compat._identity(w["data"])} for w in writes],
              "final_records": final_records, "final_content_manifest": final_contents}
    return tree, report, writes


def plan_branding_bundle(tree, records, contents, artifact_dir):
    return _make_plan(tree, records, contents, artifact_dir)[1]


def apply_branding_bundle(tree, records, contents, artifact_dir, backup_dir):
    tree, report, writes = _make_plan(tree, records, contents, artifact_dir)
    return compat.apply_change_plan(tree, records, contents, report, writes, backup_dir,
                                    report_name="branding-report.json", operation="port branding")
