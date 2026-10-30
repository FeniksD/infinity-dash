import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL='edea05157943a71191c744afe064cd7353b47ea3e8057964d3f9957cf091cc27'
PAYLOAD='21e841019201fcc09250396eedb22ee9995452b8d1b629691a6fd1dcb85a4e80'


class DsuModuleTests(unittest.TestCase):
    def run_installer(self, **overrides):
        with tempfile.TemporaryDirectory() as tmp:
            capture=Path(tmp)/'permissions'
            env=dict(os.environ,BOOTMODE='true',ARCH='arm64',API='37',MODPATH=tmp,
                     TEST_DEVICE='dash',TEST_ORIGINAL=ORIGINAL,TEST_PAYLOAD=PAYLOAD,
                     TEST_PERM_RESULT='0',TEST_CAPTURE=str(capture))
            env.update(overrides)
            script='''
abort() { printf 'ABORT:%s\\n' "$*"; exit 37; }
ui_print() { :; }
getprop() { printf '%s\\n' "$TEST_DEVICE"; }
sha256sum() {
    if [ "$1" = /system/bin/gsid ]; then value=$TEST_ORIGINAL; else value=$TEST_PAYLOAD; fi
    printf '%s  %s\\n' "$value" "$1"
}
set_perm() { printf '%s\\n' "$*" > "$TEST_CAPTURE"; return "$TEST_PERM_RESULT"; }
. '''+shlex.quote(str(ROOT/'packaging/dsu-loopfix/customize.sh'))
            result=subprocess.run(['sh','-c',script],env=env,capture_output=True,text=True)
            args=capture.read_text().strip() if capture.exists() else None
            return result,args,tmp

    def test_verified_system_sets_only_gsid_permissions(self):
        result,args,tmp=self.run_installer()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(args,tmp+'/system/bin/gsid 0 2000 0755 u:object_r:gsid_exec:s0')

    def test_wrong_context_and_hashes_abort_before_permission_changes(self):
        for values in ({'API':'36'},{'ARCH':'x86_64'},{'BOOTMODE':'false'},
                       {'TEST_DEVICE':'other'},{'TEST_ORIGINAL':'0'*64},{'TEST_PAYLOAD':'0'*64}):
            with self.subTest(values=values):
                result,args,_=self.run_installer(**values)
                self.assertEqual(result.returncode,37)
                self.assertIsNone(args)

    def test_failed_label_or_permissions_abort(self):
        result,_,_=self.run_installer(TEST_PERM_RESULT='1')
        self.assertEqual(result.returncode,37)
        self.assertIn('permissions/SELinux',result.stdout)
