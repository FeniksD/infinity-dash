"""Privileged lifecycle hooks for one temporary, source-restricted transfer.

Run prepare first. systemd must arm cleanup with ExecStopPost=+ before invoking
activate via ExecStartPre=+. The original guard baseline is never modified.
"""
import argparse
import hashlib
import importlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys

BASE = Path('/run/infinity-coloros-transfer')
STATE = BASE / 'lifecycle-state.json'
BASELINE = Path('/root/infinity-security/baseline.json')
GUARD_STATE = Path('/var/lib/infinity-guard')
UFW4 = Path('/etc/ufw/user.rules')
UFW6 = Path('/etc/ufw/user6.rules')
DROPIN = Path('/run/systemd/system/infinity-guard.service.d/coloros-transfer.conf')
TEMP_BASELINE = BASE / 'guard-baseline.json'
DROPIN_TEXT = ('[Service]\nExecStart=\nExecStart=/usr/bin/python3 -B '
               '/usr/local/lib/infinity-guard/guard.py --baseline '
               + str(TEMP_BASELINE) + ' --state-dir /var/lib/infinity-guard\n')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def expected_record(data, mode=0o600):
    return {'sha256': digest(data), 'mode': mode, 'uid': 0, 'kind': 'file', 'link': None}


def rendered_rules(output):
    return output[:output.index('COMMIT\n') + len('COMMIT\n')]


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=60).stdout


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def rule_block(ip, comment):
    ip = str(ipaddress.IPv4Address(ip))
    if not re.fullmatch(r'infinity-coloros-[0-9a-f]{4,32}', comment):
        raise ValueError('Invalid unique comment')
    return (f'### tuple ### allow tcp 9443 0.0.0.0/0 any {ip} in comment={comment.encode().hex()}\n'
            f'-A ufw-user-input -p tcp --dport 9443 -s {ip} -j ACCEPT\n\n')


def planned_rules(before, block):
    if before.count('### END RULES ###') != 1 or re.search(r'\b9443\b', before):
        raise ValueError('Transfer port already mentioned or unknown UFW format')
    return before.replace('### END RULES ###', block + '### END RULES ###')


def remove_owned_rule(current, block):
    if current.count(block) != 1:
        raise ValueError('Owned rule is absent, modified, or duplicated')
    return current.replace(block, '', 1)


def remove_owned_file(path, expected):
    if not path.exists():
        return False
    if path.is_symlink() or path.read_text() != expected:
        raise ValueError('Runtime guard override changed; preserved for inspection')
    path.unlink()
    return True


def guard_module():
    sys.path.insert(0, '/usr/local/lib/infinity-guard')
    return importlib.import_module('guard')


def rule_args(state):
    return ['allow', 'from', state['ip'], 'to', 'any', 'port', '9443',
            'proto', 'tcp', 'comment', state['comment']]


def prepare():
    import secrets
    if STATE.exists() or DROPIN.exists():
        raise ValueError('Transfer lifecycle already prepared or override exists')
    guard = guard_module()
    if guard.check(BASELINE, GUARD_STATE) != 0:
        raise ValueError('Existing guard is not healthy')
    original = BASELINE.read_bytes()
    state = {'baseline_sha256': digest(original), 'before4': UFW4.read_text(),
             'before6': UFW6.read_text(), 'dropin': DROPIN_TEXT,
             'ip': json.loads((BASE / 'phone-egress.json').read_text())['ip'],
             'comment': 'infinity-coloros-' + secrets.token_hex(8)}
    if not ipaddress.IPv4Address(state['ip']).is_global:
        raise ValueError('Expected public phone IPv4')
    state['block'] = rule_block(state['ip'], state['comment'])
    state['after4'] = planned_rules(state['before4'], state['block'])
    preview = run('ufw', '--dry-run', *rule_args(state))
    if rendered_rules(preview) != state['after4']:
        raise ValueError('Installed UFW renderer differs from exact planned delta')
    if (digest(BASELINE.read_bytes()) != state['baseline_sha256'] or
            UFW4.read_text() != state['before4'] or UFW6.read_text() != state['before6']):
        raise ValueError('Protected state changed during preparation')
    state['original_baseline'] = json.loads(original)
    state['inputs'] = {str(path): guard.file_record(path) for path in
                       [BASE / 'server.py', BASE / 'lifecycle.py',
                        Path('/run/systemd/system/infinity-coloros-transfer.service'),
                        BASE / 'private/token', BASE / 'private/key.pem', BASE / 'private/cert.pem']}
    write_json(STATE, state)
    print('Transfer lifecycle prepared; no firewall or guard changes made.', flush=True)


