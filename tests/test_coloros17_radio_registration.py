from pathlib import Path
import unittest
from ports.coloros17.radio_registration import patch_registration, REMOTE_CATCH, SECURITY_CATCH

FIXTURE = Path(__file__).parent / 'fixtures/coloros17/oplus_radio_registration.smali'

class RadioRegistrationTests(unittest.TestCase):
    def test_optional_service_denial_uses_the_existing_failure_path(self):
        original = FIXTURE.read_text()
        patched = patch_registration(original)
        self.assertEqual(patched.replace(SECURITY_CATCH + '\n', ''), original)
        self.assertIn(REMOTE_CATCH + '\n' + SECURITY_CATCH, patched)
        self.assertNotIn('.catch Ljava/lang/Exception;', patched)
        self.assertNotIn('.catch Ljava/lang/RuntimeException;', patched)

    def test_changed_donor_or_repeated_application_is_refused(self):
        original = FIXTURE.read_text()
        for text in [original.replace('IRadioStable', 'Unexpected'), original + '\n' + original,
                     patch_registration(original)]:
            with self.subTest(text=text[:50]), self.assertRaises(ValueError):
                patch_registration(text)
