import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ports/coloros17/compat.py"
GENFS = "/system/etc/selinux/plat_sepolicy_genfs_202604.cil"
INIT = "/system/etc/init/hw/init.rc"
MATRIX = "/system/etc/vintf/compatibility_matrix.dash-additions.xml"
TEMPLATE = "/system/etc/vintf/compatibility_matrix.device.xml"
SKIP_PARENT = "/system/system_ext/etc/init"
SKIP_DIR = SKIP_PARENT + "/config"
SKIP_MOUNT = SKIP_DIR + "/skip_mount.cfg"
SKIP_BYTES = b"/system_ext\n/product\n"
LABEL = b"u:object_r:system_file:s0\0".hex()
# Exact, small official donor file: expectations are independent of the helper.
BEFORE_GENFS = b'''(genfscon sysfs "/class/udc" (u object_r sysfs_udc ((s0) (s0))))
(genfscon sysfs "/power/mem_sleep" (u object_r sysfs_mem_sleep ((s0) (s0))))
(genfscon sysfs "/class/typec" (u object_r sysfs_typec ((s0) (s0))))
;; #ifdef QCOM_ONLY_CHANGES
(genfscon sysfs "/class/powercap" (u object_r sysfs_powercap ((s0) (s0))))
(genfscon sysfs "/devices/virtual/powercap" (u object_r sysfs_powercap ((s0) (s0))))
;; #endif /* QCOM_ONLY_CHANGES */
(genfscon proc "/sys/kernel/firmware_config" (u object_r proc_firmware_config ((s0) (s0))))
'''
AFTER_GENFS = b'''(genfscon sysfs "/class/udc" (u object_r sysfs_udc ((s0) (s0))))
(genfscon sysfs "/power/mem_sleep" (u object_r sysfs_mem_sleep ((s0) (s0))))
(genfscon sysfs "/class/typec" (u object_r sysfs_typec ((s0) (s0))))
;; #ifdef QCOM_ONLY_CHANGES
;; #endif /* QCOM_ONLY_CHANGES */
(genfscon proc "/sys/kernel/firmware_config" (u object_r proc_firmware_config ((s0) (s0))))
'''
BEFORE_INIT = b"# donor\non early-init\n    write /proc/bootprof 1\n    exec_start apexd-bootstrap\n    start ueventd\n"
AFTER_INIT = b"# donor\non early-init\n    write /proc/bootprof 1\n    restorecon /dev/loop-control\n    exec_start apexd-bootstrap\n    start ueventd\n"


def manifest(tree):
    records, contents = {}, {}
    for path in [tree, *sorted(tree.rglob("*"))]:
        info = path.lstat()
        name = "/" if path == tree else "/" + str(path.relative_to(tree))
        kind = {stat.S_IFREG: "file", stat.S_IFDIR: "dir", stat.S_IFLNK: "symlink"}[stat.S_IFMT(info.st_mode)]
        records[name] = {"uid": 0, "gid": 0, "mode": info.st_mode, "kind": kind,
                         "inode": info.st_ino, "size": info.st_size,
                         "xattrs": {"security.selinux": LABEL}, "ext4_flags": 0}
        if kind == "file":
            contents[name] = {"kind": "file", "size": info.st_size,
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        elif kind == "symlink":
            records[name]["symlink_target"] = os.readlink(path)
            contents[name] = {"kind": "symlink", "target": os.readlink(path)}
    return records, contents


def tree_snapshot(tree):
    return {str(p.relative_to(tree)): (os.readlink(p) if p.is_symlink() else
                                     ("dir", stat.S_IMODE(p.stat().st_mode)) if p.is_dir() else p.read_bytes())
            for p in tree.rglob("*")}


def tree_replacement(dst, kwargs, tree, name):
    parent = Path(os.readlink(f"/proc/self/fd/{kwargs['dst_dir_fd']}"))
    return parent / str(dst) == tree / name[1:]


def fixture(parent):
    tree = parent / "canonical"
    files = {GENFS: BEFORE_GENFS, INIT: BEFORE_INIT, TEMPLATE: b'<compatibility-matrix version="1.0" type="framework"/>\n',
             "/system/keep.bin": b"unchanged\x00binary\xff"}
    for name, data in files.items():
        path = tree / name[1:]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o644)
    (tree / "system/link").symlink_to("keep.bin")
    (tree / SKIP_PARENT[1:]).mkdir(parents=True)
    (tree / "system/product").mkdir()
    (tree / "system_ext").symlink_to("/system/system_ext")
    (tree / "product").symlink_to("/system/product")
    records, contents = manifest(tree)
    # Donor metadata is independent of host metadata and must survive untouched.
    records[GENFS]["uid"] = 1000
    records[GENFS]["gid"] = 2000
    records[GENFS]["mode"] = 0o100640
    records[GENFS]["xattrs"] = {"security.selinux": b"u:object_r:sepolicy_file:s0\0".hex()}
    return tree, records, contents


