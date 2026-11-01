import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ports/coloros17/fs_metadata.py"
LABEL = b"u:object_r:system_file:s0\0".hex()


def record(kind="dir", mode=0o40755, **changes):
    value = {"uid": 0, "gid": 0, "mode": mode, "inode": 1, "size": 0,
             "kind": kind, "xattrs": {"security.selinux": LABEL}}
    value.update(changes)
    return value


class MetadataCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), "metadata helper is missing")
        spec = importlib.util.spec_from_file_location("coloros_metadata", MODULE)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)


class MetadataTests(MetadataCase):
    def test_canonical_paths_are_validated_without_rewriting(self):
        for path in ("/", "/system/bin/init", "/my_product/中文.apk"):
            self.assertEqual(self.api.canonical_path(path), path)
        for path in ("", "system", "//system", "/system/", "/./system", "/x/../y",
                     "/a b", "/a\tb", "/a\nb", "/a\x00b", "/a\\b", "/\udcff", None):
            with self.subTest(path=repr(path)), self.assertRaises(ValueError):
                self.api.canonical_path(path)

    def test_only_exactly_representable_capability_xattrs_are_accepted(self):
        self.assertEqual(self.api.decode_capability_xattr(None), 0)
        raw = struct.pack("<IIIII", 0x02000001, 4, 0, 1, 0)
        self.assertEqual(self.api.decode_capability_xattr(raw), 0x100000004)
        bad = [b"", raw[:-1], struct.pack("<IIIII", 0x02000000, 4, 0, 0, 0),
               struct.pack("<IIIII", 0x02000001, 4, 1, 0, 0),
               struct.pack("<IIIII", 0x02000001, 0, 0, 0, 0),
               struct.pack("<IIIII", 0x02000001, 0, 0, 0x80000000, 0),
               struct.pack("<IIIIII", 0x03000001, 4, 0, 0, 0, 0)]
        for raw in bad:
            with self.subTest(raw=raw.hex()), self.assertRaises(ValueError):
                self.api.decode_capability_xattr(raw)

    def test_render_complete_metadata_with_root_special_modes_and_exact_labels(self):
        entries = {"/": record(uid=70000, gid=71000, mode=0o40751),
                   "/system": record(),
                   "/system/a.apk": record("file", 0o104750, uid=1000, inode=2,
                       xattrs={"security.selinux": LABEL,
                               "security.capability": struct.pack("<IIIII", 0x02000001, 0, 0, 1, 0).hex()}),
                   "/system/link": record("symlink", 0o120777, inode=3,
                                          symlink_target="a.apk")}
        before = copy.deepcopy(entries)
        self.assertEqual(self.api.render_fs_config(entries),
                         "/ 70000 71000 0751 capabilities=0x0\n"
                         "/system 0 0 0755 capabilities=0x0\n"
                         "/system/a.apk 1000 0 4750 capabilities=0x100000000\n"
                         "/system/link 0 0 0777 capabilities=0x0\n")
        self.assertEqual(self.api.render_file_contexts(entries),
                         "/ u:object_r:system_file:s0\n"
                         "/system u:object_r:system_file:s0\n"
                         "/system/a\\.apk u:object_r:system_file:s0\n"
                         "/system/link u:object_r:system_file:s0\n")
        self.assertEqual(entries, before)

    def test_render_rejects_incomplete_or_lossy_metadata(self):
        variants = [{"/x": record()},
                    {"/": record(), "/missing/x": record()},
                    {"/": record(), "/link": record("symlink", 0o120777),
                     "/link/child": record()},
                    {"/": record(uid=2**31)}, {"/": record(gid=-1)},
                    {"/": record(mode=0o100644)}, {"/": record(uid=True)},
                    {"/": record(xattrs={})},
                    {"/": record(xattrs={"security.selinux": "00"})},
                    {"/": record(xattrs={"security.selinux": "not hex"})},
                    {"/": record(xattrs={"security.selinux": LABEL, "user.extra": "01"})},
                    {"/": record(size=-1)}, {"/": record(inode=-1)}]
        for entries in variants:
            for render in (self.api.render_fs_config, self.api.render_file_contexts):
                with self.subTest(entries=entries, render=render.__name__), self.assertRaises(ValueError):
                    render(entries)

    def test_label_paths_escape_utf8_and_regex_metacharacters(self):
        entries = {"/": record(), "/a[1]": record(), "/é": record()}
        text = self.api.render_file_contexts(entries)
        self.assertIn("/a\\[1\\] u:object_r:", text)
        self.assertIn("/\\xc3\\xa9 u:object_r:", text)

    def test_erofs_zero_inode_id_can_be_rendered(self):
        self.assertEqual(self.api.render_fs_config({"/": record(inode=0)}),
                         "/ 0 0 0755 capabilities=0x0\n")

    def test_valid_hyphenated_selinux_type_is_preserved(self):
        label = b"u:object_r:ofm-service_exec:s0".hex()
        entries = {"/": record(xattrs={"security.selinux": label})}
        self.assertEqual(self.api.render_file_contexts(entries),
                         "/ u:object_r:ofm-service_exec:s0\n")

    def test_invalid_key_type_is_a_validation_error(self):
        with self.assertRaises(ValueError):
            self.api.render_fs_config({"/": record(), 3: record()})

    def test_ext4_layout_flags_do_not_change_rendered_metadata(self):
        expected = "/ 0 0 0755 capabilities=0x0\n"
        for flags in (0, 0x00001000, 0x00080000, 0x10000000, 0x10081000):
            with self.subTest(flags=hex(flags)):
                self.assertEqual(self.api.render_fs_config({"/": record(ext4_flags=flags)}), expected)

    def test_ext4_semantic_unknown_or_invalid_flags_cannot_be_rendered(self):
        # Casefold, fs-verity, immutable, append-only, and an unknown bit.
        for flags in (0x40000000, 0x00100000, 0x10, 0x20, 0x80000000,
                      0x40080000, -1, 0x100000000, True, "0"):
            for render in (self.api.render_fs_config, self.api.render_file_contexts):
                with self.subTest(flags=flags, render=render.__name__), self.assertRaises(ValueError):
                    render({"/": record(ext4_flags=flags)})


