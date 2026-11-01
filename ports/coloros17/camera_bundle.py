"""Stage the exact signed Infinity camera bundle without replacing donor files."""
import argparse
import copy
import json
from pathlib import Path, PurePosixPath
import uuid

from . import candidate, compat
from .build_image import validate_tree
from .fs_metadata import canonical_path
from .runtime_bundle import plan_runtime_bundle

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "camera-bundle.json"


class CameraBundleError(compat.CompatibilityError):
    """Camera staging failure with the verified rollback journal attached."""


def _load_manifest():
    return json.loads(MANIFEST.read_text())


def _safe_path(value, *, destination):
    if not isinstance(value, str):
        raise ValueError("camera path must be a string")
    canonical_path(value if destination else "/" + value)
    path = PurePosixPath(value)
    if value != str(path) or ".." in path.parts or "\0" in value:
        raise ValueError("camera parent traversal or noncanonical path")
    if destination:
        if not path.is_absolute() or not value.startswith("/system/"):
            raise ValueError("camera destination must be in the canonical /system tree")
    elif path.is_absolute() or not value.startswith("payload/"):
        raise ValueError("camera source must be a relative payload path")
    return path


def _make_plan(tree, records, contents, bundle_dir):
    tree = compat._canonical_host(tree, exists=True)
    bundle = compat._canonical_host(bundle_dir, exists=True)
    if tree == bundle or tree in bundle.parents:
        raise ValueError("camera bundle must be outside the canonical tree")
    validate_tree(tree, records, contents)
    spec = _load_manifest()
    if (spec.get("schema_version") != 1 or spec.get("default_camera_changed") is not False
            or spec.get("properties_changed") is not False):
        raise ValueError("unreviewed camera bundle behavior")
    template_path = spec["metadata_template"]
    template = records.get(template_path, {})
    if (template.get("kind") != "file" or template.get("uid") != 0 or template.get("gid") != 0
            or template.get("mode") != 0o100644
            or set(template.get("xattrs", {})) != {"security.selinux"}
            or bytes.fromhex(template["xattrs"]["security.selinux"]).rstrip(b"\0")
            != b"u:object_r:system_file:s0"):
        raise ValueError("camera template must be root:root 0644 system_file")
    _, host = compat._read_regular(tree / template_path[1:])
    host = dict(host, mode=0o644)
    desired, missing_dirs = {}, set()
    sources = set()
    for item in spec["files"]:
        destination = _safe_path(item["path"], destination=True)
        source = _safe_path(item["source"], destination=False)
        if str(destination) in desired or str(source) in sources:
            raise ValueError("duplicate camera source or destination")
        sources.add(str(source))
        data, _ = compat._read_regular(bundle / str(source))
        identity = compat._identity(data)
        if identity["size"] != item["size"] or identity["sha256"] != item["sha256"]:
            raise ValueError(f"camera payload hash/size mismatch: {source}")
        path = str(destination)
        if path in records:
            if (records[path]["kind"] != "file" or contents.get(path) != identity
                    or compat._read_regular(tree / path[1:])[0] != data):
                raise ValueError(f"camera destination conflicts with existing file: {path}")
        for parent in destination.parents:
            name = str(parent)
            if name in records:
                if records[name]["kind"] != "dir":
                    raise ValueError(f"camera parent is not a real directory: {name}")
            else:
                missing_dirs.add(name)
        desired[path] = data
    if not desired:
        raise ValueError("empty camera bundle")
    if missing_dirs.intersection(desired):
        raise ValueError("camera file cannot also be a parent directory")
    final_records, final_contents = copy.deepcopy(records), copy.deepcopy(contents)
    changes, writes = [], []
    for path in sorted(missing_dirs, key=lambda x: (len(PurePosixPath(x).parts), x)):
        final_records[path] = compat._synthetic_record("dir", compat._new_inode(final_records), 0, template)
        changes.append({"path": path, "action": "add", "before": None,
                        "after": {"record": copy.deepcopy(final_records[path]), "content": None}})
        writes.append({"kind": "dir", "path": path, "before": None})
    for path, data in desired.items():
        exists = path in records
        if not exists:
            final_records[path] = compat._synthetic_record("file", compat._new_inode(final_records), len(data), template)
            final_contents[path] = compat._identity(data)
            writes.append({"kind": "file", "path": path, "data": data, "before": None, "host": host})
        before = ({"record": copy.deepcopy(records[path]), "content": copy.deepcopy(contents[path])}
                  if exists else None)
        changes.append({"path": path, "action": "unchanged" if exists else "add", "before": before,
                        "after": {"record": copy.deepcopy(final_records[path]),
                                  "content": copy.deepcopy(final_contents[path])}})
    report = {"status": "planned" if writes else "already_applied", "bundle_id": spec["bundle_id"],
              "canonical_tree": str(tree), "changes": changes,
              "writes": [{"path": w["path"], "kind": w["kind"]} for w in writes],
              "final_records": final_records, "final_content_manifest": final_contents}
    return tree, report, writes


