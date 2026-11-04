from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch
from ports.coloros17 import sensor_product
from test_coloros17_compat import fixture, manifest, tree_snapshot

class SensorProductTests(unittest.TestCase):
    def setup_tree(self, root):
        tree, _, _ = fixture(root)
        p = tree / sensor_product.TARGET[1:]; p.parent.mkdir(parents=True, exist_ok=True)
        before = b'# donor\nro.product.product.name=ossi\nro.product.model=PLG110\n'
        after = before.replace(b'=ossi\n', b'=dash_global\n')
        p.write_bytes(before); p.chmod(0o644)
        records, contents = manifest(tree)
        spec = {'schema_version':1,'path':sensor_product.TARGET,
                'source_sha256':hashlib.sha256(before).hexdigest(),'source_size':len(before),
                'sha256':hashlib.sha256(after).hexdigest(),'size':len(after)}
        return tree, records, contents, spec, before, after

    def test_changes_only_product_partition_name_and_repeats_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); tree,records,contents,spec,before,after=self.setup_tree(root)
            snapshot=tree_snapshot(tree)
            with patch.object(sensor_product,'_load_manifest',return_value=spec):
                plan=sensor_product.plan_sensor_product(tree,records,contents)
                self.assertEqual(tree_snapshot(tree),snapshot)
                result=sensor_product.apply_sensor_product(tree,records,contents,root/'backup')
                repeat=sensor_product.apply_sensor_product(tree,result['final_records'],result['final_content_manifest'],root/'unused')
            self.assertEqual((tree/sensor_product.TARGET[1:]).read_bytes(),after)
            self.assertIn(b'ro.product.model=PLG110\n',after)
            self.assertEqual((root/'backup'/sensor_product.TARGET[1:]).read_bytes(),before)
            self.assertEqual(repeat['status'],'already_applied')

    def test_unknown_source_or_target_is_refused_without_writing(self):
        for mutation in ['source','target']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);tree,records,contents,spec,_,_=self.setup_tree(root)
                if mutation=='source':spec['source_sha256']='0'*64
                else:spec['path']='/system/build.prop'
                snapshot=tree_snapshot(tree)
                with patch.object(sensor_product,'_load_manifest',return_value=spec),self.assertRaises(ValueError):
                    sensor_product.apply_sensor_product(tree,records,contents,root/'backup')
                self.assertEqual(tree_snapshot(tree),snapshot)
