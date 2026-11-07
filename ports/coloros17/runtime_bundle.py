"""Plan and journal the exact live-tested dash runtime bundle on a source tree."""
import copy
import hashlib
import json
from pathlib import Path

from . import compat
from .build_image import validate_tree

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "runtime-bundle.json"
RADIO_PATH = "/my_manifest/build.prop"
RADIO_BEFORE = b"ro.product.vendor.name=CPH2791IN\n"
RADIO_AFTER = b"ro.product.vendor.name=dash_global\n"


class RuntimeBundleError(compat.CompatibilityError):
    """A failed runtime transaction, including its complete rollback report."""


def _load_manifest():
    return json.loads(MANIFEST.read_text())


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _source(item):
    source = compat._canonical_host(HERE / item["source"], exists=True)
    if HERE not in source.parents:
        raise ValueError("runtime source is outside the reviewed recipe")
    data, _ = compat._read_regular(source)
    if _sha(data) != item["sha256"]:
        raise ValueError(f"runtime recipe hash mismatch: {source}")
    return data


def _radio_property(data, spec):
    if (spec.get("path") != RADIO_PATH or spec.get("source_line", "").encode() != RADIO_BEFORE
            or spec.get("replacement_line", "").encode() != RADIO_AFTER):
        raise ValueError("unreviewed radio property target or line")
    digest = _sha(data)
    if digest == spec["sha256"] and len(data) == spec["size"]:
        if data.splitlines(keepends=True).count(RADIO_AFTER) != 1 or RADIO_BEFORE in data:
            raise ValueError("radio replacement line is ambiguous")
        return data, True
    if digest != spec["source_sha256"] or len(data) != spec["source_size"]:
        raise ValueError("unknown radio property source bytes")
    lines = data.splitlines(keepends=True)
    if (lines.count(RADIO_BEFORE) != 1
            or sum(line.startswith(b"ro.product.vendor.name=") for line in lines) != 1):
        raise ValueError("radio property must have exactly one reviewed line")
    result = data.replace(RADIO_BEFORE, RADIO_AFTER, 1)
    if _sha(result) != spec["sha256"] or len(result) != spec["size"]:
        raise ValueError("radio property result differs from the reviewed hash")
    return result, False


