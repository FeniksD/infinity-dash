#!/usr/bin/env bash
# Run only inside the root launcher's private mount/network namespace.
set -euo pipefail
trusted=/srv/infinity/dsu/trusted
source_dir=/srv/infinity/android
guard_dir=/usr/local/lib/infinity-guard
[[ $EUID != 0 ]] || { echo 'Native compilation must not run as root'; exit 1; }
python3 -E -s -B "$guard_dir/source_lock.py" verify --source "$source_dir" --manifest "$trusted/source-inventory.jsonl" --jobs 2
python3 -E -s -B "$guard_dir/source_lock.py" output-check --source "$source_dir" --output /srv/infinity/dsu/out
python3 -E -s -B "$guard_dir/source_lock.py" log-check --source "$source_dir" --logs /srv/infinity/dsu/logs
cd "$source_dir"
export OUT_DIR=out GIT_OPTIONAL_LOCKS=0 REPO_TRACE=0 PYTHONDONTWRITEBYTECODE=1
export GIT_CONFIG_GLOBAL="$trusted/gitconfig"
export GOMAXPROCS=2 TMPDIR=/srv/infinity/dsu/out/tmp CCACHE_DIR=/srv/infinity/dsu/out/ccache CCACHE_DISABLE=1
set +e
(
    set -eo pipefail
    source build/envsetup.sh
    export USE_CCACHE=0 CCACHE_DISABLE=1
    lunch infinity_dash cp2a userdebug
    [[ $TARGET_PRODUCT == infinity_dash && $TARGET_RELEASE == cp2a && $TARGET_BUILD_VARIANT == userdebug ]]
    m gsid -j2
)
result=$?
set -e
python3 -E -s -B "$guard_dir/source_lock.py" verify --source "$source_dir" --manifest "$trusted/source-inventory.jsonl" --jobs 2
echo "DSU native source verification passed; build result: $result"
exit "$result"
