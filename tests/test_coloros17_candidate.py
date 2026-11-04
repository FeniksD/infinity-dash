import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_coloros17_compat import (
    AFTER_COMPOSER, AFTER_GENFS, AFTER_INIT, BEFORE_COMPOSER,
    GENFS, INIT, MATRIX, fixture, manifest, tree_snapshot,
    tree_replacement,
)
from test_coloros17_merge import make_sources


ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def prepare(base):
    from ports.coloros17 import candidate
    donor = candidate.read_json(ROOT / 'ports/coloros17/donor.json')
    save(base / 'inputs/download-verification.json', {
        'sha256': donor['archive_sha256'], 'bytes': donor['archive_bytes'],
        'md5': donor['expected_md5'], 'md5_matches': True})
    save(base / 'control/payload-verification.json', {
        'payload_hash_verified': True, 'payload_sha256': donor['expected_payload_sha256'],
        'payload_bytes': 9592095570})
    save(base / 'control/ota-signature-verification.json', {
        'cryptographic_signature_valid': True, 'archive_sha256': donor['archive_sha256']})
    config = candidate.read_json(ROOT / 'ports/coloros17/profile.json')
    config['pipeline_adapter_ready'] = True
    config['runtime_bundle_required'] = False  # Legacy fixtures contain no runtime JAR inputs.
    config['branding_bundle_required'] = False  # Legacy fixtures contain no Settings APK.
    config['radio_registration_required'] = False  # Legacy fixtures contain no radio JAR.
    config['sensor_product_required'] = False  # Legacy fixtures contain no product build.prop.
    save(base / 'profile.json', config)
    (base / 'work').mkdir(exist_ok=True)
    return config


def legacy_tree(base):
    prepare(base)
    tree, records, contents = fixture(base / 'work')
    save(base / 'work/final-records.json', records)
    save(base / 'work/final-contents.json', contents)
    return tree, records, contents


def merge_sources(base):
    config = prepare(base)
    parts = base / 'work/parts'
    parts.mkdir()
    sources, _ = make_sources(parts)
    for name in config['required_partitions']:
        if name not in sources:
            sources[name] = parts / name
            sources[name].mkdir()
    for name, root in sources.items():
        records, contents = manifest(root)
        for item in contents.values():
            if item['kind'] == 'file':
                item['bytes'] = item.pop('size')
        save(base / f'work/inode-manifests/{name}.json', records)
        save(base / f'work/inode-manifests/{name}-contents.json', contents)
    return sources


def run_stage(base, stage):
    from ports.coloros17 import candidate
    with contextlib.redirect_stdout(io.StringIO()):
        return candidate.main(['--base', str(base), '--profile', str(base / 'profile.json'),
                               '--stage', stage])


def reject_state_commit(candidate, state_path):
    replace = os.replace

    def fail(src, dst, *args, **kwargs):
        if Path(dst) == state_path:
            value = candidate.read_json(src)
            current = value.get('current')
            if value.get('pending') is None and current and MATRIX in current['contents']:
                raise OSError('injected state commit failure')
        return replace(src, dst, *args, **kwargs)
    return fail