def _make_plan(tree, records, contents, artifact_dir):
    tree = compat._canonical_host(tree, exists=True)
    artifacts = compat._canonical_host(artifact_dir, exists=True)
    if tree == artifacts or tree in artifacts.parents:
        raise ValueError("runtime artifacts must be outside the canonical tree")
    validate_tree(tree, records, contents)
    spec = _load_manifest()
    if spec.get("schema_version") != 1 or not isinstance(spec.get("radio_product_override"), dict):
        raise ValueError("unsupported or unreviewed runtime bundle")
    template_path = spec["metadata_template"]
    template = records.get(template_path, {})
    if (template.get("kind") != "file" or template.get("uid") != 0 or template.get("gid") != 0
            or template.get("mode") != 0o100644
            or set(template.get("xattrs", {})) != {"security.selinux"}
            or bytes.fromhex(template["xattrs"]["security.selinux"]).rstrip(b"\0")
            != b"u:object_r:system_file:s0"):
        raise ValueError("runtime template must be root:root 0644 system_file")
    _, new_host = compat._read_regular(tree / template_path[1:])
    new_host = dict(new_host, mode=0o644)
    policy = spec["policy"]
    radio = spec["radio_product_override"]
    existing, hosts = {}, {}
    required = [x["path"] for x in spec["artifacts"]] + [policy["path"], policy["mapping_path"], policy["stamp_path"], radio["path"]]
    for path in required:
        if records.get(path, {}).get("kind") != "file":
            raise ValueError(f"runtime input must be a regular file: {path}")
        data, host = compat._read_regular(tree / path[1:])
        if compat._identity(data) != contents[path]:
            raise ValueError(f"runtime input changed after validation: {path}")
        existing[path], hosts[path] = data, host
    desired, applied = {}, []
    for item in spec["artifacts"]:
        if Path(item["file"]).name != item["file"]:
            raise ValueError("runtime artifact must be a basename")
        data, _ = compat._read_regular(artifacts / item["file"])
        if len(data) != item["size"] or _sha(data) != item["sha256"]:
            raise ValueError(f"runtime artifact hash/size mismatch: {item['file']}")
        path = item["path"]
        current = _sha(existing[path])
        if current not in {item["source_sha256"], item["sha256"]}:
            raise ValueError(f"unknown runtime source bytes: {path}")
        desired[path] = data
        applied.append(current == item["sha256"])
    radio_data, radio_applied = _radio_property(existing[radio["path"]], radio)
    desired[radio["path"]] = radio_data
    applied.append(radio_applied)
    mapping = existing[policy["mapping_path"]]
    if _sha(mapping) != policy["mapping_sha256"]:
        raise ValueError("runtime mapping does not match the pinned 202604 input")
    data = existing[policy["path"]]
    digest = _sha(data)
    if digest == policy["sha256"]:
        final_policy = data
        applied.append(True)
    elif digest == policy["source_sha256"]:
        fragments = [_source(item) for item in policy["fragments"]]
        final_policy = data + b"\n" + b"\n".join(fragments)
        if _sha(final_policy) != policy["sha256"]:
            raise ValueError("runtime policy result differs from the reviewed hash")
        applied.append(False)
    else:
        raise ValueError("unknown runtime policy bytes; require reviewed composer baseline")
    desired[policy["path"]] = final_policy
    stamp = (_sha(final_policy + mapping) + "\n").encode()
    current_stamp = existing[policy["stamp_path"]]
    if current_stamp == stamp:
        applied.append(True)
    elif _sha(current_stamp) in policy["accepted_source_stamp_sha256"]:
        applied.append(False)
    else:
        raise ValueError("unknown runtime policy hash stamp")
    desired[policy["stamp_path"]] = stamp
    for item in spec["additions"]:
        path, data = item["path"], _source(item)
        if records.get(str(Path(path).parent), {}).get("kind") != "dir":
            raise ValueError(f"runtime addition parent must exist: {path}")
        if path in records:
            if (not compat._same_synthetic_record(records, path, "file", len(data), template)
                    or contents.get(path) != compat._identity(data)
                    or compat._read_regular(tree / path[1:])[0] != data):
                raise ValueError(f"unknown existing runtime addition: {path}")
            applied.append(True)
        else:
            applied.append(False)
        desired[path] = data
    if any(applied) and not all(applied):
        raise ValueError("partial runtime bundle; require all original or all reviewed results")
    done = all(applied)
    final_records, final_contents = copy.deepcopy(records), copy.deepcopy(contents)
    changes, writes = [], []
    for path, data in desired.items():
        before = ({"record": copy.deepcopy(records[path]), "content": copy.deepcopy(contents[path])}
                  if path in records else None)
        if path not in records:
            final_records[path] = compat._synthetic_record("file", compat._new_inode(final_records), len(data), template)
        final_records[path]["size"] = len(data)
        final_contents[path] = compat._identity(data)
        changes.append({"path": path, "action": "unchanged" if done else "replace" if before else "add",
                        "before": before, "after": {"record": copy.deepcopy(final_records[path]),
                                                      "content": copy.deepcopy(final_contents[path])}})
        if not done:
            writes.append({"kind": "file", "path": path, "data": data,
                           "before": existing.get(path), "host": hosts.get(path, new_host)})
    report = {"status": "already_applied" if done else "planned", "bundle_id": spec["bundle_id"],
              "canonical_tree": str(tree), "policy_sha256": policy["sha256"],
              "policy_stamp": stamp.decode().strip(), "changes": changes,
              "writes": [{"path": x["path"], **compat._identity(x["data"])} for x in writes],
              "final_records": final_records, "final_content_manifest": final_contents}
    return tree, report, writes


def plan_runtime_bundle(tree, records, contents, artifact_dir):
    """Return exact JSON-safe writes and the new metadata/content pair, without mutations."""
    return _make_plan(tree, records, contents, artifact_dir)[1]


def apply_runtime_bundle(tree, records, contents, artifact_dir, backup_dir):
    """Apply the pinned bundle, retaining original bytes and a verified rollback journal."""
    tree, report, writes = _make_plan(tree, records, contents, artifact_dir)
    return compat.apply_change_plan(tree, records, contents, report, writes, backup_dir,
                                    report_name="runtime-bundle-report.json",
                                    error_type=RuntimeBundleError, operation="runtime bundle")