def erofs_fixture():
    """Hand-built flat EROFS: root, extended file and compact symlink."""
    data = bytearray(16384)
    sb = 1024
    struct.pack_into("<I", data, sb, 0xE0F5E1E2)
    data[sb + 12] = 12
    struct.pack_into("<H", data, sb + 14, 0)
    struct.pack_into("<II", data, sb + 40, 1, 3)
    # Root compact inode, directory at block 2; uid/gid offsets are independent literals.
    struct.pack_into("<HHHHIII", data, 4096, 0, 0, 0o40751, 2, 51, 0, 2)
    struct.pack_into("<HH", data, 4096 + 24, 1000, 1001)
    # File extended inode, nid 2; one inline label and one shared capability.
    label_entry = struct.pack("<BBH", 7, 6, len(bytes.fromhex(LABEL))) + b"selinux" + bytes.fromhex(LABEL)
    label_entry += b"\0" * (-len(label_entry) % 4)
    xattrs = struct.pack("<IB7xI", 0, 1, 0) + label_entry
    struct.pack_into("<HHHHQI", data, 4160, 1, 1 + (len(xattrs) - 12) // 4,
                     0o104750, 0, 1, 0)
    struct.pack_into("<II", data, 4160 + 24, 70000, 71000)
    data[4224:4224 + len(xattrs)] = xattrs
    caps = struct.pack("<IIIII", 0x02000001, 0, 0, 1, 0)
    shared = struct.pack("<BBH", 10, 6, len(caps)) + b"capability" + caps
    data[12288:12288 + len(shared)] = shared
    # Compact inline symlink, nid 6, target "file".
    struct.pack_into("<HHHHIII", data, 4288, 4, 0, 0o120777, 1, 4, 0, 0)
    data[4320:4324] = b"file"
    names = b".\0..\0file\0link\0"
    for i, (nid, name_offset, kind) in enumerate(((0, 48, 2), (0, 50, 2), (2, 53, 1), (6, 58, 7))):
        struct.pack_into("<QHBB", data, 8192 + i * 12, nid, name_offset, kind, 0)
    data[8240:8240 + len(names)] = names
    struct.pack_into("<I", data, 4096 + 8, 48 + len(names))
    return data


