"""Pinned Standoff refresh profile; preserve user-selected 60/90 Hz modes."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

TARGET = '/my_product/etc/refresh_rate_config.xml'
PACKAGE = 'com.axlebolt.standoff2'
ADDITION = (b'  <item package="com.axlebolt.standoff2" rateId="3-1-2-3" '
            b'disableViewOverride="true" /> <!-- Standoff 2: dash high refresh profile -->\r\n')
ANCHOR = b'  <item package="com.tencent.ig"'


def _load_manifest():
    return json.loads(Path(__file__).with_name('game-refresh.json').read_text())


def transform(data):
    spec = _load_manifest()
    if spec.get('schema_version') != 1 or spec.get('path') != TARGET:
        raise ValueError('unreviewed game refresh target')
    digest = hashlib.sha256(data).hexdigest()
    done = digest == spec['sha256'] and len(data) == spec['size']
    if done:
        result = data
    else:
        if digest != spec['source_sha256'] or len(data) != spec['source_size']:
            raise ValueError('unknown game refresh source')
        if data.count(ANCHOR) != 1 or PACKAGE.encode() in data:
            raise ValueError('ambiguous game refresh profile')
        result = data.replace(ANCHOR, ADDITION + ANCHOR, 1)
    if hashlib.sha256(result).hexdigest() != spec['sha256'] or len(result) != spec['size']:
        raise ValueError('game refresh result differs from pinned bytes')
    items = ET.fromstring(result).findall(f"item[@package='{PACKAGE}']")
    if len(items) != 1 or items[0].attrib != {
            'package': PACKAGE, 'rateId': '3-1-2-3', 'disableViewOverride': 'true'}:
        raise ValueError('invalid game refresh profile')
    if (result.count(ADDITION) != 1 or
            hashlib.sha256(result.replace(ADDITION, b'', 1)).hexdigest() != spec['source_sha256']):
        raise ValueError('game refresh modified unrelated source bytes')
    return result, done
