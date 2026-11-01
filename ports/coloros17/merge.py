"""Preservation-oriented, same-filesystem SAR merge of disposable unpacked trees.

File bytes are never copied or rewritten. Donor metadata, not host ownership or
directory sizes, remains authoritative. Callers must keep sources exclusively
owned and quiescent while merging; raw input images are outside this API.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from ports.coloros17.fs_metadata import canonical_path


class MergeError(RuntimeError):
    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


_PARTITION = re.compile(r"(?:system|product|system_ext|my_[a-z0-9_]+)\Z")
_TYPES = {"dir": stat.S_IFDIR, "file": stat.S_IFREG, "symlink": stat.S_IFLNK}


def _check_manifests(manifests):
    if not isinstance(manifests, dict) or not {"system", "product", "system_ext"} <= manifests.keys():
        raise ValueError("system, product and system_ext manifests are required")
    for partition, records in manifests.items():
        if not isinstance(partition, str) or not _PARTITION.fullmatch(partition):
            raise ValueError(f"unsupported partition: {partition!r}")
        if not isinstance(records, dict) or "/" not in records:
            raise ValueError(f"missing root record: {partition}")
        inodes = set()
        for path, record in records.items():
            canonical_path(path)
            if not isinstance(record, dict) or record.get("kind") not in _TYPES:
                raise ValueError(f"invalid inode kind: {partition}:{path}")
            for field in ("uid", "gid", "mode", "inode", "size"):
                if type(record.get(field)) is not int or record[field] < 0:
                    raise ValueError(f"invalid {field}: {partition}:{path}")
            if stat.S_IFMT(record["mode"]) != _TYPES[record["kind"]] or not isinstance(record.get("xattrs"), dict):
                raise ValueError(f"invalid inode metadata: {partition}:{path}")
            if path == "/":
                if record["kind"] != "dir":
                    raise ValueError(f"root is not a directory: {partition}")
            else:
                parent = path.rsplit("/", 1)[0] or "/"
                if records.get(parent, {}).get("kind") != "dir":
                    raise ValueError(f"missing directory parent: {partition}:{path}")
            if record["kind"] == "symlink" and (
                not isinstance(record.get("symlink_target"), str) or "\0" in record["symlink_target"]
            ):
                raise ValueError(f"missing/invalid symlink target: {partition}:{path}")
            if record["kind"] != "dir":
                if record["inode"] in inodes:
                    raise ValueError(f"hardlink manifests are not supported: {partition}:{path}")
                inodes.add(record["inode"])
    if manifests["system"].get("/system", {}).get("kind") != "dir":
        raise ValueError("system image must have a SAR /system directory")


def _empty_directory(records, path):
    return (records.get(path, {}).get("kind") == "dir"
            and not any(p.startswith(path + "/") for p in records))


def _trusted_label(record, path):
    value = record.get("xattrs", {}).get("security.selinux")
    try:
        label = bytes.fromhex(value).removesuffix(b"\0").decode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError(f"missing trusted SELinux context for alias: {path}") from exc
    if label.count(":") < 3 or not label or any(c.isspace() or ord(c) < 32 for c in label):
        raise ValueError(f"invalid trusted SELinux context for alias: {path}")
    return value


def plan_merge(manifests):
    """Return a pure plan, including final metadata and every changed placeholder."""
    _check_manifests(manifests)
    system = manifests["system"]
    final = copy.deepcopy(system)
    provenance = {p: {"partition": "system", "source_path": p} for p in system}
    changes = []
    placements = {"system": "/"}
    next_inode = max(r["inode"] for records in manifests.values() for r in records.values()) + 1
    for partition in ["product", "system_ext"] + sorted(p for p in manifests if p.startswith("my_")):
        target = "/system/" + partition if partition in ("product", "system_ext") else "/" + partition
        placements[partition] = target
        old = system.get(target)
        if partition in ("product", "system_ext"):
            expected_link = old and old["kind"] == "symlink" and old["symlink_target"] == "/" + partition
            if not expected_link and not _empty_directory(system, target):
                raise ValueError(f"expected symlink or empty mountpoint: {target}")
            alias = "/" + partition
            if not _empty_directory(system, alias):
                raise ValueError(f"expected empty root mountpoint: {alias}")
            context_source = old if expected_link else system["/"]
            label = _trusted_label(context_source, target if expected_link else "/")
            if expected_link:
                alias_record = copy.deepcopy(old)
            else:
                alias_record = {
                    "uid": context_source["uid"], "gid": context_source["gid"],
                    "mode": stat.S_IFLNK | 0o777, "inode": next_inode,
                    "size": 0, "kind": "symlink", "xattrs": {"security.selinux": label},
                }
                next_inode += 1
            alias_record.update(symlink_target=target, size=len(target.encode("utf-8")))
            changes.append({"path": alias, "action": "replace_empty_directory_with_alias",
                            "before": copy.deepcopy(system[alias]), "after": copy.deepcopy(alias_record)})
            final[alias] = alias_record
            provenance[alias] = {"partition": "system", "source_path": target if expected_link else "/",
                                 "synthetic_alias": True}
        elif old is not None and not _empty_directory(system, target):
            raise ValueError(f"nonempty or unexpected partition placeholder: {target}")
        changes.append({"path": target, "action": "install_partition_root",
                        "before": copy.deepcopy(old), "after": copy.deepcopy(manifests[partition]["/"])})
        final.pop(target, None)
        provenance.pop(target, None)
        for path, record in manifests[partition].items():
            destination = target if path == "/" else target + path
            canonical_path(destination)
            if destination in final:
                raise ValueError(f"partition content conflicts at {destination}")
            final[destination] = copy.deepcopy(record)
            provenance[destination] = {"partition": partition, "source_path": path}
    return {"schema_version": 1, "placements": placements,
            "final_records": dict(sorted(final.items())), "provenance": dict(sorted(provenance.items())),
            "declared_placeholder_changes": changes}


def _inventory(root, records, device):
    """Compare exact paths/types and byte lengths, without reading file content."""
    found = {}
    pending = [(root, "/")]
    while pending:
        actual, relative = pending.pop()
        info = os.lstat(actual)
        if info.st_dev != device:
            raise ValueError(f"different filesystem at {actual}")
        record = records.get(relative)
        if record is None or stat.S_IFMT(info.st_mode) != _TYPES[record["kind"]]:
            raise ValueError(f"unexpected/mismatched physical entry: {actual}")
        if record["kind"] == "dir":
            for child in actual.iterdir():
                name = relative.rstrip("/") + "/" + child.name
                canonical_path(name)
                pending.append((child, name))
        else:
            if info.st_nlink != 1:
                raise ValueError(f"physical hardlink is not supported: {actual}")
            if info.st_size != record["size"]:
                raise ValueError(f"physical file/symlink size changed: {actual}")
            if record["kind"] == "symlink" and os.readlink(actual) != record["symlink_target"]:
                raise ValueError(f"physical symlink target changed: {actual}")
        found[relative] = (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                           info.st_mtime_ns, info.st_ctime_ns)
    if found.keys() != records.keys():
        raise ValueError(f"physical entries missing below {root}")
    return found


def _write_journal(path, report, *, first=False):
    data = json.dumps(report, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if first:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_merge(sources, destination, manifests):
    """Move verified disposable trees transactionally; retain journal/placeholders.

    All input validation precedes mutation. On operational failure, reverse the
    completed moves and raise MergeError carrying the recovery report. A process
    crash still requires inspecting the persisted journal's pending operation.
    Directory host st_size is intentionally not compared to donor on-disk size.
    """
    plan = plan_merge(manifests)
    if not isinstance(sources, dict) or sources.keys() != manifests.keys():
        raise ValueError("source paths and manifest partitions must match exactly")
    destination = Path(destination).absolute()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", destination.name):
        raise ValueError("unsafe destination name")
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    journal = parent / ("." + destination.name + ".merge-journal.json")
    if os.path.lexists(destination) or os.path.lexists(journal):
        raise ValueError("destination or prior merge journal already exists")
    device = os.lstat(parent).st_dev
    roots = {}
    snapshots = {}
    for name, source in sources.items():
        source = Path(source).absolute()
        if not stat.S_ISDIR(os.lstat(source).st_mode):
            raise ValueError(f"source is not a real directory: {source}")
        source = source.resolve(strict=True)
        if destination.is_relative_to(source) or source.is_relative_to(destination):
            raise ValueError("destination overlaps source")
        if any(source.is_relative_to(other) or other.is_relative_to(source) for other in roots.values()):
            raise ValueError("source trees overlap")
        roots[name] = source
        snapshots[name] = _inventory(source, manifests[name], device)
    # Recheck all snapshots together before creating any transaction artifacts.
    for name, source in roots.items():
        if _inventory(source, manifests[name], device) != snapshots[name]:
            raise ValueError(f"source changed during preflight: {source}")
    report = {"schema_version": 1, "status": "prepared", "destination": str(destination),
              "sources": {p: str(s) for p, s in roots.items()}, "journal_path": str(journal),
              "manifest_sha256": hashlib.sha256(json.dumps(manifests, sort_keys=True).encode()).hexdigest(),
              "placements": plan["placements"],
              "declared_placeholder_changes": plan["declared_placeholder_changes"],
              "operations": [], "pending": None, "rollback_operations": [], "rollback_errors": []}
    _write_journal(journal, report, first=True)
    completed = []

    def identity(path):
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        return {"device": info.st_dev, "inode": info.st_ino, "type": stat.S_IFMT(info.st_mode)}

    def perform(action):
        if action["kind"] == "rename":
            action["source_identity"] = identity(action["from"])
            if action["source_identity"] is None:
                raise FileNotFoundError(action["from"])
            if os.path.lexists(action["to"]):
                raise FileExistsError(action["to"])
        elif os.path.lexists(action["path"]):
            raise FileExistsError(action["path"])
        report["pending"] = action
        _write_journal(journal, report)
        if action["kind"] == "rename":
            if os.path.lexists(action["to"]):
                raise FileExistsError(action["to"])
            os.rename(action["from"], action["to"])
        else:
            os.symlink(action["target"], action["path"])
        completed.append(action)
        report["operations"].append(action)
        report["pending"] = None
        _write_journal(journal, report)

    def reconcile_pending():
        # A signal may arrive after the syscall has taken effect but before
        # Python appends it to completed. Inspect the persisted intent rather
        # than assuming the syscall failed. Never guess when identities differ.
        action = report["pending"]
        if action is None:
            return
        if action in completed:
            if action not in report["operations"]:
                report["operations"].append(action)
            return
        if action["kind"] == "rename":
            source, target = identity(action["from"]), identity(action["to"])
            expected = action["source_identity"]
            if source is None and target == expected:
                outcome = "completed"
            elif source == expected and target is None:
                outcome = "not_applied"
            else:
                outcome = "ambiguous"
        elif not os.path.lexists(action["path"]):
            outcome = "not_applied"
        elif Path(action["path"]).is_symlink() and os.readlink(action["path"]) == action["target"]:
            outcome = "completed"
        else:
            outcome = "ambiguous"
        report["pending_reconciliation"] = outcome
        if outcome == "completed":
            completed.append(action)
            report["operations"].append(action)
        elif outcome == "ambiguous":
            report["rollback_errors"].append(f"pending operation has ambiguous filesystem state: {action}")

    try:
        stage = Path(tempfile.mkdtemp(prefix="." + destination.name + ".merge-", dir=parent))
        report["staging_path"] = str(stage)
        report["status"] = "merging"
        tree = stage / "tree"
        backups = stage / "placeholders"
        backups.mkdir()
        perform({"kind": "rename", "from": str(roots["system"]), "to": str(tree)})
        for partition, target in plan["placements"].items():
            if partition == "system":
                continue
            path = tree / target.lstrip("/")
            if os.path.lexists(path):
                perform({"kind": "rename", "from": str(path), "to": str(backups / (partition + "-nested"))})
            if partition in ("product", "system_ext"):
                alias = tree / partition
                perform({"kind": "rename", "from": str(alias), "to": str(backups / (partition + "-root"))})
            perform({"kind": "rename", "from": str(roots[partition]), "to": str(path)})
            if partition in ("product", "system_ext"):
                perform({"kind": "symlink", "path": str(tree / partition), "target": target})
        _inventory(tree, plan["final_records"], device)
        perform({"kind": "rename", "from": str(tree), "to": str(destination)})
        report["status"] = "complete"
        _write_journal(journal, report)
    except BaseException as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
        report["failed_operation"] = report["pending"]
        try:
            reconcile_pending()
        except Exception as reconciliation_error:
            report["rollback_errors"].append(f"cannot reconcile pending operation: {reconciliation_error}")
        for action in reversed(completed):
            try:
                if action["kind"] == "rename":
                    if os.path.lexists(action["from"]):
                        raise FileExistsError(action["from"])
                    os.rename(action["to"], action["from"])
                else:
                    if not Path(action["path"]).is_symlink() or os.readlink(action["path"]) != action["target"]:
                        raise ValueError("rollback alias changed")
                    os.unlink(action["path"])
                report["rollback_operations"].append(action)
            except Exception as rollback_error:
                report["rollback_errors"].append(f"{action}: {rollback_error}")
        if not report["rollback_errors"]:
            try:
                for name, source in roots.items():
                    restored = _inventory(source, manifests[name], device)
                    if any(restored[p][:3] != snapshots[name][p][:3] for p in restored):
                        raise ValueError(f"restored source inode identity changed: {source}")
            except Exception as verification_error:
                report["rollback_errors"].append(f"restored sources failed verification: {verification_error}")
        report["status"] = "failed_needs_recovery" if report["rollback_errors"] else "failed_rolled_back"
        if not report["rollback_errors"]:
            report["pending"] = None
        try:
            _write_journal(journal, report)
        except Exception as journal_error:
            report["journal_error"] = str(journal_error)
        if not isinstance(exc, Exception):
            raise
        raise MergeError(report["failure"], report) from exc
    return report | {"final_records": plan["final_records"], "provenance": plan["provenance"],
                     "declared_placeholder_changes": plan["declared_placeholder_changes"]}
