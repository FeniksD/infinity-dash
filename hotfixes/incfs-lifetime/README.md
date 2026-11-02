# IncFS lifetime hotfix

Temporary Magisk overlay for the existing Infinity dash Android 17 build. The
permanent source change is `patches/0006-incfs-marker-lifetime.patch` and is
registered in `sources/platform-patches.json`.

The package contains only these templates and the rebuilt
`system/lib64/service.incremental.so`. It has no network access, property
spoofing, SELinux policy changes, private keys, or background service. Magisk's
post-fs-data stage checks the original library before mounting the replacement;
another base library disables this module. The check detects changes relative
to these recorded bytes; it is not protection against a privileged attacker
changing both the checker and its input.

Expected original SHA-256:
`03fdc0558874b1396558aa2a424d322895837bb8458b469d44a6a77c5d8b4df7`

Rebuilt library SHA-256:
`50dd2f5660ebe8a82c2c2ab99431961ad5b4f70c84f732ff7ef838034486b1cf`

The binary is built from the pinned framework source and existing build inputs,
changing only `IncrementalService.cpp`. Build output belongs in `dist/`, not
Git. See `validation/2026-11-02-incfs-hotfix.json` for the recorded validation.

Install the packaged ZIP using Magisk in the matching running Infinity system.
This package does not include a recovery installer. To disable it from recovery
or an authorized root shell, create
`/data/adb/modules/infinity_incfs_lifetime_fix/disable`, then reboot. Remove the
module after installing a ROM that includes the source fix.

Module layout and boot stage ordering follow the
[Magisk developer guide](https://topjohnwu.github.io/Magisk/guides.html).
