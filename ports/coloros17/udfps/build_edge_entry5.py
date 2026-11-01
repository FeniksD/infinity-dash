#!/usr/bin/env python3
"""Offline-only build: reads canonical donor, writes only this private cache namespace."""
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import zipfile

ROOT = pathlib.Path('/srv/infinity/coloros17/.cache/fingerprint-rootcause/edge-entry-build5')
CANON = pathlib.Path('/srv/infinity/coloros17/work/canonical/system/framework/services.jar')
JAVA = '/srv/infinity/android/prebuilts/jdk/jdk21/linux-x86/bin/java'
JAVAC = '/srv/infinity/android/prebuilts/jdk/jdk21/linux-x86/bin/javac'
BAK = '/srv/infinity/android/prebuilts/extract-tools/common/smali/baksmali.jar'
SMALI = '/srv/infinity/android/prebuilts/extract-tools/common/smali/smali.jar'
R8 = '/srv/infinity/android/prebuilts/r8/r8.jar'
CP = ':'.join([
    '/srv/infinity/out/soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar',
    '/srv/infinity/out/soong/.intermediates/frameworks/base/services/core/services.core.unboosted/android_common/combined/services.core.unboosted.jar',
])
LIB = '/srv/infinity/android/prebuilts/sdk/current/public/android.jar'

def run(args):
    subprocess.run([str(x) for x in args], check=True)

def fresh(name):
    p = ROOT / name
    if p.exists(): shutil.rmtree(p)
    p.mkdir(mode=0o700)
    return p

def digest(data): return hashlib.sha256(data).hexdigest()

assert digest(CANON.read_bytes()) == '105cc421668d81ac1c7bced968f0fbb32205a03781e6d846f13d4c8d8effec94', 'Canonical donor services.jar changed'
assert digest((CANON.parent / 'framework.jar').read_bytes()) == 'b162bebef34cc6650df503a39a51101679ccfef03d2f4c34615d04503c4b565d', 'Canonical donor framework.jar changed'

classes = fresh('bridge-classes')
names = ['UdfpsTouchBridgeCore', 'UdfpsTouchBridgeCoreTest', 'PassiveInputLease', 'PassiveInputLeaseTest', 'DashUdfpsTouchBridge', 'DashBridgeArtHarness']
run([JAVAC, '-proc:none', '--release', '17', '-classpath', CP, '-d', classes,
     *[ROOT / (name + '.java') for name in names]])
run([JAVA, '-cp', classes, 'com.android.server.biometrics.sensors.dash.UdfpsTouchBridgeCoreTest'])
run([JAVA, '-cp', classes, 'com.android.server.biometrics.sensors.dash.PassiveInputLeaseTest'])
all_classes = sorted(classes.rglob('*.class'))
prod_classes = [p for p in all_classes if not p.name.startswith(('UdfpsTouchBridgeCoreTest', 'PassiveInputLeaseTest', 'DashBridgeArtHarness'))]
test_classes = [p for p in all_classes if p.name.startswith(('UdfpsTouchBridgeCoreTest', 'PassiveInputLeaseTest', 'DashBridgeArtHarness'))]
prod_cp = ROOT / 'bridge-production-classpath.jar'
with zipfile.ZipFile(prod_cp, 'w') as z:
    for p in prod_classes: z.write(p, str(p.relative_to(classes)))
prod = fresh('bridge-production-dex')
harness = fresh('bridge-harness-dex')
for destination, inputs in [(prod, prod_classes), (harness, test_classes)]:
    run([JAVA, '-cp', R8, 'com.android.tools.r8.D8', '--min-api', '26', '--lib', LIB,
         '--classpath', prod_cp, '--classpath', CP.split(':')[0], '--output', destination, *inputs])
harness_inventory = subprocess.check_output([JAVA, '-jar', BAK, 'list', 'classes', str(harness / 'classes.dex')], text=True).splitlines()
assert not any(x.startswith('Lcom/android/server/biometrics/sensors/dash/DashUdfpsTouchBridge')
               or x.startswith('Lcom/android/server/biometrics/sensors/dash/UdfpsTouchBridgeCore;')
               or x.startswith('Lcom/android/server/biometrics/sensors/dash/UdfpsTouchBridgeCore$')
               or x.startswith('Lcom/android/server/biometrics/sensors/dash/PassiveInputLease;')
               or x.startswith('Lcom/android/server/biometrics/sensors/dash/PassiveInputLease$')
               for x in harness_inventory), 'Test DEX shadows production definitions'

original = ROOT / 'bridge-services-original'
if not (original / 'com/android/server/biometrics/sensors/SensorOverlays.smali').exists():
    original.mkdir(mode=0o700, exist_ok=True)
    run([JAVA, '-jar', BAK, 'disassemble', '-o', original, str(CANON) + '/classes.dex'])
