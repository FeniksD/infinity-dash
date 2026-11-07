import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_coloros17_compat import AFTER_COMPOSER, COMPOSER_POLICY, fixture, manifest, tree_snapshot
from test_coloros17_candidate import legacy_tree, run_stage, save
from test_coloros17_compat import BEFORE_COMPOSER


ROOT = Path(__file__).resolve().parents[1]
SERVICES = "/system/framework/services.jar"
OPLUS = "/system/framework/oplus-services.jar"
MAPPING = "/system/system_ext/etc/selinux/mapping/202604.cil"
STAMP = "/system/system_ext/etc/selinux/system_ext_sepolicy_and_mapping.sha256"
FEATURE = "/system/system_ext/etc/permissions/dash-fingerprint-features.xml"
INIT = "/system/system_ext/etc/init/dash-runtime-compat.rc"
RADIO = "/my_manifest/build.prop"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def runtime_fixture(parent, tree=None):
    from ports.coloros17 import runtime_bundle
    if tree is None:
        tree, _, _ = fixture(parent)
    values = {SERVICES: b"donor services", OPLUS: b"donor oplus", MAPPING: b"mapping fixture\n",
              RADIO: b"ro.product.model=PLG110\nro.product.vendor.name=CPH2791IN\nro.product.device=OP5E11L1\n",
              STAMP: b"old-policy-stamp\n", COMPOSER_POLICY: AFTER_COMPOSER}
    for name, data in values.items():
        target = tree / name[1:]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o640)
    (tree / "system/system_ext/etc/permissions").mkdir(exist_ok=True)
    records, contents = manifest(tree)
    records[SERVICES].update(uid=1000, gid=2000, ext4_flags=0x80000)
    spec = runtime_bundle._load_manifest()
    artifacts = parent / "artifacts"
    artifacts.mkdir(exist_ok=True)
    for index, artifact in enumerate(spec["artifacts"]):
        data = ("reviewed artifact " + str(index)).encode()
        (artifacts / artifact["file"]).write_bytes(data)
        artifact.update(sha256=sha(data), size=len(data), source_sha256=sha(values[artifact["path"]]))
    policy = spec["policy"]
    policy["source_sha256"] = sha(AFTER_COMPOSER)
    policy["mapping_sha256"] = sha(values[MAPPING])
    policy["accepted_source_stamp_sha256"] = [sha(values[STAMP])]
    fragments = [(ROOT / "ports/coloros17" / f["source"]).read_bytes() for f in policy["fragments"]]
    result = AFTER_COMPOSER + b"\n" + b"\n".join(fragments)
    policy["sha256"] = sha(result)
    radio = spec["radio_product_override"]
    radio.update(source_sha256=sha(values[RADIO]), source_size=len(values[RADIO]),
                 sha256=sha(values[RADIO].replace(b"ro.product.vendor.name=CPH2791IN\n",
                                                  b"ro.product.vendor.name=dash_global\n")),
                 size=len(values[RADIO].replace(b"ro.product.vendor.name=CPH2791IN\n", b"ro.product.vendor.name=dash_global\n")))
    return tree, records, contents, artifacts, spec


