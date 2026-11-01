import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'ports/coloros17/download_artifact.sh'


class PhoneDownloadTests(unittest.TestCase):
    def run_script(self, plans, expected=b'abcdef', expected_hash=None, symlink_partial=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'bin').mkdir()
            (root / 'unused-config').write_text('')
            curl = root / 'bin/curl'
            curl.write_text('''#!/usr/bin/env python3
import os,json,sys
from pathlib import Path
p=Path(os.environ['CALLS']);n=int(p.read_text()) if p.exists() else 0
p.write_text(str(n+1));plan=json.loads(os.environ['PLANS'])[n]
assert sys.argv[sys.argv.index('--interface')+1]=='if!wlan0'
assert sys.argv[sys.argv.index('--continue-at')+1]=='-'
target=Path(sys.argv[sys.argv.index('--output')+1])
with target.open('ab') as f:f.write(plan[1].encode())
raise SystemExit(plan[0])
''')
            curl.chmod(0o755)
            sleep = root / 'bin/sleep'
            sleep.write_text('#!/bin/sh\nexit 0\n')
            sleep.chmod(0o755)
            sync = root / 'bin/sync'
            sync.write_text('#!/bin/sh\nexit 0\n')
            sync.chmod(0o755)
            env = dict(os.environ, PATH=str(root / 'bin')+':'+os.environ['PATH'],
                       PLANS=json.dumps(plans), CALLS=str(root / 'calls'))
            target=root/'image.gz'
            victim=root/'unrelated'
            victim.write_text('unchanged')
            if symlink_partial:
                target.with_suffix('.gz.part').symlink_to(victim)
            result=subprocess.run(['sh',str(SCRIPT),str(root/'unused-config'),str(target),str(len(expected)),
                                   expected_hash or hashlib.sha256(expected).hexdigest()],env=env,
                                  capture_output=True,text=True,timeout=10)
            calls=int((root/'calls').read_text()) if (root/'calls').exists() else 0
            self.assertEqual(victim.read_text(),'unchanged')
            return result.returncode, target.read_bytes() if target.exists() else None, calls

    def test_network_reset_resumes_and_verifies(self):
        self.assertEqual(self.run_script([(56,'abc'),(0,'def')]), (0,b'abcdef',2))

    def test_pin_and_http_errors_are_not_retried(self):
        for code in (90,22):
            with self.subTest(code=code):
                result,content,calls=self.run_script([(code,'abc')])
                self.assertEqual((result,content,calls),(code,None,1))

    def test_hash_mismatch_never_publishes(self):
        result,content,calls=self.run_script([(0,'abcdef')],expected_hash='0'*64)
        self.assertNotEqual(result,0)
        self.assertEqual((content,calls),(None,1))

    def test_oversized_response_never_publishes(self):
        result,content,calls=self.run_script([(0,'abcdefg')])
        self.assertNotEqual(result,0)
        self.assertEqual((content,calls),(None,1))

    def test_partial_symlink_is_rejected_before_curl(self):
        self.assertEqual(self.run_script([(0,'abcdef')],symlink_partial=True), (73,None,0))
