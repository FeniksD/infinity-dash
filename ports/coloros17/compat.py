"""Five exact source-tree compatibility fixes for official PLG110 ColorOS 17.

This operates on an exclusively owned, quiescent canonical SAR tree, never an
image, mount or device. Donor inode metadata lives in the supplied complete
records, independently of host ownership. Every input file is hash-checked
before mutation. Successful results can be fed back for a read-only no-op.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from ports.coloros17.build_image import validate_tree


GENFS_PATH = "/system/etc/selinux/plat_sepolicy_genfs_202604.cil"
INIT_PATH = "/system/etc/init/hw/init.rc"
MATRIX_PATH = "/system/etc/vintf/compatibility_matrix.dash-additions.xml"
TEMPLATE_PATH = "/system/etc/vintf/compatibility_matrix.device.xml"
SKIP_PARENT_PATH = "/system/system_ext/etc/init"
SKIP_DIR_PATH = SKIP_PARENT_PATH + "/config"
SKIP_MOUNT_PATH = SKIP_DIR_PATH + "/skip_mount.cfg"
SKIP_MOUNT_BYTES = b"/system_ext\n/product\n"
COMPOSER_POLICY_PATH = "/system/system_ext/etc/selinux/system_ext_sepolicy.cil"
COMPOSER_BEFORE_SHA256 = "a9176d643c44e2bade190fa39fca99d9962eb572aa6e94e907aab18cd3051251"
COMPOSER_LEGACY_ALLOW_SHA256 = "fe5c16850894a465381f568e0637610649378b11465d7b00a79f377f3236d528"
COMPOSER_AFTER_SHA256 = "799bb07e4a6296eff3af52a15f03edd0c56e21001b1b096a002de4d9dae8fbcc"
# Vendor grants service discovery to this attribute and excludes its members
# from the corresponding neverallow; a standalone direct allow is insufficient.
_COMPOSER_RULE = b"(typeattributeset hal_mtk_composer_ext_client (surfaceflinger))\n"
_COMPOSER_LEGACY_ALLOW = b"(allow surfaceflinger mtk_hal_composer_ext_service (service_manager (find)))\n"
GENFS_BEFORE_SHA256 = "ce8b599e06d363155930549e845c0d4d234c0d9a5eb35a2f680ea6f51530b581"
GENFS_AFTER_SHA256 = "a5fa3e379955f4209a38c161da7aebdc917b8c693ebd3992ae6eb57ab22d06e8"
_POWER_LINES = (
    b'(genfscon sysfs "/class/powercap" (u object_r sysfs_powercap ((s0) (s0))))\n',
    b'(genfscon sysfs "/devices/virtual/powercap" (u object_r sysfs_powercap ((s0) (s0))))\n',
)
_BOOTSTRAP = b"    exec_start apexd-bootstrap\n"
_RESTORECON = b"    restorecon /dev/loop-control\n"
_SOURCE_MATRIX = Path(__file__).resolve().parent / "patches/compatibility_matrix.dash-additions.xml"


class CompatibilityError(RuntimeError):
    """An operational failure; report states whether rollback was complete."""

    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def _identity(data):
    return {"kind": "file", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _canonical_host(path, *, exists):
    path = Path(path).absolute()
    if path != path.resolve(strict=exists):
        raise ValueError(f"host path must be canonical and contain no symlinks: {path}")
    return path


def _open_parent(path):
    """Open every directory component without following symlinks."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("internal host path must be absolute")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parent.parts[1:]:
            newer = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = newer
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_regular(path):
    parent = _open_parent(path)
    try:
        descriptor = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError(f"expected a single regular file: {path}")
            attrs = {name: os.getxattr(source.fileno(), name)
                     for name in os.listxattr(source.fileno())}
            data = source.read()
            after = os.fstat(source.fileno())
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError(f"file changed while reading: {path}")
            host = {"uid": before.st_uid, "gid": before.st_gid,
                    "mode": stat.S_IMODE(before.st_mode), "atime_ns": before.st_atime_ns,
                    "mtime_ns": before.st_mtime_ns, "xattrs": attrs}
            return data, host
    finally:
        os.close(parent)


