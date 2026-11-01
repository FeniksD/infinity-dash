"""Strict, read-only metadata collection and e2fsdroid input rendering.

The exporter preserves raw xattrs, including values the renderer cannot express.
Rendering fails instead of silently dropping them. It neither changes images
nor promises that the resulting Android image is bootable.
"""

import re
import stat
import struct
import unicodedata
from pathlib import Path


MYSTIC_COMMIT = "b906057b9909d9ec3272feb9c53306f7bd4912f0"
_PINNED_READERS = {
    "tools/fs/labels.py": "1555849d0c65c626c2f37f4a7e1ff02b0f140dc8",
    "tools/fs/ext4/filesystem.py": "c93c7eeabfa33d37436cf7eda993f2d9dbf24879",
}
_KINDS = {stat.S_IFREG: "file", stat.S_IFDIR: "dir", stat.S_IFLNK: "symlink"}
# These describe storage layout, which the new filesystem may choose afresh.
# Every other bit is rejected: e.g. CASEFOLD, VERITY, IMMUTABLE and APPEND
# require behavior that canned fs_config/file_contexts do not reconstruct.
EXT4_LAYOUT_FLAGS = 0x00001000 | 0x00080000 | 0x10000000  # INDEX, EXTENTS, INLINE_DATA


def canonical_path(path):
    """Require an absolute image-relative path; never normalize silently."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("path must be an absolute string")
    if "\\" in path or any(c.isspace() or unicodedata.category(c).startswith("C") for c in path):
        raise ValueError(f"unrepresentable path: {path!r}")
    if path != "/" and any(p in ("", ".", "..") for p in path[1:].split("/")):
        raise ValueError(f"noncanonical path: {path!r}")
    return path


def decode_capability_xattr(value):
    """Return the mask only when e2fsdroid reproduces the exact v2 blob."""
    if value is None:
        return 0
    if not isinstance(value, bytes) or len(value) != 20:
        raise ValueError("capability must be an exact 20-byte v2 xattr")
    magic, low, inherited_low, high, inherited_high = struct.unpack("<5I", value)
    mask = low | high << 32
    if magic != 0x02000001 or inherited_low or inherited_high or not 0 < mask <= 0x7FFFFFFFFFFFFFFF:
        raise ValueError("capability xattr is not exactly representable by e2fsdroid -C")
    return mask


def _integer(value, name, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"invalid {name}: {value!r}")
    return value


def _hex_bytes(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", value):
        raise ValueError(f"invalid hex xattr {name}")
    return bytes.fromhex(value)


def _validated_records(records):
    if not isinstance(records, dict) or "/" not in records:
        raise ValueError("complete manifest must include the root")
    for path in records:
        canonical_path(path)
    result = []
    for path in sorted(records):
        canonical_path(path)
        r = records[path]
        if not isinstance(r, dict):
            raise ValueError(f"invalid record for {path}")
        mode = _integer(r.get("mode"), "mode", 0xFFFF)
        kind = _KINDS.get(stat.S_IFMT(mode))
        if kind is None or r.get("kind") != kind:
            raise ValueError(f"inconsistent inode kind for {path}")
        if path == "/":
            if kind != "dir":
                raise ValueError("root must be a directory")
        else:
            parent = path.rsplit("/", 1)[0] or "/"
            if not isinstance(records.get(parent), dict) or records[parent].get("kind") != "dir":
                raise ValueError(f"missing directory parent for {path}")
        uid = _integer(r.get("uid"), "uid", 0x7FFFFFFF)
        gid = _integer(r.get("gid"), "gid", 0x7FFFFFFF)
        _integer(r.get("inode"), "inode", 0xFFFFFFFFFFFFFFFF)
        _integer(r.get("size"), "size", 0xFFFFFFFFFFFFFFFF)
        flags = _integer(r.get("ext4_flags", 0), "ext4_flags", 0xFFFFFFFF)
        if flags & ~EXT4_LAYOUT_FLAGS:
            raise ValueError(f"unsupported EXT4 inode flags 0x{flags:x} at {path}")
        attrs = r.get("xattrs")
        if not isinstance(attrs, dict) or set(attrs) - {"security.selinux", "security.capability"}:
            raise ValueError(f"unrepresentable extra xattrs for {path}")
        label = _hex_bytes(attrs.get("security.selinux"), "security.selinux")
        if label.endswith(b"\0"):
            label = label[:-1]
        try:
            label = label.decode("ascii")
        except UnicodeError as exc:
            raise ValueError(f"non-ASCII label for {path}") from exc
        if not re.fullmatch(r"[A-Za-z0-9_-]+:[A-Za-z0-9_-]+:[A-Za-z0-9_-]+:s[0-9]+(?:[A-Za-z0-9_:,.-]*)", label):
            raise ValueError(f"invalid SELinux label for {path}")
        cap = decode_capability_xattr(
            _hex_bytes(attrs["security.capability"], "security.capability")
            if "security.capability" in attrs else None
        )
        if cap and kind != "file":
            raise ValueError(f"capabilities on non-file {path}")
        result.append((path, uid, gid, stat.S_IMODE(mode), cap, label))
    return result


def render_fs_config(records):
    """Render complete exact paths, octal permissions and capability masks."""
    return "".join(f"{p} {u} {g} {m:04o} capabilities=0x{c:x}\n"
                   for p, u, g, m, c, _ in _validated_records(records))


def _literal_spec(path):
    literal = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/_-"
    return "".join(chr(b) if b in literal else "\\" + chr(b) if 0x20 < b < 0x7F
                   else f"\\x{b:02x}" for b in path.encode("utf-8"))


def render_file_contexts(records):
    """Render literal SELinux rules, not generic fallback labels."""
    return "".join(f"{_literal_spec(p)} {label}\n"
                   for p, _, _, _, _, label in _validated_records(records))


def _load_reader(root, fs_type):
    # Execute only the verified standalone parser, never Mystic's package
    # __init__, which imports unrelated extraction/build tools.
    import ast
    import hashlib

    relative = "tools/fs/labels.py" if fs_type == "erofs" else "tools/fs/ext4/filesystem.py"
    path = Path(root) / relative
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"missing pinned Mystic reader: {path}") from exc
    blob = b"blob " + str(len(data)).encode() + b"\0" + data
    if hashlib.sha1(blob).hexdigest() != _PINNED_READERS[relative]:
        raise ValueError(f"Mystic reader differs from {MYSTIC_COMMIT}: {path}")
    parsed = ast.parse(data, filename=str(path))
    if fs_type == "erofs":
        parsed.body = [node for node in parsed.body if
                       isinstance(node, ast.Import) and all(a.name in {"os", "stat", "struct"} for a in node.names)
                       or isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id.startswith("EROFS_") for t in node.targets)
                       or isinstance(node, ast.ClassDef) and node.name in {"LabelError", "_ErofsInode", "_Erofs"}]
    namespace = {"__name__": "_verified_mystic_metadata_reader"}
    exec(compile(parsed, str(path), "exec"), namespace)
    return namespace["_Erofs" if fs_type == "erofs" else "Ext4Filesystem"]


def _xattr_name(index, suffix):
    fixed = {2: "system.posix_acl_access", 3: "system.posix_acl_default"}
    if index in fixed and not suffix:
        return fixed[index]
    prefix = {1: "user.", 4: "trusted.", 6: "security.", 7: "system."}.get(index)
    if prefix is None or not suffix or b"\0" in suffix:
        raise ValueError("unsupported xattr namespace/name")
    return prefix + suffix.decode("utf-8", "strict")


def _add_xattr(attrs, index, name, value):
    key = _xattr_name(index, name)
    if key in attrs:
        raise ValueError(f"duplicate xattr {key}")
    attrs[key] = value.hex()


def _erofs_xattrs(fs, inode):
    attrs = {}
    if not inode.xattr_size:
        return attrs
    area = fs._read(inode.pos + inode.inode_size, inode.xattr_size)
    if len(area) < 12 or 12 + 4 * area[4] > len(area):
        raise ValueError("invalid EROFS xattr header/shared count")

    def entry(buf, offset):
        if offset + 4 > len(buf):
            raise ValueError("truncated EROFS xattr entry")
        length, index, size = struct.unpack_from("<BBH", buf, offset)
        end = offset + 4 + length + size
        aligned = (end + 3) & ~3
        if end > len(buf) or aligned > len(buf) or index & 0x80:
            raise ValueError("invalid EROFS xattr bounds or unsupported long prefix")
        _add_xattr(attrs, index, buf[offset + 4:offset + 4 + length],
                   buf[offset + 4 + length:end])
        return aligned

    count = area[4]
    for i in range(count):
        xid, = struct.unpack_from("<I", area, 12 + 4 * i)
        offset = fs._shared_xattrs + 4 * xid
        header = fs._read(offset, 4)
        length, _, size = struct.unpack("<BBH", header)
        entry(fs._read(offset, (4 + length + size + 3) & ~3), 0)
    offset = 12 + count * 4
    while offset < len(area):
        if not any(area[offset:]):
            break
        offset = entry(area, offset)
    return attrs


def _ext4_xattrs(fs, inode):
    attrs = {}

    def entries(buf, offset, base):
        values = []
        while True:
            if offset + 4 > len(buf):
                raise ValueError("unterminated EXT4 xattr list")
            if not any(buf[offset:offset + 4]):
                offset += 4
                break
            if offset + 16 > len(buf):
                raise ValueError("truncated EXT4 xattr entry")
            length, index, value_offset, value_inode, size = struct.unpack_from("<BBHII", buf, offset)
            end_name = offset + 16 + length
            if end_name > len(buf) or value_inode:
                raise ValueError("invalid EXT4 xattr name or unsupported EA inode")
            start, end = base + value_offset, base + value_offset + size
            if size and (start < 0 or end > len(buf)):
                raise ValueError("invalid EXT4 xattr value bounds")
            values.append((index, buf[offset + 16:end_name], start, end))
            offset = (end_name + 3) & ~3
        for index, name, start, end in values:
            if end > start and start < offset:
                raise ValueError("EXT4 xattr overlaps entry table")
            _add_xattr(attrs, index, name, buf[start:end])

    start = 128 + inode.extra_isize
    if start + 4 <= len(inode.raw) and struct.unpack_from("<I", inode.raw, start)[0] == 0xEA020000:
        entries(inode.raw, start + 4, start + 4)
    if inode.file_acl:
        block = fs._read_block(inode.file_acl)
        if struct.unpack_from("<I", block)[0] != 0xEA020000 or struct.unpack_from("<I", block, 8)[0] != 1:
            raise ValueError("invalid EXT4 external xattr block")
        entries(block, 32, 0)
    return attrs


def _erofs_directory(fs, inode):
    data = fs._dir_data(inode)
    for start in range(0, len(data), fs.block_size):
        block = data[start:start + fs.block_size]
        if len(block) < 12:
            raise ValueError("truncated EROFS directory")
        first, = struct.unpack_from("<H", block, 8)
        if first < 12 or first % 12 or first > len(block):
            raise ValueError("invalid EROFS directory table")
        offsets = [struct.unpack_from("<H", block, p + 8)[0] for p in range(0, first, 12)]
        if offsets != sorted(set(offsets)) or any(p < first or p >= len(block) for p in offsets):
            raise ValueError("invalid EROFS directory name offsets")
    return fs.iter_dir(inode)


def read_inode_manifest(image_path, fs_type, mystic_root):
    """Read image metadata using exact pinned readers; no writes or mounts.

    Supports regular files, directories and symlinks. Unsupported filesystem
    features/EA inodes are errors. EXT4 records also contain ext4_flags (uint32).
    The renderer separately rejects semantic inode flags and xattrs that
    e2fsdroid cannot reconstruct; this exporter retains that evidence.
    """
    if fs_type not in ("erofs", "ext4"):
        raise ValueError("only EROFS and EXT4 metadata export are supported")
    reader = _load_reader(mystic_root, fs_type)
    try:
        image_size = Path(image_path).stat().st_size

        class BoundedReader(reader):
            def _read(self, offset, length):
                if (offset < 0 or length < 0 or length > 64 * 1024 * 1024
                        or offset + length > image_size):
                    raise ValueError("metadata read exceeds image bounds or 64 MiB limit")
                return super()._read(offset, length)

        with BoundedReader(str(image_path)) as fs:
            if fs_type == "erofs":
                sb = fs._read(1024, 128)
                if struct.unpack_from("<I", sb, 80)[0] & ~0x3F or sb[91]:
                    raise ValueError("unsupported EROFS features/long xattr prefixes")
                root = fs.root_nid
            else:
                if fs.incompat & 4:
                    raise ValueError("EXT4 requires journal recovery")
                root = 2
            pending = [("/", root)]
            seen_dirs = set()
            result = {}
            while pending:
                path, number = pending.pop()
                canonical_path(path)
                if path in result:
                    raise ValueError(f"duplicate directory entry: {path}")
                inode = fs.read_inode(number)
                kind = _KINDS.get(stat.S_IFMT(inode.mode))
                if kind is None:
                    raise ValueError(f"unsupported inode type at {path}")
                if fs_type == "erofs":
                    raw = fs._read(inode.pos, inode.inode_size)
                    uid, gid = struct.unpack_from("<II" if inode.inode_size == 64 else "<HH", raw, 24)
                    attrs = _erofs_xattrs(fs, inode)
                else:
                    uid, gid = inode.uid, inode.gid
                    attrs = _ext4_xattrs(fs, inode)
                item = {"uid": uid, "gid": gid, "mode": inode.mode, "inode": number,
                        "size": inode.size, "kind": kind, "xattrs": attrs}
                if fs_type == "ext4":
                    item["ext4_flags"] = inode.flags
                if kind == "symlink":
                    target = fs._dir_data(inode) if fs_type == "erofs" else fs.read_link(inode)
                    if b"\0" in target:
                        raise ValueError(f"NUL in symlink target: {path}")
                    item["symlink_target"] = target.decode("utf-8", "strict")
                result[path] = item
                if kind == "dir":
                    if number in seen_dirs:
                        raise ValueError("directory cycle or hardlink")
                    seen_dirs.add(number)
                    children = _erofs_directory(fs, inode) if fs_type == "erofs" else fs.iter_dir(inode)
                    for name, child in children:
                        decoded = name.decode("utf-8", "strict")
                        if not decoded or "/" in decoded or decoded in (".", ".."):
                            raise ValueError("invalid directory entry")
                        pending.append(((path.rstrip("/") + "/" + decoded), child))
            if result["/"]["kind"] != "dir":
                raise ValueError("root inode is not a directory")
            return dict(sorted(result.items()))
    except Exception as exc:
        raise ValueError(f"cannot export {fs_type} metadata: {exc}") from exc
