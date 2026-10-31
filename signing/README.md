# Release signing

The public certificates in `public/release-20261031-v1/` identify the owner's
release keys. Their private counterparts stay on the owner's PC, outside this
repository and outside the build VM. They must not be regenerated for ordinary
updates: retaining the same identities is required for Android update continuity.

The signing scope includes APK roles, APEX container and payload keys, recovery
update certificates, and AVB. APEX containers and payloads use separate key pairs
even when their upstream filenames share a stem. Google/OEM presigned packages
retain their existing identities.

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
