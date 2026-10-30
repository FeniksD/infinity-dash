# DSU loop mapping — experimental candidate

This patch is not installed on the phone, applied to the running build, or included in `sources/platform-patches.json`.

Base project: `system/fs/fs_mgr`, revision `91ff6a99ae0a1be7a625a0738983c995ed03f8c1`. File hashes are recorded in `dsu-loop-fallback.json`; the original Apache-licensed source fixtures retain their upstream headers.

The candidate restores the existing loop-device route for DSU images under `/data/gsi/dsu/` when userdata is not mounted through device-mapper. Other paths retain the original refusal. It also rejects an empty split-file list and preserves the combined mapping path for multi-file images. The shared status-property and failure-cleanup path remains in use.

Validation: `python3 -m unittest discover -s tests -p test_dsu_mapping.py -v` applies the patch to the exact fixture and compiles the actual mapping methods and `IsSubdir` into a host test harness. Kernel/helper calls use controlled adapters. This checks routing and error handling, not actual allocation or boot behavior.

The existing gsid entry points canonicalize installation paths with `Realpath`; the directory check here relies on that existing caller contract. The host harness does not exercise real status-file serialization or `UnmapImageDevice` teardown. Those checks, including split-image teardown order, remain native integration requirements.

Still required: native Android compilation, ABI/SELinux validation, real loop/direct-I/O allocation and cleanup tests, then separately approved phone testing with a recovery path. Nothing here changes encryption or makes an untested phone installation safe.
