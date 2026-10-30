"""Execute actual fs_mgr mapping methods with controlled OS/helper adapters."""
import hashlib
from pathlib import Path
import resource
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SHA = '9841d041982b400e7be2295f373a7c5c8b4606e50366ffe9c2cea58f9e5cb7d8'
UTILITY_SHA = '85219cc24bb978928f5d51a5da4e4c4bda514f8b697ba9033ecd03f2e071e5cf'


class DsuMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        fixture = ROOT/'tests/fixtures/fs_mgr/image_manager.cpp'
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == FIXTURE_SHA
        target = root/'libfiemap/image_manager.cpp'
        target.parent.mkdir()
        shutil.copyfile(fixture, target)
        patch = ROOT/'patches/experimental/0003-dsu-loop-fallback.patch'
        if patch.exists():
            subprocess.run(['git','apply','--check',str(patch)],cwd=root,check=True)
            subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
        source = target.read_text()
        names = ('MapWithLoopDevice', 'MapImageDevice')
        methods = []
        for name in names:
            start = source.index(f'bool ImageManager::{name}(')
            end = source.index('\n}\n',start)+3
            methods.append(source[start:end])
        template = (ROOT/'tests/fixtures/dsu_mapping_harness.cpp').read_text()
        utility_file = ROOT/'tests/fixtures/fs_mgr/utility.cpp'
        assert hashlib.sha256(utility_file.read_bytes()).hexdigest() == UTILITY_SHA
        utility = utility_file.read_text()
        start = utility.index('bool IsSubdir(')
        end = utility.index('\n}\n',start)+3
        cpp = root/'test.cpp'
        cpp.write_text(template.replace('@@UTILITIES@@',utility[start:end]).replace('@@METHODS@@','\n'.join(methods)))
        cls.binary = root/'mapping-test'
        cls.ramdisk_binary = root/'ramdisk-test'
        for binary, extra in ((cls.binary,[]),(cls.ramdisk_binary,['-D__ANDROID_RAMDISK__'])):
            result = subprocess.run(['g++','-std=c++17','-Wall','-Wextra',*extra,str(cpp),'-o',str(binary)],capture_output=True,text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)

    def run_case(self, name, ramdisk=False):
        def no_core(): resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        result = subprocess.run([str(self.ramdisk_binary if ramdisk else self.binary),name],capture_output=True,text=True,timeout=5,preexec_fn=no_core)
        self.assertEqual(result.returncode,0,f'{name}: {result.stderr}')

    def test_device_mapper_path_preserved(self): self.run_case('device_mapper')
    def test_dsu_can_use_loop_for_direct_userdata(self): self.run_case('dsu_loop')
    def test_dsu_root_without_trailing_slash_is_supported(self): self.run_case('dsu_root')
    def test_other_paths_remain_rejected(self): self.run_case('non_dsu')
    def test_prefix_lookalike_remains_rejected(self): self.run_case('prefix_lookalike')
    def test_loop_failure_does_not_fall_through(self): self.run_case('loop_failure')
    def test_property_failure_unmaps_loop_image(self): self.run_case('property_failure')
    def test_resolution_failure_is_rejected(self): self.run_case('resolve_failure')
    def test_duplicate_mapping_is_rejected(self): self.run_case('already_mapped')
    def test_ramdisk_keeps_device_mapper_path(self): self.run_case('ramdisk',ramdisk=True)
    def test_split_image_returns_combined_device(self): self.run_case('helper_split')
    def test_empty_image_list_is_rejected(self): self.run_case('helper_empty')
    def test_direct_io_failure_detaches_loop(self): self.run_case('helper_optimize_failure')
    def test_failed_split_mapping_detaches_loops(self): self.run_case('helper_split_failure')
    def test_partial_loop_attachment_failure_detaches_previous_loop(self): self.run_case('helper_second_attach_failure')
    def test_status_write_failure_detaches_loop(self): self.run_case('helper_status_failure')
