import base64
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('protocol',ROOT/'ci/protocol.py')
protocol=importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


class ProtocolTests(unittest.TestCase):
    def test_roundtrip_start_request(self):
        request={'action':'start','run_id':123,'attempt':1,'head':'a'*40}
        self.assertEqual(protocol.decode_command(protocol.encode_command(request)),request)

    def test_shell_text_wrong_types_unknown_fields_and_traversal_are_rejected(self):
        bad=[
            {'action':'start','run_id':'1; id','attempt':1,'head':'a'*40},
            {'action':'start','run_id':True,'attempt':1,'head':'a'*40},
            {'action':'status','run_id':1,'attempt':1,'command':'id'},
            {'action':'fetch','run_id':1,'attempt':1,'artifact':'../../etc/shadow'},
            {'action':'fetch','run_id':1,'attempt':1,'artifact':'x;id'},
        ]
        for request in bad:
            command='infinity-ci '+base64.urlsafe_b64encode(json.dumps(request).encode()).decode()
            with self.assertRaises(ValueError): protocol.decode_command(command)
        with self.assertRaises(ValueError): protocol.decode_command('scp -t /tmp')

    def test_duplicate_json_fields_are_rejected(self):
        data=b'{"action":"status","action":"start","run_id":1,"attempt":1}'
        command='infinity-ci '+base64.urlsafe_b64encode(data).decode()
        with self.assertRaises(ValueError): protocol.decode_command(command)

    def test_positive_run_and_attempt_required(self):
        for run,attempt in ((0,1),(-1,1),(1,0),(1,1001)):
            with self.assertRaises(ValueError): protocol.encode_command({'action':'status','run_id':run,'attempt':attempt})
