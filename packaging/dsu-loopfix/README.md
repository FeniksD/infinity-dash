# Experimental Magisk overlay for the verified dash phone

Only `system/bin/gsid` is overlaid. There are no boot scripts, property overrides, SELinux policy changes or partition-flashing commands. Installation is restricted to the verified Android37/arm64/dash system and exact original/payload checksums.

The binary is not stored in Git. Use the verified native artifact with SHA-256 `21e841019201fcc09250396eedb22ee9995452b8d1b629691a6fd1dcb85a4e80`; the currently checked original binary is `edea05157943a71191c744afe064cd7353b47ea3e8057964d3f9957cf091cc27`. These values are specific to this build and phone software version, not a universal compatibility claim.

The ZIP for installation through Magisk contains `module.prop`, `customize.sh`, `ROLLBACK.txt` and `system/bin/gsid`. Recovery installation is intentionally not supported. The installer aborts on wrong device/API/architecture, mismatched checksums or failed permissions/labeling.

Native compilation and symbol checks alone do not prove successful DSU installation or ColorOS boot. Complete the source postcheck and dynamic loader verification before proposing installation. A normal Android restart is required because DynamicSystemService retains its existing GSI-service reference after an install attempt. See `ROLLBACK.txt` for disabling the module, and remove it before a host ROM update.
