"""Build progress follows real completions and stays live during blocking work."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build import cli, progress, runner


class Terminal(io.StringIO):
    def __init__(self):
        super().__init__()
        self.refresh = threading.Event()

    def isatty(self):
        return True

    def write(self, value):
        result = super().write(value)
        if value.startswith("\r\033[2K"):
            self.refresh.set()
        return result


class RunProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="run-progress-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.stream = io.StringIO()
        self.enterContext(patch("sys.stderr", self.stream))

    def records(self, reporter):
        return [json.loads(line) for line in reporter.path.read_text().splitlines()]

    def finish(self, reporter):
        for key, _ in reporter.stages:
            progress.complete(key)

    def test_package_counts_advance_only_after_actual_completion(self):
        with progress.RunProgress(self.project, "desktop-dev") as reporter:
            progress.stage("build")
            progress.item("linux", 1, 2)
            self.assertEqual(reporter.fraction, 0)
            progress.detail("Installing dependency sysroot")
            progress.event({"event": "command", "argv": ["make", "-j8"], "log": self.project / "build.log"})
            self.assertIn("linux (1/2) | make", reporter.text)
            progress.item("linux", 1, 2, done=True)
            self.assertEqual(reporter.fraction, 0.5)
            progress.item("busybox", 2, 2)
            self.assertEqual(reporter.fraction, 0.5)
            self.assertIn("busybox (2/2)", self.stream.getvalue())
            self.assertNotIn("100%", self.stream.getvalue())
            self.finish(reporter)
        self.assertIn("100% 13/13 steps", self.stream.getvalue())
        self.assertFalse(reporter.thread.is_alive())

    def test_bootstrap_log_updates_include_real_stage_names_and_completions(self):
        manifest = self.project / "bootstrap/stages.toml"
        manifest.parent.mkdir()
        manifest.write_text('[[stages]]\nname="binutils"\n[[stages]]\nname="gcc"\n')
        log = self.project / "out/bootstrap.log"
        with progress.RunProgress(self.project, "desktop-dev") as reporter:
            progress.stage("bootstrap")
            progress.event({"event": "command", "argv": [sys.executable, "run-stage.py"], "log": log})
            # Existing runner log format, including a partial line between reads.
            log.write_text("binutils: building; log /fixture/binutils.log\nbinutils: complete in 1s\ngcc: buil")
            with reporter.lock:
                reporter._read_bootstrap()
                self.assertEqual(reporter.fraction, 0.5)
                self.assertNotIn("gcc (2/2)", self.stream.getvalue())
                with log.open("a") as stream:
                    stream.write("ding; log /fixture/gcc.log\n")
                reporter._read_bootstrap()
                self.assertIn("gcc (2/2)", self.stream.getvalue())
                self.assertEqual(reporter.fraction, 0.5)
            self.finish(reporter)
        stages = [row for row in self.records(reporter) if row.get("event") == "progress-bootstrap"]
        self.assertEqual([(row["stage"], row["done"]) for row in stages],
                         [("binutils", False), ("binutils", True), ("gcc", False)])

    def test_parallel_package_cli_keeps_worker_events_and_counts_out_of_order_completions(self):
        recipes = {name: SimpleNamespace(name=name, dependencies={"target": dependencies})
                   for name, dependencies in [("first", []), ("second", []), ("cached", ["first", "second"])]}
        rendezvous = threading.Barrier(2)
        second_done = threading.Event()
        original_emit = cli.emit

        def emit(value):
            original_emit(value)
            if value.get("event") == "package-done" and value["package"] == "second":
                second_done.set()

        def build(project, recipe, **options):
            progress.detail(f"Compiling {recipe.name}")
            rendezvous.wait(timeout=3)
            if recipe.name == "first":
                self.assertTrue(second_done.wait(3))
                self.assertEqual(reporter.fraction, 1 / 3)
            return {"path": f"/fixture/{recipe.name}"}

        def cached(project, recipe, *args, **options):
            return {"path": "/fixture/cached"} if recipe.name == "cached" else None

        with progress.RunProgress(self.project, "desktop-dev") as reporter:
            progress.stage("build")
            with patch.object(cli, "catalog", return_value=recipes), \
                 patch.object(runner, "seed_report", return_value={}), \
                 patch.object(cli, "cached_package", side_effect=cached), \
                 patch.object(cli, "package_dependencies", return_value=[]), \
                 patch.object(runner, "build_package", side_effect=build), \
                 patch.object(cli, "emit", side_effect=emit), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(cli.main(["--project", str(self.project), "build", "--seed",
                                           "--jobs", "4", "--package-workers", "2"]), 0)
            self.assertEqual(reporter.fraction, 1)
            self.assertEqual(reporter.packages_active, set())
            self.assertIn("3/3 complete", reporter.text)
            self.finish(reporter)
        records = self.records(reporter)
        self.assertEqual([row["package"] for row in records if row.get("event") == "package-done"],
                         ["second", "first", "cached"])
        self.assertTrue(any(row.get("detail") == "Compiling first" for row in records))
        self.assertTrue(any(row.get("detail") == "Compiling second" for row in records))

    def test_verified_cache_skips_are_reported_without_running_the_action(self):
        source = self.project / "source"
        source.write_text("input")
        artifact = self.project / "artifact"
        cache = cli.DevelopmentCache(self.project, "desktop-dev")
        calls = []

        def action():
            calls.append("built")
            artifact.write_text("built output")

        with patch.object(cli, "emit"):
            cache.run("loader", lambda: [source], lambda _: [artifact], action)
        with progress.RunProgress(self.project, "desktop-dev") as reporter:
            cache.run("loader", lambda: [source], lambda _: [artifact], action)
            self.assertEqual(calls, ["built"])
            self.assertIn("Reused verified cache", self.stream.getvalue())
            self.finish(reporter)

    def test_terminal_heartbeat_continues_without_command_output(self):
        terminal = Terminal()
        with patch("sys.stderr", terminal), patch.dict("os.environ", {"TERM": "xterm"}):
            with progress.RunProgress(self.project, "console") as reporter:
                terminal.refresh.clear()
                self.assertTrue(terminal.refresh.wait(2), "no heartbeat during idle compiler work")
                self.assertIn("\r\033[2K", terminal.getvalue())
                self.finish(reporter)
            self.assertFalse(reporter.thread.is_alive())

    def test_redirected_progress_is_plain_and_preserves_structured_events(self):
        with progress.RunProgress(self.project, "systemd") as reporter:
            cli.emit({"event": "command", "argv": ["make", "-j8"], "log": self.project / "build.log"})
            progress.detail("Writing bootable OS disk")
            self.finish(reporter)
        self.assertNotIn("\r", self.stream.getvalue())
        self.assertNotIn("\033", self.stream.getvalue())
        self.assertIn("100% 11/11 steps", self.stream.getvalue())
        self.assertTrue(any(row.get("argv") == ["make", "-j8"] for row in self.records(reporter)))
        self.assertTrue(any(row.get("detail") == "Writing bootable OS disk" for row in self.records(reporter)))

    def test_narrow_terminal_keeps_the_current_application_visible_without_wrapping(self):
        terminal = Terminal()
        with patch("sys.stderr", terminal), patch.dict("os.environ", {"TERM": "xterm"}), \
             patch.object(progress.shutil, "get_terminal_size", return_value=os.terminal_size((80, 24))):
            with progress.RunProgress(self.project, "desktop-dev") as reporter:
                progress.stage("apps")
                progress.item("telorgon-file-explorer", 2, 4)
                line = terminal.getvalue().split("\r\033[2K")[-1]
                self.assertLess(len(line), 80)
                self.assertIn("telorgon-file-explorer (2/4)", line)
                self.finish(reporter)

    def test_failures_and_interruptions_stop_before_completion_and_restore_output(self):
        for error in (RuntimeError("compiler failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.stream.seek(0)
                self.stream.truncate()
                with self.assertRaises(type(error)):
                    with progress.RunProgress(self.project, "console") as reporter:
                        progress.stage("image")
                        raise error
                self.assertNotIn("100%", self.stream.getvalue())
                self.assertFalse(reporter.thread.is_alive())
                self.assertFalse(progress.event({"event": "outside-run"}))

    def test_disabled_progress_has_no_files_threads_or_output(self):
        with progress.RunProgress(self.project, "console", enabled=False) as reporter:
            progress.stage("bootstrap")
            self.assertFalse(progress.event({"event": "command"}))
        self.assertFalse((self.project / "out").exists())
        self.assertIsNone(reporter.thread)
        self.assertEqual(self.stream.getvalue(), "")

    def test_commands_still_run_and_keep_compiler_logs(self):
        log = self.project / "out/compiler.log"
        with progress.RunProgress(self.project, "console") as reporter:
            progress.stage("build")
            runner.run([sys.executable, "-c", "print('compiler output fixture')"],
                       self.project, {}, log)
            self.assertIn("compiler output fixture", log.read_text())
            self.finish(reporter)
        self.assertTrue(any(row.get("event") == "command" for row in self.records(reporter)))


if __name__ == "__main__":
    unittest.main()
