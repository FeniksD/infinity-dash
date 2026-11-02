BASE_SHA=03fdc0558874b1396558aa2a424d322895837bb8458b469d44a6a77c5d8b4df7
FIXED_SHA=50dd2f5660ebe8a82c2c2ab99431961ad5b4f70c84f732ff7ef838034486b1cf
[ "$BOOTMODE" = true ] || abort "Install from the running, rooted Infinity system."
[ "$ARCH" = arm64 ] && [ "$API" = 37 ] || abort "This hotfix requires arm64 Android 17."
[ "$(getprop ro.product.device)" = dash ] || abort "This hotfix is only for dash."
CURRENT=$(sha256sum /system/lib64/service.incremental.so)
CURRENT=${CURRENT%% *}
case "$CURRENT" in
  "$BASE_SHA"|"$FIXED_SHA") ;;
  *) abort "Base library differs; rebuild the source fix for this ROM." ;;
esac
PAYLOAD=$(sha256sum "$MODPATH/system/lib64/service.incremental.so")
[ "${PAYLOAD%% *}" = "$FIXED_SHA" ] || abort "Hotfix payload checksum mismatch."
set_perm "$MODPATH/system/lib64/service.incremental.so" 0 0 0644 u:object_r:system_lib_file:s0
set_perm "$MODPATH/post-fs-data.sh" 0 0 0755
ui_print "Verified IncFS lifetime fix for this Infinity build."
