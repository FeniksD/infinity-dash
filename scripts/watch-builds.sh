#!/usr/bin/env bash
# Read-only live view. Uses a separate tmux server from the actual build jobs.
set -euo pipefail
case "${1:-}" in
    --help)
        echo 'Usage: scripts/watch-builds.sh [--setup-only]'
        echo 'Top: Infinity X. Bottom: gsid. Ctrl+b then d detaches the viewer.'
        exit 0 ;;
    --setup-only) setup_only=1 ;;
    '') setup_only=0 ;;
    *) echo 'Unknown argument' >&2; exit 2 ;;
esac
host=root@94.237.81.2
options=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o ForwardAgent=no -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)
ssh -T "${options[@]}" "$host" python3 - <<'PY'
import shlex
import subprocess

base = ['tmux', '-L', 'infinity-view']
session = 'live-build-logs'

def run(*args, capture=False):
    return subprocess.run(base + list(args), check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout

if subprocess.run(base + ['has-session', '-t', session],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
    first = run('new-session', '-d', '-s', session, '-n', 'logs', '-x', '180', '-y', '46',
                '-P', '-F', '#{pane_id}',
                'exec tail -n 18 -F /var/log/infinity/build-launch.log', capture=True).strip()
    second = run('split-window', '-v', '-p', '50', '-t', first, '-P', '-F', '#{pane_id}',
                 'exec tail -n 18 -F /var/log/infinity/dsu-build.log', capture=True).strip()
    run('select-pane', '-t', first, '-T', 'INFINITY X — full ROM')
    run('select-pane', '-t', second, '-T', 'GSID — standalone build')
    run('select-pane', '-t', first)
run('set-option', '-g', 'mouse', 'on')
run('set-option', '-g', 'prefix', 'C-b')
run('bind-key', '-T', 'prefix', 'd', 'detach-client')
run('set-option', '-g', 'history-limit', '20000')
run('set-option', '-g', 'status-interval', '5')
run('set-option', '-g', 'status-left-length', '24')
run('set-option', '-g', 'status-left', ' BUILD LOGS | ')
run('set-option', '-g', 'status-right-length', '95')
guard = ('import json,time; s=json.load(open("/var/lib/infinity-guard/status.json")); '
         'print("SERVER GUARD: OK" if s.get("ok") and abs(time.time()-s.get("time",0))<180 '
         'else "SERVER GUARD: CHECK!")')
run('set-option', '-g', 'status-right',
    '#(python3 -c ' + shlex.quote(guard) + ') | Ctrl+b d: detach | %H:%M:%S')
run('set-window-option', '-t', session, 'pane-border-status', 'top')
run('set-window-option', '-t', session, 'pane-border-format', ' #{pane_title} ')
run('set-window-option', '-t', session, 'remain-on-exit', 'on')
PY
if [[ $setup_only == 1 ]]; then
    exit 0
fi
exec ssh -tt "${options[@]}" "$host" 'exec env TERM=xterm-256color tmux -L infinity-view attach-session -f read-only -t live-build-logs'
