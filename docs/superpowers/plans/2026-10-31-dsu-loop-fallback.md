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

### Task 2: Native validation and possible deployment (pending)

- [ ] After the current full ROM build ends, compile the patched target in a separately verified source state.
- [ ] Inspect resulting dependencies and the DSU runtime SELinux/domain permissions.
- [ ] Prepare a reversible installation method and backups before seeking approval to change the phone.
- [ ] Validate allocation, real status-file serialization and `UnmapImageDevice` cleanup (including split-image teardown order), and only then a test boot; do not claim success from a host test.
