"""Rebase reviewed dash hooks into Global framework JARs without copying CN classes.

Only our independently compiled helper DEX is reused. All original DEX entries
start from the pinned Global donor, and every assembled class is roundtripped.
"""
import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

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

def verify_classes(original, patched, actual, allowed):
    if original.keys() != patched.keys() or patched.keys() != actual.keys():
        raise ValueError('Class inventory changed during rebase')
    changed = {name for name in original if original[name] != patched[name] and normalized(original[name]) != normalized(patched[name])}
    if changed != set(allowed):
        raise ValueError('Unexpected source class modifications')
    differences = [name for name in patched if patched[name] != actual[name] and normalized(patched[name]) != normalized(actual[name])]
    if differences:
        raise ValueError('Assembled DEX differs from reviewed source: ' + ', '.join(differences[:12]))


def replace_dex(source, output, replacements, expected_sha256, additions=None):
    source, output = Path(source), Path(output)
    additions = additions or {}
    names = set(replacements) | set(additions)
    if (output.exists() or not replacements or set(replacements) & set(additions)
            or any(not re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', n) for n in names)):
        raise ValueError('Invalid DEX rewrite or existing output')
    with source.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected_sha256:
            raise ValueError('Source JAR differs from the pinned Global donor')
        stream.seek(0)
        with zipfile.ZipFile(stream) as src:
            old_names = src.namelist()
            if (len(old_names) != len(set(old_names)) or not set(replacements) <= set(old_names)
                    or set(additions) & set(old_names)
                    or any(n.upper().endswith(('.RSA', '.DSA', '.EC', '.SF')) for n in old_names)):
                raise ValueError('Unknown DEX entry, collision, duplicate, or signed JAR')
            entries = [(i, replacements.get(i.filename, src.read(i))) for i in src.infolist()]
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Source JAR changed while reading')
    with output.open('xb') as stream, zipfile.ZipFile(stream, 'w') as dst:
        for info, data in entries:
            dst.writestr(info, data)
        for name, data in additions.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            dst.writestr(info, data, compress_type=zipfile.ZIP_STORED)
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(output) as dst:
        if dst.namelist() != old_names + list(additions):
            raise ValueError('Output JAR inventory differs')
        for name in old_names:
            if name not in replacements and src.read(name) != dst.read(name):
                raise ValueError('Unrelated Global JAR entry changed')


def patch_sensor_overlays(text):
    show = '    invoke-interface/range {v2 .. v7}, Landroid/hardware/fingerprint/IUdfpsOverlayController;->showUdfpsOverlay(JIILandroid/hardware/fingerprint/IUdfpsOverlayControllerCallback;)V'
    hide = '.method public hide(I)V\n    .registers 5\n    .param p1, "sensorId"    # I'
    if text.count(show) != 1 or text.count(hide) != 1:
        raise ValueError('Global SensorOverlays hook anchors changed')
    text = text.replace(show, show + '\n\n    invoke-static {p0, v5, v6, p3}, Lcom/android/server/biometrics/sensors/dash/DashUdfpsTouchBridge;->onShow(Ljava/lang/Object;IILjava/lang/Object;)V')
    return text.replace(hide, hide + '\n\n    invoke-static {p0, p1}, Lcom/android/server/biometrics/sensors/dash/DashUdfpsTouchBridge;->onHide(Ljava/lang/Object;I)V')


def patch_getter(text):
    method = '.method public getEnrollmentTotalTimes(I)I'
    if text.count(method) != 1:
        raise ValueError('Enrollment getter missing or ambiguous')
    start = text.index(method); end = text.index('.end method', start) + len('.end method')
    before = text[start:end]; anchor = '    move-result v0\n\n    return v0'
    if before.count(anchor) != 1:
        raise ValueError('Enrollment getter result anchor changed')
    hook = '    invoke-static {v0}, Lcom/android/server/biometrics/sensors/dash/DashUdfpsTouchBridge;->normalizeEnrollmentTotal(I)I\n\n    move-result v0'
    return text[:start] + before.replace(anchor, '    move-result v0\n\n' + hook + '\n\n    return v0') + text[end:]


@contextlib.contextmanager
def build_directory(parent):
    work = Path(tempfile.mkdtemp(prefix='global-runtime-', dir=parent))
    try:
        yield work
    except BaseException:
        print('Failed runtime build retained at ' + str(work), file=sys.stderr)
        raise
    else:
        shutil.rmtree(work)


def build(base, donor_jars, helper_jar, android_root):
    base, donor_jars, helper_jar, android_root = map(Path, (base, donor_jars, helper_jar, android_root))
    spec = json.loads((HERE / 'global-runtime-inputs.json').read_text())
    for name, expected in spec['jars'].items():
        if digest(donor_jars / name) != expected:
            raise ValueError('Global JAR pin mismatch: ' + name)
    if digest(helper_jar) != spec['helper_jar_sha256']:
        raise ValueError('Reviewed helper artifact differs')
    with zipfile.ZipFile(helper_jar) as src:
        helper = src.read('classes5.dex')
    if hashlib.sha256(helper).hexdigest() != spec['helper_dex_sha256']:
        raise ValueError('Helper DEX pin mismatch')
    helper_sources = json.loads((HERE / 'udfps/manifest.json').read_text())['source_sha256']
    for name, expected in helper_sources.items():
        if digest(HERE / 'udfps' / name) != expected:
            raise ValueError('Reviewed helper source changed: ' + name)
    java = android_root / 'prebuilts/jdk/jdk21/linux-x86/bin/java'
    bak = android_root / 'prebuilts/extract-tools/common/smali/baksmali.jar'
    asm = android_root / 'prebuilts/extract-tools/common/smali/smali.jar'
    align = android_root / 'prebuilts/sdk/tools/linux/bin/zipalign'
    tool_pins = json.loads((HERE / 'radio/validation.json').read_text())['tools']
    for path in (bak, asm, align):
        if digest(path) != tool_pins[str(path)]:
            raise ValueError('Build tool pin mismatch: ' + str(path))
    output = base / 'inputs/runtime'; output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in spec['jars']):
        raise ValueError('Runtime output already exists')
    report = {'source_jars': spec['jars'], 'helper_dex_sha256': spec['helper_dex_sha256'], 'outputs': {}}
    with build_directory(base / 'analysis') as folder:
        work = Path(folder)
        jobs = [('services.jar', 'classes.dex', 'services'), ('oplus-services.jar', 'classes.dex', 'oplus1'), ('oplus-services.jar', 'classes2.dex', 'oplus2')]
        def rebuild(job):
            jar, dex_name, label = job; tree = work / label
            subprocess.run([str(java), '-jar', str(bak), 'disassemble', '-j', '4', '-o', str(tree), str(donor_jars / jar) + '/' + dex_name], check=True)
            original = {str(p.relative_to(tree)): p.read_text() for p in tree.rglob('*.smali')}
            targets = spec['classes'][label]
            for name, pin in targets.items():
                if hashlib.sha256(original[name].encode()).hexdigest() != pin:
                    raise ValueError('Global class pin mismatch: ' + name)
            if label == 'services':
                name = next(iter(targets)); (tree / name).write_text(patch_sensor_overlays(original[name]))
            else:
                patch_name = '0003-charger-invalid-diagnostic.patch' if label == 'oplus1' else '0002-dash-haptic-aosp-fallback.patch'
                subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1'], cwd=tree,
                               input=(HERE / 'patches' / patch_name).read_bytes(), check=True, stdout=subprocess.DEVNULL)
                for name, pin in spec['patched_classes'][label].items():
                    if digest(tree / name) != pin:
                        raise ValueError('Reviewed class patch result differs: ' + name)
                if label == 'oplus1':
                    name = spec['getter_class']; (tree / name).write_text(patch_getter((tree / name).read_text()))
            patched = {str(p.relative_to(tree)): p.read_text() for p in tree.rglob('*.smali')}
            dex = work / (label + '.dex'); roundtrip = work / (label + '-roundtrip')
            subprocess.run([str(java), '-jar', str(asm), 'assemble', '-a', '37', '-j', '4', '-o', str(dex), str(tree)], check=True)
            subprocess.run([str(java), '-jar', str(bak), 'disassemble', '-j', '4', '-o', str(roundtrip), str(dex)], check=True)
            actual = {str(p.relative_to(roundtrip)): p.read_text() for p in roundtrip.rglob('*.smali')}
            # Source patches contain .locals, named labels and unsorted methods.
            # Canonicalize only the approved modified classes independently;
            # unchanged Global classes are still compared to their originals.
            expected_source = work / (label + '-expected-source')
            for name in targets:
                target = expected_source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(patched[name])
            expected_dex = work / (label + '-expected.dex')
            expected_tree = work / (label + '-expected-roundtrip')
            subprocess.run([str(java), '-jar', str(asm), 'assemble', '-a', '37', '-o', str(expected_dex), str(expected_source)], check=True)
            subprocess.run([str(java), '-jar', str(bak), 'disassemble', '-o', str(expected_tree), str(expected_dex)], check=True)
            for name in targets:
                patched[name] = (expected_tree / name).read_text()
            verify_classes(original, patched, actual, targets)
            return jar, dex_name, dex.read_bytes(), len(actual)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(rebuild, jobs))
        for jar in spec['jars']:
            replacements = {name: data for source, name, data, count in results if source == jar}
            unsigned = work / jar; final = output / jar
            replace_dex(donor_jars / jar, unsigned, replacements, spec['jars'][jar],
                        {'classes5.dex': helper} if jar == 'services.jar' else None)
            subprocess.run([str(align), '4', str(unsigned), str(final)], check=True)
            subprocess.run([str(align), '-c', '4', str(final)], check=True)
            with zipfile.ZipFile(unsigned) as a, zipfile.ZipFile(final) as b:
                if a.namelist() != b.namelist() or any(a.read(n) != b.read(n) for n in a.namelist()):
                    raise ValueError('Alignment changed JAR content')
            report['outputs'][jar] = {'sha256': digest(final), 'bytes': final.stat().st_size,
                                      'classes_roundtripped': sum(count for source, _, _, count in results if source == jar)}
    (base / 'control/runtime-rebase.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--donor-jars', type=Path, required=True)
    parser.add_argument('--helper-jar', type=Path, required=True)
    parser.add_argument('--android-root', type=Path, default=Path('/srv/infinity/android'))
    args = parser.parse_args()
    print(json.dumps(build(args.base, args.donor_jars, args.helper_jar, args.android_root), indent=2))
