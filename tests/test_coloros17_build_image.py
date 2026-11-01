import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ports/coloros17/build_image.py"
LABEL = b"u:object_r:system_file:s0\0".hex()


def fixture(parent):
    tree = parent / "tree"
    tree.mkdir()
    (tree / "system").mkdir()
    (tree / "system/file").write_bytes(b"preserve\0me\n")
    (tree / "alias").symlink_to("/system/file")
    records = {}
    for name, kind, mode in (("/", "dir", 0o40755), ("/system", "dir", 0o40750),
                             ("/system/file", "file", 0o100640), ("/alias", "symlink", 0o120777)):
        physical = tree / name.lstrip("/")
        records[name] = {"kind": kind, "mode": mode, "uid": 0, "gid": 0,
                         "inode": physical.lstat().st_ino, "size": physical.lstat().st_size,
                         "xattrs": {"security.selinux": LABEL}}
        if kind == "symlink":
            records[name]["symlink_target"] = os.readlink(physical)
    contents = {
        "/system/file": {"kind": "file", "size": 12,
                         "sha256": hashlib.sha256(b"preserve\0me\n").hexdigest()},
        "/alias": {"kind": "symlink", "target": "/system/file"},
    }
    return tree, records, contents


class BuilderCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), "preservation image builder is missing")
        spec = importlib.util.spec_from_file_location("coloros_build_image", MODULE)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)