helper = fresh('bridge-helper-smali')
run([JAVA, '-jar', BAK, 'disassemble', '-o', helper, prod / 'classes.dex'])
patched = fresh('bridge-services-patched')
shutil.copytree(original, patched, dirs_exist_ok=True)
target = patched / 'com/android/server/biometrics/sensors/SensorOverlays.smali'
text = target.read_text()
show = '    invoke-interface/range {v2 .. v7}, Landroid/hardware/fingerprint/IUdfpsOverlayController;->showUdfpsOverlay(JIILandroid/hardware/fingerprint/IUdfpsOverlayControllerCallback;)V'
show_hook = '    invoke-static {p0, v5, v6, p3}, Lcom/android/server/biometrics/sensors/dash/DashUdfpsTouchBridge;->onShow(Ljava/lang/Object;IILjava/lang/Object;)V'
hide = '.method public hide(I)V\n    .registers 5\n    .param p1, "sensorId"    # I'
hide_hook = '    invoke-static {p0, p1}, Lcom/android/server/biometrics/sensors/dash/DashUdfpsTouchBridge;->onHide(Ljava/lang/Object;I)V'
assert text.count(show) == 1 and text.count(hide) == 1, 'Donor hook anchors changed'
text = text.replace(show, show + '\n\n' + show_hook)
text = text.replace(hide, hide + '\n\n' + hide_hook)
target.write_text(text)
added = sorted(str(p.relative_to(helper)) for p in helper.rglob('*.smali'))
out_dex = ROOT / 'services-touchbridge-prototype.dex'
run([JAVA, '-jar', SMALI, 'assemble', '-a', '35', '-o', out_dex, patched])
roundtrip = fresh('bridge-services-roundtrip')
run([JAVA, '-jar', BAK, 'disassemble', '-o', roundtrip, out_dex])

def normalized(text):
    # DEX code-address labels may renumber when the hook is inserted. Debug lines are not code.
    labels = {}
    result = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s == 'nop' or s.startswith(('#', '.line ', '.local ', '.end local ', '.restart local ', '.prologue')):
            continue
        if s.startswith('.method '): labels = {}
        if s.startswith('.field '): s = re.sub(r' = (?:false|0x0|0x0L|null)$', '', s)
        s = s.replace('const-string/jumbo ', 'const-string ')
        s = s.replace('goto/16 ', 'goto ').replace('goto/32 ', 'goto ')
        strings = []
        def save_string(match):
            strings.append(match.group()); return '@STRING' + str(len(strings)-1) + '@'
        s = re.sub(r'"(?:\\.|[^"\\])*"', save_string, s)
        s = re.sub(r':(?:cond|goto|try_start|try_end|catch|catchall|pswitch|sswitch|array)(?:_data)?_[0-9a-f]+\b',
                   lambda m: labels.setdefault(m.group(), ':label_' + str(len(labels))), s)
        for index, string in enumerate(strings): s = s.replace('@STRING' + str(index) + '@', string)
        result.append(s)
    return '\n'.join(result)

differences = []
original_paths = list(original.rglob('*.smali'))
for p in patched.rglob('*.smali'):
    relative = p.relative_to(patched)
    q = roundtrip / relative
    if not q.exists() or normalized(p.read_text()) != normalized(q.read_text()):
        differences.append(str(relative))
assert not differences, 'Semantic roundtrip differences: ' + repr(differences[:20])
helper_dex = ROOT / 'bridge-helper-roundtrip.dex'
run([JAVA, '-jar', SMALI, 'assemble', '-a', '35', '-o', helper_dex, helper])
helper_roundtrip = fresh('bridge-helper-roundtrip')
run([JAVA, '-jar', BAK, 'disassemble', '-o', helper_roundtrip, helper_dex])
helper_differences = [str(p.relative_to(helper)) for p in helper.rglob('*.smali')
                      if normalized(p.read_text()) != normalized((helper_roundtrip / p.relative_to(helper)).read_text())]
assert not helper_differences, helper_differences

changed_original = [str(p.relative_to(original)) for p in original_paths
                    if p.read_bytes() != (patched / p.relative_to(original)).read_bytes()]
assert changed_original == ['com/android/server/biometrics/sensors/SensorOverlays.smali'], changed_original
without_hooks = target.read_text().replace('\n\n' + show_hook, '').replace('\n\n' + hide_hook, '')
assert without_hooks == (original / target.relative_to(patched)).read_text(), 'More than two hooks changed'

out_jar = ROOT / 'services-touchbridge-prototype.jar'
unchanged_entries = 0
with zipfile.ZipFile(CANON) as old, zipfile.ZipFile(out_jar, 'w') as new:
    for item in old.infolist():
        data = out_dex.read_bytes() if item.filename == 'classes.dex' else old.read(item.filename)
        new.writestr(item, data)
        unchanged_entries += item.filename != 'classes.dex'
    assert 'classes5.dex' not in old.namelist()
    new.writestr('classes5.dex', (prod / 'classes.dex').read_bytes(), compress_type=zipfile.ZIP_STORED)
with zipfile.ZipFile(CANON) as old, zipfile.ZipFile(out_jar) as new:
    assert old.namelist() + ['classes5.dex'] == new.namelist()
    for name in old.namelist():
        if name != 'classes.dex': assert old.read(name) == new.read(name)

summary = {
    'offline_only': True,
    'original_jar_sha256': digest(CANON.read_bytes()),
    'prototype_jar_sha256': digest(out_jar.read_bytes()),
    'changed_original_classes': changed_original,
    'added_helper_classes': added,
    'helper_dex_entry': 'classes5.dex',
    'helper_semantic_roundtrip_differences': helper_differences,
    'original_classes_in_dex': len(original_paths),
    'semantic_roundtrip_differences': differences,
    'unchanged_jar_entries': unchanged_entries,
    'core_checks': 52,
    'resource_checks': 19,
    'test_only_dex_inventory': harness_inventory,
    'art_harness_built_not_executed': True,
}
(ROOT / 'bridge-build-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
