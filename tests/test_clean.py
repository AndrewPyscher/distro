"""Cleanup must remove generated products without losing source or saved VMs."""
from contextlib import redirect_stdout
import fcntl
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from distro_build import cli
from distro_build.clean import clean
from distro_build.model import BuildError


class CleanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="distro-clean-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "checkout with spaces"
        self.project.mkdir()
        self.output = self.project / "out"
        self.stdout = io.StringIO()

    def file(self, name: str) -> Path:
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep or clean this fixture\n")
        return path

    def invoke(self, **options):
        with redirect_stdout(self.stdout):
            return clean(self.project, **options)

    def test_default_clears_all_products_and_caches_preserving_sources_and_vms(self):
        source = self.file("sources/telorgon/uncommitted.rs")
        disk = self.file("out/vms/dev/disk.img")
        for name in ("bootstrap/root/tools/compiler", "packages/example.pkg.tar.gz",
                     "apps/target/object", "images/system.img", "state/run/profile.json",
                     "sources/downloads/archive", ".hidden", "verification/result.json",
                     "a new build directory/file with spaces\nand newline"):
            self.file(f"out/{name}")
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(list(self.output.iterdir()), [self.output / "vms"])
        self.assertTrue(source.is_file())
        self.assertTrue(disk.is_file())
        self.assertIn("100%", self.stdout.getvalue())
        self.assertIn("Ready to rebuild", self.stdout.getvalue())

    def test_all_also_removes_saved_vm_state(self):
        self.file("out/vms/dev/disk.img")
        self.file("out/vms/dev/OVMF_VARS.fd")
        source = self.file("sources/telorgon/Cargo.lock")
        self.invoke(all_outputs=True)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertTrue(source.is_file())

    def test_dry_run_is_read_only_in_both_modes(self):
        disk = self.file("out/vms/dev/disk.img")
        artifact = self.file("out/work/package/binary")
        before = sorted(self.project.rglob("*"))
        for all_outputs in (False, True):
            self.stdout = io.StringIO()
            self.invoke(all_outputs=all_outputs, dry_run=True)
            self.assertEqual(sorted(self.project.rglob("*")), before)
            self.assertTrue(disk.is_file())
            self.assertTrue(artifact.is_file())
            if all_outputs:
                self.assertIn("out/vms:", self.stdout.getvalue())
            else:
                self.assertNotIn("out/vms:", self.stdout.getvalue())
            self.assertIn("No changes made", self.stdout.getvalue())

    def test_missing_or_already_clean_outputs_succeed_without_creating_paths(self):
        self.assertEqual(self.invoke(), 0)
        self.assertFalse(self.output.exists())
        self.output.mkdir()
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_symlinked_output_is_refused(self):
        source = self.file("sources/telorgon/dirty.rs")
        self.output.symlink_to(source.parent, target_is_directory=True)
        with self.assertRaisesRegex(BuildError, "real directory"):
            self.invoke(all_outputs=True)
        self.assertTrue(source.is_file())

    def test_symlinks_inside_output_are_unlinked_without_following(self):
        source = self.file("sources/telorgon/dirty.rs")
        self.file("out/work/binary")
        (self.output / "work/link").symlink_to(source.parent, target_is_directory=True)
        (self.output / "apps").symlink_to(source.parent, target_is_directory=True)
        (self.output / "broken").symlink_to(self.root / "missing")
        (self.output / "vms").symlink_to(source.parent, target_is_directory=True)
        self.invoke(all_outputs=True)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertTrue(source.is_file())

    def test_active_managed_jobs_block_before_any_deletion(self):
        artifact = self.file("out/work/binary")
        for name in ("state/run.lock", "state/locks/app-shell.lock", "locks/image.lock",
                     "vms/dev/vm.lock", "vms/dev/deploy.lock"):
            lock = self.file(f"out/{name}")
            with lock.open("r") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.subTest(name=name), self.assertRaisesRegex(BuildError, "active"):
                    self.invoke(all_outputs=True)
                self.assertTrue(artifact.is_file())
        self.invoke(all_outputs=True)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_deletion_errors_fail_without_claiming_completion(self):
        artifact = self.file("out/work/binary")
        with patch("distro_build.clean.os.unlink", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.invoke()
        self.assertTrue(artifact.is_file())
        self.assertNotIn("100%", self.stdout.getvalue())
        self.assertNotIn("Ready to rebuild", self.stdout.getvalue())

    def test_terminal_progress_updates_in_place(self):
        self.file("out/work/binary")
        with patch.object(self.stdout, "isatty", return_value=True):
            self.invoke()
        self.assertIn("\r[", self.stdout.getvalue())
        self.assertIn("100%", self.stdout.getvalue())

    def test_cli_accepts_explicit_project_and_dry_run(self):
        artifact = self.file("out/packages/example.pkg.tar.gz")
        with redirect_stdout(self.stdout):
            self.assertEqual(cli.main(["--project", str(self.project), "clean", "--all", "--dry-run"]), 0)
        self.assertTrue(artifact.is_file())
        self.assertIn("Including saved VMs", self.stdout.getvalue())

    def test_shell_launcher_cleans_its_checkout_from_another_working_directory(self):
        shutil.copy2(PROJECT / "clean", self.project / "clean")
        shutil.copy2(PROJECT / "build.py", self.project / "build.py")
        shutil.copytree(PROJECT / "src", self.project / "src", ignore=shutil.ignore_patterns("__pycache__"))
        source = self.file("sources/telorgon/dirty.rs")
        self.file("out/work/binary")
        unrelated = self.root / "out/work/keep"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("another checkout's output")
        result = subprocess.run([str(self.project / "clean")], cwd=self.root,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertTrue(source.is_file())
        self.assertTrue(unrelated.is_file())
        self.assertIn("100%", result.stdout)


if __name__ == "__main__":
    unittest.main()