def _genfs(data):
    digest = hashlib.sha256(data).hexdigest()
    if digest == GENFS_AFTER_SHA256:
        if any(line in data for line in _POWER_LINES):
            raise ValueError("patched genfs unexpectedly contains a powercap rule")
        return data, True
    if digest != GENFS_BEFORE_SHA256:
        raise ValueError("genfs does not match the pinned official PLG110 donor")
    result = data
    for line in _POWER_LINES:
        if result.splitlines(keepends=True).count(line) != 1:
            raise ValueError("genfs powercap rule is absent or ambiguous")
        result = result.replace(line, b"", 1)
    if hashlib.sha256(result).hexdigest() != GENFS_AFTER_SHA256:
        raise ValueError("genfs transformation differs from the reviewed result")
    return result, False


def _init(data):
    if (data.splitlines(keepends=True).count(_BOOTSTRAP) != 1
            or data.count(b"exec_start apexd-bootstrap") != 1):
        raise ValueError("init must have one exact apexd-bootstrap command")
    occurrences = data.count(b"restorecon /dev/loop-control")
    if occurrences:
        if (occurrences == 1 and data.splitlines(keepends=True).count(_RESTORECON) == 1
                and data.count(_RESTORECON + _BOOTSTRAP) == 1):
            return data, True
        raise ValueError("loop-control restorecon is ambiguous or in the wrong location")
    return data.replace(_BOOTSTRAP, _RESTORECON + _BOOTSTRAP, 1), False


def _composer_policy(data):
    """Use the vendor client attribute, migrating the exact temporary direct allow."""
    digest = hashlib.sha256(data).hexdigest()
    if digest == COMPOSER_AFTER_SHA256:
        if (not data.endswith(_COMPOSER_RULE) or data.count(_COMPOSER_RULE) != 1
                or _COMPOSER_LEGACY_ALLOW in data):
            raise ValueError("composer client attribute is ambiguous or not the exact appended rule")
        return data, True
    if digest == COMPOSER_LEGACY_ALLOW_SHA256:
        if not data.endswith(_COMPOSER_LEGACY_ALLOW) or data.count(_COMPOSER_LEGACY_ALLOW) != 1:
            raise ValueError("temporary composer direct allow is not the exact appended rule")
        data = data[:-len(_COMPOSER_LEGACY_ALLOW)]
        digest = hashlib.sha256(data).hexdigest()
    if digest != COMPOSER_BEFORE_SHA256:
        raise ValueError("system_ext policy does not match a pinned supported input")
    if not data.endswith(b"\n") or _COMPOSER_RULE in data or _COMPOSER_LEGACY_ALLOW in data:
        raise ValueError("system_ext policy is not an unmodified appendable donor input")
    result = data + _COMPOSER_RULE
    if hashlib.sha256(result).hexdigest() != COMPOSER_AFTER_SHA256:
        raise ValueError("composer client policy differs from the reviewed result")
    return result, False


def _new_inode(records):
    used = {record["inode"] for record in records.values()}
    candidate = max(used) + 1
    if candidate > 0xFFFFFFFFFFFFFFFF:
        candidate = next(value for value in range(len(used) + 1) if value not in used)
    return candidate


def _synthetic_record(kind, inode, size, template):
    return {"uid": 0, "gid": 0, "mode": 0o40755 if kind == "dir" else 0o100644,
            "inode": inode, "size": size, "kind": kind, "ext4_flags": 0,
            "xattrs": copy.deepcopy(template["xattrs"])}


def _same_synthetic_record(records, path, kind, size, template):
    current = records.get(path, {})
    inode = current.get("inode")
    expected = _synthetic_record(kind, inode, size, template)
    return (current == expected
            and not any(r["inode"] == inode for p, r in records.items() if p != path))


