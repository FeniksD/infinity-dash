"""Exercise the actual marker-check function with AddressSanitizer."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'source_overrides/frameworks/base/services/incremental/IncrementalService.cpp'


class IncrementalMarkerLifetimeTests(unittest.TestCase):
    def test_marker_path_remains_alive_through_stat(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if not compiler:
            self.skipTest('AddressSanitizer C++ compiler is unavailable')
        source = SOURCE.read_text()
        match = re.search(r'static bool checkReadLogsDisabledMarker\(std::string_view root\) \{.*?\n\}',
                          source, re.S)
        self.assertIsNotNone(match, 'marker-check function must remain testable')
        # Substitute only the filesystem call; compile the actual function body.
        function = match.group().replace('::stat(', '::capture_stat(')
        harness = r'''
#include <string>
#include <string_view>
#include <sys/stat.h>
namespace path {
std::string join(std::string_view a, std::string_view b) {
    return std::string(a) + "/" + std::string(b);
}
// A joined std::string is NUL-terminated, so the real CStrWrapper borrows
// its buffer. This fixture preserves that ownership/lifetime behavior.
const char* c_str(const std::string& value) { return value.c_str(); }
}
struct Constants { std::string_view readLogsDisabledMarkerName = ".readlogs_disabled"; };
const Constants& constants() { static Constants value; return value; }
std::string expected;
int capture_stat(const char* filename, struct stat*) {
    return std::string_view(filename) == expected ? 0 : -1;
}
''' + function + r'''
int main() {
    const std::string root = "/data/incremental/MT_" + std::string(180, 'x');
    expected = path::join(root, constants().readLogsDisabledMarkerName);
    return checkReadLogsDisabledMarker(root) ? 0 : 2;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'test.cpp').write_text(harness)
            compile_result = subprocess.run([compiler, '-std=c++17', '-O1', '-g',
                                             '-fsanitize=address', '-fno-omit-frame-pointer',
                                             str(path / 'test.cpp'), '-o', str(path / 'test')],
                                            capture_output=True, text=True, timeout=30)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run([str(path / 'test')], capture_output=True, text=True,
                                    env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1'),
                                    timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
