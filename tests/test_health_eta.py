"""Compile and exercise the same ETA filter used by the vendor health HAL."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HEADER_DIR = ROOT / "source_overrides/hardware/mediatek/aidl/health"


class HealthEtaTests(unittest.TestCase):
    def check_variant(self, ignore_eta):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler, "A C++ compiler is required for HAL policy tests")
        # The observed invalid predictions, a plausible ETA, unsupported, full,
        # and a value beyond int32 all have to survive correctly on other boards.
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "test.cpp"
            source.write_text('''#include "ChargeTimeToFull.h"
#include <cstdint>
#include <iostream>
int main() {
    const int64_t inputs[] = {2005333, 1955200, 1905066, 1804800,
                              902400, 3600, -1, 0, 5000000000LL};
    for (const auto input : inputs)
        std::cout << mediatek::health::ChargeTimeToFullSeconds(input) << '\\n';
}
''')
            executable = folder / "health-eta-test"
            command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                       "-I", str(HEADER_DIR), str(source), "-o", str(executable)]
            if ignore_eta:
                command.append("-DMEDIATEK_HEALTH_IGNORE_TIME_TO_FULL=1")
            subprocess.run(command, check=True, capture_output=True, text=True)
            actual = subprocess.check_output([str(executable)], text=True)
        return [int(line) for line in actual.splitlines()]

    def test_dash_reports_hardware_eta_unavailable_instead_of_bogus_duration(self):
        self.assertEqual(self.check_variant(True), [-1] * 9)

    def test_other_boards_preserve_every_reported_duration(self):
        self.assertEqual(self.check_variant(False),
                         [2005333, 1955200, 1905066, 1804800,
                          902400, 3600, -1, 0, 5000000000])