class CandidateGateTests(unittest.TestCase):
    def setUp(self):
        from ports.coloros17 import compat
        # This suite imports the small compatibility fixture, not the 1.7 MB donor.
        for name, data in (("COMPOSER_BEFORE_SHA256", BEFORE_COMPOSER),
                           ("COMPOSER_AFTER_SHA256", AFTER_COMPOSER)):
            context = patch.object(compat, name, hashlib.sha256(data).hexdigest())
            context.start()
            self.addCleanup(context.stop)

    def test_build_refuses_missing_required_radio_registration_patch(self):
        from ports.coloros17 import candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            legacy_tree(base)
            run_stage(base, 'patch')
            profile = candidate.read_json(base / 'profile.json')
            profile['radio_registration_required'] = True
            save(base / 'profile.json', profile)
            with self.assertRaisesRegex(ValueError, 'radio registration'):
                run_stage(base, 'build')

    def test_build_refuses_missing_required_sensor_product_identity(self):
        from ports.coloros17 import candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            legacy_tree(base)
            run_stage(base, 'patch')
            profile = candidate.read_json(base / 'profile.json')
            profile['sensor_product_required'] = True
            save(base / 'profile.json', profile)
            with self.assertRaisesRegex(ValueError, 'sensor product'):
                run_stage(base, 'build')

    def test_unreviewed_profile_stops_before_creating_work_files(self):
        from ports.coloros17.candidate import main
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            profile = base / 'profile.json'
            config = json.loads((ROOT / 'ports/coloros17/profile.json').read_text())
            config['pipeline_adapter_ready'] = False
            save(profile, config)
            before = {p.name for p in base.iterdir()}
            with self.assertRaises(ValueError):
                main(['--base', str(base), '--profile', str(profile), '--stage', 'merge'])
            self.assertEqual({p.name for p in base.iterdir()}, before)

    def test_build_stage_refuses_a_tree_without_all_three_compatibility_patches(self):
        for applied in ((), (GENFS,), (INIT,), (MATRIX,), (GENFS, INIT)):
            with self.subTest(applied=applied), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                tree, _, _ = legacy_tree(base)
                for name in applied:
                    data = {GENFS: AFTER_GENFS, INIT: AFTER_INIT,
                            MATRIX: (ROOT / 'ports/coloros17/patches/compatibility_matrix.dash-additions.xml').read_bytes()}[name]
                    (tree / name[1:]).write_bytes(data)
                    (tree / name[1:]).chmod(0o644)
                records, contents = manifest(tree)
                save(base / 'work/final-records.json', records)
                save(base / 'work/final-contents.json', contents)
                with self.assertRaises(ValueError):
                    run_stage(base, 'build')
                self.assertEqual(list((base / 'output').glob('*')), [])

    def test_completed_build_cli_preserves_optional_publication_warnings(self):
        from ports.coloros17 import candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            tree, _, _ = legacy_tree(base)
            run_stage(base, 'patch')
            before = tree_snapshot(tree)
            for warnings in ({}, {'post_publish_warning': 'KeyboardInterrupt: after publication'},
                             {'report_save_error': 'OSError: report storage unavailable'},
                             {'post_publish_warning': 'KeyboardInterrupt: after publication',
                              'report_save_error': 'OSError: report storage unavailable'}):
                with self.subTest(warnings=warnings):
                    completed = {'status': 'complete', 'output': str(base / 'output/lab.img'),
                                 'image_bytes': 4096, 'sha256': 'a' * 64,
                                 'report_path': str(base / 'output/report.json'), **warnings}
                    output = io.StringIO()
                    with patch.object(candidate, 'build_image', return_value=completed), \
                            contextlib.redirect_stdout(output):
                        result = candidate.main(['--base', str(base), '--profile', str(base / 'profile.json'),
                                                 '--stage', 'build'])
                    self.assertEqual(result, 0)
                    self.assertEqual(json.loads(output.getvalue()), completed)
                    self.assertEqual(tree_snapshot(tree), before)

    def test_build_honors_explicit_output_without_replacing_the_baseline(self):
        from ports.coloros17 import candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            legacy_tree(base)
            run_stage(base, 'patch')
            output = base / 'output' / 'runtime-candidate.img'
            baseline = base / 'output' / 'ColorOS17-PLG110-dash-lab.img'
            baseline.parent.mkdir()
            baseline.write_bytes(b'preserved baseline')
            with patch.object(candidate, 'build_image', return_value={'status': 'complete'}) as build, \
                    contextlib.redirect_stdout(io.StringIO()):
                candidate.main(['--base', str(base), '--profile', str(base / 'profile.json'),
                                '--stage', 'build', '--output', str(output)])
            self.assertEqual(build.call_args.args[3], output)
            self.assertEqual(baseline.read_bytes(), b'preserved baseline')

    def test_receipts_require_literal_true_and_exact_donor_binding(self):
        cases = [
            ('inputs/download-verification.json', 'md5_matches', 'false'),
            ('inputs/download-verification.json', 'md5_matches', 1),
            ('inputs/download-verification.json', 'bytes', 123),
            ('inputs/download-verification.json', 'sha256', '0' * 64),
            ('inputs/download-verification.json', 'md5', '0' * 32),
            ('control/payload-verification.json', 'payload_hash_verified', 'false'),
            ('control/payload-verification.json', 'payload_hash_verified', 1),
            ('control/payload-verification.json', 'payload_sha256', '0' * 64),
            ('control/payload-verification.json', 'payload_bytes', 123),
            ('control/payload-verification.json', 'payload_sha256', None),
            ('control/ota-signature-verification.json', 'cryptographic_signature_valid', 'false'),
            ('control/ota-signature-verification.json', 'cryptographic_signature_valid', 1),
            ('control/ota-signature-verification.json', 'archive_sha256', '0' * 64),
            ('control/ota-signature-verification.json', 'archive_sha256', None),
        ]
        for filename, key, value in cases:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                tree, _, _ = legacy_tree(base)
                path = base / filename
                receipt = json.loads(path.read_text())
                receipt[key] = value
                save(path, receipt)
                before = tree_snapshot(tree)
                with self.assertRaises(ValueError):
                    run_stage(base, 'patch')
                self.assertEqual(tree_snapshot(tree), before)
                self.assertFalse((base / 'work/final-state.json').exists())

    def test_invalid_source_contents_never_move_any_tree(self):
        for damage in ('missing', 'size', 'hash', 'physical-hash', 'symlink', 'extra'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                sources = merge_sources(base)
                path = base / 'work/inode-manifests/product-contents.json'
                contents = json.loads(path.read_text())
                if damage == 'missing':
                    contents.pop('/app/product.apk')
                elif damage == 'size':
                    contents['/app/product.apk']['bytes'] += 1
                elif damage == 'hash':
                    contents['/app/product.apk']['sha256'] = '0' * 64
                elif damage == 'physical-hash':
                    (sources['product'] / 'app/product.apk').write_bytes(b'changed')
                elif damage == 'symlink':
                    path = base / 'work/inode-manifests/system-contents.json'
                    contents = json.loads(path.read_text())
                    contents['/system/product']['target'] = '/wrong'
                else:
                    contents['/unrecorded'] = {'kind': 'file', 'bytes': 0, 'sha256': '0' * 64}
                save(path, contents)
                before = {name: tree_snapshot(root) for name, root in sources.items()}
                with self.assertRaises((ValueError, KeyError)):
                    run_stage(base, 'merge')
                self.assertEqual({name: tree_snapshot(root) for name, root in sources.items()}, before)
                self.assertFalse((base / 'work/canonical').exists())
                self.assertFalse((base / 'work/.canonical.merge-journal.json').exists())
                self.assertFalse((base / 'work/final-state.json').exists())

    def test_failed_pending_state_write_prevents_merge_mutation(self):
        from ports.coloros17 import candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            sources = merge_sources(base)
            before = {name: tree_snapshot(root) for name, root in sources.items()}
            replace = os.replace

            def fail(src, dst, *args, **kwargs):
                if Path(dst) == base / 'work/final-state.json':
                    raise OSError('injected pending state failure')
                return replace(src, dst, *args, **kwargs)

            with patch.object(candidate.os, 'replace', fail):
                with self.assertRaisesRegex(OSError, 'pending state failure'):
                    run_stage(base, 'merge')
            self.assertEqual({name: tree_snapshot(root) for name, root in sources.items()}, before)
            self.assertFalse((base / 'work/canonical').exists())
            self.assertFalse((base / 'work/.canonical.merge-journal.json').exists())

    def test_legacy_pair_bootstraps_and_future_patch_state_is_one_authoritative_file(self):
        from ports.coloros17.build_image import validate_tree
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            tree, records, contents = legacy_tree(base)
            self.assertEqual(run_stage(base, 'patch'), 0)
            state = json.loads((base / 'work/final-state.json').read_text())
            self.assertIsNone(state['pending'])
            validate_tree(tree, state['current']['records'], state['current']['contents'])
            self.assertEqual((tree / INIT[1:]).read_bytes(), AFTER_INIT)
            self.assertEqual(json.loads((base / 'work/final-records.json').read_text()), records)
            self.assertEqual(json.loads((base / 'work/final-contents.json').read_text()), contents)
            # Once bootstrapped, the old pair is no longer read or overwritten.
            save(base / 'work/final-records.json', {})
            save(base / 'work/final-contents.json', {})
            before = tree_snapshot(tree)
            self.assertEqual(run_stage(base, 'patch'), 0)
            self.assertEqual(tree_snapshot(tree), before)

    def test_patch_commit_failure_retains_atomic_pair_and_recovers_patched_tree(self):
        from ports.coloros17 import candidate
        from ports.coloros17.build_image import validate_tree
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            tree, records, contents = legacy_tree(base)
            path = base / 'work/final-state.json'
            with patch.object(candidate.os, 'replace', reject_state_commit(candidate, path)):
                with self.assertRaisesRegex(OSError, 'state commit failure'):
                    run_stage(base, 'patch')
            saved = json.loads(path.read_text())
            self.assertEqual(saved['current'], {'records': records, 'contents': contents})
            validate_tree(tree, saved['pending']['after']['records'], saved['pending']['after']['contents'])
            before = tree_snapshot(tree)
            journals = {p: p.read_bytes() for p in (base / 'work').glob('compat-backup-*/compatibility-report.json')}
            self.assertEqual(len(journals), 1)
            self.assertEqual(run_stage(base, 'patch'), 0)
            recovered = json.loads(path.read_text())
            self.assertIsNone(recovered['pending'])
            self.assertEqual(recovered['current'], saved['pending']['after'])
            self.assertEqual(tree_snapshot(tree), before)
            self.assertEqual({p: p.read_bytes() for p in journals}, journals)

    def test_patch_rollback_recovers_before_state_and_uses_a_fresh_backup(self):
        from ports.coloros17 import candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            tree, _, _ = legacy_tree(base)
            before = tree_snapshot(tree)
            replace = os.replace
            failed = False

            def fail_init(src, dst, *args, **kwargs):
                nonlocal failed
                if kwargs.get('dst_dir_fd') is not None and tree_replacement(dst, kwargs, tree, INIT) and not failed:
                    failed = True
                    raise OSError('injected patch failure')
                return replace(src, dst, *args, **kwargs)

            with patch.object(candidate.os, 'replace', fail_init):
                with self.assertRaises(RuntimeError):
                    run_stage(base, 'patch')
            self.assertEqual(tree_snapshot(tree), before)
            journals = {p: p.read_bytes() for p in (base / 'work').glob('compat-backup-*/compatibility-report.json')}
            self.assertEqual(len(journals), 1)
            self.assertEqual(run_stage(base, 'patch'), 0)
            self.assertEqual((tree / INIT[1:]).read_bytes(), AFTER_INIT)
            self.assertEqual(len(list((base / 'work').glob('compat-backup-*'))), 2)
            self.assertEqual({p: p.read_bytes() for p in journals}, journals)

    def test_pending_patch_with_neither_complete_tree_fails_closed(self):
        from ports.coloros17 import candidate
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            tree, _, _ = legacy_tree(base)
            path = base / 'work/final-state.json'
            with patch.object(candidate.os, 'replace', reject_state_commit(candidate, path)):
                with self.assertRaises(OSError):
                    run_stage(base, 'patch')
            (tree / 'system/keep.bin').write_bytes(b'damaged')
            before = tree_snapshot(tree)
            saved = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'recovery'):
                run_stage(base, 'patch')
            self.assertEqual(tree_snapshot(tree), before)
            self.assertEqual(path.read_bytes(), saved)

    def test_merge_commit_failure_recovers_final_tree_without_repeating_moves(self):
        from ports.coloros17 import candidate
        from ports.coloros17.build_image import validate_tree
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            sources = merge_sources(base)
            path = base / 'work/final-state.json'
            replace = os.replace

            def fail(src, dst, *args, **kwargs):
                if Path(dst) == path and candidate.read_json(src).get('pending') is None:
                    raise OSError('injected merge commit failure')
                return replace(src, dst, *args, **kwargs)

            with patch.object(candidate.os, 'replace', fail):
                with self.assertRaisesRegex(OSError, 'merge commit failure'):
                    run_stage(base, 'merge')
            saved = json.loads(path.read_text())
            self.assertIsNone(saved['current'])
            tree = base / 'work/canonical'
            validate_tree(tree, saved['pending']['after']['records'], saved['pending']['after']['contents'])
            self.assertTrue(all(not source.exists() for source in sources.values()))
            inode = (tree / 'system/product/app/product.apk').stat().st_ino
            journal = base / 'work/.canonical.merge-journal.json'
            before_journal = journal.read_bytes()
            self.assertEqual(run_stage(base, 'merge'), 0)
            self.assertEqual((tree / 'system/product/app/product.apk').stat().st_ino, inode)
            self.assertEqual(journal.read_bytes(), before_journal)
            state = json.loads(path.read_text())
            self.assertEqual(state['current'], saved['pending']['after'])
            self.assertIsNone(state['pending'])

    def test_merge_retry_archives_rolled_back_journal_and_preserves_staging(self):
        from ports.coloros17 import candidate
        from ports.coloros17.build_image import validate_tree
        for after_move in (False, True):
            with self.subTest(after_move=after_move), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                sources = merge_sources(base)
                before = {name: tree_snapshot(root) for name, root in sources.items()}
                rename = os.rename

                def fail_first_move(src, dst):
                    if Path(src) == sources['system']:
                        if after_move:
                            rename(src, dst)
                        raise OSError('injected first move failure')
                    return rename(src, dst)

                with patch.object(candidate.os, 'rename', fail_first_move):
                    with self.assertRaisesRegex(RuntimeError, 'first move failure'):
                        run_stage(base, 'merge')
                self.assertEqual({name: tree_snapshot(root) for name, root in sources.items()}, before)
                journal = base / 'work/.canonical.merge-journal.json'
                saved = journal.read_bytes()
                report = json.loads(saved)
                self.assertEqual(report['status'], 'failed_rolled_back')
                marker = Path(report['staging_path']) / 'unknown-artifact'
                marker.write_bytes(b'preserve for inspection')
                self.assertEqual(run_stage(base, 'merge'), 0)
                history = list((base / 'work').glob('.canonical.merge-journal.history-*.json'))
                self.assertEqual([path.read_bytes() for path in history], [saved])
                self.assertEqual(marker.read_bytes(), b'preserve for inspection')
                self.assertEqual(json.loads(journal.read_text())['status'], 'complete')
                state = json.loads((base / 'work/final-state.json').read_text())
                self.assertIsNone(state['pending'])
                validate_tree(base / 'work/canonical', state['current']['records'], state['current']['contents'])

    def test_crash_before_first_move_can_retry_and_keeps_unfinished_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            sources = merge_sources(base)
            before = {name: tree_snapshot(root) for name, root in sources.items()}
            script = '''
import os
from pathlib import Path
import sys
from ports.coloros17 import candidate
base = Path(sys.argv[1])
def crash_before_first_move(src, dst):
    os._exit(92)
candidate.os.rename = crash_before_first_move
candidate.main(['--base', str(base), '--profile', str(base / 'profile.json'), '--stage', 'merge'])
'''
            result = subprocess.run([sys.executable, '-c', script, str(base)], cwd=ROOT,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 92, result.stderr)
            self.assertEqual({name: tree_snapshot(root) for name, root in sources.items()}, before)
            journal = base / 'work/.canonical.merge-journal.json'
            saved = journal.read_bytes()
            staging = Path(json.loads(saved)['staging_path'])
            self.assertEqual(run_stage(base, 'merge'), 0)
            history = list((base / 'work').glob('.canonical.merge-journal.history-*.json'))
            self.assertEqual([path.read_bytes() for path in history], [saved])
            self.assertTrue(staging.is_dir())

    def test_partial_merge_crash_preserves_pending_state_and_journal_for_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            merge_sources(base)
            script = '''
import os
from pathlib import Path
import sys
from ports.coloros17 import candidate
base = Path(sys.argv[1])
rename = os.rename
def crash_after_first_move(src, dst):
    rename(src, dst)
    os._exit(91)
candidate.os.rename = crash_after_first_move
candidate.main(['--base', str(base), '--profile', str(base / 'profile.json'), '--stage', 'merge'])
'''
            result = subprocess.run([sys.executable, '-c', script, str(base)], cwd=ROOT,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 91, result.stderr)
            state_path = base / 'work/final-state.json'
            journal = base / 'work/.canonical.merge-journal.json'
            before = {p: p.read_bytes() for p in (state_path, journal)}
            self.assertFalse((base / 'work/parts/system').exists())
            self.assertFalse((base / 'work/canonical').exists())
            with self.assertRaisesRegex(ValueError, 'recovery'):
                run_stage(base, 'merge')
            self.assertEqual({p: p.read_bytes() for p in before}, before)


if __name__ == '__main__':
    unittest.main()
