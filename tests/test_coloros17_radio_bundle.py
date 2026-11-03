import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_coloros17_compat import fixture, manifest, tree_snapshot
from ports.coloros17 import radio_bundle

class RadioBundleTests(unittest.TestCase):
    def setup_tree(self, root):
        tree, _, _ = fixture(root)
        target = tree / radio_bundle.TARGET[1:]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'original radio jar')
        target.chmod(0o644)
        records, contents = manifest(tree)
        artifacts = root / 'radio-input'; artifacts.mkdir()
        (artifacts / 'oplus-telephony-common.jar').write_bytes(b'guarded radio jar')
        spec = {'schema_version': 1, 'path': radio_bundle.TARGET,
                'file': 'oplus-telephony-common.jar',
                'source_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'sha256': hashlib.sha256(b'guarded radio jar').hexdigest(), 'size': 17}
        return tree, records, contents, artifacts, spec

    def test_plan_does_not_write_and_apply_preserves_original_with_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); tree, records, contents, artifacts, spec = self.setup_tree(root)
            before = tree_snapshot(tree)
            with patch.object(radio_bundle, '_load_manifest', return_value=spec):
                plan = radio_bundle.plan_radio_bundle(tree, records, contents, artifacts)
                self.assertEqual(tree_snapshot(tree), before)
                self.assertEqual([x['path'] for x in plan['writes']], [radio_bundle.TARGET])
                result = radio_bundle.apply_radio_bundle(tree, records, contents, artifacts, root/'backup')
                repeat = radio_bundle.apply_radio_bundle(tree, result['final_records'], result['final_content_manifest'], artifacts, root/'unused')
            self.assertEqual((tree/radio_bundle.TARGET[1:]).read_bytes(), b'guarded radio jar')
            self.assertEqual((root/'backup'/radio_bundle.TARGET[1:]).read_bytes(), b'original radio jar')
            self.assertEqual(repeat['status'], 'already_applied')

    def test_unreviewed_input_and_artifact_are_rejected_without_mutation(self):
        for change in ['input', 'artifact', 'target']:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); tree, records, contents, artifacts, spec = self.setup_tree(root)
                if change == 'input': spec['source_sha256'] = '0'*64
                elif change == 'artifact': (artifacts/'oplus-telephony-common.jar').write_bytes(b'wrong')
                else: spec['path'] = '/system/framework/other.jar'
                before = tree_snapshot(tree)
                with patch.object(radio_bundle, '_load_manifest', return_value=spec), self.assertRaises(ValueError):
                    radio_bundle.apply_radio_bundle(tree, records, contents, artifacts, root/'backup')
                self.assertEqual(tree_snapshot(tree), before)
