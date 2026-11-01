#!/usr/bin/env python3
"""Offline-only getter patch layered onto accepted charging/haptics JAR."""
from pathlib import Path
import hashlib,json,re,subprocess,zipfile,shutil
ROOT=Path('/srv/infinity/coloros17/.cache/fingerprint-rootcause/ui-compat-build8')
BASE=Path('/srv/infinity/coloros17/.cache/charging-fix/oplus-services-charging-haptics-v4.jar')
BASE_SHA='2a60e7f1318e7decdb7d02d382c1ae55c9e986d9fc2ddd6d6f0958073dac0ff7'
CANON=Path('/srv/infinity/coloros17/work/canonical/system/framework/oplus-services.jar')
CANON_SHA='8b5310eb659073e1dc2127c94133f75f6a325e06780a43eec8cca89a945b0af4'
JAVA='/srv/infinity/android/prebuilts/jdk/jdk21/linux-x86/bin/java'
BAK='/srv/infinity/android/prebuilts/extract-tools/common/smali/baksmali.jar'
SMALI='/srv/infinity/android/prebuilts/extract-tools/common/smali/smali.jar'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args): subprocess.run([str(a) for a in args],check=True)
def fresh(name):
 p=ROOT/name
 if p.exists(): shutil.rmtree(p)
 p.mkdir(mode=0o700)
 return p
assert digest(BASE)==BASE_SHA, 'Accepted Oplus base changed'
assert digest(CANON)==CANON_SHA, 'Canonical Oplus source changed'
original=ROOT/'oplus-base-smali'
if not original.exists():
 original.mkdir(mode=0o700)
 run([JAVA,'-jar',BAK,'disassemble','-o',original,str(BASE)+'/classes.dex'])
patched=fresh('oplus-patched-smali')
shutil.copytree(original,patched,dirs_exist_ok=True)
relative=Path('com/android/server/biometrics/sensors/fingerprint/aidl/FingerprintServiceProviderExtImpl.smali')
target=patched/relative
text=target.read_text()
start=text.index('.method public getEnrollmentTotalTimes(I)I')
end=text.index('.end method',start)+len('.end method')
before=text[start:end]
anchor='    move-result v0\n\n    return v0'
assert before.count(anchor)==1, 'Getter result anchor changed'
hook='    invoke-static {v0}, Lcom/android/server/biometrics/sensors/dash/DashUdfpsTouchBridge;->normalizeEnrollmentTotal(I)I\n\n    move-result v0'
after=before.replace(anchor,'    move-result v0\n\n'+hook+'\n\n    return v0')
target.write_text(text[:start]+after+text[end:])
assert target.read_text().replace('\n\n'+hook,'',1)==(original/relative).read_text(), 'More than getter hook changed'
changed=[str(x.relative_to(original)) for x in original.rglob('*.smali') if x.read_bytes()!=(patched/x.relative_to(original)).read_bytes()]
assert changed==[str(relative)],changed
dex=ROOT/'oplus-ui-compat8.dex'
run([JAVA,'-jar',SMALI,'assemble','-a','35','-o',dex,patched])
roundtrip=fresh('oplus-roundtrip-smali')
run([JAVA,'-jar',BAK,'disassemble','-o',roundtrip,dex])
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
differences=[str(x.relative_to(patched)) for x in patched.rglob('*.smali') if normalized(x.read_text())!=normalized((roundtrip/x.relative_to(patched)).read_text())]
assert not differences,differences[:20]
out=ROOT/'oplus-services-ui-compat8.jar'
with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(out,'w') as new:
 for item in old.infolist(): new.writestr(item,dex.read_bytes() if item.filename=='classes.dex' else old.read(item.filename))
with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(out) as new:
 assert old.namelist()==new.namelist()
 unchanged=[name for name in old.namelist() if name!='classes.dex']
 for name in unchanged: assert old.read(name)==new.read(name)
 assert old.read('classes2.dex')==new.read('classes2.dex'), 'Haptic classes2 changed'
summary={'offline_only':True,'canonical_oplus_sha256':CANON_SHA,'accepted_oplus_base_sha256':BASE_SHA,
 'candidate_oplus_sha256':digest(out),'changed_original_classes':changed,'changed_method':'getEnrollmentTotalTimes(I)I',
 'original_classes_checked':len(list(patched.rglob('*.smali'))),'semantic_roundtrip_differences':differences,
 'unchanged_jar_entries':len(unchanged),'haptic_classes2_byte_identical':True,
 'requires_companion_services_helper':'com.android.server.biometrics.sensors.dash.DashUdfpsTouchBridge.normalizeEnrollmentTotal(I)I'}
(ROOT/'oplus-build-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
(ROOT/'getter-patch.txt').write_text(after+'\n')
print(json.dumps(summary,indent=2))
