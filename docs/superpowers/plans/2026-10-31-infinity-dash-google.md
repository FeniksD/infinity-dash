# Infinity X dash Google integration implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and validate an Android 17 GApps build with Gboard and the selected Google replacements, then install it using an agreed data-migration procedure.

**Architecture:** Enable the existing pinned Infinity GMS integration. Add the selected optional applications and the Google Dialer shared-library declaration in the device product. Preserve hardware and security configuration; reuse the guarded build and artifact verification workflow.

**Tech Stack:** Android product makefiles, Soong, existing Python preparation checks, AOSP artifact tools, ADB/fastboot.

**Spec:** `docs/superpowers/specs/2026-10-31-infinity-dash-google-design.md`

## Global Constraints

- Target `infinity_dash`, Android 17, `UNOFFICIAL`, current working `user` variant; maintain author identity FeniksD.
- Use pinned `vendor/pixel/gms` commit `4d2eb0026075de0f6f4a95bc5818dacdd1c0e852`; do not update unrelated source repositories.
- Keep MIUI Camera, Launcher3QuickStep, providers, IMS/eSIM, encryption, SELinux and existing kernel/vendor cohort.
- Do not install root, alter charging, change bootloader state or import private attestation keys.
- Preserve Vanilla artifacts and backups. A new wipe requires specific user approval; absence of ADB is not permission to skip checks.

## Review Focus

- Selected Google Phone requires `com.google.android.dialer.support` at package-install time.
- A user-facing replacement must not remove its system provider, permission service or IMS dependency.
- Google prebuilt APK/APEX signatures, uses-library dependencies and privileged allowlists must remain valid.
- Actual produced package selection and super usage must be checked; a successful product-variable change is insufficient.
- Vanilla-to-GApps migration and Google certification/Integrity must not be represented as automatically safe or successful.

---

### Task 1: Product configuration and reproducible patch

**Files:** Modify `device/xiaomi/dash/infinity_dash.mk` and `patches/0001-infinity-dash.patch`; update `README.md` after validation.

**Interface:** The product consumes the existing `WITH_GAPPS` integration and pinned GMS modules; the output is the complete selected Google product, reproducible by `tools/apply_device.py`.

- [ ] Change the product to `WITH_GAPPS := true`.
- [ ] Within its GApps block add `CalendarGooglePrebuilt`, `Photos`, `GoogleDialer`, `PrebuiltBugle` and `com.google.android.dialer.support`.
- [ ] Copy the existing GMS `com.google.android.dialer.support.xml` to `$(TARGET_COPY_OUT_PRODUCT)/etc/permissions/`.
- [ ] Regenerate the corresponding upstream patch without changing unrelated hunks.
- [ ] Run `python3 -B -m unittest discover -s tests` and `python3 -B tools/preflight.py`. Expected: existing preparation/patch round-trip suite and preflight pass. This is a configuration change; do not add tests that merely duplicate literal makefile text.
- [ ] Commit the configuration as FeniksD.

### Task 2: Native integration and source promotion

**Files:** Existing source inventory/baseline records; modify a pinned GMS `Android.bp` override only if native validation proves a missing uses-library declaration.

**Interface:** Consume Task 1's tested preparation bundle; produce a sealed source state and build invocation using that exact bundle.

- [ ] Save the current source inventory, preparation archive, root baseline and Vanilla output identity.
- [ ] Prepare the minimal source-change inventory locally and stage the new archive. Check hashes before controlled promotion.
- [ ] Apply only the approved source delta while the existing build is idle, re-seal source, update root/local anchors together, then verify both guards.
- [ ] Run the existing guarded build launcher with the current output/cache. Expected: a GApps `m bacon` build, with no disabled checks or unexpected source changes.
- [ ] If Soong reports a real missing `uses_libs` declaration for Google Phone, add that declaration through a pinned one-file GMS patch and repeat the normal validation/promotion process. Do not relax global checks.

### Task 3: Artifact and application validation

**Files:** New private GApps artifact/report directory; `README.md` validation summary.

**Interface:** Consume the successful native output; produce the exact installable image set, package inventory and verified hashes.

- [ ] Complete the existing whole-ZIP/payload, raw-image hash, AVB chain and VINTF checks using final packaged images.
- [ ] Inspect produced package inventory: required Google applications and providers present; overridden LatinIME/Jelly/Glimpse/Dialer/Messaging/DeskClock/ExactCalculator/Contacts absent as applicable; MIUI Camera and Launcher3QuickStep present.
- [ ] Verify the selected Google Phone APK's required shared library, its JAR and XML registration exist in the actual output. Verify privileged allowlists and APK signatures.
- [ ] Verify the actual dynamic image sizes fit the configured super group. Preserve the earlier Vanilla artifacts.
- [ ] Commit accurate source/validation documentation. Do not publish a release automatically.

### Task 4: Reviewed migration and device acceptance

**Files:** Private installation plan and handset acceptance report.

**Interface:** Consume Task 3's verified image set and a live handset connection; produce an installed, tested GApps system or a clear pending installation checkpoint.

- [ ] Inspect current user data and the supported migration procedure. Back up new data; obtain explicit approval if a new format is required. Until then do not write phone partitions.
- [ ] Use only the coherent selected Android image set and existing verified recovery/rollback checks; never flash the complete firmware-bearing OTA.
- [ ] After boot, have the user sign in to Google. Verify Play Store installation/update, Gboard, selected application roles, providers and basic camera/telephony/eSIM/lighting.
- [ ] Record Play certification and each observed Integrity verdict separately. Do not claim all checks passed from GApps installation alone.
