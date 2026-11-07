import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from ports.coloros17 import game_refresh
from ports.coloros17 import compat
from test_coloros17_compat import fixture, manifest, BEFORE_COMPOSER, AFTER_COMPOSER


SOURCE = (b'<?xml version="1.0"?>\r\n<refresh_rate_config version="20260513">\r\n'
          b'  <config defaultRateId="1-1-2-3" disableViewOverrideDefault="false" />\r\n'
          b'  <item package="com.tencent.ig" rateId="3-1-2-3" disableViewOverride="true" />\r\n'
          b'  <item package="low.rate.app" rateId="2-2-2-2" />\r\n'
          b'</refresh_rate_config>\r\n')
ADDITION = (b'  <item package="com.axlebolt.standoff2" rateId="3-1-2-3" '
            b'disableViewOverride="true" /> <!-- Standoff 2: dash high refresh profile -->\r\n')
AFTER = SOURCE.replace(b'  <item package="com.tencent.ig"', ADDITION + b'  <item package="com.tencent.ig"', 1)


def spec():
    return {'schema_version': 1, 'path': game_refresh.TARGET,
            'source_sha256': hashlib.sha256(SOURCE).hexdigest(), 'source_size': len(SOURCE),
            'sha256': hashlib.sha256(AFTER).hexdigest(), 'size': len(AFTER)}


class GameRefreshTests(unittest.TestCase):
    def test_preserves_existing_profiles_and_explicit_60hz_selection(self):
        with patch.object(game_refresh, '_load_manifest', return_value=spec()):
            result, applied = game_refresh.transform(SOURCE)
            repeated, already = game_refresh.transform(result)
        self.assertFalse(applied)
        self.assertTrue(already)
        self.assertEqual(repeated, result)
        self.assertEqual(result.replace(ADDITION, b'', 1), SOURCE)
        item = ET.fromstring(result).find("item[@package='com.axlebolt.standoff2']")
        self.assertEqual(item.attrib['rateId'].split('-'), ['3', '1', '2', '3'])
        self.assertEqual(item.attrib['disableViewOverride'], 'true')

    def test_refuses_changed_input_or_wrong_target(self):
        with patch.object(game_refresh, '_load_manifest', return_value=spec()):
            with self.assertRaises(ValueError):
                game_refresh.transform(SOURCE.replace(b'low.rate.app', b'other.app'))
        bad = spec(); bad['path'] = '/system/build.prop'
        with patch.object(game_refresh, '_load_manifest', return_value=bad):
            with self.assertRaises(ValueError):
                game_refresh.transform(SOURCE)

    def test_compatibility_stage_updates_manifest_and_keeps_rollback_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); tree, _, _ = fixture(root)
            target = tree / game_refresh.TARGET[1:]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(SOURCE); target.chmod(0o644)
            records, contents = manifest(tree)
            old_record = copy.deepcopy(records[game_refresh.TARGET])
            with patch.object(game_refresh, '_load_manifest', return_value=spec()), \
                    patch.object(compat, 'COMPOSER_BEFORE_SHA256', hashlib.sha256(BEFORE_COMPOSER).hexdigest()), \
                    patch.object(compat, 'COMPOSER_AFTER_SHA256', hashlib.sha256(AFTER_COMPOSER).hexdigest()):
                plan = compat.plan_compatibility(tree, records, contents, game_refresh_enabled=True)
                self.assertEqual(target.read_bytes(), SOURCE)
                result = compat.apply_compatibility(tree, records, contents, root/'backup', game_refresh_enabled=True)
                repeat = compat.plan_compatibility(tree, result['final_records'], result['final_content_manifest'], game_refresh_enabled=True)
            self.assertEqual(target.read_bytes(), AFTER)
            self.assertEqual((root/'backup'/game_refresh.TARGET[1:]).read_bytes(), SOURCE)
            self.assertEqual(result['final_records'], plan['final_records'])
            old_record['size'] = len(AFTER)
            self.assertEqual(result['final_records'][game_refresh.TARGET], old_record)
            self.assertEqual(repeat['status'], 'already_applied')

    def test_build_requires_refresh_profile_when_enabled(self):
        from ports.coloros17 import candidate
        from test_coloros17_candidate import legacy_tree, run_stage
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree, _, _ = legacy_tree(root)
            target = tree / game_refresh.TARGET[1:]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(SOURCE); target.chmod(0o644)
            records, contents = manifest(tree)
            (root/'work/final-records.json').write_text(json.dumps(records))
            (root/'work/final-contents.json').write_text(json.dumps(contents))
            config = json.loads((root/'profile.json').read_text())
            config['game_refresh_required'] = True
            (root/'profile.json').write_text(json.dumps(config))
            with patch.object(game_refresh, '_load_manifest', return_value=spec()), \
                    patch.object(compat, 'COMPOSER_BEFORE_SHA256', hashlib.sha256(BEFORE_COMPOSER).hexdigest()), \
                    patch.object(compat, 'COMPOSER_AFTER_SHA256', hashlib.sha256(AFTER_COMPOSER).hexdigest()), \
                    patch.object(candidate, 'build_image', return_value={'status': 'complete'}) as build:
                with self.assertRaises(ValueError):
                    run_stage(root, 'build')
                build.assert_not_called()
                run_stage(root, 'patch')
                run_stage(root, 'build')
                build.assert_called_once()
            self.assertEqual(target.read_bytes(), AFTER)


if __name__ == '__main__':
    unittest.main()