def plan_camera_bundle(tree, records, contents, bundle_dir):
    """Validate every byte and path; return the metadata/content delta without writes."""
    return _make_plan(tree, records, contents, bundle_dir)[1]


def apply_camera_bundle(tree, records, contents, bundle_dir, backup_dir):
    tree, report, writes = _make_plan(tree, records, contents, bundle_dir)
    return compat.apply_change_plan(tree, records, contents, report, writes, backup_dir,
                                    report_name="camera-bundle-report.json",
                                    error_type=CameraBundleError, operation="camera bundle")


def _read_only_state(work):
    path = work / "final-state.json"
    if path.exists():
        state = candidate.read_json(path)
        if (not isinstance(state, dict) or state.get("schema_version") != 1
                or set(state) != {"schema_version", "current", "pending"}):
            raise ValueError("Invalid final manifest state")
        if state["pending"] is not None:
            raise ValueError("Pending transformation requires recovery before a camera dry-run")
    else:
        state = {"schema_version": 1, "pending": None, "current": {
            "records": candidate.read_json(work / "final-records.json"),
            "contents": candidate.read_json(work / "final-contents.json")}}
    candidate._validate_pair(work / "canonical", state["current"])
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    base = args.base.resolve(strict=True)
    work, tree = base / "work", base / "work/canonical"
    candidate._verify_receipts(base, candidate.read_json(HERE / "donor.json"))
    state = _read_only_state(work) if args.dry_run else candidate._load_state(work)
    pair = state["current"]
    if pair is None:
        raise ValueError("Merge and runtime bundle must precede camera staging")
    runtime = plan_runtime_bundle(tree, pair["records"], pair["contents"], base / "inputs/runtime")
    if runtime["status"] != "already_applied":
        raise ValueError("Verified runtime bundle must precede camera staging")
    plan = plan_camera_bundle(tree, pair["records"], pair["contents"], args.bundle_dir)
    if args.dry_run:
        report = {key: plan[key] for key in ("status", "bundle_id", "changes", "writes")}
        report["dry_run"] = True
    elif plan["status"] == "already_applied":
        report = {"status": "already_applied", "stage": "camera", "report": None}
    else:
        after = {"records": plan["final_records"], "contents": plan["final_content_manifest"]}
        backup = work / ("camera-backup-" + uuid.uuid4().hex)
        state["pending"] = {"stage": "camera", "after": after, "backup_dir": str(backup)}
        candidate.write_json(work / "final-state.json", state)
        result = apply_camera_bundle(tree, pair["records"], pair["contents"], args.bundle_dir, backup)
        candidate._validate_pair(tree, after)
        state.update(current=after, pending=None)
        candidate.write_json(work / "final-state.json", state)
        report = {"status": result["status"], "stage": "camera", "report": result["report_path"]}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