def _make_plan(tree, records, content_manifest):
    tree = _canonical_host(tree, exists=True)
    validate_tree(tree, records, content_manifest)
    for path in (GENFS_PATH, INIT_PATH, TEMPLATE_PATH, COMPOSER_POLICY_PATH):
        if records.get(path, {}).get("kind") != "file":
            raise ValueError(f"compatibility input must be a regular file: {path}")
    if records.get(SKIP_PARENT_PATH, {}).get("kind") != "dir":
        raise ValueError(f"skip-mount parent must already be a real directory: {SKIP_PARENT_PATH}")
    template = records[TEMPLATE_PATH]
    if (template["uid"] != 0 or template["gid"] != 0 or template["mode"] != 0o100644
            or set(template["xattrs"]) != {"security.selinux"}
            or bytes.fromhex(template["xattrs"]["security.selinux"]).rstrip(b"\0")
            != b"u:object_r:system_file:s0"):
        raise ValueError("VINTF template must be root:root 0644 with only system_file context")
    try:
        original = {}
        host_metadata = {}
        for path in (GENFS_PATH, INIT_PATH, TEMPLATE_PATH, COMPOSER_POLICY_PATH):
            data, host = _read_regular(tree / path[1:])
            if _identity(data) != content_manifest[path]:
                raise ValueError(f"file changed after manifest validation: {path}")
            original[path], host_metadata[path] = data, host
        matrix, _ = _read_regular(_SOURCE_MATRIX)
        genfs, genfs_applied = _genfs(original[GENFS_PATH])
        init, init_applied = _init(original[INIT_PATH])
        composer_policy, composer_applied = _composer_policy(original[COMPOSER_POLICY_PATH])
        matrix_exists = MATRIX_PATH in records
        if matrix_exists:
            if records[MATRIX_PATH]["kind"] != "file":
                raise ValueError("existing VINTF addition is not a regular file")
            existing, _ = _read_regular(tree / MATRIX_PATH[1:])
            expected = copy.deepcopy(template)
            expected.update(size=len(matrix), inode=records[MATRIX_PATH]["inode"])
            if (existing != matrix or records[MATRIX_PATH] != expected
                    or _identity(existing) != content_manifest[MATRIX_PATH]
                    or any(r["inode"] == expected["inode"] for p, r in records.items()
                           if p != MATRIX_PATH)):
                raise ValueError("unexpected existing VINTF addition")
        legacy_applied = genfs_applied and init_applied and matrix_exists
        if any((genfs_applied, init_applied, matrix_exists)) and not legacy_applied:
            raise ValueError("partial compatibility state; require all original or all reviewed results")
        skip_applied = SKIP_DIR_PATH in records or SKIP_MOUNT_PATH in records
        if skip_applied:
            if (not legacy_applied
                    or not _same_synthetic_record(records, SKIP_DIR_PATH, "dir", 0, template)
                    or not _same_synthetic_record(records, SKIP_MOUNT_PATH, "file",
                                                  len(SKIP_MOUNT_BYTES), template)
                    or {p for p in records if p.startswith(SKIP_DIR_PATH + "/")} != {SKIP_MOUNT_PATH}
                    or content_manifest.get(SKIP_MOUNT_PATH) != _identity(SKIP_MOUNT_BYTES)
                    or _read_regular(tree / SKIP_MOUNT_PATH[1:])[0] != SKIP_MOUNT_BYTES):
                raise ValueError("unexpected existing skip-mount configuration")
        composer_migration = (hashlib.sha256(original[COMPOSER_POLICY_PATH]).hexdigest()
                              == COMPOSER_LEGACY_ALLOW_SHA256)
        if (composer_applied or composer_migration) and not (legacy_applied and skip_applied):
            raise ValueError("composer client policy is present without the previous complete fixes")
    except OSError as exc:
        raise ValueError(f"cannot safely read compatibility input: {exc}") from exc
    final_records = copy.deepcopy(records)
    final_contents = copy.deepcopy(content_manifest)
    transformed = {GENFS_PATH: genfs, INIT_PATH: init, MATRIX_PATH: matrix}
    changes = []
    writes = []
    for path, data in transformed.items():
        before = ({"record": copy.deepcopy(records[path]),
                   "content": copy.deepcopy(content_manifest[path])} if path in records else None)
        if path == MATRIX_PATH and not legacy_applied:
            final_records[path] = copy.deepcopy(template)
            final_records[path]["inode"] = _new_inode(final_records)
        final_records[path]["size"] = len(data)
        final_contents[path] = _identity(data)
        changes.append({"path": path,
                        "action": "unchanged" if legacy_applied else "replace" if before else "add",
                        "before": before,
                        "after": {"record": copy.deepcopy(final_records[path]),
                                  "content": copy.deepcopy(final_contents[path])}})
        if not legacy_applied:
            writes.append({"kind": "file", "path": path, "data": data, "before": original.get(path),
                           "host": host_metadata[TEMPLATE_PATH if path == MATRIX_PATH else path]})
    for path, kind, data in ((SKIP_DIR_PATH, "dir", None),
                             (SKIP_MOUNT_PATH, "file", SKIP_MOUNT_BYTES)):
        if not skip_applied:
            final_records[path] = _synthetic_record(kind, _new_inode(final_records),
                                                     len(data) if data is not None else 0, template)
            if kind == "file":
                final_contents[path] = _identity(data)
            write = {"kind": kind, "path": path, "before": None}
            if kind == "file":
                write.update(data=data, host=dict(host_metadata[TEMPLATE_PATH], mode=0o644))
            writes.append(write)
        changes.append({"path": path, "action": "unchanged" if skip_applied else "add",
                        "before": {"record": copy.deepcopy(records[path]),
                                   "content": copy.deepcopy(content_manifest.get(path))} if skip_applied else None,
                        "after": {"record": copy.deepcopy(final_records[path]),
                                  "content": copy.deepcopy(final_contents.get(path))}})
    final_records[COMPOSER_POLICY_PATH]["size"] = len(composer_policy)
    final_contents[COMPOSER_POLICY_PATH] = _identity(composer_policy)
    changes.append({"path": COMPOSER_POLICY_PATH,
                    "action": "unchanged" if composer_applied else "replace",
                    "before": {"record": copy.deepcopy(records[COMPOSER_POLICY_PATH]),
                               "content": copy.deepcopy(content_manifest[COMPOSER_POLICY_PATH])},
                    "after": {"record": copy.deepcopy(final_records[COMPOSER_POLICY_PATH]),
                              "content": copy.deepcopy(final_contents[COMPOSER_POLICY_PATH])}})
    if not composer_applied:
        writes.append({"kind": "file", "path": COMPOSER_POLICY_PATH, "data": composer_policy,
                       "before": original[COMPOSER_POLICY_PATH], "host": host_metadata[COMPOSER_POLICY_PATH]})
    report = {"status": "already_applied" if legacy_applied and skip_applied and composer_applied else "planned",
              "donor": "official PLG110 ColorOS 17", "canonical_tree": str(tree),
              "changes": changes, "final_records": final_records,
              "final_content_manifest": final_contents}
    return tree, report, writes


