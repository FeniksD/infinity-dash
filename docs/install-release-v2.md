# Infinity X 4.1 / dash — release-v2 installation preview

This is an **UNOFFICIAL testing build** for POCO X8 Pro Max / Redmi Turbo 5 Max (`dash`). It has booted on the owner's `2602BPC18G`. Other regional variants and starting firmware versions have not yet been qualified. Do not use it on POCO X8 Pro or a different codename.

ROM: `Project_Infinity-X-4.1-dash-31.10.2026-GAPPS-UNOFFICIAL-RELEASE-v2.zip`

SHA-256: `2d51adbaaa53665c6c61f933872ef85de383d4f94eab56115da8f95ed6256e95`

The ZIP already contains Google apps and services. Do not install another GApps package. Root is optional and is not included. The installed release uses the owner's release signing keys; switching from another ROM or another signing identity requires a clean installation.

## Before installing

- Confirm the bootloader is genuinely unlocked. Do not relock it with this build installed. Spoofed Android lock-state properties are not evidence of an unlocked/locked bootloader.
- Back up personal files, app data and eSIM recovery details. **The clean installation below erases user data.** eSIM preservation is not guaranteed.
- Keep a verified rollback package and your own device backups. The OTA changes `pvmfw` to match the signed virtualization stack. On the tested phone both original pvmfw slots were backed up before installation; no universal rollback images are supplied.
- Use current Android platform-tools, a reliable USB connection and the matching bootstrap images from this release. Verify the downloaded hashes.

The tested ZIP contains only 16 approved partitions: boot, init_boot, vendor_boot, dtbo, vbmeta, vbmeta_system, vbmeta_vendor, system, system_ext, product, vendor, odm, system_dlkm, vendor_dlkm, odm_dlkm and pvmfw. It excludes LK, preloader, modem and NV partitions. Do not add separate low-level firmware flashes to these instructions.

## Clean installation

Extract the companion installation kit on the PC. Keep the ROM ZIP intact. From Android, enter bootloader mode:

```sh
adb reboot bootloader
fastboot getvar product
```

The product must be `dash`. The following commands replace the current slot's boot environment, including the recovery supplied by this release:

```sh
fastboot flash dtbo images/dtbo.img
fastboot flash init_boot images/init_boot.img
fastboot flash vendor_boot images/vendor_boot.img
fastboot flash boot images/boot.img
fastboot reboot recovery
```

In recovery select **Factory reset → Format data/factory reset → Format data**. Then select **Apply update → Apply from ADB** and run:

```sh
adb sideload Project_Infinity-X-4.1-dash-31.10.2026-GAPPS-UNOFFICIAL-RELEASE-v2.zip
```

Wait for recovery to report a successful installation, then reboot to system. The host percentage alone is not the success criterion. If recovery reports a signature, partition, version or post-install error, stop and preserve its log instead of attempting extra flashes.

This bootstrap-plus-sideload sequence was used on the owner's phone. A one-ZIP first installation from every third-party recovery is **not** validated. Dirty updates from this release and retention of a separate OrangeFox build are also not yet qualified.

## After boot

Complete setup and test calls, mobile data, Wi-Fi, Bluetooth, camera, biometrics, NFC, charging, sleep and recovery. Report the starting firmware, build filename, reproduction steps and a redacted log; remove serial numbers, IMEI, account data and tokens before sharing.

The owner obtained Basic, Device and Strong Integrity plus Play Store certification **after separate runtime configuration**. That configuration is not pre-applied in this ZIP, is owner-SKU-specific, and uses an expiring/revocable certificate. Do not advertise permanent Strong Integrity. See `docs/integrity.md` in the source repository.

## Optional root

Use the official Magisk app and patch this release's original `init_boot.img` on the **same phone** where it will be installed. See the [official installation guide](https://topjohnwu.github.io/Magisk/install.html). Do not distribute or flash another person's patched image.

Save the original matching image for rollback. Root may change app compatibility and Integrity results; validate them again after installation. The base ROM remains unrooted.

## Credits

ROM base: Project Infinity X. Device integration and hardware support: xiaomi-mt6991 and original contributors. Infinity adaptation, release signing and validation: FeniksD. Original authorship is retained.
