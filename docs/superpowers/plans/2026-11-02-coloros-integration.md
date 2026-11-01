# ColorOS tested-runtime integration plan

> **For agentic workers:** Use `superpowers:executing-plans` for the main integration; keep independent read-only face, radio and camera investigations separate.

**Goal:** Make the verified dash fingerprint/haptic/charging fixes survive a DSU reboot, then integrate real Face Unlock, working cellular service and the exact Infinity MIUI Camera where compatible.

**Architecture:** Retain the Xiaomi kernel, vendor and modem. Apply hash-pinned system-only deltas to the canonical metadata/content pair and to an inactive, unmounted DSU image. Each hardware change gets a separate runtime test and rollback; do not replace the current working biometric implementation speculatively.

**Tech Stack:** Python, existing metadata-preserving EXT4 builder/reader, Android init/CIL, verified Android JARs/APKs, ADB and isolated DSU mappings.

**Spec:** Owner's 2026-11-02 instruction; `ports/coloros17/udfps/manifest.json`, `fingerprint-compat.json`, `charger-diagnostics.json`, `haptic-fallback.json`, `radio-compat.json`.

## Global constraints

- Target is POCO dash, SDK 37; installed host Infinity and DSU userdata must survive.
- No modem/NV/IMEI/eSIM writes, no fake biometric success or strength promotion, no permissive SELinux.
- Keep original signatures and require evidence for privileged APK compatibility.
- Never modify the mounted active GSI block device; first return to Infinity and verify an exclusive inactive mapping.
- Preserve a trusted local manifest and rollback bytes before mutations. Current source baseline is commit `a2172f3`.
- VDS space is limited. Preserve source/out and final artifacts; reclaim only identified reproducible scratch.

## Review focus

- Reboot must load both matching JARs, correct early properties and effective narrow policy.
- Partial updates must not publish mismatched JARs or metadata; recover the complete before/after state.
- SELinux hash stamps must describe changed CIL so an old precompiled policy cannot silently win.
- Camera/face dependencies must retain working Xiaomi interfaces and original biometric classification.
- Radio experiments must change one evidenced input and restore it if the test fails.

### Task 1: Snapshot and runtime bundle

**Files:** Create `ports/coloros17/runtime-bundle.json`, `runtime_bundle.py`, `patches/dash-runtime-compat.rc`; test `tests/test_coloros17_runtime_bundle.py`.

**Interface:** `plan_runtime_bundle(tree, records, contents, artifact_dir)` returns exact file writes and a new metadata/content pair. `apply_runtime_bundle(..., backup_dir)` returns a verified journal or a rollback error.

- [ ] Snapshot current JAR hashes, policy, property values and active DSU identity privately.
- [ ] Add failing tests for bad artifact hashes, unknown existing bytes, idempotence and partial-write rollback.
- [ ] Integrate verified C9 services, C8 combined Oplus services, fingerprint feature, startup properties and reviewed CIL fragments.
- [ ] Verify real CIL compile and its hash-stamp inputs; add tests for deterministic policy/property output.
- [ ] Extend `candidate.py` with a journalled runtime stage and require it before the new image variant is published.
- [ ] Run relevant tests and commit under the existing FeniksD identity.

### Task 2: Permanent image and cold boot

**Files:** Create an explicit image-delta receipt/tool under `ports/coloros17/`; reuse `build_image.py` metadata/content verification. Keep device orchestration in private task cache.

- [ ] Preserve the old compressed image or another byte-exact recovery copy before host image edits.
- [ ] Test metadata-preserving writes and failure recovery on a small generated EXT4 image.
- [ ] Apply only the planned file delta to the host image, or rebuild if space permits; verify full filesystem and contents.
- [ ] Return the phone to Infinity without deleting DSU userdata; map DSU only through the reviewed ImageManager helper.
- [ ] Patch inactive DSU with backups, file hash guards and preserved owner/mode/SELinux labels.
- [ ] Unmount, run read-only fsck, hash readback, unmap, and boot the same DSU slot once.
- [ ] Verify effective policy/properties and fingerprint enrollment, animation, wake and retry after the cold boot.

### Task 3: Cellular

- [ ] Preserve current private logs and verify `ro.product.vendor.name` is returned through CCCI RPC during modem critical-data validation.
- [ ] Test only the retained hardware value `dash_global`, with the audited bounded capture and equivalent fresh-modem restart.
- [ ] Require successful radio-on confirmation and real network registration; restore on failure.
- [ ] Promote only a demonstrated fix into the runtime bundle; otherwise obtain the matched Infinity baseline.

### Task 4: MIUI Camera

- [ ] Inventory exact working Infinity APK, libraries, permission files and certificate.
- [ ] Check shared UID, native symbols and framework dependencies against the retained ColorOS/Xiaomi combination.
- [ ] Stage the minimum hash-pinned bundle; test launch, preview, front/back cameras, capture and video before replacing the default camera.

### Task 5: Face Unlock

- [ ] Audit the genuine Infinity Sense matcher, signing requirements and provider API.
- [ ] Design an own-UID matcher + trusted framework adapter if the original shared UID cannot be retained safely.
- [ ] Preserve weak/RGB classification and enforce matching user/request, cancellation and lockout semantics.
- [ ] Test real enrollment, correct/incorrect face, reboot, deletion and cancellation. Keep unavailable rather than report fabricated authentication.