def plan_compatibility(tree, records, content_manifest):
    """Validate the complete tree and return an immutable-input, JSON-safe plan."""
    return _make_plan(tree, records, content_manifest)[1]


def _atomic_write(path, data, host=None):
    """Replace one regular file through a same-directory, no-follow temporary."""
    path = Path(path)
    parent = _open_parent(path)
    temporary = f".{path.name}.compat-{uuid.uuid4().hex}"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            if host is not None:
                current = os.fstat(output.fileno())
                if current.st_uid != host["uid"] or current.st_gid != host["gid"]:
                    os.fchown(output.fileno(), host["uid"], host["gid"])
                os.fchmod(output.fileno(), host["mode"])
                for name in os.listxattr(output.fileno()):
                    if name not in host["xattrs"]:
                        os.removexattr(output.fileno(), name)
                for name, value in host["xattrs"].items():
                    os.setxattr(output.fileno(), name, value)
                os.utime(output.fileno(), ns=(host["atime_ns"], host["mtime_ns"]))
            os.fsync(output.fileno())
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        finally:
            os.close(parent)


def _journal(report):
    # Full manifests are returned to the caller; journal just the exact deltas.
    saved = {k: v for k, v in report.items()
             if k not in {"final_records", "final_content_manifest"}}
    _atomic_write(Path(report["report_path"]),
                  (json.dumps(saved, sort_keys=True, indent=2) + "\n").encode())


def _current_bytes(path):
    try:
        return _read_regular(path)[0]
    except FileNotFoundError:
        return None


def _unlink(path):
    parent = _open_parent(path)
    try:
        os.unlink(Path(path).name, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def _directory_state(path):
    parent = _open_parent(path)
    try:
        try:
            info = os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"expected a real directory: {path}")
        return info.st_dev, info.st_ino
    finally:
        os.close(parent)


def _mkdir(path):
    parent = _open_parent(path)
    try:
        os.mkdir(Path(path).name, mode=0o755, dir_fd=parent)
        descriptor = os.open(Path(path).name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=parent)
        try:
            os.fchmod(descriptor, 0o755)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(parent)
    finally:
        os.close(parent)


