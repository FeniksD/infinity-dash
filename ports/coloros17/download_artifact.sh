#!/system/bin/sh
# Run through authorized root to bind this download to Wi-Fi, independently of VPN.
set -u
umask 077
# Android mksh's builtin test overflows on ordinary multi-GiB image sizes.
size_test() {
    if [ -x /system/bin/toybox ]; then
        /system/bin/toybox test "$@"
    else
        /usr/bin/test "$@"
    fi
}
[ "$#" -eq 4 ] || exit 64
config=$1
target=$2
expected_size=$3
expected_sha=$4
partial=$target.part
case "$expected_size" in ''|*[!0-9]*) exit 64;; esac
size_test "$expected_size" -gt 0 || exit 64
[ "${#expected_sha}" -eq 64 ] || exit 64
case "$expected_sha" in *[!0-9a-f]*) exit 64;; esac
[ -r "$config" ] || exit 66
[ ! -L "$target" ] && [ ! -L "$partial" ] || exit 73
[ ! -e "$target" ] || exit 73
directory=$(dirname "$target")
[ ! -L "$directory" ] || exit 73
mkdir -p "$directory" || exit 73
[ "$(stat -c %u "$directory")" = "$(id -u)" ] || exit 73
[ "$(stat -c %a "$directory")" = 700 ] || exit 73
attempt=1
code=1
while [ "$attempt" -le 12 ]; do
    have=0
    [ ! -L "$partial" ] || exit 73
    if [ -e "$partial" ]; then
        [ -f "$partial" ] && [ "$(stat -c %h "$partial")" = 1 ] || exit 73
        have=$(stat -c %s "$partial") || exit 74
    fi
    size_test "$have" -le "$expected_size" || exit 65
    if size_test "$have" -eq "$expected_size"; then
        code=0
        break
    fi
    printf 'DOWNLOAD_ATTEMPT=%s RESUME_BYTES=%s\n' "$attempt" "$have"
    curl --config "$config" --interface if!wlan0 --continue-at - \
        --output "$partial" --max-time 900 --speed-time 30 --speed-limit 1024 \
        --write-out 'download_bytes=%{size_download} speed_bytes_per_second=%{speed_download} seconds=%{time_total}\n'
    code=$?
    [ "$code" -ne 0 ] || break
    case "$code" in
        7|18|28|35|52|55|56) :;;
        *) exit "$code";; # Includes authentication failure and TLS pin mismatch.
    esac
    attempt=$((attempt + 1))
    [ "$attempt" -gt 12 ] || sleep 5
done
[ "$code" -eq 0 ] || exit "$code"
size_test "$(stat -c %s "$partial")" -eq "$expected_size" || exit 65
actual=$(sha256sum "$partial") || exit 74
actual=${actual%% *}
[ "$actual" = "$expected_sha" ] || exit 65
mv -n "$partial" "$target" || exit 73
[ ! -e "$partial" ] || exit 73
sync || exit 74
printf 'TRANSFER_VERIFIED\n'
