"""Build the optional OPPO-radio registration guard against the pinned donor JAR."""
from pathlib import Path
import hashlib, importlib.util, json, subprocess, sys, tempfile, zipfile

INPUT_SHA256 = '48b53efe64fd5e4cb183f9ead2e351b7b47152b07923cbbb0480755bd78a04a4'
CLASS = 'com/oplus/internal/telephony/OplusRadioAidl.smali'


def build(source, output, patch_module, android_root):
    source, output, patch_module, android_root = map(Path, (source, output, patch_module, android_root))
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if digest(source) != INPUT_SHA256 or output.exists():
        raise ValueError('Input JAR differs or output already exists')
    spec = importlib.util.spec_from_file_location('registration_patch', patch_module)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    java = android_root / 'prebuilts/jdk/jdk21/linux-x86/bin/java'
    bak = android_root / 'prebuilts/extract-tools/common/smali/baksmali.jar'
    asm = android_root / 'prebuilts/extract-tools/common/smali/smali.jar'
    align = android_root / 'prebuilts/sdk/tools/linux/bin/zipalign'
    with tempfile.TemporaryDirectory(prefix='radio-registration-', dir=output.parent) as folder:
        work = Path(folder); tree = work / 'smali'
        subprocess.run([str(java), '-jar', str(bak), 'disassemble', str(source) + '/classes.dex', '-o', str(tree)], check=True)
        hashes = {str(p.relative_to(tree)): digest(p) for p in tree.rglob('*.smali')}
        target = tree / CLASS; target.write_text(module.patch_registration(target.read_text()))
        changed = [str(p.relative_to(tree)) for p in tree.rglob('*.smali') if digest(p) != hashes[str(p.relative_to(tree))]]
        if changed != [CLASS]: raise ValueError('Unexpected class changes')
        dex = work / 'classes.dex'
        subprocess.run([str(java), '-jar', str(asm), 'assemble', str(tree), '-o', str(dex)], check=True)
        unsigned = work / 'candidate.jar'
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(unsigned, 'w') as dst:
            if any(n.upper().endswith(('.RSA', '.DSA', '.EC', '.SF')) for n in src.namelist()):
                raise ValueError('Signed JAR requires a separate signature workflow')
            for item in src.infolist(): dst.writestr(item, dex.read_bytes() if item.filename == 'classes.dex' else src.read(item))
        subprocess.run([str(align), '-f', '4', str(unsigned), str(output)], check=True)
        subprocess.run([str(align), '-c', '4', str(output)], check=True)
        with zipfile.ZipFile(source) as a, zipfile.ZipFile(output) as b:
            if a.namelist() != b.namelist(): raise ValueError('JAR entry inventory changed')
            if any(a.read(n) != b.read(n) for n in a.namelist() if n != 'classes.dex'):
                raise ValueError('Unrelated JAR entries changed')
        report = {'source_sha256': digest(source), 'output_sha256': digest(output),
                  'bytes': output.stat().st_size, 'changed_classes': changed,
                  'method': module.METHOD, 'original_method_sha256': module.ORIGINAL_METHOD_SHA256,
                  'tools': {str(p): digest(p) for p in [bak, asm, align]}}
        output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
        return report

if __name__ == '__main__':
    print(json.dumps(build(*sys.argv[1:]), indent=2))