def legacy_fixture(parent):
    """Represent the reviewed earlier three-fix report without using compat.py."""
    tree, records, contents = fixture(parent)
    replacements = {GENFS: AFTER_GENFS, INIT: AFTER_INIT,
                    MATRIX: (ROOT / "ports/coloros17/patches/compatibility_matrix.dash-additions.xml").read_bytes()}
    records[MATRIX] = copy.deepcopy(records[TEMPLATE])
    records[MATRIX]["inode"] = max(r["inode"] for r in records.values()) + 1
    for name, data in replacements.items():
        (tree / name[1:]).write_bytes(data)
        (tree / name[1:]).chmod(0o644)
        records[name]["size"] = len(data)
        contents[name] = {"kind": "file", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return tree, records, contents


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), "compatibility helper is missing")
        spec = importlib.util.spec_from_file_location("coloros_compat", MODULE)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)

    def test_plan_preserves_other_bytes_and_metadata_and_adds_unique_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree, records, contents = fixture(Path(tmp))
            before_records, before_contents = copy.deepcopy(records), copy.deepcopy(contents)
            before_tree = tree_snapshot(tree)
            plan = self.api.plan_compatibility(tree, records, contents)
            self.assertEqual(plan["status"], "planned")
            self.assertEqual([c["path"] for c in plan["changes"]], [GENFS, INIT, MATRIX, SKIP_DIR, SKIP_MOUNT])
            self.assertEqual([c["action"] for c in plan["changes"]], ["replace", "replace", "add", "add", "add"])
            changed = plan["final_records"]
            for name in (GENFS, INIT):
                self.assertEqual({k: v for k, v in changed[name].items() if k != "size"},
                                 {k: v for k, v in records[name].items() if k != "size"})
            new = changed[MATRIX]
            self.assertEqual({k: v for k, v in new.items() if k not in ("inode", "size")},
                             {k: v for k, v in records[TEMPLATE].items() if k not in ("inode", "size")})
            self.assertNotIn(new["inode"], {r["inode"] for r in records.values()})
            for name, kind, mode, size in ((SKIP_DIR, "dir", 0o40755, 0),
                                           (SKIP_MOUNT, "file", 0o100644, 21)):
                self.assertEqual((changed[name]["kind"], changed[name]["mode"], changed[name]["size"]),
                                 (kind, mode, size))
                self.assertEqual((changed[name]["uid"], changed[name]["gid"]), (0, 0))
                self.assertEqual(changed[name]["xattrs"], {"security.selinux": LABEL})
            new_inodes = {changed[name]["inode"] for name in (MATRIX, SKIP_DIR, SKIP_MOUNT)}
            self.assertEqual(len(new_inodes), 3)
            self.assertTrue(new_inodes.isdisjoint({r["inode"] for r in records.values()}))
            self.assertNotIn(SKIP_DIR, plan["final_content_manifest"])
            self.assertEqual(plan["final_content_manifest"][SKIP_MOUNT],
                             {"kind": "file", "size": 21, "sha256": hashlib.sha256(SKIP_BYTES).hexdigest()})
            self.assertEqual(plan["final_content_manifest"][GENFS]["sha256"],
                             "a5fa3e379955f4209a38c161da7aebdc917b8c693ebd3992ae6eb57ab22d06e8")
            self.assertEqual(plan["changes"][0]["before"]["content"]["sha256"],
                             "ce8b599e06d363155930549e845c0d4d234c0d9a5eb35a2f680ea6f51530b581")
            for name in set(records) - {GENFS, INIT}:
                self.assertEqual(changed[name], records[name])
            self.assertEqual(records, before_records)
            self.assertEqual(contents, before_contents)
            self.assertEqual(tree_snapshot(tree), before_tree)
            json.dumps(plan)

    def test_apply_retains_backups_and_is_idempotent_with_returned_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            before_tree = tree_snapshot(tree)
            backup = parent / "backups"
            report = self.api.apply_compatibility(tree, records, contents, backup)
            self.assertEqual(report["status"], "complete")
            self.assertEqual((tree / GENFS[1:]).read_bytes(), AFTER_GENFS)
            self.assertEqual((tree / INIT[1:]).read_bytes(), AFTER_INIT)
            self.assertEqual((tree / MATRIX[1:]).read_bytes(),
                             (ROOT / "ports/coloros17/patches/compatibility_matrix.dash-additions.xml").read_bytes())
            self.assertEqual((backup / GENFS[1:]).read_bytes(), BEFORE_GENFS)
            self.assertEqual((backup / INIT[1:]).read_bytes(), BEFORE_INIT)
            self.assertFalse((backup / MATRIX[1:]).exists())
            self.assertTrue((tree / SKIP_MOUNT[1:]).is_file())
            self.assertEqual((tree / SKIP_MOUNT[1:]).read_bytes(), SKIP_BYTES)
            self.assertEqual(stat.S_IMODE((tree / SKIP_DIR[1:]).stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((tree / SKIP_MOUNT[1:]).stat().st_mode), 0o644)
            self.assertFalse((backup / SKIP_DIR[1:]).exists())
            self.assertEqual(json.loads(Path(report["report_path"]).read_text())["status"], "complete")
            for name, data in before_tree.items():
                if "/" + name not in (GENFS, INIT):
                    self.assertEqual(tree_snapshot(tree)[name], data)
            saved_report = Path(report["report_path"]).read_bytes()
            again = self.api.apply_compatibility(tree, report["final_records"],
                                                  report["final_content_manifest"], backup)
            self.assertEqual(again["status"], "already_applied")
            self.assertEqual(Path(report["report_path"]).read_bytes(), saved_report)
            self.assertEqual(again["final_records"], report["final_records"])

    def test_legacy_three_fix_tree_adds_only_skip_mount_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = legacy_fixture(parent)
            original_records = copy.deepcopy(records)
            original_contents = copy.deepcopy(contents)
            report = self.api.apply_compatibility(tree, records, contents, parent / "backups")
            self.assertEqual(report["status"], "complete")
            self.assertEqual([c["action"] for c in report["changes"]],
                             ["unchanged", "unchanged", "unchanged", "add", "add"])
            self.assertEqual((tree / SKIP_MOUNT[1:]).read_bytes(), SKIP_BYTES)
            for name in records:
                self.assertEqual(report["final_records"][name], original_records[name])
            for name in contents:
                self.assertEqual(report["final_content_manifest"][name], original_contents[name])
            self.assertEqual(os.readlink(tree / "system_ext"), "/system/system_ext")
            self.assertEqual(os.readlink(tree / "product"), "/system/product")
            self.assertEqual(records, original_records)
            self.assertEqual(contents, original_contents)

    def test_skip_mount_requires_real_parent_and_no_unexpected_configuration(self):
        for bad in ("missing-parent", "symlink-parent", "empty-config", "symlink-config", "wrong-file"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                tree, _, _ = legacy_fixture(parent)
                if bad == "missing-parent":
                    (tree / SKIP_PARENT[1:]).rmdir()
                elif bad == "symlink-parent":
                    (tree / SKIP_PARENT[1:]).rmdir()
                    outside = parent / "outside"
                    outside.mkdir()
                    (tree / SKIP_PARENT[1:]).symlink_to(outside)
                elif bad == "symlink-config":
                    outside = parent / "outside"
                    outside.mkdir()
                    (tree / SKIP_DIR[1:]).symlink_to(outside)
                else:
                    (tree / SKIP_DIR[1:]).mkdir(mode=0o755)
                    (tree / SKIP_DIR[1:]).chmod(0o755)
                    if bad == "wrong-file":
                        (tree / SKIP_MOUNT[1:]).write_bytes(b"/vendor\n")
                        (tree / SKIP_MOUNT[1:]).chmod(0o644)
                records, contents = manifest(tree)
                before_tree = tree_snapshot(tree)
                with self.assertRaises(ValueError):
                    self.api.apply_compatibility(tree, records, contents, parent / "backups")
                self.assertEqual(tree_snapshot(tree), before_tree)
                self.assertFalse((parent / "backups").exists())

    def test_changed_content_is_rejected_before_any_mutation(self):
        for damage in ("same-size", "size", "missing-content", "pinned-genfs", "extra-file"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                tree, records, contents = fixture(parent)
                if damage == "same-size":
                    (tree / "system/keep.bin").write_bytes(b"xxxxxxxxxxxxxxxxx")
                elif damage == "size":
                    (tree / INIT[1:]).write_bytes(b"changed")
                elif damage == "missing-content":
                    del contents[INIT]
                elif damage == "pinned-genfs":
                    (tree / GENFS[1:]).write_bytes(BEFORE_GENFS.replace(b"/class/udc", b"/class/abc"))
                    records, contents = manifest(tree)
                else:
                    (tree / "system/unexpected").write_text("keep")
                before_tree = tree_snapshot(tree)
                with self.assertRaises(ValueError):
                    self.api.apply_compatibility(tree, records, contents, parent / "backups")
                self.assertEqual(tree_snapshot(tree), before_tree)
                self.assertFalse((parent / "backups").exists())

    def test_missing_ambiguous_or_partially_patched_init_is_rejected(self):
        for data in (b"on boot\n", BEFORE_INIT + b"    exec_start apexd-bootstrap\n",
                     AFTER_INIT, BEFORE_INIT + b"    restorecon /dev/loop-control\n",
                     BEFORE_INIT.replace(b"    exec_start", b"\texec_start")):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                tree, _, _ = fixture(parent)
                (tree / INIT[1:]).write_bytes(data)
                records, contents = manifest(tree)
                with self.assertRaises(ValueError):
                    self.api.apply_compatibility(tree, records, contents, parent / "backups")
                self.assertEqual((tree / INIT[1:]).read_bytes(), data)
                self.assertFalse((parent / "backups").exists())

    def test_idempotency_requires_the_exact_restorecon_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, _, _ = fixture(parent)
            (tree / GENFS[1:]).write_bytes(AFTER_GENFS)
            (tree / INIT[1:]).write_bytes(AFTER_INIT.replace(b"    restorecon", b"x    restorecon"))
            (tree / MATRIX[1:]).write_bytes((ROOT / "ports/coloros17/patches/compatibility_matrix.dash-additions.xml").read_bytes())
            (tree / MATRIX[1:]).chmod(0o644)
            records, contents = manifest(tree)
            before_tree = tree_snapshot(tree)
            with self.assertRaises(ValueError):
                self.api.apply_compatibility(tree, records, contents, parent / "backups")
            self.assertEqual(tree_snapshot(tree), before_tree)
            self.assertFalse((parent / "backups").exists())

    def test_existing_addition_is_rejected_even_when_bytes_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, _, _ = fixture(parent)
            (tree / MATRIX[1:]).write_bytes((ROOT / "ports/coloros17/patches/compatibility_matrix.dash-additions.xml").read_bytes())
            (tree / MATRIX[1:]).chmod(0o644)
            records, contents = manifest(tree)
            with self.assertRaises(ValueError):
                self.api.apply_compatibility(tree, records, contents, parent / "backups")
            self.assertEqual((tree / GENFS[1:]).read_bytes(), BEFORE_GENFS)
            self.assertFalse((parent / "backups").exists())

    def test_symlink_target_files_and_parent_redirects_are_never_written(self):
        for kind in ("file", "parent", "root"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                tree, _, _ = fixture(parent)
                outside = parent / "outside"
                outside.mkdir()
                victim = outside / "init.rc"
                victim.write_bytes(BEFORE_INIT)
                if kind == "file":
                    (tree / INIT[1:]).unlink()
                    (tree / INIT[1:]).symlink_to(victim)
                elif kind == "parent":
                    (tree / INIT[1:]).unlink()
                    (tree / "system/etc/init/hw").rmdir()
                    (tree / "system/etc/init/hw").symlink_to(outside)
                else:
                    alias = parent / "alias"
                    alias.symlink_to(tree)
                records, contents = manifest(tree)
                with self.assertRaises(ValueError):
                    self.api.apply_compatibility(alias if kind == "root" else tree,
                                                 records, contents, parent / "backups")
                self.assertEqual(victim.read_bytes(), BEFORE_INIT)
                self.assertFalse((parent / "backups").exists())

    def test_unsafe_backup_destination_and_template_metadata_are_rejected(self):
        for bad in ("inside", "existing", "alias", "uid", "mode", "label", "capability"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                tree, records, contents = fixture(parent)
                backup = parent / "backups"
                if bad == "inside":
                    backup = tree / "backups"
                elif bad == "existing":
                    backup.mkdir()
                elif bad == "alias":
                    alias = parent / "alias"
                    alias.symlink_to(tree)
                    backup = alias / "backups"
                elif bad == "uid":
                    records[TEMPLATE]["uid"] = 1000
                elif bad == "mode":
                    records[TEMPLATE]["mode"] = 0o100600
                elif bad == "label":
                    records[TEMPLATE]["xattrs"]["security.selinux"] = b"u:object_r:vendor_file:s0\0".hex()
                else:
                    records[TEMPLATE]["xattrs"]["security.capability"] = "0100000201000000000000000000000000000000"
                before_tree = tree_snapshot(tree)
                with self.assertRaises(ValueError):
                    self.api.apply_compatibility(tree, records, contents, backup)
                self.assertEqual(tree_snapshot(tree), before_tree)

    def test_failed_replace_restores_bytes_and_reports_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            before_tree = tree_snapshot(tree)
            replace = self.api.os.replace
            failed = False
            def fail_init_once(src, dst, *args, **kwargs):
                nonlocal failed
                if tree_replacement(dst, kwargs, tree, INIT) and not failed:
                    failed = True
                    raise OSError("injected write failure")
                return replace(src, dst, *args, **kwargs)
            with patch.object(self.api.os, "replace", fail_init_once):
                with self.assertRaises(self.api.CompatibilityError) as failure:
                    self.api.apply_compatibility(tree, records, contents, parent / "backups")
            report = failure.exception.report
            self.assertEqual(report["status"], "failed_rolled_back")
            self.assertEqual(tree_snapshot(tree), before_tree)
            self.assertEqual(report["rollback_errors"], [])
            self.assertEqual(json.loads(Path(report["report_path"]).read_text())["status"], "failed_rolled_back")

    def test_failure_after_replace_is_reconciled_and_rolled_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            before_tree = tree_snapshot(tree)
            replace = self.api.os.replace
            failed = False
            def replace_then_fail(src, dst, *args, **kwargs):
                nonlocal failed
                result = replace(src, dst, *args, **kwargs)
                if tree_replacement(dst, kwargs, tree, INIT) and not failed:
                    failed = True
                    raise OSError("injected failure after replace")
                return result
            with patch.object(self.api.os, "replace", replace_then_fail):
                with self.assertRaises(self.api.CompatibilityError) as failure:
                    self.api.apply_compatibility(tree, records, contents, parent / "backups")
            self.assertEqual(failure.exception.report["status"], "failed_rolled_back")
            self.assertEqual(tree_snapshot(tree), before_tree)

    def test_failure_after_adding_matrix_removes_it_and_restores_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            before_tree = tree_snapshot(tree)
            replace = self.api.os.replace
            failed = False
            def replace_then_fail(src, dst, *args, **kwargs):
                nonlocal failed
                result = replace(src, dst, *args, **kwargs)
                if tree_replacement(dst, kwargs, tree, MATRIX) and not failed:
                    failed = True
                    raise OSError("injected failure after VINTF creation")
                return result
            with patch.object(self.api.os, "replace", replace_then_fail):
                with self.assertRaises(self.api.CompatibilityError) as failure:
                    self.api.apply_compatibility(tree, records, contents, parent / "backups")
            self.assertEqual(failure.exception.report["status"], "failed_rolled_back")
            self.assertEqual(tree_snapshot(tree), before_tree)
            self.assertFalse((tree / MATRIX[1:]).exists())
            self.assertEqual(failure.exception.report["rollback_operations"], [MATRIX, INIT, GENFS])

    def test_keyboard_interrupt_after_real_replace_rolls_back_each_target(self):
        for target in (GENFS, INIT, MATRIX, SKIP_MOUNT):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                tree, records, contents = fixture(parent)
                before_tree = tree_snapshot(tree)
                replace = self.api.os.replace
                interrupted = False
                def replace_then_interrupt(src, dst, *args, **kwargs):
                    nonlocal interrupted
                    result = replace(src, dst, *args, **kwargs)
                    if tree_replacement(dst, kwargs, tree, target) and not interrupted:
                        interrupted = True
                        raise KeyboardInterrupt("after a successful replacement")
                    return result
                with patch.object(self.api.os, "replace", replace_then_interrupt):
                    with self.assertRaises(KeyboardInterrupt) as failure:
                        self.api.apply_compatibility(tree, records, contents, parent / "backups")
                report = failure.exception.compatibility_report
                self.assertEqual(report["status"], "failed_rolled_back")
                self.assertEqual(report["rollback_errors"], [])
                self.assertEqual(tree_snapshot(tree), before_tree)
                self.assertEqual(json.loads(Path(report["report_path"]).read_text())["status"],
                                 "failed_rolled_back")
                self.assertNotIn("final_records", report)
                self.assertNotIn("final_content_manifest", report)

    def test_interrupt_after_real_config_mkdir_rolls_back_the_new_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            before_tree = tree_snapshot(tree)
            mkdir = self.api.os.mkdir
            interrupted = False
            def mkdir_then_interrupt(path, *args, **kwargs):
                nonlocal interrupted
                result = mkdir(path, *args, **kwargs)
                if kwargs.get("dir_fd") is not None:
                    directory = Path(os.readlink(f"/proc/self/fd/{kwargs['dir_fd']}"))
                    if directory / str(path) == tree / SKIP_DIR[1:] and not interrupted:
                        interrupted = True
                        raise KeyboardInterrupt("after successful configuration directory creation")
                return result
            with patch.object(self.api.os, "mkdir", mkdir_then_interrupt):
                with self.assertRaises(KeyboardInterrupt) as failure:
                    self.api.apply_compatibility(tree, records, contents, parent / "backups")
            report = failure.exception.compatibility_report
            self.assertEqual(report["status"], "failed_rolled_back")
            self.assertEqual(tree_snapshot(tree), before_tree)
            self.assertFalse((tree / SKIP_DIR[1:]).exists())

    def test_rollback_preserves_unexpected_new_directory_contents_and_reports_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            replace = self.api.os.replace
            interrupted = False
            def replace_then_add_unexpected_file(src, dst, *args, **kwargs):
                nonlocal interrupted
                result = replace(src, dst, *args, **kwargs)
                if tree_replacement(dst, kwargs, tree, SKIP_MOUNT) and not interrupted:
                    interrupted = True
                    (tree / SKIP_DIR[1:] / "unexpected").write_bytes(b"preserve me")
                    raise OSError("unexpected writer during replacement")
                return result
            with patch.object(self.api.os, "replace", replace_then_add_unexpected_file):
                with self.assertRaises(self.api.CompatibilityError) as failure:
                    self.api.apply_compatibility(tree, records, contents, parent / "backups")
            report = failure.exception.report
            self.assertEqual(report["status"], "failed_needs_recovery")
            self.assertTrue(report["rollback_errors"])
            self.assertEqual((tree / SKIP_DIR[1:] / "unexpected").read_bytes(), b"preserve me")
            self.assertFalse((tree / SKIP_MOUNT[1:]).exists())
            self.assertEqual((tree / GENFS[1:]).read_bytes(), BEFORE_GENFS)
            self.assertEqual((tree / INIT[1:]).read_bytes(), BEFORE_INIT)

    def test_rollback_failure_is_reported_as_needing_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents = fixture(parent)
            replace = self.api.os.replace
            genfs_writes = 0
            def fail_forward_and_rollback(src, dst, *args, **kwargs):
                nonlocal genfs_writes
                if tree_replacement(dst, kwargs, tree, GENFS):
                    genfs_writes += 1
                    if genfs_writes > 1:
                        raise OSError("injected rollback failure")
                if tree_replacement(dst, kwargs, tree, INIT):
                    raise OSError("injected forward failure")
                return replace(src, dst, *args, **kwargs)
            with patch.object(self.api.os, "replace", fail_forward_and_rollback):
                with self.assertRaises(self.api.CompatibilityError) as failure:
                    self.api.apply_compatibility(tree, records, contents, parent / "backups")
            report = failure.exception.report
            self.assertEqual(report["status"], "failed_needs_recovery")
            self.assertTrue(report["rollback_errors"])
            self.assertEqual((parent / "backups" / GENFS[1:]).read_bytes(), BEFORE_GENFS)
            self.assertTrue(Path(report["report_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
