"""Cleanup must remove build outputs while preserving source and saved work."""
import fcntl
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build.cli import clean_outputs, main
from distro_build.model import BuildError


class CleanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.output = self.project / "out"
        self.artifacts = ["bootstrap/root/compiler", "work/package/object", "apps/incremental/object",
                          "sdk/root/library", "images/base.img", "state/run/desktop-dev/apps.json",
                          "sources/extracted/source", "qualification/probe", "compiler-cache/object"]
        self.saved = ["sources/downloads/archive", "vms/dev/disk.img", "vms/dev/OVMF_VARS.fd",
                      "verification/results.json", "contribution/app/.git", "bundles/source.tar.xz",
                      "tools/rustfmt", "custom-workspace/local-change"]
        for name in self.artifacts + self.saved + ["state/run.lock", "state/locks/package.lock", "locks/image.lock"]:
            path = self.output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        source = self.project / "sources/app/src/main.rs"
        source.parent.mkdir(parents=True)
        source.write_text("uncommitted source")

    def test_default_removes_artifacts_preserving_sources_disks_and_lock_inodes(self):
        locks = [self.output / name for name in ["state/run.lock", "state/locks/package.lock", "locks/image.lock"]]
        inodes = [p.stat().st_ino for p in locks]
        clean_outputs(self.project)
        self.assertTrue(all(not (self.output / name).exists() for name in self.artifacts))
        self.assertTrue(all((self.output / name).read_text() == name for name in self.saved))
        self.assertEqual(inodes, [p.stat().st_ino for p in locks])
        self.assertEqual((self.project / "sources/app/src/main.rs").read_text(), "uncommitted source")
        clean_outputs(self.project)  # Repeated cleanup is harmless.

    def test_downloads_and_vm_disks_require_explicit_flags(self):
        clean_outputs(self.project, downloads=True, vms=True)
        self.assertFalse((self.output / "sources/downloads").exists())
        self.assertFalse((self.output / "vms").exists())
        self.assertTrue((self.output / "verification/results.json").exists())
        self.assertTrue((self.output / "contribution/app/.git").exists())

    def test_dry_run_leaves_every_byte_and_inode_unchanged(self):
        before = {p: (p.stat().st_ino, p.read_bytes()) for p in self.project.rglob("*") if p.is_file()}
        report = clean_outputs(self.project, downloads=True, vms=True, dry_run=True)
        self.assertIn(str(self.output / "vms"), report["planned"])
        self.assertIn(str(self.output / "sources/downloads"), report["planned"])
        self.assertEqual(before, {p: (p.stat().st_ino, p.read_bytes()) for p in self.project.rglob("*") if p.is_file()})

    def test_active_build_bootstrap_package_image_and_vm_block_before_deletion(self):
        for name in ["state/run.lock", "state/locks/package.lock", "locks/image.lock",
                     "bootstrap/work/.bootstrap.lock", "vms/dev/vm.lock", "vms/dev/deploy.lock"]:
            with self.subTest(lock=name):
                path = self.output / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a+") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaisesRegex(BuildError, "running"):
                        clean_outputs(self.project, vms=True)
                    self.assertTrue(all((self.output / name).exists() for name in self.artifacts))

    def test_symlinked_output_control_directories_and_locks_are_rejected(self):
        outside = self.project / "outside"
        outside.mkdir()
        sentinel = outside / "keep"
        sentinel.write_text("important")
        for name in ["apps", "state", "sources", "vms", "state/locks", "state/run.lock"]:
            path = self.output / name
            renamed = path.with_name(path.name + ".saved")
            with self.subTest(path=name):
                path.rename(renamed)
                path.symlink_to(outside)
                try:
                    with self.assertRaisesRegex(BuildError, "symlink"):
                        clean_outputs(self.project, vms=True)
                finally:
                    path.unlink()
                    renamed.rename(path)
                self.assertEqual(sentinel.read_text(), "important")
                self.assertTrue(all((self.output / name).exists() for name in self.artifacts))
        self.output.rename(self.project / "saved-out")
        self.output.symlink_to(outside)
        with self.assertRaisesRegex(BuildError, "symlink"):
            clean_outputs(self.project)
        self.assertEqual(sentinel.read_text(), "important")

    def test_nested_artifact_symlink_does_not_delete_its_target(self):
        sentinel = self.project / "keep"
        sentinel.write_text("important")
        (self.output / "work/package/link").symlink_to(sentinel)
        clean_outputs(self.project)
        self.assertEqual(sentinel.read_text(), "important")

    def test_cli_preview_and_empty_checkout_need_no_build_dependencies(self):
        with patch("sys.stdout", new=io.StringIO()) as output:
            self.assertEqual(main(["--project", str(self.project), "clean", "--dry-run"]), 0)
        self.assertIn('"planned"', output.getvalue())
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(clean_outputs(Path(temporary))["removed"], [])
            self.assertFalse((Path(temporary) / "out").exists())
        # Exercise the executable wrapper from outside the checkout; the only
        # real workspace operation is a read-only preview.
        script = Path(__file__).resolve().parents[1] / "clean"
        result = subprocess.run([str(script), "--dry-run"], cwd=self.project,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"dry_run": true', result.stdout)
