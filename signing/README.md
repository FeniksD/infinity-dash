# Release signing

The public certificates in `public/release-20261031-v1/` identify the owner's
release keys. Their private counterparts stay on the owner's PC, outside this
repository and outside the build VM. They must not be regenerated for ordinary
updates: retaining the same identities is required for Android update continuity.
The encrypted backup and its passphrase are stored separately. Back up both
securely; the public certificates in Git cannot recover lost private keys.

The signing scope includes APK roles, APEX container and payload keys, recovery
update certificates, and AVB. APEX containers and payloads use separate key pairs
even when their upstream filenames share a stem. Google/OEM presigned packages
retain their existing identities.

For each non-presigned APEX, pass both `--extra_apks=NAME=CONTAINER_KEY` and
`--extra_apex_payload_key=NAME=PAYLOAD_KEY.pem` to the pinned signer. Do not rely
on `--key_mapping` alone for APEX containers. Check the effective APK/APEX key
mapping before starting the signing pass.

The original 754decc build and rollback images are retained. The release process
exports target-files without redundant images, signs them locally with the
matching AOSP tools, regenerates images, and creates the Android-only OTA. Each
export has a file manifest and SHA-256 checksum pinned before download.

`release_driver.py` wraps the pinned AOSP signer for this Android 17 target.
After APK/APEX signing it regenerates fs-verity sidecars and the digest assets
inside the two BuildManifest APKs, including their v4 signatures. It retains the
signed staging tree for OTA generation and cleans only task-owned temporary
files. Run it through the matching hermetic AOSP Python tool environment.

Changing platform signing keys can require a clean installation. The release
artifact must pass APK/APEX, AVB, VINTF, payload and OTA signature verification
before installation. Signing with private release keys is not a guarantee of
Google Play certification or Device/Strong Integrity; those require separate
on-device verification.

This release also updates `pvmfw` because its embedded guest-verification key
must match the newly signed virtualization APEX and `vbmeta_system` descriptor.
The Android-only allowlist therefore contains 16 partitions. Preserve verified
raw backups of both actual pvmfw slots before installation; the original
build's pvmfw image is not a substitute for the phone's own rollback copy.

Before partial OTA generation, run `ota_input.py` on the disposable target-files
directory produced by AOSP `CopyTargetFilesDir`, with
`--partitions signing/android-partitions.json`. It makes that copy's metadata
owner-writable and removes only excluded image symlinks. The pinned AOSP writer
silently ignores permission errors on read-only metadata; `--partial` alone can
therefore leave the full firmware partition list in the payload. Check the exact
list again at payload generation and in the final payload manifest. Never use
this preparation helper on the original signed staging tree.
