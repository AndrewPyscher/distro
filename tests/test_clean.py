"""Cleanup must remove build outputs while preserving source and saved work."""
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
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
        capture = patch("sys.stderr", new=io.StringIO())
        self.stderr = capture.start()
        self.addCleanup(capture.stop)
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

    def test_all_cli_alias_removes_downloads_and_vms_preserving_evidence(self):
        with patch("sys.stdout", new=io.StringIO()) as output:
            self.assertEqual(main(["--project", str(self.project), "clean", "--all"]), 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report["downloads_removed"])
        self.assertTrue(report["saved_vms_removed"])
        self.assertFalse((self.output / "sources/downloads").exists())
        self.assertFalse((self.output / "vms").exists())
        self.assertTrue((self.output / "verification/results.json").exists())
        self.assertTrue((self.output / "contribution/app/.git").exists())

    def test_shell_launcher_uses_its_checkout_with_spaces_from_another_directory(self):
        repository = Path(__file__).resolve().parents[1]
        checkout = self.project / "checkout with spaces"
        checkout.mkdir()
        for name in ("clean", "build.py"):
            shutil.copy2(repository / name, checkout / name)
        shutil.copytree(repository / "src", checkout / "src", ignore=shutil.ignore_patterns("__pycache__"))
        artifact = checkout / "out/work/object"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("generated")
        result = subprocess.run([str(checkout / "clean")], cwd=self.project,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(artifact.exists())
        self.assertTrue(all((self.output / name).exists() for name in self.artifacts))
        self.assertIn("100%", result.stderr)
        self.assertIn('"entries_removed"', result.stdout)

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

    def test_live_progress_keeps_json_stdout_and_persists_log(self):
        with patch("sys.stdout", new=io.StringIO()) as output:
            self.assertEqual(main(["--project", str(self.project), "clean"]), 0)
        report = json.loads(output.getvalue())
        text = self.stderr.getvalue()
        self.assertIn("Cleaning out/work", text)
        self.assertIn("Finished out/work", text)
        self.assertIn("100%", text)
        self.assertIn("entries removed", text)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\r", text)
        self.assertGreater(report["entries_removed"], len(report["removed"]))
        log = Path(report["log"])
        self.assertEqual(log.parent, self.output / "verification/clean")
        self.assertIn("Cleanup complete", log.read_text())
        self.assertIn("Cleaning out/work", log.read_text())
        self.assertNotIn("\x1b", log.read_text())
        second = clean_outputs(self.project)
        self.assertNotEqual(second["log"], str(log))
        self.assertTrue(log.exists())

    def test_large_single_target_reports_entries_before_target_finishes(self):
        from distro_build.cleanup import CleanupProgress, remove_artifact
        directory = self.output / "large"
        directory.mkdir()
        for number in range(10):
            (directory / str(number)).touch()
        logs = self.output / "verification"
        # A controlled clock exercises periodic updates without slowing deletion.
        with patch("distro_build.cleanup.time.monotonic", side_effect=range(100)):
            with CleanupProgress(self.project, 1, logs) as status:
                status.begin(directory)
                remove_artifact(directory, status)
                status.done(directory)
        text = self.stderr.getvalue()
        self.assertIn("0% (0/1 targets) 1 entries removed", text)
        self.assertIn("Removed out/large/", text)
        self.assertIn("100% (1/1 targets) 11 entries removed", text)

    def test_terminal_gets_live_bar_but_saved_log_has_no_controls(self):
        self.stderr.isatty = lambda: True
        with patch("distro_build.cleanup.time.monotonic", side_effect=range(1000)):
            report = clean_outputs(self.project)
        self.assertIn("\r\x1b[2K", self.stderr.getvalue())
        self.assertIn("100%", self.stderr.getvalue())
        self.assertNotIn("\x1b", Path(report["log"]).read_text())

    def test_partial_failure_logs_error_and_never_claims_completion(self):
        unlink = os.unlink

        def fail(name, *args, **kwargs):
            if str(name) == "object":
                raise PermissionError("fixture refuses deletion")
            return unlink(name, *args, **kwargs)

        with patch("distro_build.cleanup.os.unlink", side_effect=fail):
            with self.assertRaisesRegex(PermissionError, "fixture refuses deletion"):
                clean_outputs(self.project)
        logs = list((self.output / "verification/clean").glob("*.log"))
        self.assertEqual(len(logs), 1)
        text = logs[0].read_text()
        self.assertIn("FAILED at out/apps/incremental/object", text)
        self.assertNotIn("Cleanup complete", text)
        self.assertTrue((self.output / "apps/incremental/object").exists())

    def test_interruption_is_recorded_without_deleting_remaining_targets(self):
        with patch("distro_build.cleanup.remove_artifact", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                clean_outputs(self.project)
        log = next((self.output / "verification/clean").glob("*.log"))
        self.assertIn("Interrupted at out/apps", log.read_text())
        self.assertNotIn("Cleanup complete", log.read_text())
        self.assertTrue(all((self.output / name).exists() for name in self.artifacts))

    def test_redirected_log_directories_fail_before_artifact_deletion(self):
        outside = self.project / "outside"
        outside.mkdir()
        (self.output / "verification/clean").symlink_to(outside)
        with self.assertRaisesRegex(BuildError, "symlink"):
            clean_outputs(self.project)
        self.assertTrue(all((self.output / name).exists() for name in self.artifacts))
        self.assertEqual(list(outside.iterdir()), [])

    def test_directory_symlink_and_dangling_link_are_unlinked_without_traversal(self):
        outside = self.project / "outside"
        outside.mkdir()
        (outside / "keep").write_text("saved")
        (self.output / "work/package/linked-dir").symlink_to(outside, target_is_directory=True)
        (self.output / "work/package/dangling").symlink_to(self.project / "missing")
        clean_outputs(self.project)
        self.assertEqual((outside / "keep").read_text(), "saved")

    def test_dry_run_creates_no_progress_log(self):
        report = clean_outputs(self.project, dry_run=True)
        self.assertNotIn("log", report)
        self.assertFalse((self.output / "verification/clean").exists())
        self.assertEqual(self.stderr.getvalue(), "")
