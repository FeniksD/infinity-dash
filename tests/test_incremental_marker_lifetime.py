"""Run the actual marker check and upstream path helpers under AddressSanitizer.

Set INCREMENTAL_MARKER_SOURCE to an upstream IncrementalService.cpp to run the
same regression against the unpatched source. Only the function under test is
extracted; the path helpers below are verbatim upstream code, not test doubles.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get(
    "INCREMENTAL_MARKER_SOURCE",
    ROOT / "source_overrides/frameworks/base/services/incremental/IncrementalService.cpp",
))

# frameworks/base at 376ae8444e798ed5dffeba922e518ac603b759bb.
# services/incremental/path.h SHA256:
# 750fc98e46c207a1c06bc5c6e5fa9b400a3b8a50af156d16698ff7b53dc0c56b
# services/incremental/path.cpp SHA256:
# a22fb3e5b9a2325a2b9d30dac881b11bbf6ee44d018b0e1786691e18d2db6e40
# Preserve the real overloads, CStrWrapper ownership behavior, and path joining.
PATH_HEADER = r'''/*
 * Copyright (C) 2019 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#pragma once

#include <optional>
#include <string>
#include <string_view>

namespace android::incremental::path {

namespace details {

class CStrWrapper {
public:
    CStrWrapper(std::string_view sv);

    CStrWrapper(const CStrWrapper&) = delete;
    void operator=(const CStrWrapper&) = delete;
    CStrWrapper(CStrWrapper&&) = delete;
    void operator=(CStrWrapper&&) = delete;

    const char* get() const { return mCstr; }
    operator const char*() const { return get(); }

private:
    const char* mCstr;
    std::optional<std::string> mCopy;
};

void append_next_path(std::string& res, std::string_view c);

} // namespace details

//
// An std::map<> comparator that makes all nested paths to be ordered before the parents.
//

struct PathCharsLess {
    bool operator()(char l, char r) const;
};

struct PathLess {
    using is_transparent = void;
    bool operator()(std::string_view l, std::string_view r) const;
};

//
// Returns a zero-terminated version of a passed string view
// Only makes a copy if it wasn't zero-terminated already
// Useful for passing string view parameters to system functions.
//
inline details::CStrWrapper c_str(std::string_view sv) {
    return {sv};
}

std::string_view relativize(std::string_view parent, std::string_view nested);
inline std::string_view relativize(const char* parent, const char* nested) {
    return relativize(std::string_view(parent), std::string_view(nested));
}
inline std::string_view relativize(std::string_view parent, const char* nested) {
    return relativize(parent, std::string_view(nested));
}
inline std::string_view relativize(const char* parent, std::string_view nested) {
    return relativize(std::string_view(parent), nested);
}

std::string_view relativize(std::string&& parent, std::string_view nested) = delete;
std::string_view relativize(std::string_view parent, std::string&& nested) = delete;

bool isAbsolute(std::string_view path);
std::string normalize(std::string_view path);
std::string_view dirname(std::string_view path);
std::string_view basename(std::string_view path);
std::optional<bool> isEmptyDir(std::string_view dir);
bool startsWith(std::string_view path, std::string_view prefix);

template <class... Paths>
std::string join(std::string&& first, std::string_view second, Paths&&... paths) {
    std::string& result = first;
    {
        using std::size;
        result.reserve(first.size() + second.size() + 1 + (sizeof...(paths) + ... + size(paths)));
    }
    (details::append_next_path(result, second), ...,
     details::append_next_path(result, std::forward<Paths>(paths)));
    return std::move(result);
}

template <class... Paths>
std::string join(std::string_view first, std::string_view second, Paths&&... paths) {
    return path::join(std::string(), first, second, std::forward<Paths>(paths)...);
}

template <class... Paths>
std::string join(const char* first, std::string_view second, Paths&&... paths) {
    return path::join(std::string_view(first), second, std::forward<Paths>(paths)...);
}

} // namespace android::incremental::path
'''

# Only these three path.cpp definitions are reachable by the marker check.
PATH_IMPLEMENTATION = r'''#include <iterator>
#include "path.h"
namespace android::incremental::path {
static void preparePathComponent(std::string_view& path, bool trimAll) {
    // need to check for double front slash as a single one has a separate meaning in front
    while (!path.empty() && path.front() == '/' &&
           (trimAll || (path.size() > 1 && path[1] == '/'))) {
        path.remove_prefix(1);
    }
    // for the back we don't care about double-vs-single slash difference
    while (path.size() > !trimAll && path.back() == '/') {
        path.remove_suffix(1);
    }
}

void details::append_next_path(std::string& target, std::string_view path) {
    preparePathComponent(path, !target.empty());
    if (path.empty()) {
        return;
    }
    if (!target.empty() && !target.ends_with('/')) {
        target.push_back('/');
    }
    target += path;
}

details::CStrWrapper::CStrWrapper(std::string_view sv) {
    auto is_string_view_nul_terminated = [](std::string_view sv) {
        // NOTE(ag/38334313): `sv.data()[sv.size()]` is used instead of
        // `sv[sv.size()]` to avoid libcxx hardening checks. It's required that
        // users only pass `string_view`s here that are constructed from
        // underlying, nul-terminated C strings, and it's required that users
        // not pass `string_view`s with nul characters embedded in them.
        // Hence, reaching one past the end is always safe.
        return sv.data()[sv.size()] == '\0';
    };

    if (sv.empty()) {
        mCstr = "";
    } else if (is_string_view_nul_terminated(sv)) {
        mCstr = sv.data();
    } else {
        mCopy.emplace(sv);
        mCstr = mCopy->c_str();
    }
}
}
'''

HARNESS = r'''#include <iterator>
#include "path.h"
#include <sys/stat.h>
#include <cstring>
#include <iostream>

extern "C" int __real_stat(const char*, struct stat*);
extern "C" int __wrap_stat(const char* pathname, struct stat* result) {
    // A host kernel reads pathname outside ASan's instrumentation. Read the
    // same NUL-terminated buffer in userspace, then call the real filesystem.
    volatile auto length = std::strlen(pathname);
    (void)length;
    return __real_stat(pathname, result);
}

namespace android::incremental {
struct Constants {
    static constexpr std::string_view readLogsDisabledMarkerName = ".readlogs_disabled";
};
const Constants& constants() { static const Constants value; return value; }
FUNCTION_UNDER_TEST
}

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    const bool present = android::incremental::checkReadLogsDisabledMarker(argv[1]);
    const bool expected = std::string_view(argv[2]) == "present";
    if (present != expected) {
        std::cerr << "marker present=" << present << ", expected=" << expected << '\n';
        return 3;
    }
    return 0;
}
'''

class IncrementalMarkerLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang++") or shutil.which("g++")
        if not compiler:
            raise RuntimeError("An AddressSanitizer C++ compiler is required")
        source = SOURCE.read_text()
        match = re.search(
            r"static bool checkReadLogsDisabledMarker\(std::string_view root\) \{.*?\n\}",
            source, re.S,
        )
        if match is None:
            raise AssertionError("Could not extract the actual marker check")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        (cls.directory / "path.h").write_text(PATH_HEADER)
        (cls.directory / "path.cpp").write_text(PATH_IMPLEMENTATION)
        (cls.directory / "marker.cpp").write_text(
            HARNESS.replace("FUNCTION_UNDER_TEST", match.group())
        )
        cls.executable = cls.directory / "marker-test"
        result = subprocess.run(
            [compiler, "-std=c++20", "-O1", "-g", "-fsanitize=address",
             "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-Wl,--wrap=stat",
             str(cls.directory / "marker.cpp"), str(cls.directory / "path.cpp"),
             "-o", str(cls.executable)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def check_marker(self, root, present):
        folder = self.directory / root
        folder.mkdir(exist_ok=True)
        marker = folder / ".readlogs_disabled"
        if present:
            marker.touch()
        else:
            marker.unlink(missing_ok=True)
        result = subprocess.run(
            [str(self.executable), root, "present" if present else "absent"],
            cwd=self.directory, capture_output=True, text=True, timeout=10,
            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0:halt_on_error=1"),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_short_root_without_marker(self):
        self.check_marker("s", False)

    def test_short_root_with_marker(self):
        self.check_marker("s", True)

    def test_long_root_without_marker(self):
        self.check_marker("MT_data_app_vmdl116_" + "x" * 160, False)

    def test_long_root_with_marker(self):
        self.check_marker("MT_data_app_vmdl116_" + "x" * 160, True)


if __name__ == "__main__":
    unittest.main()
