# Dash release signing implementation plan

> **For agentic workers:** Use `superpowers:executing-plans`. Keep private signing material on the owner's PC; no private keys in Git or on the build VM.

**Goal:** Produce a locally signed Android-only Infinity X package from the verified 754decc target-files, replacing public AOSP signing keys with persistent owner-controlled keys.

**Architecture:** Export verified target-files without redundant IMAGES plus the matching host tools from the VM. Sign APKs/APEX payloads and their containers locally, regenerate images and AVB, then create the existing 15-partition Android-only OTA. Preserve Google/OEM presigned packages and firmware. Verify before any installation. Passing Google Play Integrity remains an unproven outcome.

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

- [ ] Compare active guard, source baseline, frozen target metadata and images with existing records.
- [ ] Inventory installed APK/APEX certificates and identify all local test-key roles.
- [ ] Export target-files excluding redundant IMAGES, with a deterministic entry manifest.
- [ ] Export only matching signing/OTA host tools and required shared libraries; validate local executable compatibility and space.

### Task 2: Establish owner-controlled signing identities

- [ ] Create reusable local keys for APK roles, APEX payload/container roles and AVB/OTA as needed by the inventory.
- [ ] Restrict directories/files to 0700/0600; create an encrypted local backup and verify that it decrypts correctly.
- [ ] Store public certificate fingerprints and key mappings in the repo; guard against private-key publication.

### Task 3: Sign and package locally

- [ ] Use AOSP signing tools to replace test-key APK/APEX signatures consistently.
- [ ] Regenerate fs-verity metadata and signed BuildManifest digest lists after APK signing.
- [ ] Regenerate images and AVB descriptors with matching local identities.
- [ ] Generate a signed Android-only OTA with exactly the previously approved 15 partitions.
- [ ] Keep input and output hash reports, signing log and public verification evidence.

### Task 4: Verify and prepare installation

- [ ] Verify every produced APK/APEX signature and confirm presigned packages remain unchanged.
- [ ] Check VINTF, AVB chains, payload signatures, whole-OTA signature and partition allowlist.
- [ ] Preserve a verified current-ROM rollback and record migration requirements.
- [ ] Only then carry out installation within the user's authorized scope, obtaining specific consent if a new data wipe is required.
- [ ] Test live platform identity, Google certification and Basic/Device/Strong independently.
