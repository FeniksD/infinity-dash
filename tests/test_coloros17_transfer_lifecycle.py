from pathlib import Path
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ports.coloros17.transfer_lifecycle import rule_block, planned_rules, remove_owned_rule, remove_owned_file


class FirewallDeltaTests(unittest.TestCase):
    def setUp(self):
        self.before = '*filter\n### RULES ###\n\n### tuple ### allow tcp 22 0.0.0.0/0 any 0.0.0.0/0 in\n-A ufw-user-input -p tcp --dport 22 -j ACCEPT\n\n### END RULES ###\nCOMMIT\n'
        self.block = rule_block('192.0.2.4', 'infinity-coloros-1234')

    def test_exact_add_and_remove(self):
        after = planned_rules(self.before, self.block)
        self.assertEqual(after.replace(self.block, ''), self.before)
        self.assertEqual(remove_owned_rule(after, self.block), self.before)

    def test_preexisting_port_rule_is_rejected_even_with_other_comment(self):
        after = planned_rules(self.before, self.block)
        with self.assertRaises(ValueError):
            planned_rules(after.replace('31323334', '35363738'), self.block)

    def test_cleanup_preserves_other_edits(self):
        after = planned_rules(self.before, self.block) + '# another administrator\n'
        self.assertEqual(remove_owned_rule(after, self.block), self.before + '# another administrator\n')

    def test_cleanup_refuses_changed_or_duplicate_owned_rule(self):
        after = planned_rules(self.before, self.block)
        for changed in [after.replace('--dport 9443', '--dport 9444'), after.replace(self.block, self.block * 2)]:
            with self.assertRaises(ValueError):
                remove_owned_rule(changed, self.block)

    def test_dropin_removed_only_when_identical(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'override.conf'
            p.write_text('owned')
            self.assertTrue(remove_owned_file(p, 'owned'))
            p.write_text('changed')
            with self.assertRaises(ValueError):
                remove_owned_file(p, 'owned')
            self.assertEqual(p.read_text(), 'changed')

    def test_cleanup_restores_guard_even_when_rule_deletion_fails(self):
        from ports.coloros17 import transfer_lifecycle as m
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'private').mkdir()
            (root / 'private/token').write_text('secret')
            baseline = root / 'baseline'
            baseline.write_text('{}')
            state = {'before4': self.before, 'block': self.block,
                     'dropin': 'owned', 'ip': '192.0.2.4',
                     'comment': 'infinity-coloros-1234',
                     'inputs': {str(root / 'private/token'): {'test_hash': 'secret'}},
                     'baseline_sha256': m.digest(baseline.read_bytes())}
            (root / 'state').write_text(json.dumps(state))
            (root / 'rules').write_text(planned_rules(self.before, self.block))
            (root / 'dropin').write_text('owned')
            commands, reports = [], []
            def run(*args):
                commands.append(args)
                if args[0] == 'ufw':
                    raise RuntimeError('simulated deletion failure')
                return ''
            with patch.multiple(m, BASE=root, STATE=root / 'state', BASELINE=baseline,
                                UFW4=root / 'rules', DROPIN=root / 'dropin', DROPIN_TEXT='owned'), \
                    patch.object(m, 'run', side_effect=run), \
                    patch.object(m, 'guard_module', return_value=SimpleNamespace(
                        file_record=lambda p: {'test_hash': p.read_text()})), \
                    patch.object(m, 'write_json', side_effect=lambda p, d: reports.append(d)):
                self.assertEqual(m.cleanup(), 1)
            self.assertFalse((root / 'dropin').exists())
            self.assertFalse((root / 'private/token').exists())
            self.assertIn(('systemctl', 'start', 'infinity-guard.timer'), commands)
            self.assertTrue(reports[-1]['original_baseline_unchanged'])
            self.assertTrue(reports[-1]['owned_firewall_rule_remaining'])

    def test_missing_state_still_restores_known_guard_override(self):
        from ports.coloros17 import transfer_lifecycle as m
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'baseline').write_text('{}')
            (root / 'rules').write_text(self.before)
            (root / 'dropin').write_text('owned')
            commands = []
            with patch.multiple(m, BASE=root, STATE=root / 'missing', BASELINE=root / 'baseline',
                                UFW4=root / 'rules', DROPIN=root / 'dropin', DROPIN_TEXT='owned'), \
                    patch.object(m, 'run', side_effect=lambda *args: commands.append(args) or ''), \
                    patch.object(m, 'write_json'):
                self.assertEqual(m.cleanup(), 1)
            self.assertFalse((root / 'dropin').exists())
            self.assertIn(('systemctl', 'start', 'infinity-guard.timer'), commands)


if __name__ == '__main__':
    unittest.main()
