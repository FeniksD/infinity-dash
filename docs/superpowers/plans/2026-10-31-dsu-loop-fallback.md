# DSU Loop Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prepare a tested experimental Android 17 source patch for DSU images stored on directly mounted userdata.

**Architecture:** Restore the existing loop-device helper for the DSU directory only, retaining the device-mapper path elsewhere. Compile the actual extracted upstream/patched C++ methods with controlled helper implementations to test routing, returned paths and cleanup.

**Tech Stack:** C++17, Python unittest, Git unified patches.

**Spec:** `docs/superpowers/specs/2026-10-31-dsu-loop-fallback.md`

## Global Constraints

- Base: `system/fs/fs_mgr` revision `91ff6a99ae0a1be7a625a0738983c995ed03f8c1`.
- No changes to the running build, phone partitions, encryption or installation state.
- Patch remains experimental and is not added to the automatic platform-patch list.
- Preserve caller authorization, reliable-pinning checks, direct-I/O checks and failure cleanup.

## Review Focus

- A split image must return the combined mapping, never its final fragment.
- Empty file lists must fail without dereferencing `back()`.
- A failed loop mapper must not fall through to raw physical mapping.
- Non-DSU paths must retain the original refusal, including prefix lookalikes.
- Ramdisk/recovery mapping and property-failure cleanup must retain original behavior.

### Task 1: Candidate patch and executable routing tests

- [x] Preserve the original licensed source fixture and its SHA-256.
- [x] Add a host C++ harness using actual extracted `MapImageDevice`/`MapWithLoopDevice` methods; observe failure against unchanged source.
- [x] Create the narrow patch and test ordinary device mapper, DSU loop, refusal, split/empty input and failure cleanup.
- [x] Run the complete local suite, validate exact patch application, and obtain a fresh code review.
- [x] Commit the candidate separately with its unvalidated integration boundaries documented.

### Task 2: Native validation and possible deployment (in progress)

- [x] Prepare a separately verified source view, private output filesystem, resource limits and clean environment without changing the active ROM build.
- [x] Compile the patched `gsid` target in that private namespace (running alongside the ROM build at the user's request).
- [x] Check native dependencies against phone libraries and run the dynamic linker's non-executing list mode.
- [ ] Validate DSU runtime SELinux/domain permissions during real allocation and mapping.
- [x] Prepare a reversible installation method and original-binary backup before seeking approval to change the phone.
- [ ] Validate allocation, real status-file serialization and `UnmapImageDevice` cleanup (including split-image teardown order), and only then a test boot; do not claim success from a host test.

Native launcher: `build/dsu-native-launch.sh` runs as root only for setup, creates a private mount/network/PID namespace, and delegates compilation to UID1000. The original output/log/home paths are read-only inside that namespace. `build/dsu-native-build.sh` checks the full variant source inventory before and after `m gsid -j2`. The separate output filesystem is capped at40GiB; initial cgroup limits are CPU2/RAM24GiB/swap4GiB. The cold Soong graph needed temporarily higher limits; these were restored afterward. The source override and both manifests remain root-owned and covered by the host guard. Native build and full postcheck exited0; GSI allocation and boot validation remain pending.
