"""Retain dash identity for the vendor HWC's ALS frame-notification allowlist."""
import copy
import hashlib
import json
from pathlib import Path
from . import compat
from .build_image import validate_tree

HERE = Path(__file__).resolve().parent
TARGET = '/system/product/etc/build.prop'
BEFORE = b'ro.product.product.name=ossi\n'
AFTER = b'ro.product.product.name=dash_global\n'


def _load_manifest():
    return json.loads((HERE / 'sensor-product.json').read_text())


def _make_plan(tree, records, contents):
    tree = compat._canonical_host(tree, exists=True)
    validate_tree(tree, records, contents)
    spec = _load_manifest()
    if spec.get('schema_version') != 1 or spec.get('path') != TARGET:
        raise ValueError('unreviewed sensor product target')
    data, host = compat._read_regular(tree / TARGET[1:])
    if records.get(TARGET, {}).get('kind') != 'file' or contents.get(TARGET) != compat._identity(data):
        raise ValueError('sensor product source metadata/content mismatch')
    digest = hashlib.sha256(data).hexdigest()
    done = digest == spec['sha256'] and len(data) == spec['size']
    if done:
        if data.splitlines(keepends=True).count(AFTER) != 1 or BEFORE in data:
            raise ValueError('ambiguous installed sensor identity')
        result = data
    else:
        if digest != spec['source_sha256'] or len(data) != spec['source_size']:
            raise ValueError('unknown sensor product source')
        if (data.splitlines(keepends=True).count(BEFORE) != 1
                or sum(x.startswith(b'ro.product.product.name=') for x in data.splitlines()) != 1):
            raise ValueError('ambiguous sensor product line')
        result = data.replace(BEFORE, AFTER, 1)
        if hashlib.sha256(result).hexdigest() != spec['sha256'] or len(result) != spec['size']:
            raise ValueError('sensor product result hash differs')
    final_records, final_contents = copy.deepcopy(records), copy.deepcopy(contents)
    final_records[TARGET]['size'] = len(result)
    final_contents[TARGET] = compat._identity(result)
    writes = [] if done else [{'kind':'file','path':TARGET,'before':data,'data':result,'host':host}]
    report = {'status':'already_applied' if done else 'planned',
              'changes':[{'path':TARGET,'action':'unchanged' if done else 'replace',
                          'before':{'record':copy.deepcopy(records[TARGET]),'content':contents[TARGET]},
                          'after':{'record':copy.deepcopy(final_records[TARGET]),'content':final_contents[TARGET]}}],
              'writes':[{'path':TARGET,**compat._identity(result)}] if writes else [],
              'final_records':final_records,'final_content_manifest':final_contents}
    return tree, report, writes


def plan_sensor_product(tree, records, contents):
    return _make_plan(tree, records, contents)[1]


def apply_sensor_product(tree, records, contents, backup_dir):
    tree, report, writes = _make_plan(tree, records, contents)
    return compat.apply_change_plan(tree, records, contents, report, writes, backup_dir,
                                    report_name='sensor-product-report.json', operation='sensor product identity')