class ExporterTests(MetadataCase):
    def setUp(self):
        super().setUp()
        location = os.environ.get("MYSTIC_SOURCE_ROOT")
        if not location:
            self.skipTest("set MYSTIC_SOURCE_ROOT for pinned-parser integration tests")
        self.source = Path(location)

    def test_erofs_exports_inline_shared_attrs_and_extended_ids_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sample.img"
            image.write_bytes(erofs_fixture())
            before = hashlib.sha256(image.read_bytes()).digest()
            entries = self.api.read_inode_manifest(image, "erofs", self.source)
            self.assertEqual(set(entries), {"/", "/file", "/link"})
            self.assertEqual((entries["/"]["uid"], entries["/"]["gid"]), (1000, 1001))
            self.assertEqual((entries["/file"]["uid"], entries["/file"]["gid"]), (70000, 71000))
            self.assertEqual(entries["/file"]["xattrs"]["security.selinux"], LABEL)
            self.assertEqual(entries["/file"]["xattrs"]["security.capability"],
                             "0100000200000000000000000100000000000000")
            self.assertEqual(entries["/link"]["symlink_target"], "file")
            self.assertEqual(before, hashlib.sha256(image.read_bytes()).digest())

    def test_erofs_rejects_long_prefixes_and_broken_xattr_bounds(self):
        for offset, payload in ((1104, struct.pack("<I", 0x40)), (4228, b"\x7f"),
                                (4242, b"\xff\xff")):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as tmp:
                data = erofs_fixture()
                data[offset:offset + len(payload)] = payload
                image = Path(tmp) / "bad.img"
                image.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.api.read_inode_manifest(image, "erofs", self.source)

    @unittest.skipUnless(shutil.which("mke2fs"), "mke2fs required for EXT4 fixture")
    def test_ext4_exports_regular_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            (tree / "file").write_bytes(b"abc")
            (tree / "file").chmod(0o750)
            (tree / "link").symlink_to("file")
            image = Path(tmp) / "sample.img"
            with image.open("wb") as output:
                output.truncate(16 * 1024 * 1024)
            subprocess.run([shutil.which("mke2fs"), "-q", "-t", "ext4", "-O", "^has_journal",
                            "-F", "-d", str(tree), str(image)], check=True, capture_output=True)
            before = hashlib.sha256(image.read_bytes()).digest()
            entries = self.api.read_inode_manifest(image, "ext4", self.source)
            self.assertEqual(entries["/file"]["mode"], stat.S_IFREG | 0o750)
            self.assertEqual(entries["/file"]["size"], 3)
            self.assertEqual(entries["/file"]["uid"], os.getuid())
            self.assertEqual(entries["/link"]["symlink_target"], "file")
            self.assertEqual(before, hashlib.sha256(image.read_bytes()).digest())

    @unittest.skipUnless(shutil.which("mke2fs") and shutil.which("debugfs"), "e2fsprogs required")
    def test_ext4_exports_raw_security_xattrs_and_rejects_bad_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            (tree / "file").write_bytes(b"abc")
            image = Path(tmp) / "attrs.img"
            with image.open("wb") as output:
                output.truncate(16 * 1024 * 1024)
            subprocess.run([shutil.which("mke2fs"), "-q", "-t", "ext4", "-O", "^has_journal",
                            "-F", "-d", str(tree), str(image)], check=True, capture_output=True)
            capfile = Path(tmp) / "caps.bin"
            capfile.write_bytes(struct.pack("<IIIII", 0x02000001, 4, 0, 1, 0))
            commands = [f"ea_set -f {capfile} /file security.capability",
                        "ea_set /file security.selinux u:object_r:system_file:s0"]
            for command in commands:
                subprocess.run([shutil.which("debugfs"), "-w", "-R", command, str(image)],
                               check=True, capture_output=True)
            entries = self.api.read_inode_manifest(image, "ext4", self.source)
            self.assertEqual(entries["/file"]["xattrs"],
                             {"security.capability": "0100000204000000000000000100000000000000",
                              "security.selinux": b"u:object_r:system_file:s0".hex()})
            data = bytearray(image.read_bytes())
            # An ext4 xattr name follows its 16-byte entry header.
            name_start = data.index(b"selinux")
            struct.pack_into("<H", data, name_start - 14, 0xFFFF)
            image.write_bytes(data)
            with self.assertRaises(ValueError):
                self.api.read_inode_manifest(image, "ext4", self.source)

    @unittest.skipUnless(shutil.which("mke2fs") and shutil.which("debugfs"), "e2fsprogs required")
    def test_ext4_exports_casefold_verity_and_immutable_flags_without_dropping_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            (tree / "file").write_bytes(b"abc")
            (tree / "folded").mkdir()
            image = Path(tmp) / "flags.img"
            with image.open("wb") as output:
                output.truncate(16 * 1024 * 1024)
            subprocess.run([shutil.which("mke2fs"), "-q", "-t", "ext4", "-O", "^has_journal",
                            "-F", "-d", str(tree), str(image)], check=True, capture_output=True)
            original = image.read_bytes()
            for path, flags in (("/folded", 0x40080000), ("/file", 0x00180000),
                                ("/file", 0x00080010), ("/file", 0x00080020)):
                with self.subTest(path=path, flags=hex(flags)):
                    image.write_bytes(original)
                    subprocess.run([shutil.which("debugfs"), "-w", "-R",
                                    f"set_inode_field {path} flags {hex(flags)}", str(image)],
                                   check=True, capture_output=True)
                    entries = self.api.read_inode_manifest(image, "ext4", self.source)
                    self.assertEqual(entries[path]["ext4_flags"], flags)
                    # Supply an otherwise renderable label to isolate this flag rejection.
                    selected = dict(entries[path], xattrs={"security.selinux": LABEL})
                    one = {"/": record()} | {path: selected}
                    for render in (self.api.render_fs_config, self.api.render_file_contexts):
                        with self.assertRaisesRegex(ValueError, "unsupported EXT4 inode flags"):
                            render(one)

    def test_unpinned_reader_sources_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.api.read_inode_manifest("unused.img", "erofs", tmp)

    def test_invalid_or_truncated_images_raise_validation_errors(self):
        for fs_type in ("erofs", "ext4"):
            with self.subTest(fs_type=fs_type), tempfile.TemporaryDirectory() as tmp:
                image = Path(tmp) / "invalid.img"
                image.write_bytes(b"bad image")
                with self.assertRaises(ValueError):
                    self.api.read_inode_manifest(image, fs_type, self.source)

    def test_erofs_huge_metadata_read_is_rejected_before_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = erofs_fixture()
            struct.pack_into("<I", data, 4096 + 8, 0xFFFFFFFF)
            image = Path(tmp) / "bad.img"
            image.write_bytes(data)
            with self.assertRaises(ValueError):
                self.api.read_inode_manifest(image, "erofs", self.source)


if __name__ == "__main__":
    unittest.main()
