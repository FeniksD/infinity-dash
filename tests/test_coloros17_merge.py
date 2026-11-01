import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ports/coloros17/merge.py"
LABEL = b"u:object_r:system_file:s0\0".hex()


def inventory(root):
    records = {}

    def visit(path, name):
        info = path.lstat()
        kind = {stat.S_IFDIR: "dir", stat.S_IFREG: "file", stat.S_IFLNK: "symlink"}[stat.S_IFMT(info.st_mode)]
        records[name] = {"uid": info.st_uid, "gid": info.st_gid, "mode": info.st_mode,
                         "inode": info.st_ino, "size": info.st_size, "kind": kind,
                         "xattrs": {"security.selinux": LABEL}}
        if kind == "symlink":
            records[name]["symlink_target"] = os.readlink(path)
        if kind == "dir":
            for child in path.iterdir():
                visit(child, name.rstrip("/") + "/" + child.name)
    visit(root, "/")
    return records


def make_sources(parent):
    sources = {name: parent / name for name in ("system", "product", "system_ext", "my_stock")}
    for root in sources.values():
        root.mkdir()
    root = sources["system"]
    (root / "system").mkdir()
    for name in ("product", "system_ext"):
        (root / name).mkdir()
        (root / "system" / name).symlink_to("/" + name)
    (root / "my_stock").mkdir()
    (root / "system/build.prop").write_bytes(b"ro.build.version.sdk=37\n")
    for name in ("product", "system_ext", "my_stock"):
        (sources[name] / "app").mkdir()
        (sources[name] / "app" / (name + ".apk")).write_bytes(name.encode())
    return sources, {name: inventory(path) for name, path in sources.items()}


