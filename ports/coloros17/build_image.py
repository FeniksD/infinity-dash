"""Build and verify a raw, editable EXT4 lab artifact without mounting it.

Linux and an unprivileged account are required. Callers provide complete donor
metadata and an exact content manifest: files have ``kind``, ``size`` and
``sha256``; symlinks have ``kind`` and ``target``. Host ownership/mode are not
donor metadata. Keep the input tree, tools and destination exclusively owned
and quiescent for the duration of the call. No AVB footer or signing is added;
a verified filesystem is not a claim of DSU boot or hardware compatibility.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from ports.coloros17.fs_metadata import (
    EXT4_LAYOUT_FLAGS, _load_reader, canonical_path, read_inode_manifest,
    render_file_contexts, render_fs_config,
)


_BLOCK = 4096
_CHUNK = 1024 * 1024
_DISK_MARGIN = 512 * 1024**2
_TOOLS = {"mke2fs", "e2fsdroid", "e2fsck", "debugfs"}
_KINDS = {"dir": stat.S_IFDIR, "file": stat.S_IFREG, "symlink": stat.S_IFLNK}
_TEMP_LABEL = b"u:object_r:system_file:s0\0".hex()


class BuildError(RuntimeError):
    """An operational failure with retained staging files, logs and report."""

    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def _aligned(size):
    return ((size + _BLOCK - 1) // _BLOCK) * _BLOCK


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_build_tables(records):
    """Render exact metadata, allowing only the verified empty donor reserve.

    e2fsdroid cannot express an absent label. The temporary label is removed
    from this one exact inode by debugfs before independent verification.
    """
    if isinstance(records, dict) and "/lost+found" in records:
        raise ValueError("donor /lost+found requires explicit support")
    build_records = copy.deepcopy(records)
    exceptions = []
    if isinstance(build_records, dict) and isinstance(build_records.get("/my_reserve"), dict):
        reserve = build_records["/my_reserve"]
        if reserve.get("xattrs") == {}:
            if (reserve.get("kind") != "dir" or reserve.get("uid") != 0
                    or reserve.get("gid") != 0 or reserve.get("mode") != 0o40755
                    or any(p.startswith("/my_reserve/") for p in build_records)):
                raise ValueError("only the exact empty donor /my_reserve may be unlabeled")
            reserve["xattrs"] = {"security.selinux": _TEMP_LABEL}
            exceptions.append({"path": "/my_reserve", "kind": "preserve_absent_selinux",
                               "action": "remove temporary system_file xattr before verification"})
    return render_fs_config(build_records), render_file_contexts(build_records), exceptions


def _validate_contents(records, contents):
    if not isinstance(contents, dict):
        raise ValueError("content_manifest must be a dictionary")
    for path in contents:
        canonical_path(path)
    required = {path for path, item in records.items() if item["kind"] != "dir"}
    if contents.keys() != required:
        raise ValueError("content manifest must cover exactly all files and symlinks")
    for path, item in contents.items():
        record = records[path]
        if not isinstance(item, dict) or item.get("kind") != record["kind"]:
            raise ValueError(f"content kind mismatch: {path}")
        if record["kind"] == "file":
            if type(item.get("size")) is not int or item["size"] < 0 or item["size"] != record["size"]:
                raise ValueError(f"content size mismatch: {path}")
            if not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise ValueError(f"invalid SHA256: {path}")
        else:
            target = item.get("target")
            if (not isinstance(target, str) or not target or "\0" in target
                    or target != record.get("symlink_target")):
                raise ValueError(f"content symlink target mismatch: {path}")
            try:
                length = len(target.encode("utf-8", "strict"))
            except UnicodeError as exc:
                raise ValueError(f"non-UTF8 symlink target: {path}") from exc
            if length != record["size"]:
                raise ValueError(f"symlink size mismatch: {path}")


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _inventory(tree, records, contents, *, hash_contents):
    found = {}
    pending = [(tree, "/")]
    device = tree.lstat().st_dev
    while pending:
        physical, path = pending.pop()
        canonical_path(path)
        info = physical.lstat()
        record = records.get(path)
        if (record is None or stat.S_IFMT(info.st_mode) != _KINDS[record["kind"]]
                or info.st_dev != device):
            raise ValueError(f"unexpected physical entry/type/filesystem: {path}")
        before = _fingerprint(info)
        if record["kind"] == "dir":
            for child in physical.iterdir():
                pending.append((child, path.rstrip("/") + "/" + child.name))
        else:
            if info.st_nlink != 1 or info.st_size != record["size"]:
                raise ValueError(f"physical size changed or hardlink found: {path}")
            if record["kind"] == "symlink":
                if os.readlink(physical) != contents[path]["target"]:
                    raise ValueError(f"physical symlink target changed: {path}")
            elif hash_contents:
                descriptor = os.open(physical, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as source:
                    if _fingerprint(os.fstat(source.fileno())) != before:
                        raise ValueError(f"physical file changed before hashing: {path}")
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: source.read(_CHUNK), b""):
                        digest.update(chunk)
                    if (_fingerprint(os.fstat(source.fileno())) != before
                            or digest.hexdigest() != contents[path]["sha256"]):
                        raise ValueError(f"physical content hash changed: {path}")
        if _fingerprint(physical.lstat()) != before:
            raise ValueError(f"physical entry changed during validation: {path}")
        found[path] = before
    if found.keys() != records.keys():
        raise ValueError("physical tree is missing manifest entries")
    return found


def validate_tree(tree, records, content_manifest):
    """Validate exact paths, kinds, sizes and hashes without modifying the tree."""
    render_build_tables(records)
    _validate_contents(records, content_manifest)
    tree = Path(tree).absolute()
    if not stat.S_ISDIR(tree.lstat().st_mode):
        raise ValueError("input tree must be a real directory")
    return _inventory(tree, records, content_manifest, hash_contents=True)


class ForwardHashSink:
    """Bounded-memory hash destination for the pinned EXT4 write_file reader."""

    def __init__(self, size):
        if type(size) is not int or size < 0:
            raise ValueError("invalid expected file size")
        self.size = size
        self.position = 0
        self.digest = hashlib.sha256()
        self.finalized = False

    def tell(self):
        return self.position

    def write(self, data):
        if self.finalized or self.position + len(data) > self.size:
            raise ValueError("file reader wrote beyond expected size")
        self.digest.update(data)
        self.position += len(data)
        return len(data)

    def seek(self, offset, whence=os.SEEK_SET):
        if whence != os.SEEK_SET or type(offset) is not int or offset < self.position or offset > self.size:
            raise ValueError("file reader attempted backward or out-of-bounds seek")
        zeros = b"\0" * min(_CHUNK, offset - self.position)
        while self.position < offset:
            self.write(zeros[:min(len(zeros), offset - self.position)])
        return self.position

    def truncate(self, size=None):
        if size != self.size:
            raise ValueError("file reader truncated to an unexpected size")
        self.seek(size)
        self.finalized = True
        return size

    def hexdigest(self):
        if not self.finalized:
            raise ValueError("file reader did not finalize its expected size")
        return self.digest.hexdigest()


def _semantic_xattrs(attrs):
    if not isinstance(attrs, dict):
        raise ValueError("invalid output xattrs")
    result = {}
    for name, value in attrs.items():
        if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", value):
            raise ValueError(f"invalid output xattr: {name}")
        decoded = bytes.fromhex(value)
        result[name] = decoded.rstrip(b"\0") if name == "security.selinux" else decoded
    return result


def verify_metadata(expected, actual):
    """Compare donor semantics while ignoring inode IDs and storage layout."""
    missing, extra = expected.keys() - actual.keys(), actual.keys() - expected.keys()
    if missing or extra:
        raise ValueError(f"output path mismatch: missing={sorted(missing)}, extra={sorted(extra)}")
    for path, wanted in expected.items():
        received = actual[path]
        for field in ("uid", "gid", "mode", "kind"):
            if received.get(field) != wanted[field]:
                raise ValueError(f"output metadata mismatch at {path}: {field}")
        if received.get("ext4_flags", 0) & ~EXT4_LAYOUT_FLAGS:
            raise ValueError(f"output has unsupported semantic inode flags: {path}")
        if wanted["kind"] != "dir" and received.get("size") != wanted["size"]:
            raise ValueError(f"output size mismatch: {path}")
        if wanted["kind"] == "symlink" and received.get("symlink_target") != wanted["symlink_target"]:
            raise ValueError(f"output symlink target mismatch: {path}")
        if _semantic_xattrs(received.get("xattrs")) != _semantic_xattrs(wanted["xattrs"]):
            raise ValueError(f"output xattr mismatch: {path}")
    return []


def _verify_content(image, actual, content_manifest, mystic_root):
    reader = _load_reader(mystic_root, "ext4")
    count = 0
    with reader(str(image)) as fs:
        for path, item in content_manifest.items():
            if item["kind"] != "file":
                continue
            inode = fs.read_inode(actual[path]["inode"])
            if inode.size != item["size"]:
                raise ValueError(f"output inode size changed: {path}")
            sink = ForwardHashSink(item["size"])
            fs.write_file(inode, sink)
            if sink.hexdigest() != item["sha256"]:
                raise ValueError(f"output content SHA256 mismatch: {path}")
            count += 1
    return count


def _size_plan(records, reserve_bytes):
    if type(reserve_bytes) is not int or reserve_bytes < 0:
        raise ValueError("reserve_bytes must be a nonnegative integer")
    allocated = sum(_aligned(r["size"]) for r in records.values()
                    if r["kind"] == "file" or r["kind"] == "symlink" and r["size"] >= 60)
    # Account for aligned ext4 dirents rather than donor filesystem dir sizes.
    entries = {p: 24 + 12 for p, r in records.items() if r["kind"] == "dir"}
    for path in records:
        if path != "/":
            parent, _, name = path.rpartition("/")
            entries[parent or "/"] += ((8 + len(name.encode("utf-8")) + 3) // 4) * 4
    directory_bytes = sum(_aligned(size) for size in entries.values())
    if "/lost+found" not in records:
        directory_bytes += 4 * _BLOCK
    base = allocated + directory_bytes
    overhead = (base * 8 + 99) // 100
    return {"file_allocated_bytes": allocated, "directory_bytes": directory_bytes,
            "overhead_bytes": overhead, "reserve_bytes": reserve_bytes,
            "image_bytes": _aligned(base + overhead + reserve_bytes)}


def _validated_tools(paths, hashes):
    if not isinstance(paths, dict) or not isinstance(hashes, dict) or paths.keys() != _TOOLS or hashes.keys() != _TOOLS:
        raise ValueError("explicit paths and SHA256 hashes for exactly four native tools are required")
    result = {}
    for name in sorted(_TOOLS):
        path = Path(paths[name])
        if not path.is_absolute():
            raise ValueError(f"native tool path must be absolute: {name}")
        path = path.resolve(strict=True)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f"native tool is not an executable regular file: {name}")
        if (not isinstance(hashes[name], str) or not re.fullmatch(r"[0-9a-f]{64}", hashes[name])
                or _hash_file(path) != hashes[name]):
            raise ValueError(f"native tool hash mismatch: {name}")
        result[name] = str(path)
    return result


def _save_report(report):
    path = Path(report["report_path"])
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def build_image(tree, records, content_manifest, output, mystic_root, tool_paths, tool_hashes,
                reserve_bytes=1024**3):
    """Build, independently verify, then atomically publish one raw EXT4 image.

    Input validation failures raise ValueError before staging. Operational
    failures raise BuildError with a persisted report and retained native logs.
    Success returns that report, including its path and whole-image SHA256.
    Preflight requires the planned image size plus 512 MiB free on the output
    filesystem. Interruptions after the verified image has been published
    return a complete report with post_publish_warning. A failed final report
    write also sets report_save_error; the saved report may still say verified.
    """
    if not sys.platform.startswith("linux") or not hasattr(os, "geteuid"):
        raise ValueError("the builder requires Linux")
    if os.geteuid() == 0:
        raise ValueError("root execution is forbidden; use an unprivileged build account")
    tree = Path(tree).absolute()
    if not stat.S_ISDIR(tree.lstat().st_mode):
        raise ValueError("input tree must be a real directory")
    tree = tree.resolve(strict=True)
    output = Path(output).absolute()
    output = output.parent.resolve(strict=True) / output.name
    if output.is_relative_to(tree):
        raise ValueError("output must be outside the input tree")
    if os.path.lexists(output):
        raise ValueError("output already exists")
    config, contexts, exceptions = render_build_tables(records)
    _validate_contents(records, content_manifest)
    sizes = _size_plan(records, reserve_bytes)
    free_bytes = shutil.disk_usage(output.parent).free
    required_bytes = sizes["image_bytes"] + _DISK_MARGIN
    if free_bytes < required_bytes:
        raise ValueError(f"insufficient disk space: need {required_bytes} bytes, have {free_bytes}")
    native = _validated_tools(tool_paths, tool_hashes)
    _load_reader(mystic_root, "ext4")
    snapshot = validate_tree(tree, records, content_manifest)
    stage = Path(tempfile.mkdtemp(prefix="." + output.name + ".build-", dir=output.parent))
    report = {"schema_version": 1, "status": "building", "tree": str(tree), "output": str(output),
              "staging_path": str(stage), "report_path": str(stage / "build-report.json"),
              "artifact_kind": "raw_editable_ext4_lab_image", "avb_signed": False,
              "metadata_sha256": _json_hash(records), "content_manifest_sha256": _json_hash(content_manifest),
              "tool_paths": native, "tool_hashes": dict(tool_hashes), "size_plan": sizes,
              "disk_space": {"free_bytes": free_bytes, "required_bytes": required_bytes,
                             "safety_margin_bytes": _DISK_MARGIN},
              "exceptions": exceptions, "commands": []}
    publication_identity = None

    def run(name, arguments):
        if _hash_file(native[name]) != tool_hashes[name]:
            raise ValueError(f"native tool hash changed before execution: {name}")
        entry = {"tool": name, "argv": [native[name], *arguments],
                 "log_path": str(stage / f"{len(report['commands']) + 1:02d}-{name}.log")}
        report["commands"].append(entry)
        _save_report(report)
        with open(entry["log_path"], "wb") as log:
            result = subprocess.run(entry["argv"], stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, check=False, cwd=stage,
                                    env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"})
        entry["returncode"] = result.returncode
        _save_report(report)
        if result.returncode:
            raise RuntimeError(f"{name} exited {result.returncode}; see {entry['log_path']}")

    try:
        _save_report(report)
        config_path, contexts_path = stage / "fs_config", stage / "file_contexts"
        config_path.write_text(config, encoding="utf-8")
        contexts_path.write_text(contexts, encoding="utf-8")
        image = stage / "filesystem.img"
        with image.open("xb") as stream:
            stream.truncate(sizes["image_bytes"])
        run("mke2fs", ["-q", "-t", "ext4", "-b", str(_BLOCK), "-I", "256", "-m", "0",
                       "-N", str(max(256, len(records) + 11 + (len(records) + 9) // 10)),
                       "-O", "^has_journal", "-F", str(image), str(sizes["image_bytes"] // _BLOCK)])
        formatted = read_inode_manifest(image, "ext4", mystic_root)
        if (set(formatted) != {"/", "/lost+found"}
                or formatted["/lost+found"]["kind"] != "dir"):
            raise ValueError("formatter output differs from an empty filesystem with /lost+found")
        run("debugfs", ["-w", "-R", "rmdir /lost+found", str(image)])
        report["formatter_cleanup"] = {"path": "/lost+found", "action": "remove_empty_generated_directory"}
        if _inventory(tree, records, content_manifest, hash_contents=False) != snapshot:
            raise ValueError("input tree changed after initial verification")
        run("e2fsdroid", ["-e", "-T", "1230768000", "-C", str(config_path), "-S", str(contexts_path),
                          "-f", str(tree), "-a", "/", str(image)])
        if exceptions:
            run("debugfs", ["-w", "-R", "ea_rm /my_reserve security.selinux", str(image)])
        run("e2fsck", ["-f", "-n", str(image)])
        actual = read_inode_manifest(image, "ext4", mystic_root)
        report["exceptions"].extend(verify_metadata(records, actual))
        report["metadata_verified_inodes"] = len(records)
        report["content_verified_files"] = _verify_content(image, actual, content_manifest, mystic_root)
        if _inventory(tree, records, content_manifest, hash_contents=False) != snapshot:
            raise ValueError("input tree changed during image build")
        report["sha256"] = _hash_file(image)
        verified_stat = image.stat()
        report["image_bytes"] = verified_stat.st_size
        publication_identity = (verified_stat.st_dev, verified_stat.st_ino, verified_stat.st_size)
        report["verified_image_identity"] = dict(zip(("device", "inode", "size"), publication_identity))
        report["status"] = "verified"
        _save_report(report)
        if os.path.lexists(output):
            raise ValueError("output appeared before publication")
        os.replace(image, output)
        report["status"] = "complete"
        _save_report(report)
    except BaseException as exc:
        # A signal can arrive after rename committed but before the next Python
        # assignment. Reconcile inode identity, not just an in-memory flag.
        committed = False
        if publication_identity is not None:
            try:
                published_stat = output.lstat()
                committed = (not os.path.lexists(image) and stat.S_ISREG(published_stat.st_mode)
                             and (published_stat.st_dev, published_stat.st_ino, published_stat.st_size)
                             == publication_identity)
            except OSError:
                pass
        if committed:
            report["status"] = "complete"
            report["post_publish_warning"] = f"{type(exc).__name__}: {exc}"
            try:
                _save_report(report)
            except BaseException as save_error:
                report["report_save_error"] = f"{type(save_error).__name__}: {save_error}"
            return report
        report["status"] = "failed"
        report["failure"] = f"{type(exc).__name__}: {exc}"
        try:
            _save_report(report)
        except BaseException as save_error:
            report["report_save_error"] = str(save_error)
        if not isinstance(exc, Exception):
            raise
        raise BuildError(report["failure"], report) from exc
    return report
