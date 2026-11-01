import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ports/coloros17/preflight.py"


class ColorOS17PreflightTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), "ColorOS17 preflight is missing")
        spec = importlib.util.spec_from_file_location("coloros_preflight", MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.metadata = {"product_name": "PLG110", "version_name": "PLG110_17.0.0.105(CN01)",
                         "post-sdk-level": "37", "android_version": "17", "os_version": "V17.0.0"}
        self.payload = {"magic": "CrAU", "major_version": 2, "minor_version": 9,
                        "partial_update": True, "metadata_hash_matches": True,
                        "partitions": [{"name": name, "size": 4096, "old_partition_info_present": False,
                                        "operations_with_source_extents": 0, "operations": {"REPLACE_XZ": 1}}
                                       for name in ("system", "system_ext", "product", "my_stock", "boot")]}
        self.profile = {"schema_version": 1, "rom_type": "coloros", "sdk": 37,
                        "product": "PLG110", "version": "PLG110_17.0.0.105(CN01)",
                        "required_partitions": ["system", "system_ext", "product", "my_stock"],
                        "pipeline_adapter_ready": True, "use_stock_init": True,
                        "add_vendor_stuff": False, "debloat": {},
                        "allow_insecure_adb": False, "allow_permissive_selinux": False,
                        "allow_unreviewed_binary_patches": False}

    def test_self_contained_partial_payload_can_be_an_extraction_donor(self):
        report = self.module.validate(self.metadata, self.payload, self.profile)
        self.assertEqual(report["partitions"], ["system", "system_ext", "product", "my_stock"])
        self.assertEqual(report["image_bytes"], 16384)
        self.assertFalse(report["phone_flash_authorized"])

    def test_android16_cannot_be_accepted_based_on_a_coloros17_filename(self):
        self.metadata["post-sdk-level"] = "36"
        self.metadata["android_version"] = "16"
        with self.assertRaises(ValueError): self.module.validate(self.metadata, self.payload, self.profile)

    def test_wrong_model_or_os_identity_is_rejected(self):
        for key, value in [("product_name", "PKC110"), ("os_version", "V16.0.0")]:
            with self.subTest(key=key):
                metadata = self.metadata | {key: value}
                with self.assertRaises(ValueError): self.module.validate(metadata, self.payload, self.profile)

    def test_source_dependent_operations_are_rejected(self):
        self.payload["partitions"][0]["operations"] = {"SOURCE_COPY": 1}
        self.payload["partitions"][0]["operations_with_source_extents"] = 1
        with self.assertRaises(ValueError): self.module.validate(self.metadata, self.payload, self.profile)

    def test_old_partition_dependency_is_rejected_even_with_replace_operations(self):
        self.payload["partitions"][0]["old_partition_info_present"] = True
        with self.assertRaises(ValueError): self.module.validate(self.metadata, self.payload, self.profile)

    def test_missing_required_or_unreviewed_my_partition_is_rejected(self):
        for payload in [self.payload | {"partitions": self.payload["partitions"][1:]},
                        self.payload | {"partitions": self.payload["partitions"] +
                                       [self.payload["partitions"][0] | {"name": "my_new_feature"}]}]:
            with self.assertRaises(ValueError): self.module.validate(self.metadata, payload, self.profile)

    def test_missing_unready_or_unsafe_profile_cannot_start_preparation(self):
        profiles = [None, self.profile | {"pipeline_adapter_ready": False},
                    self.profile | {"allow_insecure_adb": True}, self.profile | {"debloat": {"system": ["*"]}}]
        for profile in profiles:
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError): self.module.validate(self.metadata, self.payload, profile)

    def test_validation_leaves_inputs_unchanged(self):
        before = copy.deepcopy((self.metadata, self.payload, self.profile))
        self.module.validate(self.metadata, self.payload, self.profile)
        self.assertEqual((self.metadata, self.payload, self.profile), before)

    def test_unverified_metadata_and_duplicate_partitions_are_rejected(self):
        variants = [self.payload | {"metadata_hash_matches": False},
                    self.payload | {"partitions": self.payload["partitions"] + [self.payload["partitions"][0]]}]
        for payload in variants:
            with self.assertRaises(ValueError): self.module.validate(self.metadata, payload, self.profile)

    def test_partition_paths_cannot_escape_the_extraction_directory(self):
        for name in ["my_/../../vendor", "my_../vendor", "my_bad\\name", "/system", "my_bad-name"]:
            with self.subTest(name=name):
                profile = self.profile | {"required_partitions": self.profile["required_partitions"] + [name]}
                payload = self.payload | {"partitions": self.payload["partitions"] +
                                          [self.payload["partitions"][0] | {"name": name}]}
                with self.assertRaises(ValueError): self.module.validate(self.metadata, payload, profile)


if __name__ == "__main__": unittest.main()
