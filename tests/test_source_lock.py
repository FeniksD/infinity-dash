import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("source_lock", Path(__file__).resolve().parents[1] / "security/source_lock.py")
lock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lock)


class SourceLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.root.mkdir()
        (self.root / "file.mk").write_text("trusted\n")
        self.manifest = self.base / "sources.jsonl"

    def test_roundtrip_and_excluded_output(self):
        lock.snapshot(self.root, self.manifest)
        (self.root / "out").mkdir()
        (self.root / "out/log").write_text("mutable build output")
        self.assertEqual(lock.verify(self.root, self.manifest), [])

    def test_changed_added_and_removed_sources_are_detected(self):
        lock.snapshot(self.root, self.manifest)
        (self.root / "file.mk").write_text("changed")
        self.assertTrue(lock.verify(self.root, self.manifest))
        (self.root / "file.mk").unlink()
        self.assertTrue(lock.verify(self.root, self.manifest))
        (self.root / "file.mk").write_text("trusted\n")
        (self.root / "extra.mk").write_text("extra")
        self.assertTrue(lock.verify(self.root, self.manifest))

    def test_relative_internal_link_is_accepted_but_escape_is_rejected(self):
        (self.root / "alias").symlink_to("file.mk")
        lock.snapshot(self.root, self.manifest)
        self.assertEqual(lock.verify(self.root, self.manifest), [])
        (self.root / "alias").unlink()
        (self.root / "alias").symlink_to("../outside")
        with self.assertRaises(ValueError):
            lock.snapshot(self.root, self.base / "other.jsonl")

    def test_hardlink_alias_and_manifest_inside_source_are_rejected(self):
        os.link(self.root / "file.mk", self.base / "alias")
        with self.assertRaises(ValueError):
            lock.snapshot(self.root, self.manifest)
        with self.assertRaises(ValueError):
            lock.snapshot(self.root, self.root / "manifest")

    def test_mount_requires_exact_read_only_root_and_restricts_writable_children(self):
        prefix = f"1 0 8:1 / {self.root} "
        self.assertEqual(lock.mount_errors(self.root, prefix + "ro,relatime - ext4 /dev/vda2 rw\n"), [])
        self.assertTrue(lock.mount_errors(self.root, prefix + "rw,relatime - ext4 /dev/vda2 rw\n"))
        self.assertTrue(lock.mount_errors(self.root, "1 0 8:1 / / ro - ext4 /dev/vda2 ro\n"))
        child = f"2 1 8:1 / {self.root}/vendor rw - ext4 /dev/vda2 rw\n"
        self.assertTrue(lock.mount_errors(self.root, prefix + "ro - ext4 /dev/vda2 rw\n" + child))
        output = f"2 1 8:1 / {self.root}/out rw - ext4 /dev/vda2 rw\n"
        self.assertEqual(lock.mount_errors(self.root, prefix + "ro - ext4 /dev/vda2 rw\n" + output), [])

    def test_second_snapshot_does_not_replace_baseline(self):
        lock.snapshot(self.root, self.manifest)
        before = self.manifest.read_bytes()
        with self.assertRaises(FileExistsError):
            lock.snapshot(self.root, self.manifest)
        self.assertEqual(before, self.manifest.read_bytes())

    def test_links_into_excluded_trees_are_rejected_even_indirectly(self):
        for folder in (".infinity-dash-logs", ".repo", ".git", "out"):
            with self.subTest(folder=folder):
                target = self.root / folder
                target.mkdir(exist_ok=True)
                (target / "input.mk").write_text("mutable")
                link = self.root / "alias"
                link.symlink_to(f"{folder}/input.mk")
                indirect = self.root / "indirect"
                indirect.symlink_to("alias")
                with self.assertRaises(ValueError):
                    lock.record(self.root, "indirect")
                indirect.unlink()
                link.unlink()

    def test_log_destination_must_reference_the_same_directory(self):
        mounted = self.root / ".infinity-dash-logs"
        mounted.mkdir()
        other = self.base / "logs"
        other.mkdir()
        self.assertTrue(lock.log_errors(self.root, other))
        self.assertEqual(lock.log_errors(self.root, mounted), [])

    def test_output_destination_must_reference_the_same_directory(self):
        mounted = self.root / "out"
        mounted.mkdir()
        other = self.base / "output"
        other.mkdir()
        self.assertTrue(lock.output_errors(self.root, other))
        self.assertEqual(lock.output_errors(self.root, mounted), [])

    def test_exact_missing_image_link_policy_is_allowed(self):
        target = "/etc/systemd/system/infinity-unit-test-not-present.service"
        (self.root / "image-link").symlink_to(target)
        policy = {"image-link": target}
        lock.snapshot(self.root, self.manifest, image_links=policy)
        self.assertEqual(lock.verify(self.root, self.manifest, image_links=policy), [])
        self.assertTrue(lock.verify(self.root, self.manifest, image_links={}))

    def test_image_policy_never_allows_existing_or_writable_external_targets(self):
        target = self.base / "external"
        target.write_text("untrusted")
        (self.root / "image-link").symlink_to(target)
        policy = {"image-link": str(target)}
        with self.assertRaises(ValueError):
            lock.snapshot(self.root, self.manifest, image_links=policy)
        target.unlink()
        with self.assertRaises(ValueError):
            lock.snapshot(self.root, self.manifest, image_links=policy)

    def test_parallel_verification_matches_serial_results(self):
        for i in range(40):
            (self.root / f"file-{i}.txt").write_text(str(i))
        lock.snapshot(self.root, self.manifest)
        self.assertEqual(lock.verify(self.root, self.manifest, jobs=4), [])
        (self.root / "file-17.txt").write_text("changed")
        self.assertEqual(lock.verify(self.root, self.manifest, jobs=4), lock.verify(self.root, self.manifest, jobs=1))
        with self.assertRaises(ValueError):
            lock.verify(self.root, self.manifest, jobs=0)


if __name__ == "__main__":
    unittest.main()