def activate():
    state_bytes = STATE.read_bytes()
    state = json.loads(state_bytes)
    guard = guard_module()
    if guard.file_record(STATE) != expected_record(state_bytes) or guard.changed_files(state['inputs']):
        raise ValueError('Prepared controls changed')
    if guard.check(BASELINE, GUARD_STATE) != 0:
        raise ValueError('Existing guard is not healthy')
    run('systemctl', 'stop', 'infinity-guard.timer', 'infinity-guard.service')
    if (digest(BASELINE.read_bytes()) != state['baseline_sha256'] or
            UFW4.read_text() != state['before4'] or UFW6.read_text() != state['before6']):
        raise ValueError('Protected state changed before activation')
    run('ufw', *rule_args(state))
    if UFW4.read_text() != state['after4'] or UFW6.read_text() != state['before6']:
        raise ValueError('Unexpected firewall delta; cleanup will preserve unrelated edits')
    if digest(BASELINE.read_bytes()) != state['baseline_sha256']:
        raise ValueError('Original baseline changed concurrently')
    temporary = state['original_baseline']
    errors = guard.changed_files(temporary['files'])
    if errors != ['protected file changed: /etc/ufw/user.rules']:
        raise ValueError(f'Unexpected protected changes: {errors}')
    if guard.changed_trees(temporary.get('trees', {})):
        raise ValueError('Protected directory membership changed')
    DROPIN.parent.mkdir(parents=True, exist_ok=True)
    with DROPIN.open('x') as stream:
        stream.write(state['dropin'])
    DROPIN.chmod(0o644)
    temporary['files'][str(UFW4)] = dict(temporary['files'][str(UFW4)],
                                        sha256=digest(state['after4'].encode()))
    temporary['files'].update(state['inputs'])
    temporary['files'][str(STATE)] = expected_record(state_bytes)
    temporary['files'][str(DROPIN)] = expected_record(state['dropin'].encode(), 0o644)
    temporary['listeners'] = sorted(set(temporary['listeners']) | {'tcp 0.0.0.0 9443'})
    temporary['services'] = sorted(set(temporary['services']) | {'infinity-coloros-transfer.service'})
    write_json(TEMP_BASELINE, temporary)
    run('systemctl', 'daemon-reload')
    if guard.check(TEMP_BASELINE, GUARD_STATE) != 0:
        raise ValueError('Scoped guard rejected activation')
    run('systemctl', 'start', 'infinity-guard.timer')
    print('Scoped guard and source-restricted firewall activated.', flush=True)


def cleanup():
    errors = []

    def attempt(fn):
        try:
            return fn()
        except Exception as exc:
            errors.append(type(exc).__name__ + ': ' + str(exc))

    state = attempt(lambda: json.loads(STATE.read_text()))
    attempt(lambda: run('systemctl', 'stop', 'infinity-guard.timer', 'infinity-guard.service'))

    def remove_rule():
        current = UFW4.read_text()
        if current == state['before4']:
            return
        expected = remove_owned_rule(current, state['block'])
        # An identical matching tuple with a different comment must not be deleted.
        tuple_start = state['block'].split(' comment=')[0]
        if current.count(tuple_start) != 1:
            raise ValueError('Matching firewall tuple is ambiguous')
        preview = run('ufw', '--dry-run', '--force', 'delete', *rule_args(state))
        if rendered_rules(preview) != expected:
            raise ValueError('UFW deletion would change unrelated content')
        if UFW4.read_text() != current:
            raise ValueError('Firewall changed before cleanup')
        run('ufw', '--force', 'delete', *rule_args(state))
        if UFW4.read_text() != expected:
            raise ValueError('Unexpected firewall deletion delta')

    if state is not None:
        attempt(remove_rule)
    else:
        errors.append('Firewall cleanup requires the missing prepared state')
    attempt(lambda: remove_owned_file(DROPIN, DROPIN_TEXT))
    attempt(lambda: run('systemctl', 'daemon-reload'))
    if not DROPIN.exists():
        attempt(lambda: run('/usr/bin/python3', '-B', '/usr/local/lib/infinity-guard/guard.py',
                            '--baseline', str(BASELINE), '--state-dir', str(GUARD_STATE)))
        attempt(lambda: run('systemctl', 'start', 'infinity-guard.timer'))
    else:
        errors.append('Runtime override remains; original timer not resumed')
    if state is not None:
        def remove_private(path):
            if path.exists():
                record = state['inputs'][str(path)]
                if guard_module().file_record(path) != record:
                    raise ValueError('Private input changed; preserving ' + path.name)
                path.unlink()
        for name in ['token', 'key.pem', 'cert.pem']:
            attempt(lambda name=name: remove_private(BASE / 'private' / name))
    result = {'cleanup_complete': not errors, 'errors': errors,
              'original_baseline_unchanged': state is not None and digest(BASELINE.read_bytes()) == state['baseline_sha256'],
              'owned_firewall_rule_remaining': state is None or state['block'] in UFW4.read_text(),
              'runtime_override_remaining': DROPIN.exists()}
    write_json(Path('/srv/infinity/coloros17/control/transfer-cleanup.json'), result)
    print(json.dumps(result), flush=True)
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'activate', 'cleanup'])
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Lifecycle hooks require root')
    if args.action == 'prepare':
        prepare()
    elif args.action == 'activate':
        activate()
    else:
        return cleanup()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
