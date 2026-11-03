import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import subprocess
import sys
import tempfile
import struct
import zipfile

from ports.coloros17 import branding


ANDROID = "{http://schemas.android.com/apk/res/android}"
SETTINGS = "{http://schemas.android.com/apk/prv/res/com.android.settings}"
DUMP = '''N: android=http://schemas.android.com/apk/res/android (line=1)
  N: settings=http://schemas.android.com/apk/res-auto (line=1)
    E: PreferenceScreen (line=1)
      A: http://schemas.android.com/apk/res/android:title(0x010101e1)=@0x7f150001
        E: com.oplus.settings.widget.preference.SettingsPreferenceCategory (line=2)
          A: http://schemas.android.com/apk/res/android:key(0x010101e8)="existing_category" (Raw: "existing_category")
            E: com.oplus.settings.widget.preference.SettingsSimpleJumpPreference (line=3)
              A: http://schemas.android.com/apk/res/android:key(0x010101e8)="original_setting" (Raw: "original_setting")
              A: http://schemas.android.com/apk/res/android:summary(0x010101e9)="Original & safe" (Raw: "Original & safe")
              A: http://schemas.android.com/apk/res-auto:showSummary(0x7f040001)=true
'''
RESOURCES = {"0x7f150001": "string/about_device", "0x7f040001": "attr/showSummary"}


class AboutBrandingTests(unittest.TestCase):
    def test_prebuilt_uses_relocatable_ids_instead_of_aliasing_settings(self):
        # Both Settings and the old overlay used 0x7f. Android relocated every
        # donor reference to the overlay, so integer orders and titles broke.
        apk = Path(branding.__file__).parent / "branding_overlay/FeniksDAboutOverlay.apk"
        with zipfile.ZipFile(apk) as archive:
            data = archive.read("resources.arsc")
        _, header, size = struct.unpack_from("<HHI", data)
        packages = []
        offset = header
        while offset < size:
            kind, child_header, child_size = struct.unpack_from("<HHI", data, offset)
            if kind == 0x0200:
                packages.append(struct.unpack_from("<I", data, offset + 8)[0])
            self.assertGreater(child_size, 0)
            offset += child_size
        self.assertEqual(packages, [0], "RRO must keep its own IDs separate from Settings 0x7f")

    def test_cli_refuses_another_settings_apk_before_creating_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            apk = root / "Settings.apk"
            apk.write_bytes(b"different firmware")
            output = root / "overlay.apk"
            result = subprocess.run([sys.executable, "-m", "ports.coloros17.branding",
                "--settings-apk", str(apk), "--framework-apk", str(root / "missing-framework.apk"),
                "--aapt2", str(root / "missing-aapt2"), "--output", str(output)],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Settings APK checksum", result.stderr)
            self.assertFalse(output.exists())

    def test_existing_settings_remain_and_channel_entry_is_clickable(self):
        xml = branding.render_about_overlay(DUMP, RESOURCES)
        self.assertIsInstance(xml, bytes)
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "PreferenceScreen")
        self.assertEqual(root.get(ANDROID + "title"), "@*com.android.settings:string/about_device")
        self.assertEqual(len(root), 2)
        original = root[0][0]
        self.assertEqual(original.get(ANDROID + "key"), "original_setting")
        self.assertEqual(original.get(ANDROID + "summary"), "Original & safe")
        self.assertEqual(original.get(SETTINGS + "showSummary"), "true")
        entry = root[1][0]
        self.assertEqual(entry.get(ANDROID + "key"), "feniksd_port_info")
        self.assertEqual(entry.get(ANDROID + "summary"), "@string/feniksd_port_summary")
        self.assertEqual(entry[0].get(ANDROID + "action"), "android.intent.action.VIEW")
        self.assertEqual(entry[0].get(ANDROID + "data"), "https://t.me/feniksd_dash")

    def test_dash_credits_precede_hardware_without_replacing_original_widgets(self):
        dump = DUMP.replace('"existing_category"', '"device_hardware_info_category"')
        dump += '''            E: com.oplus.settings.feature.deviceinfo.DeviceMarketNameItemPreference (line=4)
              A: http://schemas.android.com/apk/res/android:key(0x010101e8)="device_market_name_header"
              A: http://schemas.android.com/apk/res/android:order(0x010101ea)=350
            E: com.oplus.settings.feature.deviceinfo.DeviceCameraInfoItemPreference (line=5)
              A: http://schemas.android.com/apk/res/android:key(0x010101e8)="camera_info"
              A: http://schemas.android.com/apk/res/android:order(0x010101ea)=380
'''
        root = ET.fromstring(branding.render_about_overlay(dump, RESOURCES))
        hardware = root[0]
        nodes = {n.get(ANDROID + "key"): n for n in hardware}
        self.assertEqual(nodes["device_market_name_header"].tag,
                         "com.oplus.settings.feature.deviceinfo.DeviceMarketNameItemPreference")
        self.assertEqual(nodes["camera_info"].tag,
                         "com.oplus.settings.feature.deviceinfo.DeviceCameraInfoItemPreference")
        self.assertNotIn("feniksd_device_identity", nodes)
        self.assertEqual(root[1].get(ANDROID + "key"), "feniksd_port_category")
        self.assertEqual(root[1].get(ANDROID + "order"), "176")
        self.assertEqual(len(root), 2)

    def test_unresolved_donor_resource_is_refused(self):
        with self.assertRaisesRegex(ValueError, "resource"):
            branding.render_about_overlay(DUMP, {})

    def test_duplicate_port_entry_is_refused(self):
        with self.assertRaisesRegex(ValueError, "already"):
            branding.render_about_overlay(DUMP.replace("original_setting", "feniksd_port_info"), RESOURCES)

    def test_unknown_dump_statement_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "statement"):
            branding.render_about_overlay(DUMP + "        unexpected statement\n", RESOURCES)

    def test_a_second_root_is_refused(self):
        with self.assertRaisesRegex(ValueError, "root"):
            branding.render_about_overlay(DUMP + "    E: PreferenceScreen (line=9)\n", RESOURCES)

    def test_coui_enum_keeps_its_meaning_when_recompiled(self):
        dump = DUMP + '''              A: http://schemas.android.com/apk/res-auto:couiClickStyle(0x7f040002)=2
              A: http://schemas.android.com/apk/res/android:order(0x010101ea)=2
'''
        root = ET.fromstring(branding.render_about_overlay(dump, RESOURCES))
        self.assertEqual(root[0][0].get(SETTINGS + "couiClickStyle"), "unclick")
        self.assertEqual(root[0][0].get(ANDROID + "order"), "2")