def contents(sources):
    result = {}
    for name, root in sources.items():
        result[name] = {}
        for path, record in inventory(root).items():
            actual = root / path.lstrip("/")
            result[name][path] = (record["kind"], actual.read_bytes() if record["kind"] == "file"
                                  else record.get("symlink_target"))
    return result


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), "preservation merge helper is missing")
        spec = importlib.util.spec_from_file_location("coloros_merge", MODULE)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)

    def test_plan_maps_every_partition_and_declares_only_placeholders_and_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources, manifests = make_sources(Path(tmp))
            manifests["product"]["/app/product.apk"]["uid"] = 12345
            before = copy.deepcopy(manifests)
            plan = self.api.plan_merge(manifests)
            final = plan["final_records"]
            self.assertEqual(final["/system/product/app/product.apk"]["uid"], 12345)
            self.assertEqual(final["/my_stock/app/my_stock.apk"], manifests["my_stock"]["/app/my_stock.apk"])
            self.assertEqual(final["/system/product"], manifests["product"]["/"])
            self.assertEqual(final["/product"]["symlink_target"], "/system/product")
            self.assertEqual(final["/product"]["xattrs"], manifests["system"]["/system/product"]["xattrs"])
            self.assertEqual(final["/product"]["size"], len("/system/product"))
            self.assertEqual(set(plan["placements"]), set(sources))
            self.assertEqual({c["path"] for c in plan["declared_placeholder_changes"]},
                             {"/product", "/system/product", "/system_ext", "/system/system_ext", "/my_stock"})
            self.assertEqual(manifests, before)

    def test_apply_moves_trees_and_keeps_source_file_identity_without_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            sources, manifests = make_sources(parent)
            original_inode = (sources["product"] / "app/product.apk").stat().st_ino
            report = self.api.apply_merge(sources, parent / "merged", manifests)
            self.assertEqual(report["status"], "complete")
            self.assertTrue(all(not path.exists() for path in sources.values()))
            merged = parent / "merged"
            self.assertEqual((merged / "system/product/app/product.apk").read_bytes(), b"product")
            self.assertEqual((merged / "system/product/app/product.apk").stat().st_ino, original_inode)
            self.assertEqual(os.readlink(merged / "product"), "/system/product")
            self.assertEqual((merged / "my_stock/app/my_stock.apk").read_bytes(), b"my_stock")
            self.assertEqual(set(inventory(merged)), set(report["final_records"]))
            journal = json.loads(Path(report["journal_path"]).read_text())
            self.assertEqual(journal["status"], "complete")
            self.assertEqual(journal["declared_placeholder_changes"], report["declared_placeholder_changes"])

    def test_nonempty_or_unexpected_placeholder_is_rejected_before_mutation(self):
        for bad in ("nonempty", "wrong-link", "nonempty-my"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                sources, _ = make_sources(parent)
                if bad == "nonempty":
                    (sources["system"] / "product/file").write_bytes(b"keep")
                elif bad == "nonempty-my":
                    (sources["system"] / "my_stock/file").write_bytes(b"keep")
                else:
                    link = sources["system"] / "system/product"
                    link.unlink()
                    link.symlink_to("/different")
                manifests = {name: inventory(path) for name, path in sources.items()}
                before = contents(sources)
                with self.assertRaises(ValueError):
                    self.api.apply_merge(sources, parent / "merged", manifests)
                self.assertEqual(contents(sources), before)
                self.assertEqual(set(parent.iterdir()), set(sources.values()))

    def test_missing_unexpected_changed_files_or_existing_destination_are_rejected(self):
        for bad in ("missing", "extra", "size", "symlink-target", "destination", "different-device"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                sources, manifests = make_sources(parent)
                if bad == "missing":
                    (sources["product"] / "app/product.apk").unlink()
                elif bad == "extra":
                    (sources["product"] / "extra").write_text("unknown")
                elif bad == "size":
                    (sources["product"] / "app/product.apk").write_bytes(b"larger than original")
                elif bad == "symlink-target":
                    link = sources["system"] / "system/product"
                    link.unlink()
                    link.symlink_to("/another")  # Same size as /product.
                elif bad == "destination":
                    (parent / "merged").mkdir()
                before = contents(sources)
                if bad == "different-device":
                    original = self.api.os.lstat
                    def changed_device(path, *args, **kwargs):
                        info = original(path, *args, **kwargs)
                        if Path(path) == sources["product"]:
                            fields = list(info)
                            fields[2] += 1
                            return os.stat_result(fields)
                        return info
                    context = patch.object(self.api.os, "lstat", changed_device)
                else:
                    from contextlib import nullcontext
                    context = nullcontext()
                with context, self.assertRaises(ValueError):
                    self.api.apply_merge(sources, parent / "merged", manifests)
                self.assertEqual(contents(sources), before)

    def test_empty_nested_mountpoint_uses_existing_root_context_for_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources, manifests = make_sources(Path(tmp))
            mountpoint = sources["system"] / "system/product"
            mountpoint.unlink()
            mountpoint.mkdir()
            manifests["system"] = inventory(sources["system"])
            plan = self.api.plan_merge(manifests)
            self.assertEqual(plan["final_records"]["/product"]["xattrs"],
                             manifests["system"]["/"]["xattrs"])
            manifests["system"]["/"]["xattrs"] = {}
            with self.assertRaises(ValueError):
                self.api.plan_merge(manifests)

    def test_partition_names_and_hardlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources, manifests = make_sources(Path(tmp))
            with self.assertRaises(ValueError):
                self.api.plan_merge(manifests | {"vendor": manifests["product"]})
            with self.assertRaises(ValueError):
                self.api.plan_merge(manifests | {"my_../escape": manifests["product"]})
            os.link(sources["product"] / "app/product.apk", sources["product"] / "alias")
            manifests["product"] = inventory(sources["product"])
            with self.assertRaises(ValueError):
                self.api.plan_merge(manifests)

    def test_early_rename_failure_rolls_back_sources_and_leaves_failure_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            sources, manifests = make_sources(parent)
            before = contents(sources)
            rename = os.rename
            count = 0
            def fail_once(src, dst):
                nonlocal count
                count += 1
                if count == 3:
                    raise OSError("injected rename failure")
                return rename(src, dst)
            with patch.object(self.api.os, "rename", fail_once):
                with self.assertRaises(self.api.MergeError) as failure:
                    self.api.apply_merge(sources, parent / "merged", manifests)
            self.assertEqual(contents(sources), before)
            self.assertFalse((parent / "merged").exists())
            self.assertEqual(failure.exception.report["status"], "failed_rolled_back")
            self.assertIsNone(failure.exception.report["pending"])
            saved = json.loads(Path(failure.exception.report["journal_path"]).read_text())
            self.assertEqual(saved["status"], "failed_rolled_back")

    def test_late_rename_failure_removes_aliases_and_restores_all_partitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            sources, manifests = make_sources(parent)
            before = contents(sources)
            rename = os.rename
            def fail_commit(src, dst):
                if Path(dst) == parent / "merged":
                    raise OSError("injected commit failure")
                return rename(src, dst)
            with patch.object(self.api.os, "rename", fail_commit):
                with self.assertRaises(self.api.MergeError) as failure:
                    self.api.apply_merge(sources, parent / "merged", manifests)
            self.assertEqual(contents(sources), before)
            self.assertEqual(failure.exception.report["status"], "failed_rolled_back")
            self.assertEqual(len(failure.exception.report["rollback_operations"]),
                             len(failure.exception.report["operations"]))

    def test_rollback_failure_reports_recovery_needed_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            sources, manifests = make_sources(parent)
            rename = os.rename
            calls = 0
            def fail_twice(src, dst):
                nonlocal calls
                calls += 1
                if calls in (3, 4):
                    raise OSError("injected move/rollback failure")
                return rename(src, dst)
            with patch.object(self.api.os, "rename", fail_twice):
                with self.assertRaises(self.api.MergeError) as failure:
                    self.api.apply_merge(sources, parent / "merged", manifests)
            report = failure.exception.report
            self.assertEqual(report["status"], "failed_needs_recovery")
            self.assertTrue(report["rollback_errors"])
            self.assertTrue(Path(report["journal_path"]).is_file())

    def test_interrupt_after_successful_rename_reconciles_and_restores_sources(self):
        for when in ("first", "commit"):
            with self.subTest(when=when), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                sources, manifests = make_sources(parent)
                before = contents(sources)
                rename = os.rename
                interrupted = False
                def rename_then_interrupt(src, dst):
                    nonlocal interrupted
                    result = rename(src, dst)
                    if not interrupted and (when == "first" or Path(dst) == parent / "merged"):
                        interrupted = True
                        raise KeyboardInterrupt("after successful rename")
                    return result
                with patch.object(self.api.os, "rename", rename_then_interrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        self.api.apply_merge(sources, parent / "merged", manifests)
                self.assertTrue(all(p.is_dir() for p in sources.values()))
                self.assertEqual(contents(sources), before)
                report = json.loads((parent / ".merged.merge-journal.json").read_text())
                self.assertEqual(report["status"], "failed_rolled_back")
                self.assertIsNone(report["pending"])
                self.assertFalse((parent / "merged").exists())

    def test_interrupt_after_symlink_creation_reconciles_and_removes_new_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            sources, manifests = make_sources(parent)
            before = contents(sources)
            symlink = os.symlink
            interrupted = False
            def symlink_then_interrupt(target, path):
                nonlocal interrupted
                result = symlink(target, path)
                if not interrupted:
                    interrupted = True
                    raise KeyboardInterrupt("after symlink creation")
                return result
            with patch.object(self.api.os, "symlink", symlink_then_interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    self.api.apply_merge(sources, parent / "merged", manifests)
            self.assertEqual(contents(sources), before)
            report = json.loads((parent / ".merged.merge-journal.json").read_text())
            self.assertEqual(report["status"], "failed_rolled_back")
            self.assertIsNone(report["pending"])

    def test_ambiguous_interrupted_rename_keeps_recovery_status_and_original_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            sources, manifests = make_sources(parent)
            rename = os.rename
            interrupted = False
            def rename_recreate_and_interrupt(src, dst):
                nonlocal interrupted
                result = rename(src, dst)
                if not interrupted:
                    interrupted = True
                    Path(src).mkdir()
                    raise KeyboardInterrupt("ambiguous source replacement")
                return result
            with patch.object(self.api.os, "rename", rename_recreate_and_interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    self.api.apply_merge(sources, parent / "merged", manifests)
            report = json.loads((parent / ".merged.merge-journal.json").read_text())
            self.assertEqual(report["status"], "failed_needs_recovery")
            self.assertIsNotNone(report["pending"])
            saved = Path(report["staging_path"]) / "tree/system/build.prop"
            self.assertEqual(saved.read_bytes(), b"ro.build.version.sdk=37\n")


if __name__ == "__main__":
    unittest.main()
