import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('state',ROOT/'ci/state.py')
state=importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.request={'action':'start','run_id':123,'attempt':1,'head':'a'*40}

    def test_request_is_reserved_once_and_retry_is_idempotent(self):
        first,created=state.reserve(self.root,self.request,'source-sha')
        self.assertTrue(created)
        again,created=state.reserve(self.root,self.request,'source-sha')
        self.assertFalse(created)
        self.assertEqual(first,again)
        self.assertEqual(first['status'],'accepted')

    def test_same_identity_with_different_commit_is_rejected(self):
        state.reserve(self.root,self.request,'source-sha')
        changed=dict(self.request,head='b'*40)
        with self.assertRaises(ValueError): state.reserve(self.root,changed,'source-sha')

    def test_symlink_and_invalid_identity_are_rejected(self):
        target=self.root/'outside'; target.write_text('keep')
        (self.root/'123-1.json').symlink_to(target)
        with self.assertRaises(ValueError): state.reserve(self.root,self.request,'source-sha')
        with self.assertRaises(ValueError): state.load(self.root,'../outside',1)
        self.assertEqual(target.read_text(),'keep')

    def test_atomic_status_update_keeps_request_identity(self):
        item,_=state.reserve(self.root,self.request,'source-sha')
        state.update(self.root,123,1,status='running',pid=42)
        result=state.load(self.root,123,1)
        self.assertEqual(result['head'],item['head'])
        self.assertEqual(result['status'],'running')
        with self.assertRaises(ValueError): state.update(self.root,123,1,head='b'*40)

    def test_damaged_receipt_does_not_allow_replay(self):
        path=self.root/'123-1.json'; path.write_text('partial')
        with self.assertRaises(ValueError): state.reserve(self.root,self.request,'source-sha')
        self.assertEqual(path.read_text(),'partial')
