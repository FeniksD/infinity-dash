#!/usr/bin/env bash
# Only the namespace setup runs as root; all build steps run as UID1000.
set -euo pipefail
if [[ $EUID != 0 ]]; then
    echo "Use the root launcher to create the isolated network namespace"
    exit 1
fi
cd /srv/infinity
sha256sum -c /root/infinity-security/source-inventory.sha256
python3 -I - <<'PY'
import json, time
with open('/var/lib/infinity-guard/status.json') as f:
    state = json.load(f)
if not state.get('ok') or abs(time.time()-state.get('time',0)) > 180:
    raise SystemExit('Security guard is not healthy/recent; build refused')
PY
attempt="$(date -u +%Y%m%dT%H%M%SZ)"
status_file="/srv/infinity/verified-sources/build-${attempt}.exit"
set +e
unshare --net /bin/bash -c '
    set -e
    ip link set lo up
    exec runuser -u rombuild -- env BUILD_JOBS=8 GIT_OPTIONAL_LOCKS=0 PYTHONDONTWRITEBYTECODE=1 \
        bash /usr/local/lib/infinity-guard/build_guarded.sh \
        /srv/infinity/android /srv/infinity/verified-sources/source-inventory-initial.jsonl \
        /srv/infinity/out /srv/infinity/logs
'
status=$?
set -e
printf '%s\n' "$status" > "$status_file"
printf 'Build attempt %s exited %s\n' "$attempt" "$status"
exit "$status"
