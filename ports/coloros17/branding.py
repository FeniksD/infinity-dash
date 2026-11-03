"""Build a Settings resource overlay that keeps the donor APK unchanged."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ANDROID_URI = "http://schemas.android.com/apk/res/android"
AUTO_URI = "http://schemas.android.com/apk/res-auto"
SETTINGS_URI = "http://schemas.android.com/apk/prv/res/com.android.settings"
ANDROID = "{" + ANDROID_URI + "}"
SETTINGS = "{" + SETTINGS_URI + "}"
CHANNEL = "https://t.me/feniksd_dash"


def _value(raw, resources):
    raw = raw.strip()
    if raw.startswith('"'):
        value, end = json.JSONDecoder().raw_decode(raw)
        if not isinstance(value, str) or (raw[end:].strip() and not raw[end:].strip().startswith("(Raw:")):
            raise ValueError("unrecognized string statement")
        return "\\" + value if value.startswith(("@", "?")) else value
    if re.fullmatch(r"[@?]0x[0-9a-fA-F]{8}", raw):
        resource = resources.get(raw[1:].lower())
        if not resource or not re.fullmatch(r"[A-Za-z0-9_]+/[A-Za-z0-9_.]+", resource):
            raise ValueError("unresolved donor resource: " + raw)
        return raw[0] + "*com.android.settings:" + resource
    if raw in ("true", "false", "@null", "@empty") or re.fullmatch(r"-?(?:[0-9]+|0x[0-9a-fA-F]+)", raw):
        return raw
    raise ValueError("unrecognized attribute statement: " + raw)


def render_about_overlay(dump, resources):
    """Preserve donor settings; put port credits just below the storage card."""
    root, stack = None, []
    for raw in dump.splitlines():
        if not raw.strip():
            continue
        line, indent = raw.lstrip(), len(raw) - len(raw.lstrip())
        if line.startswith("N:"):
            continue
        element = re.fullmatch(r"E: ([A-Za-z0-9_.$]+) \(line=[0-9]+\)", line)
        if element:
            while stack and stack[-1][0] >= indent:
                stack.pop()
            node = ET.Element(element[1])
            if stack:
                stack[-1][1].append(node)
            elif root is None:
                root = node
            else:
                raise ValueError("multiple XML roots")
            stack.append((indent, node))
            continue
        attribute = re.fullmatch(r"A: (?:(https?://.+):)?([^(:=\s]+)(?:\(0x[0-9a-fA-F]+\))?=(.*)", line)
        if not attribute or not stack or indent <= stack[-1][0]:
            raise ValueError("unrecognized XML statement: " + line)
        namespace, name, value = attribute.groups()
        if namespace == AUTO_URI:
            namespace = SETTINGS_URI
        elif namespace not in (None, ANDROID_URI):
            raise ValueError("unrecognized attribute namespace")
        key = "{" + namespace + "}" + name if namespace else name
        if key in stack[-1][1].attrib:
            raise ValueError("duplicate XML attribute")
        converted = _value(value, resources)
        # AAPT2 prints the typed enum as an integer, but its source XML parser
        # requires the symbol. These values belong to the pinned donor COUI API.
        if namespace == SETTINGS_URI and name == "couiClickStyle":
            converted = {"0": "nomal", "1": "click", "2": "unclick"}.get(converted, converted)
        stack[-1][1].set(key, converted)
    if root is None or root.tag != "PreferenceScreen":
        raise ValueError("expected a PreferenceScreen root")
    if any(n.get(ANDROID + "key") in {"feniksd_port_category", "feniksd_port_info"} for n in root.iter()):
        raise ValueError("port information is already present")
    coloros = any(n.tag == "com.oplus.settings.widget.preference.SettingsSimpleJumpPreference" for n in root.iter())
    category = ET.SubElement(root,
        "com.oplus.settings.widget.preference.SettingsPreferenceCategory" if coloros else "PreferenceCategory",
        {ANDROID + "key": "feniksd_port_category", ANDROID + "title": "@string/feniksd_port_category",
         ANDROID + "order": "176" if coloros else "1000"})
    entry = ET.SubElement(category,
        "com.oplus.settings.widget.preference.SettingsSimpleJumpPreference" if coloros else "Preference",
        {ANDROID + "key": "feniksd_port_info", ANDROID + "title": "@string/feniksd_port_title",
         ANDROID + "summary": "@string/feniksd_port_summary"})
    if coloros:
        entry.set(SETTINGS + "layoutCategory", "no_icon")
        entry.set(SETTINGS + "showSummary", "true")
    ET.SubElement(entry, "intent", {ANDROID + "action": "android.intent.action.VIEW", ANDROID + "data": CHANNEL})
    ET.register_namespace("android", ANDROID_URI)
    ET.register_namespace("settings", SETTINGS_URI)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_overlay(settings_apk, framework_apk, aapt2, output):
    here = Path(__file__).resolve().parent
    spec = json.loads((here / "branding-bundle.json").read_text())
    settings_apk, framework_apk, aapt2, output = map(Path, (settings_apk, framework_apk, aapt2, output))
    def digest(path):
        with path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    if digest(settings_apk) != spec["settings_apk_sha256"]:
        raise ValueError("Settings APK checksum differs from the reviewed donor")
    if output.exists():
        raise ValueError("Refusing to replace an existing overlay")
    def run(*args):
        p = subprocess.run([str(aapt2), *map(str, args)], capture_output=True, text=True)
        if p.returncode:
            raise ValueError("AAPT2 failed: " + p.stderr)
        return p.stdout
    dumps = {n: run("dump", "xmltree", settings_apk, "--file", "res/xml/" + n + ".xml")
             for n in ("device_info", "my_device_info")}
    needed = set(re.findall(r"0x7f[0-9a-fA-F]{6}", "\n".join(dumps.values())))
    resources = {}
    for line in run("dump", "resources", settings_apk).splitlines():
        m = re.search(r"resource (0x[0-9a-fA-F]{8}) ([^\s]+)", line)
        if m and m[1] in needed:
            resources[m[1]] = m[2]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="feniksd-about-", dir=output.parent) as temp:
        work = Path(temp)
        for source in (here / "branding_overlay").rglob("*.xml"):
            target = work / source.relative_to(here / "branding_overlay")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        for name, dump in dumps.items():
            (work / "res/xml" / ("feniksd_" + name + ".xml")).write_bytes(render_about_overlay(dump, resources))
        run("compile", "--dir", work / "res", "-o", work / "resources.zip")
        apk = work / "unsigned.apk"
        # A 0x7f overlay aliases Settings references when loaded as an RRO.
        # Shared-library IDs leave donor IDs absolute and relocate only our own.
        run("link", "--manifest", work / "AndroidManifest.xml", "-I", framework_apk,
            "-I", settings_apk, "--auto-add-overlay", "--no-resource-deduping",
            "--no-resource-removal", "--shared-lib", "-o", apk, work / "resources.zip")
        def normalized(text):
            lines = text.splitlines()
            skip_keys = {"feniksd_port_category", "feniksd_port_info"}
            output, i = [], 0
            while i < len(lines):
                line = lines[i]
                indent = len(line) - len(line.lstrip())
                if line.lstrip().startswith("E:"):
                    j = i + 1
                    while j < len(lines) and not lines[j].lstrip().startswith("E:"):
                        j += 1
                    if any(re.search(r':key\(0x[0-9a-fA-F]+\)="' + re.escape(key) + '"', attr)
                           for key in skip_keys for attr in lines[i + 1:j]):
                        i += 1
                        while i < len(lines) and (not lines[i].strip()
                                or len(lines[i]) - len(lines[i].lstrip()) > indent):
                            i += 1
                        continue
                if line.strip() and not line.lstrip().startswith("N:"):
                    output.append(re.sub(r" \(line=[0-9]+\)", "", line.strip()).replace(SETTINGS_URI, AUTO_URI))
                i += 1
            return output
        for name, original in dumps.items():
            compiled = run("dump", "xmltree", apk, "--file", "res/xml/feniksd_" + name + ".xml")
            old, new = normalized(original), normalized(compiled)
            if old != new:
                raise ValueError("Compiled overlay changed an original preference")
        os.link(apk, output)
    return {"output": str(output), "sha256": digest(output), "bytes": output.stat().st_size,
            "settings_apk_sha256": digest(settings_apk), "framework_apk_sha256": digest(framework_apk),
            "aapt2_sha256": digest(aapt2), "original_preferences_preserved": True}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings-apk", required=True)
    parser.add_argument("--framework-apk", required=True)
    parser.add_argument("--aapt2", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(build_overlay(args.settings_apk, args.framework_apk, args.aapt2, args.output), indent=2))
