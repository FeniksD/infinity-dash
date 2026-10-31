# Persist the verified dash Integrity configuration

> Execution: implement inline in the existing gapps17 worktree. Do not rebuild or flash Android.

**Goal:** Preserve the configuration that passed Basic, Device, Strong and Play Store certification, with a fail-closed restore workflow.

**Spec:** User requested saving the working configuration in firmware sources and detecting unexpected future changes.

**Design:** Keep public PIF/game-property data and the approved keybox SHA-256 plus Google root fingerprints in the device tree. Ship those public JSON files in future builds. Keep attestation private keys outside Git. A host-side tool downloads/inspects the official Evo source, validates it with OpenSSL and Google's revocation data, and applies only an explicitly requested, approved configuration over ADB. It backs up the affected settings privately and restores them on a failed update. No automatic background refresh, no root or partition writes.

## Constraints

- Device: dash, model2602BPC18G; factory attestation product dash_ru is owner-device-specific, not a universal SKU assumption.
- Current approved keybox SHA256: 1e59118fbed898bb175a23bd1bc53e15f3e7e9f3282244ed61419fb41dbd4939.
- Current keybox expires 2026-11-06; do not present success as permanent certification.
- Public source: https://gitea.com/Evolution-X/keybox/raw/branch/main/keybox.xml.
- Reject oversized XML, DTD/entities, mismatched private/public keys, untrusted roots, invalid/expired chains and revoked certificates.
- Apply only to GMS, Vending and GSF; never clear GMS data or reboot/flash as part of restore.

## Tasks

- [x] Add failing tests for validation, pin mismatch and safe apply/rollback boundaries.
- [x] Add public device recipe, validator/restore tool and device copy rules; keep private XML excluded.
- [x] Regenerate and round-trip-check device patch; run unit tests and offline preflight.
- [x] Review changed code and update current verified result documentation; commit as FeniksD with this plan.

Validation: 128 unit tests; offline preflight; actual approved XML inspected against live Google revocations; 13 patched files round-tripped against pinned upstream. Review found one rollback-reporting issue, fixed with red/green CLI tests and re-reviewed. No rebuild, reflash or settings apply performed while saving this configuration.
