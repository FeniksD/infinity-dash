#!/system/bin/sh
# Magisk invokes this before mounting module contents. Never overlay another ROM.
MODDIR=${0%/*}
BASE_SHA=03fdc0558874b1396558aa2a424d322895837bb8458b469d44a6a77c5d8b4df7
FIXED_SHA=50dd2f5660ebe8a82c2c2ab99431961ad5b4f70c84f732ff7ef838034486b1cf
CURRENT=$(sha256sum /system/lib64/service.incremental.so 2>/dev/null)
PAYLOAD=$(sha256sum "$MODDIR/system/lib64/service.incremental.so" 2>/dev/null)
if [ "$(getprop ro.product.device)" != dash ] ||
   [ "$(getprop ro.build.version.sdk)" != 37 ] ||
   [ "${CURRENT%% *}" != "$BASE_SHA" ] ||
   [ "${PAYLOAD%% *}" != "$FIXED_SHA" ]; then
    touch "$MODDIR/skip_mount" "$MODDIR/disable"
    printf '%s\n' 'Disabled: device, base library or hotfix checksum differs.' > "$MODDIR/disabled-reason.txt"
fi