def _rmdir(path):
    parent = _open_parent(path)
    try:
        # Never remove unrelated contents while recovering an interrupted mkdir.
        os.rmdir(Path(path).name, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def apply_compatibility(tree, records, content_manifest, backup_dir):
    """Apply only the reviewed changes, or roll them back on operational failure.

    ``backup_dir`` must be an explicit directory outside the canonical tree
    with an existing parent, and must be fresh when changes are required.
    Original files and a precise journal remain there after success or failure. An incomplete rollback raises
    CompatibilityError with status ``failed_needs_recovery``; no updated
    manifest is returned for a failed operation.
    """
    tree, report, writes = _make_plan(tree, records, content_manifest)
    backup = _canonical_host(backup_dir, exists=False)
    if backup == tree or tree in backup.parents or not backup.parent.is_dir():
        raise ValueError("backup_dir must be outside the tree with an existing parent")
    if not writes:
        report.update(backup_dir=None, report_path=None)
        return report
    if backup.exists():
        raise ValueError("backup_dir must be fresh when changes are required")
    report.update(backup_dir=str(backup), report_path=str(backup / "compatibility-report.json"),
                  applied=[], rollback_operations=[], rollback_errors=[])
    attempted = []
    try:
        backup.mkdir(mode=0o700)
        report["status"] = "backing_up"
        _journal(report)
        for write in writes:
            if write["before"] is not None:
                destination = backup / write["path"][1:]
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                _atomic_write(destination, write["before"], write["host"])
                if _read_regular(destination)[0] != write["before"]:
                    raise OSError(f"backup verification failed: {write['path']}")
        report["status"] = "applying"
        _journal(report)
        for write in writes:
            destination = tree / write["path"][1:]
            current = (_directory_state(destination) if write["kind"] == "dir"
                       else _current_bytes(destination))
            if current != write["before"]:
                raise OSError(f"target changed before replacement: {write['path']}")
            attempted.append(write)
            report["pending"] = write["path"]
            _journal(report)
            if write["kind"] == "dir":
                _mkdir(destination)
                if _directory_state(destination) is None:
                    raise OSError(f"directory creation verification failed: {write['path']}")
            else:
                _atomic_write(destination, write["data"], write["host"])
                if _read_regular(destination)[0] != write["data"]:
                    raise OSError(f"replacement verification failed: {write['path']}")
            report["applied"].append(write["path"])
            report["pending"] = None
            _journal(report)
        validate_tree(tree, report["final_records"], report["final_content_manifest"])
        report["status"] = "complete"
        _journal(report)
        return report
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report.pop("final_records", None)
        report.pop("final_content_manifest", None)
        for write in reversed(attempted):
            destination = tree / write["path"][1:]
            try:
                if write["kind"] == "dir":
                    if _directory_state(destination) is not None:
                        _rmdir(destination)
                else:
                    current = _current_bytes(destination)
                    if current != write["before"]:
                        if current != write["data"]:
                            raise OSError("target differs from both original and intended bytes")
                        if write["before"] is None:
                            _unlink(destination)
                        else:
                            saved = _read_regular(backup / write["path"][1:])[0]
                            if saved != write["before"]:
                                raise OSError("backup differs from original bytes")
                            _atomic_write(destination, saved, write["host"])
                report["rollback_operations"].append(write["path"])
            except BaseException as rollback_exc:
                report["rollback_errors"].append(
                    {"path": write["path"], "error": f"{type(rollback_exc).__name__}: {rollback_exc}"})
        try:
            validate_tree(tree, records, content_manifest)
        except BaseException as verification_exc:
            report["rollback_errors"].append(
                {"path": "/", "error": f"rollback verification failed: {verification_exc}"})
        report["status"] = "failed_needs_recovery" if report["rollback_errors"] else "failed_rolled_back"
        if not report["rollback_errors"]:
            report["pending"] = None
        try:
            _journal(report)
        except BaseException as journal_exc:
            report["report_error"] = f"{type(journal_exc).__name__}: {journal_exc}"
        if not isinstance(exc, Exception):
            exc.compatibility_report = report
            raise
        raise CompatibilityError(f"compatibility patch failed ({report['status']}): {exc}", report) from exc
