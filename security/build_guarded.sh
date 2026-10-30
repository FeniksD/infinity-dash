#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 4 ]]; then
    echo "Usage: build_guarded.sh SOURCE MANIFEST OUTPUT LOGS"
    exit 2
fi
guard_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source_dir="$(realpath -e -- "$1")"
manifest="$(realpath -e -- "$2")"
output_dir="$(realpath -m -- "$3")"
logs_dir="$(realpath -m -- "$4")"
for path in "$manifest" "$output_dir" "$logs_dir"; do
    if [[ "$path" == "$source_dir" || "$path" == "$source_dir/"* ]]; then
        echo "Manifest, output and logs must be outside the source tree"
        exit 1
    fi
done
python3 -E -s -B "$guard_dir/source_lock.py" verify --source "$source_dir" --manifest "$manifest"
python3 -E -s -B "$guard_dir/source_lock.py" log-check --source "$source_dir" --logs "$logs_dir"
python3 -E -s -B "$guard_dir/source_lock.py" output-check --source "$source_dir" --output "$output_dir"
if [[ $EUID == 0 ]]; then
    echo "Compilation must run as the unprivileged build user"
    exit 1
fi
mkdir -p -- "$output_dir" "$logs_dir"
# Both Siso and Soong expect an in-workspace output path. The verified bind
# mount keeps this logical path on the physically separate output directory.
export OUT_DIR=out GIT_OPTIONAL_LOCKS=0 PYTHONDONTWRITEBYTECODE=1
set +e
bash /srv/infinity/infinity-dash-prep/scripts/build-server.sh "$source_dir"
build_status=$?
set -e
python3 -E -s -B "$guard_dir/source_lock.py" verify --source "$source_dir" --manifest "$manifest"
echo "Source verification after compilation passed; build exit status: $build_status"
exit "$build_status"
