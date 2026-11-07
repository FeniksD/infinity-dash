# ColorOS 17 Global with existing dash patches

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Keep work in the existing isolated workspace on `feat/coloros17-global`.

**Goal:** Produce and test a separate Global ColorOS 17 DSU candidate for dash, carrying forward the verified CN compatibility fixes.

**Architecture:** Retain the Infinity kernel/vendor/odm base and use the Global Find X9 Pro user-space donor. Rebase each existing compatibility change against verified Global inputs; never mix CN framework binaries into Global without proving their source identity. Preserve the current CN image and its manifest pair as rollback material.

**Tech Stack:** Existing Python construction pipeline, Android OTA/EXT4 metadata tools, smali/ART regression harnesses, ADB/DSU, SHA-256 and OTA signature verification.

**Spec:** `docs/superpowers/specs/2026-11-01-coloros17-dsu-design.md`, with the donor delta below.

## Follow-up checkpoint: 2026-11-07

The Global artifact was constructed, readback-verified and booted to an unlocked
launcher. Follow-up scope and remaining acceptance gaps are recorded in
`ports/coloros17/global-runtime-status.json`; optional AI experiments are in
`ports/coloros17/feature-trials-20261107.json`. Do not turn the checklist below
into a blanket assertion that every Global hardware test passed. CN-only test
results remain separate evidence.

The owner now chooses Global and has abandoned CN credential recovery. Do not
resume CN boot tests. The owner also prohibits further interaction with the phone
until renewed authorization: continue only on the host. The server guard remains
latched, so these follow-up records do not authorize a new build or baseline reset.

## Global constraints

- Candidate donor: Find X9 Pro `CPH2791_17.0.0.102(EX01)`, Android 17; select the exact regional artifact from inspected metadata.
- The current CN source branch is `feat/coloros17-dsu`; do not alter its server workspace `/srv/infinity/coloros17` in place.
- Global server workspace: `/srv/infinity/coloros17-global`.
- Preserve Infinity, modem/NV, current CN userdata, private signing keys, and user application data.
- Keep SELinux enforcing, existing temperature protection, and source/image identity checks.
- No unverified AOD or camera experiment becomes part of the candidate merely because it exists in a private cache.
- Do not delete build caches or rollback artifacts to make space without a checked recovery route.
- Resolve the server guard's reported user/SSH/VPN changes before executing a build there. Do not approve a new baseline by assuming those changes were authorized.

## Review focus

- A download mirror or renewed signed URL must not silently select another release; compare metadata, hashes and the signer against established trust material.
- A changed Global method must cause a patch precondition failure, rather than a byte-offset patch against the wrong code.
- Identical file content with different filesystem labels or ownership must not be treated as an interchangeable source inode.
- A failed Global boot must leave a verified route back to Infinity and the saved CN candidate.
- Bundled Google applications must be checked for actual enabled/running state; their presence does not imply Play certification or Integrity verdicts.

## Task 1: Authenticate and inventory the Global donor

**Files:** Existing `ports/coloros17/donor.json`, `donor-metadata.json`, `payload-summary.json`, `payload-verification.json`, and `ota-signature-verification.json` on the Global branch.

- [ ] Inspect the ZIP footer, OTA metadata, payload header and partition manifest with bounded HTTP ranges.
- [ ] Compare the OTA signer to the verified CN signer; if different, establish independent manufacturer provenance before accepting the new key.
- [ ] Pin the exact regional artifact's size, MD5, SHA-256, payload hash and metadata values.
- [ ] Download the archive on the server only after the security/storage gates are satisfied. Verify the complete archive signature and payload; partial metadata checks alone are insufficient.
- [ ] Verify all selected OS partitions can be reconstructed without missing source-image extents. Do not install donor boot/vendor/modem partitions on dash.

## Task 2: Prepare storage and a separate canonical tree

**Files:** `/srv/infinity/coloros17-global/{inputs,control,work,output}` and private storage receipts.

- [ ] Record current CN image hashes and the canonical metadata/content manifest hashes.
- [ ] Identify free-space reclamation that retains all useful artifacts. The GSID build loop filesystem has free internal blocks: inspect discard support before considering trim; do not resize or delete its live contents blindly.
- [ ] Budget archive, extraction, output and rollback space before writing large files.
- [ ] Extract Global OS partitions using the existing verified metadata-preserving path.
- [ ] Produce a per-file CN/Global identity comparison, including metadata, for the framework files and overlay targets touched by our patches.

## Task 3: Rebase the verified compatibility changes

**Files:** `ports/coloros17/compat.py`, `runtime-bundle.json`, `runtime-image.json`, `radio_registration.py`, `radio-registration.json`, `sensor_product.py`, `sensor-product.json`, `branding.py`, and their existing tests/manifests as required by the Global inputs.

- [ ] Run the existing test suite as a baseline.
- [ ] Preserve monolithic DSU mount handling, loop-control labeling and the reviewed composer-client policy.
- [ ] Rebase haptics fallback and invalid charging-diagnostic handling, then execute their existing ART regression probes against the resulting code.
- [ ] Rebase fingerprint initialization, enrollment/UI routing, repeated attempts and screen-on resume. Preserve authentication decisions and the current screen-off restrictions.
- [ ] Rebase optional OPPO radio-service exception handling; run the actual-method tests including the unrelated exception that must still propagate.
- [ ] Restore the retained dash product identity required by HWC light compensation, preserving all other Global build properties.
- [ ] Rebuild the About overlay against the actual Global Settings resources and preserve the owner's preferred layout and channel credit.
- [ ] Carry MIUI Camera only as a clearly unverified optional payload until preview/capture succeeds; do not describe the reported connection error as fixed.
- [ ] Check Global's own GMS/GSF/Play Store and regional app configuration before adding or removing packages.

## Task 4: Build and verify a new artifact

**Files:** Global `output/` artifact and its new verification receipt.

- [ ] Construct into a new output filename; do not overwrite CN rollback material.
- [ ] Run filesystem checks and compare every regular-file hash and relevant inode metadata with the final manifest pair.
- [ ] Record the raw image's size/hash and, if generated, the compressed transfer artifact's size/hash.
- [ ] Run only the tests justified by the changed stages; record skipped device-dependent checks explicitly.

## Task 5: Controlled DSU test

**Files:** Private device preflight, install/readback and runtime test receipts.

- [ ] Verify the connected device, current OS, available space and current DSU state before selecting an install method.
- [ ] Prefer a separately named Global slot with fresh 32 GiB userdata; preserve CN's current slot/data. If the installed API cannot retain both safely, prepare and verify a CN rollback copy before any replacement.
- [ ] Transfer using a hash-verified HTTPS path and check the downloaded bytes before installation.
- [ ] Perform one controlled Global boot. Record logs and return to Infinity on failure; do not repeatedly cycle through a failed boot.
- [ ] Verify calls/SMS, actual signal levels, auto brightness, charging warning behavior, haptics and fingerprint enrollment/repeated unlock.
- [ ] Record AOD, face unlock, camera, eSIM management, game FPS and Google verdicts individually. These remain open unless their actual tests pass.
- [ ] Commit and publish the Global branch's source/receipts as FeniksD; do not advertise a release-ready ROM based only on a successful boot.
