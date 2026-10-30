# This module is installed through Magisk only; it changes no boot partitions.
[ "$BOOTMODE" = true ] || abort "Install from Magisk while Android is running."
[ "$ARCH" = arm64 ] || abort "This binary requires arm64."
[ "$API" = 37 ] || abort "This package is only for the verified Android 17 system."
[ "$(getprop ro.product.device)" = dash ] || abort "This package is only for dash."
original=$(sha256sum /system/bin/gsid | cut -d ' ' -f 1)
[ "$original" = edea05157943a71191c744afe064cd7353b47ea3e8057964d3f9957cf091cc27 ] || abort "The installed gsid differs from the version checked for this package."
payload=$(sha256sum "$MODPATH/system/bin/gsid" | cut -d ' ' -f 1)
[ "$payload" = 21e841019201fcc09250396eedb22ee9995452b8d1b629691a6fd1dcb85a4e80 ] || abort "Payload checksum mismatch."
set_perm "$MODPATH/system/bin/gsid" 0 2000 0755 u:object_r:gsid_exec:s0 || abort "Failed to set gsid permissions/SELinux context."
ui_print "Only /system/bin/gsid is overlaid by this module."
ui_print "Reboot the current Android system before trying DSU."
ui_print "Disable this module and reboot to restore the original gsid."
