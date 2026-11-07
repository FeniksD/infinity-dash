import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from ports.coloros17.runtime_rebase import replace_dex, verify_classes, normalized


class RuntimeRebaseTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'original.jar'
        with zipfile.ZipFile(source, 'w') as z:
            z.writestr('META-INF/MANIFEST.MF', b'original metadata')
            z.writestr('classes.dex', b'original first dex')
            z.writestr('classes2.dex', b'untouched second dex')
        return source, hashlib.sha256(source.read_bytes()).hexdigest()

    def test_global_jar_keeps_unrelated_dex_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source, digest = self.fixture(root); out = root / 'result.jar'
            replace_dex(source, out, {'classes.dex': b'patched'}, digest, {'classes5.dex': b'our helper'})
            with zipfile.ZipFile(out) as z:
                self.assertEqual(z.namelist(), ['META-INF/MANIFEST.MF', 'classes.dex', 'classes2.dex', 'classes5.dex'])
                self.assertEqual(z.read('classes2.dex'), b'untouched second dex')
                self.assertEqual(z.read('META-INF/MANIFEST.MF'), b'original metadata')
                self.assertEqual(z.read('classes.dex'), b'patched')

    def test_added_helper_uses_a_fixed_timestamp_for_reproducible_jars(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source, digest = self.fixture(root); out = root / 'result.jar'
            replace_dex(source, out, {'classes.dex': b'patched'}, digest, {'classes5.dex': b'our helper'})
            with zipfile.ZipFile(out) as z:
                self.assertEqual(z.getinfo('classes5.dex').date_time, (1980, 1, 1, 0, 0, 0))

    def test_changed_input_unknown_entry_or_existing_output_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source, digest = self.fixture(root); out = root / 'result.jar'
            for replacements, expected, additions in [({'classes.dex': b'x'}, '0'*64, {}), ({'classes9.dex': b'x'}, digest, {}), ({'classes.dex': b'x'}, digest, {'classes2.dex': b'x'})]:
                with self.subTest(replacements=replacements), self.assertRaises(ValueError):
                    replace_dex(source, out, replacements, expected, additions)
                self.assertFalse(out.exists())
            out.write_bytes(b'keep')
            with self.assertRaises(ValueError):replace_dex(source, out, {'classes.dex': b'x'}, digest)
            self.assertEqual(out.read_bytes(), b'keep')

    def test_unrelated_class_changes_are_rejected(self):
        before = {'Target.smali': 'old', 'Other.smali': 'keep'}
        expected = {'Target.smali': 'new', 'Other.smali': 'keep'}
        verify_classes(before, expected, expected, {'Target.smali'})
        with self.assertRaises(ValueError):
            verify_classes(before, expected, expected | {'Other.smali': 'changed'}, {'Target.smali'})
        with self.assertRaises(ValueError):
            verify_classes(before, expected, expected | {'Extra.smali': 'new class'}, {'Target.smali'})

    def test_label_normalization_preserves_literal_string_contents(self):
        a = '.method m()V\n:cond_1\nconst-string v0, "literal :cond_1"\ngoto :cond_1\n.end method'
        b = a.replace(':cond_1\n', ':cond_f\n').replace('goto :cond_1', 'goto :cond_f')
        self.assertEqual(normalized(a), normalized(b))
        self.assertNotEqual(normalized(a), normalized(a.replace('literal :cond_1', 'literal :cond_f')))