class BuilderTests(BuilderCase):
    def test_physical_content_is_exact_and_donor_host_modes_may_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree, records, contents = fixture(Path(tmp))
            (tree / "system/file").chmod(0o600)
            records["/system/file"].update(uid=123456, gid=3003, mode=0o106750)
            snapshot = self.api.validate_tree(tree, records, contents)
            self.assertEqual(set(snapshot), set(records))
            self.assertEqual((tree / "system/file").read_bytes(), b"preserve\0me\n")

    def test_missing_extra_type_size_hash_symlink_and_hardlink_changes_fail(self):
        for change in ("missing", "extra", "type", "size", "hash", "target", "hardlink", "badpath"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                tree, records, contents = fixture(Path(tmp))
                if change == "missing":
                    (tree / "system/file").unlink()
                elif change == "extra":
                    (tree / "unknown").write_text("unknown")
                elif change == "type":
                    (tree / "system/file").unlink()
                    (tree / "system/file").mkdir()
                elif change == "size":
                    (tree / "system/file").write_bytes(b"changed")
                elif change == "hash":
                    (tree / "system/file").write_bytes(b"Preserve\0me\n")
                elif change == "target":
                    (tree / "alias").unlink()
                    (tree / "alias").symlink_to("/system/FILE")
                elif change == "hardlink":
                    os.link(tree / "system/file", Path(tmp) / "outside-hardlink")
                else:
                    records["/system/../bad"] = copy.deepcopy(records["/system/file"])
                with self.assertRaises(ValueError):
                    self.api.validate_tree(tree, records, contents)

    def test_content_manifest_must_cover_exactly_nondirectories(self):
        for change in ("missing", "extra", "directory", "size", "digest", "target"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                tree, records, contents = fixture(Path(tmp))
                if change == "missing":
                    contents.pop("/alias")
                elif change == "extra":
                    contents["/unknown"] = dict(contents["/system/file"])
                elif change == "directory":
                    contents["/system"] = {"kind": "dir"}
                elif change == "size":
                    contents["/system/file"]["size"] = True
                elif change == "digest":
                    contents["/system/file"]["sha256"] = "0" * 63
                else:
                    contents["/alias"]["target"] = "/elsewhere"
                with self.assertRaises(ValueError):
                    self.api.validate_tree(tree, records, contents)

    def test_only_exact_empty_my_reserve_can_lack_selinux_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree, records, contents = fixture(Path(tmp))
            (tree / "my_reserve").mkdir()
            records["/my_reserve"] = dict(records["/"], size=0, xattrs={})
            before = copy.deepcopy(records)
            config, contexts, exceptions = self.api.render_build_tables(records)
            self.assertIn("/my_reserve 0 0 0755 capabilities=0x0\n", config)
            self.assertIn("/my_reserve u:object_r:system_file:s0\n", contexts)
            self.assertEqual(exceptions[0]["path"], "/my_reserve")
            self.assertEqual(records, before)
            for field, value in (("uid", 1), ("gid", 1), ("mode", 0o40700), ("kind", "file")):
                bad = copy.deepcopy(records)
                bad["/my_reserve"][field] = value
                with self.assertRaises(ValueError):
                    self.api.render_build_tables(bad)
            bad = copy.deepcopy(records)
            bad["/my_reserve/child"] = dict(records["/system/file"])
            with self.assertRaises(ValueError):
                self.api.render_build_tables(bad)
            records["/system"]["xattrs"] = {}
            with self.assertRaises(ValueError):
                self.api.render_build_tables(records)

    def test_hash_sink_fills_sparse_holes_and_rejects_backward_or_overflow_writes(self):
        sink = self.api.ForwardHashSink(12)
        sink.write(b"ab")
        sink.seek(6)
        sink.write(b"cd")
        sink.truncate(12)
        self.assertEqual(sink.hexdigest(), hashlib.sha256(b"ab" + b"\0" * 4 + b"cd" + b"\0" * 4).hexdigest())
        with self.assertRaises(ValueError):
            sink.seek(1)
        with self.assertRaises(ValueError):
            sink.write(b"x")
        with self.assertRaises(ValueError):
            self.api.ForwardHashSink(4).truncate(3)

    def test_metadata_verification_ignores_layout_but_detects_semantic_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, records, _ = fixture(Path(tmp))
            actual = copy.deepcopy(records)
            for item in actual.values():
                item["inode"] += 1000
                item["ext4_flags"] = 0x80000
                item["xattrs"]["security.selinux"] = bytes.fromhex(LABEL).rstrip(b"\0").hex()
                if item["kind"] == "dir":
                    item["size"] = 4096
            exceptions = self.api.verify_metadata(records, actual)
            self.assertEqual(exceptions, [])
            for field, value in (("uid", 1), ("mode", 0o100600), ("size", 11),
                                 ("xattrs", {}), ("ext4_flags", 0x80010)):
                bad = copy.deepcopy(actual)
                bad["/system/file"][field] = value
                with self.assertRaises(ValueError):
                    self.api.verify_metadata(records, bad)
            actual["/lost+found"] = dict(actual["/"], mode=0o40700, xattrs={})
            with self.assertRaises(ValueError):
                self.api.verify_metadata(records, actual)

    def test_donor_lost_found_is_rejected_before_build_instead_of_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree, records, contents = fixture(Path(tmp))
            (tree / "lost+found").mkdir()
            records["/lost+found"] = dict(records["/"])
            with self.assertRaisesRegex(ValueError, "lost\\+found"):
                self.api.validate_tree(tree, records, contents)
            self.assertTrue((tree / "lost+found").is_dir())

    def test_output_file_reader_must_hash_every_byte_and_finalize_declared_size(self):
        class Inode:
            size = 12

        class Reader:
            def __init__(self, path):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read_inode(self, number):
                return Inode()

            def write_file(self, inode, out):
                out.write(b"Preserve\0me\n")
                out.truncate(12)

        with tempfile.TemporaryDirectory() as tmp:
            _, records, contents = fixture(Path(tmp))
            with patch.object(self.api, "_load_reader", return_value=Reader):
                with self.assertRaisesRegex(ValueError, "SHA256"):
                    self.api._verify_content("unused.img", records, contents, "unused")

    def test_size_uses_file_allocation_and_reserve_without_donor_directory_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, records, _ = fixture(Path(tmp))
            records["/"]["size"] = 1024**4
            records["/system"]["size"] = 1024**4
            size = self.api._size_plan(records, 1024**3)
            self.assertEqual(size["file_allocated_bytes"], 4096)
            self.assertEqual(size["directory_bytes"], 24576)
            self.assertEqual(size["image_bytes"], 1073774592)
            for invalid in (-1, True, "4096"):
                with self.assertRaises(ValueError):
                    self.api._size_plan(records, invalid)

    def test_build_preflight_rejects_root_existing_or_nested_output_and_unpinned_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            executable = parent / "tool"
            executable.write_text("#!/bin/sh\nexit 99\n")
            executable.chmod(0o700)
            paths = {name: str(executable) for name in ("mke2fs", "e2fsdroid", "e2fsck", "debugfs")}
            hashes = {name: hashlib.sha256(executable.read_bytes()).hexdigest() for name in paths}
            with patch.object(self.api.os, "geteuid", return_value=0), self.assertRaisesRegex(ValueError, "root"):
                self.api.build_image(tree, records, contents, parent / "image", parent, paths, hashes)
            for output in (tree / "inside.img", parent / "existing.img"):
                if output.parent == parent:
                    output.touch()
                with self.assertRaises(ValueError):
                    self.api.build_image(tree, records, contents, output, parent, paths, hashes)
            hashes["debugfs"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "hash"):
                self.api.build_image(tree, records, contents, parent / "image", parent, paths, hashes)
            self.assertEqual(set(parent.iterdir()), {tree, executable, parent / "existing.img"})

    def test_native_failure_preserves_logs_and_never_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            executable = parent / "tool"
            executable.write_text("#!/bin/sh\necho explicit-native-failure >&2\nexit 7\n")
            executable.chmod(0o700)
            paths = {name: str(executable) for name in ("mke2fs", "e2fsdroid", "e2fsck", "debugfs")}
            hashes = {name: hashlib.sha256(executable.read_bytes()).hexdigest() for name in paths}
            with patch.object(self.api, "_load_reader", return_value=object), self.assertRaises(self.api.BuildError) as failure:
                self.api.build_image(tree, records, contents, parent / "image", parent, paths, hashes, reserve_bytes=16 * 1024**2)
            report = failure.exception.report
            self.assertFalse((parent / "image").exists())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["commands"][0]["returncode"], 7)
            self.assertIn("explicit-native-failure", Path(report["commands"][0]["log_path"]).read_text())
            self.assertEqual(json.loads(Path(report["report_path"]).read_text())["status"], "failed")
            self.assertEqual((tree / "system/file").read_bytes(), b"preserve\0me\n")

    def test_insufficient_disk_space_rejects_before_staging_or_native_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            executable = parent / "tool"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            paths = {name: str(executable) for name in ("mke2fs", "e2fsdroid", "e2fsck", "debugfs")}
            hashes = {name: hashlib.sha256(executable.read_bytes()).hexdigest() for name in paths}
            # Fixture: 32 KiB after allocation/overhead rounding, plus reserve.
            required = 32768 + 16 * 1024**2 + 512 * 1024**2
            capacity = shutil.disk_usage(parent)._replace(free=required - 1)
            with patch("shutil.disk_usage", return_value=capacity), \
                    patch.object(self.api, "_load_reader", return_value=object), \
                    patch.object(self.api.tempfile, "mkdtemp", side_effect=AssertionError("staging attempted")), \
                    patch.object(self.api.subprocess, "run", side_effect=AssertionError("native execution attempted")):
                with self.assertRaisesRegex(ValueError, "disk space"):
                    self.api.build_image(tree, records, contents, parent / "image", parent, paths, hashes,
                                         reserve_bytes=16 * 1024**2)
            self.assertEqual(set(parent.iterdir()), {tree, executable})


class NativeBuilderTests(BuilderCase):
    def native_environment(self):
        mystic = os.environ.get("MYSTIC_SOURCE_ROOT")
        native = os.environ.get("COLOROS_NATIVE_TOOL_DIR")
        if not mystic or not native or os.geteuid() == 0:
            self.skipTest("set MYSTIC_SOURCE_ROOT and COLOROS_NATIVE_TOOL_DIR as an unprivileged Linux user")
        paths = {name: str(Path(native) / name) if name in ("mke2fs", "e2fsdroid") else shutil.which(name)
                 for name in ("mke2fs", "e2fsdroid", "e2fsck", "debugfs")}
        if any(not value or not Path(value).is_file() for value in paths.values()):
            self.skipTest("all four native tools are required")
        hashes = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in paths.items()}
        return mystic, paths, hashes

    def test_real_ext4_preserves_capabilities_high_ids_sparse_bytes_and_unlabeled_directory(self):
        mystic, paths, hashes = self.native_environment()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            (tree / "my_reserve").mkdir()
            records["/my_reserve"] = dict(records["/"], size=0, xattrs={})
            records["/system/file"].update(uid=123456, gid=3003, mode=0o106750)
            records["/system/file"]["xattrs"]["security.capability"] = struct.pack("<5I", 0x02000001, 4, 0, 1, 0).hex()
            with (tree / "sparse").open("wb") as stream:
                stream.seek(8192)
                stream.write(b"end")
            records["/sparse"] = dict(records["/system/file"], size=8195, inode=99,
                                       mode=0o100600, xattrs={"security.selinux": LABEL})
            contents["/sparse"] = {"kind": "file", "size": 8195,
                                   "sha256": hashlib.sha256(b"\0" * 8192 + b"end").hexdigest()}
            before = copy.deepcopy(records)
            output = parent / "preserved.img"
            report = self.api.build_image(tree, records, contents, output, mystic, paths, hashes,
                                          reserve_bytes=16 * 1024**2)
            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(report["content_verified_files"], 2)
            self.assertEqual(records, before)
            self.assertTrue(all(item["returncode"] == 0 for item in report["commands"]))
            actual = self.api.read_inode_manifest(output, "ext4", mystic)
            self.assertEqual(actual["/my_reserve"]["xattrs"], {})
            self.assertEqual(set(actual), set(records))

    def test_report_write_failure_after_publication_keeps_verified_success_explicit(self):
        mystic, paths, hashes = self.native_environment()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            save_report = self.api._save_report

            def fail_completed_report(report):
                if report["status"] == "complete":
                    raise OSError("injected report storage error")
                save_report(report)

            with patch.object(self.api, "_save_report", side_effect=fail_completed_report):
                report = self.api.build_image(tree, records, contents, parent / "image", mystic,
                                              paths, hashes, reserve_bytes=16 * 1024**2)
            self.assertEqual(report["status"], "complete")
            self.assertIn("injected report storage error", report["report_save_error"])
            self.assertEqual(hashlib.sha256((parent / "image").read_bytes()).hexdigest(), report["sha256"])
            self.assertEqual(json.loads(Path(report["report_path"]).read_text())["status"], "verified")

    def test_interrupt_immediately_after_real_publication_preserves_complete_report(self):
        mystic, paths, hashes = self.native_environment()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            output = parent / "image"
            replace = self.api.os.replace

            def replace_then_interrupt(source, destination):
                replace(source, destination)
                if Path(destination) == output:
                    raise KeyboardInterrupt("injected after actual image rename")

            with patch.object(self.api.os, "replace", side_effect=replace_then_interrupt):
                try:
                    report = self.api.build_image(tree, records, contents, output, mystic, paths, hashes,
                                                  reserve_bytes=16 * 1024**2)
                except BaseException as error:
                    self.fail(f"published image was treated as interrupted: {error!r}")
            self.assertEqual(report["status"], "complete")
            self.assertIn("KeyboardInterrupt", report["post_publish_warning"])
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), report["sha256"])
            self.assertEqual(json.loads(Path(report["report_path"]).read_text())["status"], "complete")

    def test_interrupt_while_saving_final_report_keeps_published_image_complete(self):
        mystic, paths, hashes = self.native_environment()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            save_report = self.api._save_report

            def interrupt_final_report(report):
                if report["status"] == "complete":
                    raise KeyboardInterrupt("injected final report interrupt")
                save_report(report)

            with patch.object(self.api, "_save_report", side_effect=interrupt_final_report):
                try:
                    report = self.api.build_image(tree, records, contents, parent / "image", mystic,
                                                  paths, hashes, reserve_bytes=16 * 1024**2)
                except BaseException as error:
                    self.fail(f"published image was treated as interrupted: {error!r}")
            self.assertEqual(report["status"], "complete")
            self.assertIn("KeyboardInterrupt", report["post_publish_warning"])
            self.assertIn("KeyboardInterrupt", report["report_save_error"])
            self.assertEqual(hashlib.sha256((parent / "image").read_bytes()).hexdigest(), report["sha256"])
            self.assertEqual(json.loads(Path(report["report_path"]).read_text())["status"], "verified")


if __name__ == "__main__":
    unittest.main()
