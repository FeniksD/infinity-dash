import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_coloros17_compat import fixture, manifest, tree_snapshot
from test_coloros17_candidate import prepare, save


def sha(data):
    return hashlib.sha256(data).hexdigest()


def camera_fixture(parent):
    from ports.coloros17 import camera_bundle
    tree, _, _ = fixture(parent)
    donor = tree / "my_product/app/OplusCamera/OplusCamera.apk"
    donor.parent.mkdir(parents=True)
    donor.write_bytes(b"keep original Oppo camera")
    spec = camera_bundle._load_manifest()
    bundle = parent / "bundle"
    for item in spec["files"]:
        data = ("camera fixture " + item["path"]).encode()
        item.update(size=len(data), sha256=sha(data))
        source = bundle / item["source"]
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(data)
    records, contents = manifest(tree)
    return tree, records, contents, bundle, spec


class CameraBundleTests(unittest.TestCase):
    def test_path_validation_rejects_unrepresentable_names_before_file_access(self):
        from ports.coloros17 import camera_bundle
        for value, destination in (("/system/bad name", True), ("/system/bad\nname", True),
                                   ("payload/bad\\name", False), ("payload/bad\tname", False)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                camera_bundle._safe_path(value, destination=destination)

    def test_manifest_matches_signed_minimal_payload_and_sar_paths(self):
        from ports.coloros17 import camera_bundle
        spec = camera_bundle._load_manifest()
        self.assertEqual(len(spec["files"]), 11)
        self.assertEqual(spec["apk"]["signer_sha256"], "c8a2e9bccf597c2fb6dc66bee293fc13f2fc47ec77bc6b2b0d52c11f51192ab8")
        self.assertEqual(spec["files"][0]["sha256"], "4e5387a5b0a79890813b490fa8df012fa6037a66b672896f226a04eaa890a16c")
        self.assertTrue(all(x["path"].startswith("/system/") for x in spec["files"]))
        self.assertEqual(sum(x["path"].startswith("/system/system_ext/") for x in spec["files"]), 6)

    def test_plan_is_read_only_and_allocates_unique_metadata_for_new_entries(self):
        from ports.coloros17 import camera_bundle
        with tempfile.TemporaryDirectory() as folder:
            tree, records, contents, bundle, spec = camera_fixture(Path(folder))
            before = tree_snapshot(tree)
            original = copy.deepcopy((records, contents))
            with patch.object(camera_bundle, "_load_manifest", return_value=spec):
                plan = camera_bundle.plan_camera_bundle(tree, records, contents, bundle)
            self.assertEqual(tree_snapshot(tree), before)
            self.assertEqual((records, contents), original)
            final = plan["final_records"]
            for name in records:
                self.assertEqual(final[name], records[name])
            inodes = [r["inode"] for r in final.values()]
            self.assertEqual(len(inodes), len(set(inodes)))
            for name in final.keys() - records.keys():
                expected_mode = 0o40755 if final[name]["kind"] == "dir" else 0o100644
                self.assertEqual((final[name]["uid"], final[name]["gid"], final[name]["mode"]), (0, 0, expected_mode))

    def test_identical_existing_library_metadata_is_preserved_but_conflicts_rejected(self):
        from ports.coloros17 import camera_bundle
        for conflict in (False, True):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as folder:
                tree, _, _, bundle, spec = camera_fixture(Path(folder))
                item = spec["files"][1]
                target = tree / item["path"][1:]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"conflicting library" if conflict else (bundle / item["source"]).read_bytes())
                records, contents = manifest(tree)
                records[item["path"]].update(uid=1111, gid=2222, mode=0o100600)
                before = tree_snapshot(tree)
                with patch.object(camera_bundle, "_load_manifest", return_value=spec):
                    if conflict:
                        with self.assertRaisesRegex(ValueError, "conflict"):
                            camera_bundle.plan_camera_bundle(tree, records, contents, bundle)
                    else:
                        plan = camera_bundle.plan_camera_bundle(tree, records, contents, bundle)
                        self.assertEqual(plan["final_records"][item["path"]], records[item["path"]])
                        self.assertNotIn(item["path"], [w["path"] for w in plan["writes"]])
                self.assertEqual(tree_snapshot(tree), before)

    def test_hash_size_symlink_and_parent_traversal_rejected_before_writes(self):
        from ports.coloros17 import camera_bundle
        for damage in ("hash", "size", "source-symlink", "source-directory-symlink",
                       "source-parent", "target-parent", "target-symlink"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as folder:
                tree, records, contents, bundle, spec = camera_fixture(Path(folder))
                item = spec["files"][0]
                source = bundle / item["source"]
                if damage == "hash": source.write_bytes(b"not pinned")
                elif damage == "size": item["size"] += 1
                elif damage == "source-symlink":
                    source.rename(source.with_name("original")); source.symlink_to("original")
                elif damage == "source-directory-symlink":
                    root = bundle / "payload/system"
                    root.rename(root.with_name("original-system")); root.symlink_to("original-system")
                elif damage == "source-parent": item["source"] = "../outside.apk"
                elif damage == "target-parent": item["path"] = "/system/../data/app.apk"
                else:
                    (tree / "system/priv-app").symlink_to("/outside")
                    records, contents = manifest(tree)
                before = tree_snapshot(tree)
                with patch.object(camera_bundle, "_load_manifest", return_value=spec):
                    with self.assertRaises((OSError, ValueError)):
                        camera_bundle.apply_camera_bundle(tree, records, contents, bundle, Path(folder) / "backup")
                self.assertEqual(tree_snapshot(tree), before)
                self.assertFalse((Path(folder) / "backup").exists())

    def test_planned_file_cannot_also_be_a_parent_directory(self):
        from ports.coloros17 import camera_bundle
        with tempfile.TemporaryDirectory() as folder:
            tree, records, contents, bundle, spec = camera_fixture(Path(folder))
            spec["files"][0]["path"] = "/system/new-camera"
            spec["files"][1]["path"] = "/system/new-camera/child.so"
            with patch.object(camera_bundle, "_load_manifest", return_value=spec):
                with self.assertRaisesRegex(ValueError, "parent"):
                    camera_bundle.plan_camera_bundle(tree, records, contents, bundle)

    def test_apply_idempotence_and_late_failure_rollback_keep_oppo(self):
        from ports.coloros17 import camera_bundle, compat
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as folder:
                tree, records, contents, bundle, spec = camera_fixture(Path(folder))
                before = tree_snapshot(tree)
                original = compat._atomic_write
                last = tree / spec["files"][-1]["path"][1:]
                def injected(path, data, host=None):
                    original(path, data, host)
                    if Path(path) == last and fail:
                        raise OSError("injected camera write failure")
                with patch.object(camera_bundle, "_load_manifest", return_value=spec), \
                        patch.object(compat, "_atomic_write", side_effect=injected):
                    if fail:
                        with self.assertRaises(camera_bundle.CameraBundleError) as caught:
                            camera_bundle.apply_camera_bundle(tree, records, contents, bundle, Path(folder) / "backup")
                        self.assertEqual(caught.exception.report["status"], "failed_rolled_back")
                        self.assertEqual(tree_snapshot(tree), before)
                    else:
                        result = camera_bundle.apply_camera_bundle(tree, records, contents, bundle, Path(folder) / "backup")
                        inodes = {p: p.lstat().st_ino for p in tree.rglob("*")}
                        second = camera_bundle.apply_camera_bundle(tree, result["final_records"], result["final_content_manifest"], bundle, Path(folder) / "unused")
                        self.assertEqual(second["status"], "already_applied")
                        self.assertEqual(inodes, {p: p.lstat().st_ino for p in tree.rglob("*")})
                        self.assertFalse((Path(folder) / "unused").exists())
                self.assertEqual((tree / "my_product/app/OplusCamera/OplusCamera.apk").read_bytes(), b"keep original Oppo camera")


class CameraCliTests(unittest.TestCase):
    def ready(self, base):
        from ports.coloros17 import candidate
        prepare(base)
        tree, records, contents, bundle, spec = camera_fixture(base / "work")
        save(base / "work/final-state.json", {"schema_version": 1, "current": {"records": records, "contents": contents}, "pending": None})
        return tree, bundle, spec

    def invoke(self, base, bundle, dry=False):
        from ports.coloros17 import camera_bundle
        args = ["--base", str(base), "--bundle-dir", str(bundle)]
        if dry: args.append("--dry-run")
        with contextlib.redirect_stdout(io.StringIO()):
            return camera_bundle.main(args)

    def test_dry_run_never_writes_state_or_payload_and_requires_runtime(self):
        from ports.coloros17 import camera_bundle, candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); tree, bundle, spec = self.ready(base)
            state = (base / "work/final-state.json").read_bytes(); before = tree_snapshot(tree)
            with patch.object(camera_bundle, "_load_manifest", return_value=spec), \
                    patch.object(camera_bundle, "plan_runtime_bundle", return_value={"status": "already_applied"}), \
                    patch.object(candidate, "write_json", side_effect=AssertionError("dry run wrote state")):
                self.assertEqual(self.invoke(base, bundle, True), 0)
            self.assertEqual(before, tree_snapshot(tree))
            self.assertEqual(state, (base / "work/final-state.json").read_bytes())
            with patch.object(camera_bundle, "plan_runtime_bundle", return_value={"status": "planned"}):
                with self.assertRaisesRegex(ValueError, "runtime"):
                    self.invoke(base, bundle, True)

    def test_commit_failure_recovers_camera_after_pair_without_rewrite(self):
        from ports.coloros17 import camera_bundle, candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); tree, bundle, spec = self.ready(base)
            apk = spec["files"][0]["path"]
            real_write = candidate.write_json
            def fail_commit(path, value):
                if value.get("pending") is None and apk in value.get("current", {}).get("contents", {}):
                    raise OSError("injected camera state failure")
                real_write(path, value)
            with patch.object(camera_bundle, "_load_manifest", return_value=spec), \
                    patch.object(camera_bundle, "plan_runtime_bundle", return_value={"status": "already_applied"}):
                with patch.object(candidate, "write_json", side_effect=fail_commit):
                    with self.assertRaisesRegex(OSError, "camera state"):
                        self.invoke(base, bundle)
                state = candidate.read_json(base / "work/final-state.json")
                self.assertEqual(state["pending"]["stage"], "camera")
                inode = (tree / apk[1:]).stat().st_ino
                self.assertEqual(self.invoke(base, bundle), 0)
                self.assertEqual(inode, (tree / apk[1:]).stat().st_ino)
                self.assertIsNone(candidate.read_json(base / "work/final-state.json")["pending"])

    def test_rolled_back_camera_state_recovers_before_pair_and_retries(self):
        from ports.coloros17 import camera_bundle, compat, candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); tree, bundle, spec = self.ready(base)
            before = tree_snapshot(tree)
            original = compat._atomic_write
            last = tree / spec["files"][-1]["path"][1:]
            def fail_last(path, data, host=None):
                original(path, data, host)
                if Path(path) == last:
                    raise OSError("injected camera payload failure")
            with patch.object(camera_bundle, "_load_manifest", return_value=spec), \
                    patch.object(camera_bundle, "plan_runtime_bundle", return_value={"status": "already_applied"}):
                with patch.object(compat, "_atomic_write", side_effect=fail_last):
                    with self.assertRaises(camera_bundle.CameraBundleError):
                        self.invoke(base, bundle)
                self.assertEqual(tree_snapshot(tree), before)
                self.assertEqual(candidate.read_json(base / "work/final-state.json")["pending"]["stage"], "camera")
                with self.assertRaisesRegex(ValueError, "recovery"):
                    self.invoke(base, bundle, True)
                self.assertEqual(self.invoke(base, bundle), 0)
            self.assertEqual(len(list((base / "work").glob("camera-backup-*/camera-bundle-report.json"))), 2)


if __name__ == "__main__":
    unittest.main()
