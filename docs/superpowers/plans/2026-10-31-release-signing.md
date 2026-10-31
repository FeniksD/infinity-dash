# Dash release signing implementation plan

> **For agentic workers:** Use `superpowers:executing-plans`. Keep private signing material on the owner's PC; no private keys in Git or on the build VM.

**Goal:** Produce a locally signed Android-only Infinity X package from the verified 754decc target-files, replacing public AOSP signing keys with persistent owner-controlled keys.

**Architecture:** Export verified target-files without redundant IMAGES plus the matching host tools from the VM. Sign APKs/APEX payloads and their containers locally, regenerate images and AVB, then create an Android-only OTA. The original 15-partition allowlist is extended only with `pvmfw`: its embedded key must match the newly signed virtualization APEX. Preserve Google/OEM presigned packages and other firmware. Verify before any installation. Passing Google Play Integrity remains an unproven outcome.

**Tech stack:** AOSP releasetools, OpenSSL, Python, existing sealed build outputs, local encrypted key storage.

**Spec:** User approved release-key signing after the platform certificate comparison in this conversation.

## Global constraints

- Existing build: `754decc022b25740754389324cc878d094c34721`; retain the frozen original and rollback images.
- Private keys remain on the owner's PC outside the repository; public certificates and mapping metadata may be versioned.
- Do not overwrite/recreate an existing key set. Persist it for future updates.
- Do not change LK, preloader, modem, NV, eSIM, or bootloader lock state.
- All packaging inputs must match a locally retained hash manifest.
- Use bounded local disk space; never remove personal backups to make room.
- Keep Google/OEM presigned identities unchanged; reject unclassified AOSP-test-signed presigned APKs.
- Do not claim Device/Strong or certification success before a live post-installation check.

## Review focus

- Shared UID packages and APKs inside APEX must receive consistent signing identities.
- APEX payload and container keys must both be replaced; presigned Google modules stay byte-identical.
- Recovery trust and payload/OTA signing must use the new public identities, not leftover public test keys.
- Migration from old platform keys can require a clean installation; do not silently erase user data.
- Export/extraction must preserve Android symlinks without dereferencing outside the target tree.

### Task 1: Validate and export signing inputs

- [x] Compare active guard, source baseline, frozen target metadata and images with existing records.
- [x] Inventory installed APK/APEX certificates and identify all local test-key roles.
- [x] Export target-files excluding redundant IMAGES, with a deterministic entry manifest.
- [x] Export only matching signing/OTA host tools and required shared libraries; validate local executable compatibility and space.

### Task 2: Establish owner-controlled signing identities

- [x] Create reusable local keys for APK roles, APEX payload/container roles and AVB/OTA as needed by the inventory.
- [x] Restrict directories/files to 0700/0600; create an encrypted local backup and verify that it decrypts correctly.
- [x] Store public certificate fingerprints and key mappings in the repo; guard against private-key publication.

### Task 3: Sign and package locally

- [x] Use AOSP signing tools to replace test-key APK/APEX signatures consistently.
- [x] Regenerate fs-verity metadata and signed BuildManifest digest lists after APK signing.
- [x] Regenerate images and AVB descriptors with matching local identities.
- [x] Generate a signed Android-only OTA with the original 15 partitions plus required `pvmfw`.
- [x] Back up both physical pvmfw slots before installation.
- [x] Keep input and output hash reports, signing log and public verification evidence.

### Task 4: Verify and prepare installation

- [x] Verify every produced APK/APEX signature and confirm presigned packages remain unchanged.
- [x] Check VINTF, AVB chains, payload signatures, whole-OTA signature and partition allowlist.
- [x] Preserve a verified current-ROM rollback and record migration requirements.
- [x] Only then carry out installation within the user's authorized scope, obtaining specific consent if a new data wipe is required.
- [x] Test live platform identity, Google certification and Basic/Device/Strong independently. Result: owner signature confirmed; Basic passes, Device/Strong and certification still fail.
