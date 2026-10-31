"""Exercise the real extras makefile's sound policy with GNU make."""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXTRAS = ROOT / "source_overrides/vendor/extras/prebuilts.mk"


class GappsSoundPolicyTests(unittest.TestCase):
    def evaluate(self, gapps, preserve=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dependency = root / "vendor/extras/misc/ax_tflite/common.mk"
            dependency.parent.mkdir(parents=True)
            dependency.write_text("# Unrelated TFLite dependency is outside this sound-policy test.\n")
            definitions = f"WITH_GAPPS := {str(gapps).lower()}\n"
            if preserve is not None:
                definitions += f"TARGET_KEEP_STOCK_SOUNDS := {str(preserve).lower()}\n"
            (root / "Makefile").write_text(
                definitions
                + f"include {EXTRAS}\n"
                + "all:\n"
                + "\t@printf '%s\\n' '$(PRODUCT_PACKAGES)' '$(PRODUCT_COPY_FILES)' '$(PRODUCT_PRODUCT_PROPERTIES)'\n"
            )
            result = subprocess.run(
                ["make", "--no-print-directory", "-s", "-C", str(root), "all"],
                capture_output=True, text=True, check=True,
            )
            return result.stdout

    def test_keep_stock_sounds_excludes_google_tones_and_default_reassignment(self):
        output = self.evaluate(True, True)
        self.assertIn("MlkitBarcodeUIPrebuilt", output)
        for sound in ("Eureka.ogg", "Fresh_start.ogg", "Your_new_adventure.ogg"):
            self.assertNotIn(sound, output)
        self.assertNotIn("ro.config.notification_sound=", output)
        self.assertNotIn("ro.config.alarm_alert=", output)
        self.assertNotIn("ro.config.ringtone=", output)

    def test_unset_flag_preserves_upstream_gapps_policy(self):
        self.assertIn("ro.config.notification_sound=Eureka.ogg", self.evaluate(True))

    def test_vanilla_does_not_install_google_tones(self):
        self.assertNotIn("Eureka.ogg", self.evaluate(False))


if __name__ == "__main__":
    unittest.main()
