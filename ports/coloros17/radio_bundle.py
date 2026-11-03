"""Journal a pinned optional-radio registration fix without changing radio policy."""
import copy
import hashlib
import json
from pathlib import Path
from . import compat
from .build_image import validate_tree

HERE = Path(__file__).resolve().parent
TARGET = '/system/system_ext/framework/oplus-telephony-common.jar'


def _load_manifest():
    return json.loads((HERE / 'radio-registration.json').read_text())


def _make_plan(tree, records, contents, artifact_dir):
    tree = compat._canonical_host(tree, exists=True)
    artifacts = compat._canonical_host(artifact_dir, exists=True)
    if artifacts == tree or tree in artifacts.parents:
        raise ValueError('radio artifact must be outside the canonical tree')
    validate_tree(tree, records, contents)
    spec = _load_manifest()
    if (spec.get('schema_version') != 1 or spec.get('path') != TARGET
            or spec.get('file') != 'oplus-telephony-common.jar'):
        raise ValueError('unreviewed radio artifact target')
    current, host = compat._read_regular(tree / TARGET[1:])
    record = records.get(TARGET, {})
    if (record.get('kind') != 'file' or record.get('uid') != 0 or record.get('gid') != 0
            or record.get('mode') != 0o100644 or contents.get(TARGET) != compat._identity(current)):
        raise ValueError('radio input metadata or content changed')
    data, _ = compat._read_regular(artifacts / spec['file'])
    identity = compat._identity(data)
    if identity['sha256'] != spec['sha256'] or len(data) != spec['size']:
        raise ValueError('radio artifact hash/size differs')
    before_sha = hashlib.sha256(current).hexdigest()
    if before_sha not in {spec['source_sha256'], spec['sha256']}:
        raise ValueError('unknown radio input bytes')
    done = current == data
    final_records, final_contents = copy.deepcopy(records), copy.deepcopy(contents)
    final_records[TARGET]['size'] = len(data)
    final_contents[TARGET] = identity
    writes = [] if done else [{'kind': 'file', 'path': TARGET, 'before': current, 'data': data, 'host': host}]
    report = {'status': 'already_applied' if done else 'planned',
              'changes': [{'path': TARGET, 'action': 'unchanged' if done else 'replace',
                           'before': {'record': copy.deepcopy(record), 'content': copy.deepcopy(contents[TARGET])},
                           'after': {'record': copy.deepcopy(final_records[TARGET]), 'content': identity}}],
              'writes': [{'path': w['path'], **identity} for w in writes],
              'final_records': final_records, 'final_content_manifest': final_contents}
    return tree, report, writes


def plan_radio_bundle(tree, records, contents, artifact_dir):
    return _make_plan(tree, records, contents, artifact_dir)[1]


def apply_radio_bundle(tree, records, contents, artifact_dir, backup_dir):
    tree, report, writes = _make_plan(tree, records, contents, artifact_dir)
    return compat.apply_change_plan(tree, records, contents, report, writes, backup_dir,
                                    report_name='radio-registration-report.json', operation='radio registration')
