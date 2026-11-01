"""Run reviewed host-only ColorOS construction stages; never flash a device.

``work/final-state.json`` atomically stores the metadata/content pair and any
pending transformation. Existing final-records.json/final-contents.json are
validated and imported once, then left untouched. Keep this workspace
exclusively owned and quiescent, as required by the transformation helpers.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import uuid

from .preflight import validate
from .merge import apply_merge, plan_merge
from .compat import apply_compatibility, plan_compatibility
from .build_image import build_image, validate_tree

HERE = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_pair(tree, pair):
    if not isinstance(pair, dict) or set(pair) != {"records", "contents"}:
        raise ValueError("Invalid final manifest pair")
    validate_tree(tree, pair["records"], pair["contents"])


def _matches(tree, pair):
    try:
        _validate_pair(tree, pair)
    except (OSError, ValueError):
        return False
    return True


def _load_state(work):
    """Recover only a completely verified before/after state; retain journals."""
    path = work / "final-state.json"
    tree = work / "canonical"
    if not path.exists():
        records, contents = work / "final-records.json", work / "final-contents.json"
        state = {"schema_version": 1, "current": None, "pending": None}
        if records.exists() or contents.exists():
            pair = {"records": read_json(records), "contents": read_json(contents)}
            _validate_pair(tree, pair)
            state["current"] = pair
            write_json(path, state)
        elif os.path.lexists(tree):
            raise ValueError("Canonical tree has no authoritative manifest state")
        return state
    state = read_json(path)
    if (not isinstance(state, dict) or state.get("schema_version") != 1
            or set(state) != {"schema_version", "current", "pending"}):
        raise ValueError("Invalid final manifest state")
    pending = state["pending"]
    if pending is not None:
        if not isinstance(pending, dict) or pending.get("stage") not in {"merge", "patch"}:
            raise ValueError("Invalid pending transformation state; recovery required")
        if _matches(tree, pending.get("after")):
            state["current"] = pending["after"]
        elif pending["stage"] == "patch" and _matches(tree, state["current"]):
            pass
        elif (pending["stage"] == "merge" and state["current"] is None
              and not os.path.lexists(tree) and isinstance(pending.get("sources"), dict)
              and pending["sources"] and all(
                  _matches(work / "parts" / name, pair)
                  for name, pair in pending["sources"].items())):
            # A failed helper or a crash before its first move can leave a
            # journal even though every original tree is intact. Retain it
            # under a fresh name so the helper can safely start a new attempt.
            # Unknown staging directories remain untouched for inspection.
            journal = work / ".canonical.merge-journal.json"
            if os.path.lexists(journal):
                history = work / (".canonical.merge-journal.history-" + uuid.uuid4().hex + ".json")
                os.rename(journal, history)
                directory = os.open(work, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        else:
            raise ValueError("Incomplete transformation needs recovery; neither complete state matches")
        state["pending"] = None
        write_json(path, state)
    if state["current"] is not None:
        _validate_pair(tree, state["current"])
    elif os.path.lexists(tree):
        raise ValueError("Canonical tree has no authoritative manifest pair; recovery required")
    return state


def _source_pair(records, contents):
    """Normalize the extraction manifest without inferring missing entries."""
    if not isinstance(contents, dict):
        raise ValueError("Source content manifest must be a dictionary")
    normalized = {}
    for path, item in contents.items():
        if not isinstance(item, dict):
            raise ValueError(f"Invalid source content entry: {path}")
        if item.get("kind") == "file":
            normalized[path] = {"kind": "file", "size": item.get("bytes"),
                                "sha256": item.get("sha256")}
        else:
            normalized[path] = copy.deepcopy(item)
    return {"records": records, "contents": normalized}


def _prepare_merge(work, names):
    sources = {}
    for name in names:
        pair = _source_pair(read_json(work / "inode-manifests" / (name + ".json")),
                            read_json(work / "inode-manifests" / (name + "-contents.json")))
        _validate_pair(work / "parts" / name, pair)
        sources[name] = pair
    plan = plan_merge({name: pair["records"] for name, pair in sources.items()})
    contents = {}
    for path, record in plan["final_records"].items():
        if record["kind"] == "symlink":
            contents[path] = {"kind": "symlink", "target": record["symlink_target"]}
        elif record["kind"] == "file":
            origin = plan["provenance"][path]
            contents[path] = copy.deepcopy(sources[origin["partition"]]["contents"][origin["source_path"]])
    return sources, {"records": plan["final_records"], "contents": contents}


def _verify_receipts(base, donor):
    archive = read_json(base / "inputs/download-verification.json")
    if (archive.get("sha256") != donor["archive_sha256"] or
            type(archive.get("bytes")) is not int or archive["bytes"] != donor["archive_bytes"] or
            archive.get("md5") != donor["expected_md5"] or archive.get("md5_matches") is not True):
        raise ValueError("Verified archive record differs from the pinned donor")
    payload = read_json(base / "control/payload-verification.json")
    if (payload.get("payload_hash_verified") is not True or
            payload.get("payload_sha256") != donor["expected_payload_sha256"] or
            type(payload.get("payload_bytes")) is not int or
            payload["payload_bytes"] != donor["expected_payload_bytes"]):
        raise ValueError("Full payload verification must match the pinned donor")
    signature = read_json(base / "control/ota-signature-verification.json")
    if (signature.get("cryptographic_signature_valid") is not True or
            signature.get("archive_sha256") != donor["archive_sha256"]):
        raise ValueError("OTA signature consistency verification must match the pinned donor")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=HERE / "profile.json")
    parser.add_argument("--stage", choices=["merge", "patch", "build"], required=True)
    args = parser.parse_args(argv)
    profile = read_json(args.profile)
    validate(read_json(HERE / "donor-metadata.json"), read_json(HERE / "payload-summary.json"), profile)
    base = args.base.resolve(strict=True)
    work = base / "work"
    _verify_receipts(base, read_json(HERE / "donor.json"))
    state_path = work / "final-state.json"
    state = _load_state(work)
    tree = work / "canonical"
    if args.stage == "merge":
        if state["current"] is not None:
            report = {"status": "already_applied", "stage": "merge",
                      "inodes": len(state["current"]["records"])}
        else:
            sources, after = _prepare_merge(work, profile["required_partitions"])
            state["pending"] = {"stage": "merge", "sources": sources, "after": after}
            write_json(state_path, state)
            result = apply_merge({name: work / "parts" / name for name in sources}, tree,
                                 {name: pair["records"] for name, pair in sources.items()})
            _validate_pair(tree, after)
            state.update(current=after, pending=None)
            write_json(state_path, state)
            write_json(base / "control/merge-report.json", result)
            report = {"status": result["status"], "stage": "merge", "inodes": len(after["records"])}
    elif args.stage == "patch":
        pair = state["current"]
        if pair is None:
            raise ValueError("Merge must complete before compatibility patching")
        plan = plan_compatibility(tree, pair["records"], pair["contents"])
        if plan["status"] == "already_applied":
            report = {"status": "already_applied", "stage": "patch", "report": None}
        else:
            after = {"records": plan["final_records"], "contents": plan["final_content_manifest"]}
            backup = work / ("compat-backup-" + uuid.uuid4().hex)
            state["pending"] = {"stage": "patch", "after": after, "backup_dir": str(backup)}
            write_json(state_path, state)
            result = apply_compatibility(tree, pair["records"], pair["contents"], backup)
            _validate_pair(tree, after)
            state.update(current=after, pending=None)
            write_json(state_path, state)
            report = {"status": result["status"], "stage": "patch", "report": result["report_path"]}
    else:
        pair = state["current"]
        if pair is None:
            raise ValueError("Merge must complete before building")
        plan = plan_compatibility(tree, pair["records"], pair["contents"])
        if plan["status"] != "already_applied":
            raise ValueError("Required compatibility patches must be applied before building")
        native = read_json(HERE / "native-tools.json")
        paths = {name: "/srv/infinity/out/host/linux-x86/bin/" + name for name in ["mke2fs", "e2fsdroid"]}
        hashes = {name: native["hashes"][name] for name in paths}
        for name in ["debugfs", "e2fsck"]:
            paths[name] = native["system_tools"][name]["path"]
            hashes[name] = native["system_tools"][name]["sha256"]
        result = build_image(tree, pair["records"], pair["contents"],
                             base / "output/ColorOS17-PLG110-dash-lab.img", base / "sources/mysticgsi",
                             paths, hashes)
        report = {key: result.get(key) for key in ["status", "output", "image_bytes", "sha256", "report_path"]}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
