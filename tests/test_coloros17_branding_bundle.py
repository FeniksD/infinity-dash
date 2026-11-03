import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ports.coloros17 import branding_bundle
from test_coloros17_compat import fixture, manifest, tree_snapshot

ROOT = Path(__file__).resolve().parents[1]
INFO = "/system/etc/feniksd-port-info.txt"
OVERLAY = "/system/system_ext/overlay/FeniksDAboutOverlay.apk"


def setup_fixture(parent):
    tree, _, _ = fixture(parent)
    (tree / "system/system_ext/overlay").mkdir(parents=True)
    settings = tree / "system/system_ext/priv-app/Settings/Settings.apk"
    settings.parent.mkdir(parents=True)
    settings.write_bytes(b"fixture settings")
    records, contents = manifest(tree)
    artifacts = parent / "branding-inputs"
    artifacts.mkdir()
    data = b"fixture overlay APK"
    (artifacts / "FeniksDAboutOverlay.apk").write_bytes(data)
    spec = branding_bundle._load_manifest()
    spec["settings_apk_sha256"] = hashlib.sha256(b"fixture settings").hexdigest()
    spec["files"][1].update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    return tree, records, contents, artifacts, spec


class BrandingBundleTests(unittest.TestCase):
    def test_plan_is_read_only_and_changes_only_two_credit_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree, records, contents, artifacts, spec = setup_fixture(Path(tmp))
            before, metadata = tree_snapshot(tree), copy.deepcopy((records, contents))
            with patch.object(branding_bundle, "_load_manifest", return_value=spec):
                plan = branding_bundle.plan_branding_bundle(tree, records, contents, artifacts)
            self.assertIsInstance(plan, dict)
            self.assertEqual({x["path"] for x in plan["writes"]}, {INFO, OVERLAY})
            self.assertEqual(tree_snapshot(tree), before)
            self.assertEqual((records, contents), metadata)

    def test_apply_preserves_existing_files_and_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            tree, records, contents, artifacts, spec = setup_fixture(parent)
            before = tree_snapshot(tree)
            with patch.object(branding_bundle, "_load_manifest", return_value=spec):
                result = branding_bundle.apply_branding_bundle(tree, records, contents, artifacts, parent / "backup")
                self.assertIsInstance(result, dict)
                for p, value in before.items():
                    self.assertEqual(tree_snapshot(tree)[p], value)
                self.assertIn(b"https://t.me/feniksd_dash", (tree / INFO[1:]).read_bytes())
                again = branding_bundle.apply_branding_bundle(tree, result["final_records"], result["final_content_manifest"], artifacts, parent / "unused")
            self.assertEqual(again["status"], "already_applied")
            self.assertFalse((parent / "unused").exists())

    def test_unknown_existing_credit_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree, _, _, artifacts, spec = setup_fixture(Path(tmp))
            (tree / INFO[1:]).write_bytes(b"unknown owner file")
            records, contents = manifest(tree)
            before = tree_snapshot(tree)
            with patch.object(branding_bundle, "_load_manifest", return_value=spec):
                with self.assertRaises(ValueError):
                    branding_bundle.apply_branding_bundle(tree, records, contents, artifacts, Path(tmp) / "backup")
            self.assertEqual(tree_snapshot(tree), before)

    def test_bad_overlay_hash_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree, records, contents, artifacts, spec = setup_fixture(Path(tmp))
            (artifacts / "FeniksDAboutOverlay.apk").write_bytes(b"changed")
            before = tree_snapshot(tree)
            with patch.object(branding_bundle, "_load_manifest", return_value=spec):
                with self.assertRaises(ValueError):
                    branding_bundle.apply_branding_bundle(tree, records, contents, artifacts, Path(tmp) / "backup")
            self.assertEqual(tree_snapshot(tree), before)
