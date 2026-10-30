#!/usr/bin/env bash
# Root performs mount/cgroup setup; the compiler runs as rombuild with no network.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Root launcher required'; exit 1; }
[[ $# == 0 ]] || { echo 'No arguments accepted'; exit 1; }
trusted=/srv/infinity/dsu/trusted
cd "$trusted"
sha256sum -c SHA256SUMS
(cd /srv/infinity && sha256sum -c /root/infinity-security/source-inventory.sha256)
python3 -I - <<'PY'
from pathlib import Path
import json,time
state=json.loads(Path('/var/lib/infinity-guard/status.json').read_text())
assert state['ok'] and abs(time.time()-state['time'])<180, 'Server guard must be healthy and recent'
assert not Path('/var/lib/infinity-guard/incident.json').exists(), 'Incident must be reviewed first'
PY
cgroup=/sys/fs/cgroup/infinity-dsu
mkdir "$cgroup"
trap 'rmdir "$cgroup" 2>/dev/null || true' EXIT
printf '200000 100000\n' > "$cgroup/cpu.max"
printf '%s\n' 19327352832 > "$cgroup/memory.high"
printf '%s\n' 25769803776 > "$cgroup/memory.max"
printf '%s\n' 4294967296 > "$cgroup/memory.swap.max"
printf '%s\n' 2048 > "$cgroup/pids.max"
printf '%s\n' 1 > "$cgroup/memory.oom.group"
attempt=$(date -u +%Y%m%dT%H%M%SZ)
set +e
unshare --mount --net --pid --fork --mount-proc --propagation private /bin/bash -s <<'NS'
set -euo pipefail
printf '%s\n' "$$" > /sys/fs/cgroup/infinity-dsu/cgroup.procs
mount --make-rprivate /
ip link set lo up
for directory in /srv/infinity/out /srv/infinity/logs /home/rombuild; do
    mount --bind "$directory" "$directory"
    mount -o remount,bind,ro "$directory"
done
mount -t tmpfs -o mode=1777,nosuid,nodev,size=1G tmpfs /tmp
mount -t tmpfs -o mode=1777,nosuid,nodev,size=512M tmpfs /var/tmp
mount --bind /srv/infinity/dsu/trusted/image_manager.cpp /srv/infinity/android/system/fs/fs_mgr/libfiemap/image_manager.cpp
mount -o remount,bind,ro /srv/infinity/android/system/fs/fs_mgr/libfiemap/image_manager.cpp
mount --bind /srv/infinity/dsu/out /srv/infinity/android/out
mount --bind /srv/infinity/dsu/logs /srv/infinity/android/.infinity-dash-logs
exec runuser -u rombuild -- env -i \
    HOME=/srv/infinity/dsu/out/.home USER=rombuild LOGNAME=rombuild \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 SHELL=/bin/bash \
    nice -n 10 ionice -c 2 -n 7 /bin/bash /srv/infinity/dsu/trusted/dsu-native-build.sh
NS
result=$?
set -e
printf '%s\n' "$result" > "/srv/infinity/dsu/build-${attempt}.exit"
echo "DSU native attempt $attempt finished: $result"
exit "$result"
