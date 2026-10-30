#!/usr/bin/env bash
set -eo pipefail
if [[ $# != 1 || "$1" == "--help" ]]; then
    echo "Usage: bash scripts/build-server.sh /path/to/prepared/android"
    echo "Builds only. Does not install or flash a phone. BUILD_JOBS defaults to 8."
    [[ "${1:-}" == "--help" ]] && exit 0
    exit 2
fi
bundle_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source_dir="$(cd -- "$1" && pwd -P)"
python3 "$bundle_dir/tools/preflight.py" --source-root "$source_dir"
[[ -f "$source_dir/build/envsetup.sh" ]] || { echo "Missing Android build environment"; exit 1; }
mkdir -p "$source_dir/.infinity-dash-logs"
cd -- "$source_dir"
source build/envsetup.sh
lunch infinity_dash-cp2a-userdebug
log_file="$source_dir/.infinity-dash-logs/build-$(date -u +%Y%m%dT%H%M%SZ).log"
m bacon "-j${BUILD_JOBS:-8}" 2>&1 | tee "$log_file"
echo "Build command completed. See out/target/product/dash/ and $log_file"