class RuntimeBundleTests(unittest.TestCase):
    def test_manifest_pins_reviewed_jars_and_only_confirmed_radio_identity(self):
        from ports.coloros17 import runtime_bundle
        spec = runtime_bundle._load_manifest()
        self.assertEqual({x["sha256"] for x in spec["artifacts"]}, {
            "3ae64fe5be2e1525580475f30079bd6f27f65b7ba90bb1fd6f57035b7ea9a04e",
            "048b6d404d9a48da6f1cb4c7385ecbdda0e62b69424fcc001a16b9de0f4299c5"})
        rc = (ROOT / "ports/coloros17/patches/dash-runtime-compat.rc").read_text()
        self.assertNotIn("ro.product.vendor.name", rc)
        self.assertIn("setprop vendor.fingerprint.aidl.support 1", rc)
        radio = spec["radio_product_override"]
        self.assertEqual(radio["path"], RADIO)
        self.assertEqual(radio["source_line"], "ro.product.vendor.name=CPH2791IN\n")
        self.assertEqual(radio["replacement_line"], "ro.product.vendor.name=dash_global\n")
        self.assertEqual((radio["source_size"], radio["size"]), (5095, 5097))
        self.assertEqual(radio["sha256"], "ecba5b7fe559ecd6a0ce64c04f93ebb59ab149287d90f29c14c99b628161df1a")

    def test_runtime_properties_are_synchronous_before_zygote_and_preserve_optout(self):
        # AOSP queues property-triggered actions behind already-queued boot actions.
        # Keep these commands in the synchronous system_ext post-fs-data action,
        # parsed after main init's load_persist_props and before zygote-start.
        rc = (ROOT / "ports/coloros17/patches/dash-runtime-compat.rc").read_text()
        actions, current = {}, None
        for raw in rc.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("on "):
                current = line[3:]
                self.assertNotIn(current, actions)
                actions[current] = []
            else:
                actions[current].append(line.split())
        self.assertEqual(set(actions), {"early-init", "post-fs-data"})
        self.assertEqual(actions["early-init"], [["setprop", "vendor.fingerprint.aidl.support", "1"],
                                                 ["setprop", "ro.vendor.imeisv", "05"]])
        expected = {
            "vendor.fingerprint.aidl.support": "1",
            "persist.vendor.fingerprint.sensor_type": "ultrasonic",
            "persist.vendor.fingerprint.optical.iconsize": "220",
            "persist.vendor.fingerprint.optical.iconlocation": "712",
            "persist.sys.dash.udfps_touch_bridge": "${persist.sys.dash.udfps_touch_bridge:-true}",
            "persist.sys.dash.haptic_fallback": "${persist.sys.dash.haptic_fallback:-true}",
        }
        self.assertEqual(actions["post-fs-data"], [["setprop", name, value] for name, value in expected.items()])
        for name in ("persist.sys.dash.udfps_touch_bridge", "persist.sys.dash.haptic_fallback"):
            expression = expected[name]
            # AOSP ExpandProps uses GetProperty(name, "") and applies :- only
            # to an empty value. Pin this exact token rather than an unconditional
            # true, which would override a persisted false after properties load.
            self.assertEqual(expression, "${" + name + ":-true}")

    def test_plan_is_read_only_exact_and_preserves_donor_metadata(self):
        from ports.coloros17 import runtime_bundle
        with tempfile.TemporaryDirectory() as folder:
            tree, records, contents, artifacts, spec = runtime_fixture(Path(folder))
            before, original = tree_snapshot(tree), copy.deepcopy((records, contents))
            with patch.object(runtime_bundle, "_load_manifest", return_value=spec):
                plan = runtime_bundle.plan_runtime_bundle(tree, records, contents, artifacts)
                again = runtime_bundle.plan_runtime_bundle(tree, records, contents, artifacts)
            self.assertEqual(plan, again)
            self.assertEqual(tree_snapshot(tree), before)
            self.assertEqual((records, contents), original)
            self.assertEqual({x["path"] for x in plan["writes"]}, {SERVICES, OPLUS, COMPOSER_POLICY, STAMP, FEATURE, INIT, RADIO})
            for name in records:
                expected = copy.deepcopy(records[name])
                if name in {SERVICES, OPLUS, COMPOSER_POLICY, STAMP, RADIO}:
                    expected["size"] = plan["final_records"][name]["size"]
                self.assertEqual(plan["final_records"][name], expected)
            added = [plan["final_records"][name]["inode"] for name in (FEATURE, INIT)]
            self.assertEqual(len(set(added)), 2)
            self.assertTrue(set(added).isdisjoint(r["inode"] for r in records.values()))
            self.assertEqual(plan["final_records"][FEATURE]["mode"], 0o100644)

    def test_valid_template_label_without_nul_is_preserved(self):
        from ports.coloros17 import runtime_bundle
        with tempfile.TemporaryDirectory() as folder:
            tree, records, contents, artifacts, spec = runtime_fixture(Path(folder))
            template = records[spec["metadata_template"]]
            template["xattrs"]["security.selinux"] = b"u:object_r:system_file:s0".hex()
            with patch.object(runtime_bundle, "_load_manifest", return_value=spec):
                plan = runtime_bundle.plan_runtime_bundle(tree, records, contents, artifacts)
            self.assertEqual(plan["final_records"][FEATURE]["xattrs"], template["xattrs"])

    def test_bad_artifact_and_unknown_preimage_never_mutate_tree(self):
        from ports.coloros17 import runtime_bundle
        for damage in ("artifact", "symlink", "source", "mapping", "stamp", "radio"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as folder:
                tree, records, contents, artifacts, spec = runtime_fixture(Path(folder))
                artifact = artifacts / spec["artifacts"][0]["file"]
                if damage == "artifact":
                    artifact.write_bytes(b"unreviewed")
                elif damage == "symlink":
                    value = artifact.read_bytes()
                    artifact.unlink()
                    (artifacts / "other").write_bytes(value)
                    artifact.symlink_to("other")
                else:
                    name = {"source": SERVICES, "mapping": MAPPING, "stamp": STAMP, "radio": RADIO}[damage]
                    (tree / name[1:]).write_bytes(b"unknown input")
                    new_records, contents = manifest(tree)
                    for path in records:
                        records[path]["size"] = new_records[path]["size"]
                before = tree_snapshot(tree)
                with patch.object(runtime_bundle, "_load_manifest", return_value=spec):
                    with self.assertRaises((OSError, ValueError)):
                        runtime_bundle.apply_runtime_bundle(tree, records, contents, artifacts, Path(folder) / "backup")
                self.assertEqual(tree_snapshot(tree), before)
                self.assertFalse((Path(folder) / "backup").exists())

    def test_apply_stamp_and_idempotence_preserve_unrelated_host_inode(self):
        from ports.coloros17 import runtime_bundle
        from ports.coloros17.build_image import validate_tree
        with tempfile.TemporaryDirectory() as folder:
            tree, records, contents, artifacts, spec = runtime_fixture(Path(folder))
            keep = tree / "system/keep.bin"
            inode = keep.stat().st_ino
            with patch.object(runtime_bundle, "_load_manifest", return_value=spec):
                result = runtime_bundle.apply_runtime_bundle(tree, records, contents, artifacts, Path(folder) / "backup")
                records, contents = result["final_records"], result["final_content_manifest"]
                validate_tree(tree, records, contents)
                self.assertEqual((tree / STAMP[1:]).read_bytes(),
                                 (sha((tree / COMPOSER_POLICY[1:]).read_bytes() + (tree / MAPPING[1:]).read_bytes()) + "\n").encode())
                before = {str(p): p.lstat().st_ino for p in tree.rglob("*")}
                second = runtime_bundle.apply_runtime_bundle(tree, records, contents, artifacts, Path(folder) / "unused")
            self.assertEqual(second["status"], "already_applied")
            self.assertFalse((Path(folder) / "unused").exists())
            self.assertEqual(before, {str(p): p.lstat().st_ino for p in tree.rglob("*")})
            self.assertEqual(keep.stat().st_ino, inode)
            self.assertEqual((tree / RADIO[1:]).read_bytes(),
                             b"ro.product.model=PLG110\nro.product.vendor.name=dash_global\nro.product.device=OP5E11L1\n")

    def test_radio_requires_one_exact_line_even_for_hash_pinned_fixture(self):
        from ports.coloros17 import runtime_bundle
        for data in (b"ro.product.vendor.name=CPH2791IN\nro.product.vendor.name=CPH2791IN\n",
                     b"ro.product.vendor.name = PLG110\n"):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as folder:
                tree, records, contents, artifacts, spec = runtime_fixture(Path(folder))
                (tree / RADIO[1:]).write_bytes(data)
                records[RADIO]["size"] = len(data)
                contents[RADIO] = {"kind": "file", "size": len(data), "sha256": sha(data)}
                spec["radio_product_override"].update(source_sha256=sha(data), source_size=len(data))
                before = tree_snapshot(tree)
                with patch.object(runtime_bundle, "_load_manifest", return_value=spec):
                    with self.assertRaisesRegex(ValueError, "radio.*line"):
                        runtime_bundle.plan_runtime_bundle(tree, records, contents, artifacts)
                self.assertEqual(before, tree_snapshot(tree))

    def test_radio_only_partial_state_is_rejected(self):
        from ports.coloros17 import runtime_bundle
        with tempfile.TemporaryDirectory() as folder:
            tree, records, contents, artifacts, spec = runtime_fixture(Path(folder))
            data = (tree / RADIO[1:]).read_bytes().replace(b"=CPH2791IN\nro.product.device", b"=dash_global\nro.product.device")
            (tree / RADIO[1:]).write_bytes(data)
            records[RADIO]["size"] = len(data)
            contents[RADIO] = {"kind": "file", "size": len(data), "sha256": sha(data)}
            with patch.object(runtime_bundle, "_load_manifest", return_value=spec):
                with self.assertRaisesRegex(ValueError, "partial"):
                    runtime_bundle.plan_runtime_bundle(tree, records, contents, artifacts)

    def test_partial_state_rejected_and_late_failure_rolls_back_all_bytes(self):
        from ports.coloros17 import runtime_bundle, compat
        with tempfile.TemporaryDirectory() as folder:
            tree, records, contents, artifacts, spec = runtime_fixture(Path(folder))
            before = tree_snapshot(tree)
            write = compat._atomic_write
            failed = False
            def fail_last(path, data, host=None):
                nonlocal failed
                write(path, data, host)
                if Path(path) == tree / INIT[1:] and not failed:
                    failed = True
                    raise OSError("injected late runtime failure")
            with patch.object(runtime_bundle, "_load_manifest", return_value=spec), \
                    patch.object(compat, "_atomic_write", side_effect=fail_last):
                with self.assertRaises(runtime_bundle.RuntimeBundleError) as caught:
                    runtime_bundle.apply_runtime_bundle(tree, records, contents, artifacts, Path(folder) / "backup")
            self.assertEqual(caught.exception.report["status"], "failed_rolled_back")
            self.assertEqual(tree_snapshot(tree), before)
            self.assertEqual((Path(folder) / "backup" / SERVICES[1:]).read_bytes(), b"donor services")
            self.assertEqual((Path(folder) / "backup" / RADIO[1:]).read_bytes(),
                             b"ro.product.model=PLG110\nro.product.vendor.name=CPH2791IN\nro.product.device=OP5E11L1\n")
            (tree / SERVICES[1:]).write_bytes((artifacts / spec["artifacts"][0]["file"]).read_bytes())
            new_records, contents = manifest(tree)
            for name in records:
                records[name]["size"] = new_records[name]["size"]
            with patch.object(runtime_bundle, "_load_manifest", return_value=spec):
                with self.assertRaisesRegex(ValueError, "partial"):
                    runtime_bundle.plan_runtime_bundle(tree, records, contents, artifacts)


class RuntimeCandidateTests(unittest.TestCase):
    def setUp(self):
        from ports.coloros17 import compat
        for name, data in (("COMPOSER_BEFORE_SHA256", BEFORE_COMPOSER),
                           ("COMPOSER_AFTER_SHA256", AFTER_COMPOSER)):
            item = patch.object(compat, name, sha(data)); item.start(); self.addCleanup(item.stop)

    def ready(self, base):
        from ports.coloros17 import candidate
        tree, _, _ = legacy_tree(base)
        run_stage(base, "patch")
        state = candidate.read_json(base / "work/final-state.json")
        prior = state["current"]["records"]
        tree, records, contents, artifacts, spec = runtime_fixture(base, tree)
        for name, record in prior.items():
            current_size = records[name]["size"]
            records[name] = copy.deepcopy(record)
            if record["kind"] == "file":
                records[name]["size"] = current_size
        state["current"] = {"records": records, "contents": contents}
        save(base / "work/final-state.json", state)
        destination = base / "inputs/runtime"
        artifacts.rename(destination)
        profile = candidate.read_json(base / "profile.json")
        profile.pop("runtime_bundle_required", None)  # Production default must require it.
        save(base / "profile.json", profile)
        return tree, spec

    def test_runtime_is_required_before_build_and_default_artifact_path_is_used(self):
        from ports.coloros17 import candidate, runtime_bundle
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); tree, spec = self.ready(base)
            completed = {"status": "complete", "output": "test.img"}
            with patch.object(runtime_bundle, "_load_manifest", return_value=spec), \
                    patch.object(candidate, "build_image", return_value=completed) as build:
                with self.assertRaisesRegex(ValueError, "runtime"):
                    run_stage(base, "build")
                build.assert_not_called()
                self.assertEqual(run_stage(base, "runtime"), 0)
                self.assertEqual(run_stage(base, "build"), 0)
                build.assert_called_once()
                self.assertEqual(run_stage(base, "patch"), 0)  # Cannot strip runtime CIL on retry.
            state = candidate.read_json(base / "work/final-state.json")
            self.assertIsNone(state["pending"])
            self.assertIn(INIT, state["current"]["contents"])
            self.assertEqual(len(list((base / "work").glob("runtime-backup-*/runtime-bundle-report.json"))), 1)

    def test_runtime_state_commit_failure_recovers_after_pair_without_rewriting(self):
        from ports.coloros17 import candidate, runtime_bundle
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); tree, spec = self.ready(base)
            original_write = candidate.write_json
            def fail_commit(path, value):
                current = value.get("current", {})
                if value.get("pending") is None and INIT in current.get("contents", {}):
                    raise OSError("injected runtime state commit failure")
                original_write(path, value)
            with patch.object(runtime_bundle, "_load_manifest", return_value=spec):
                with patch.object(candidate, "write_json", side_effect=fail_commit):
                    with self.assertRaisesRegex(OSError, "state commit failure"):
                        run_stage(base, "runtime")
                saved = candidate.read_json(base / "work/final-state.json")
                self.assertEqual(saved["pending"]["stage"], "runtime")
                inode = (tree / SERVICES[1:]).stat().st_ino
                self.assertEqual(run_stage(base, "runtime"), 0)
                self.assertEqual((tree / SERVICES[1:]).stat().st_ino, inode)
                self.assertIsNone(candidate.read_json(base / "work/final-state.json")["pending"])

    def test_compatibility_hash_extension_is_limited_to_pinned_runtime_policy(self):
        from ports.coloros17 import compat, candidate, runtime_bundle
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); tree, spec = self.ready(base)
            unknown = b"unreviewed policy bytes\n"
            (tree / COMPOSER_POLICY[1:]).write_bytes(unknown)
            pair = candidate.read_json(base / "work/final-state.json")["current"]
            pair["records"][COMPOSER_POLICY]["size"] = len(unknown)
            pair["contents"][COMPOSER_POLICY] = {"kind": "file", "size": len(unknown), "sha256": sha(unknown)}
            with patch.object(runtime_bundle, "_load_manifest", return_value=spec):
                with self.assertRaisesRegex(ValueError, "pinned"):
                    compat.plan_compatibility(tree, pair["records"], pair["contents"],
                                              runtime_policy_sha256=sha(unknown))


if __name__ == "__main__":
    unittest.main()
