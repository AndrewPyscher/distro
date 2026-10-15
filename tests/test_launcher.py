"""Run the real entry points against local Git upstreams, without OS builds."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
CANONICAL = "https://github.com/WIPOperatingSystemName/distro.git"


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="distro-launcher-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.origin = self.root / "origin"
        self.local = self.root / "local"
        self.git(self.root, "init", "-b", "main", str(self.origin))
        self.git(self.origin, "config", "user.name", "Fixture")
        self.git(self.origin, "config", "user.email", "fixture@example.invalid")
        for name in ("build.py", "run", "src/distro_build/__init__.py",
                     "src/distro_build/launcher.py", "src/distro_build/upstream.py",
                     "src/distro_build/source_projects.py"):
            destination = self.origin / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT / name, destination)
        self.write_cli("old")
        (self.origin / ".gitignore").write_text("__pycache__/\n")
        (self.origin / "tracked").write_text("initial")
        self.commit(self.origin, "Initial launcher")
        self.git(self.root, "clone", str(self.origin), str(self.local))
        self.git(self.local, "remote", "set-url", "origin", CANONICAL)
        # Keep the real canonical-origin check; transport stays entirely local.
        self.git(self.local, "config", f"url.{self.origin}.insteadOf", CANONICAL)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        transport = self.bin / "git"
        # get-url expands insteadOf. Expose the declared URL to the origin check
        # while real Git handles every transport/history operation locally.
        transport.write_text(
            f"#!{sys.executable}\nimport os, sys\n"
            "args = sys.argv[1:]\n"
            "if args[-3:] == ['remote', 'get-url', 'origin']:\n"
            "    args = args[:-3] + ['config', '--get', 'remote.origin.url']\n"
            f"os.execv({shutil.which('git')!r}, ['git', *args])\n"
        )
        transport.chmod(0o755)
        self.initial = self.git(self.local, "rev-parse", "HEAD")

    def git(self, path, *arguments):
        return subprocess.run(["git", "-C", str(path), *arguments], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, path, message):
        self.git(path, "add", ".")
        self.git(path, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-m", message)

    def write_cli(self, version):
        (self.origin / "src/distro_build/cli.py").write_text(
            "import json, os\nfrom pathlib import Path\n"
            "def main(argv):\n"
            f"    print(json.dumps({{'version': {version!r}, 'arguments': argv,\n"
            "        'packages': sorted(p.name for p in Path('packages').glob('*')),\n"
            "        'catalog': Path('source-projects.toml').read_text() if Path('source-projects.toml').exists() else '',\n"
            "        'reloaded': os.environ.get('DISTRO_TEST_UPDATED_LAUNCHER')}))\n"
            "    return 0\n"
        )

    def advance(self):
        self.write_cli("new")
        (self.origin / "tracked").write_text("upstream update")
        (self.origin / "packages/new-app").mkdir(parents=True, exist_ok=True)
        (self.origin / "packages/new-app/package.toml").write_text('name = "new-app"\n')
        (self.origin / "source-projects.toml").write_text('new-component = "registered"\n')
        launcher = self.origin / "src/distro_build/launcher.py"
        with launcher.open("a") as stream:
            stream.write('\nos.environ["DISTRO_TEST_UPDATED_LAUNCHER"] = "yes"\n')
        self.commit(self.origin, "Add app, component and updated coordinator")
        return self.git(self.origin, "rev-parse", "HEAD")

    def launch(self, *arguments, wrapper=False):
        command = [sys.executable, str(self.local / ("run" if wrapper else "build.py"))]
        if not wrapper:
            command.append("run")
        return subprocess.run([*command, *arguments], cwd=self.local,
                              env={**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]},
                              capture_output=True, text=True, timeout=15)

    def test_both_entry_points_update_and_reload_before_using_new_inputs(self):
        for wrapper in (False, True):
            with self.subTest(wrapper=wrapper):
                latest = self.advance()
                result = self.launch("--new-upstream-option", "value", "--name", "fresh", wrapper=wrapper)
                self.assertEqual(result.returncode, 0, result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(receipt["version"], "new")
                self.assertEqual(receipt["packages"], ["new-app"])
                self.assertIn("new-component", receipt["catalog"])
                self.assertEqual(receipt["reloaded"], "yes")
                self.assertIn("--new-upstream-option", receipt["arguments"])
                self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), latest)

    def test_staged_and_untracked_work_survives_update_on_current_branch(self):
        self.git(self.local, "switch", "-c", "contribution")
        (self.local / "draft").write_text("staged work")
        self.git(self.local, "add", "draft")
        (self.local / "notes").write_text("untracked notes")
        status = self.git(self.local, "status", "--porcelain")
        self.advance()
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.local, "status", "--porcelain"), status)
        self.assertEqual(self.git(self.local, "branch", "--show-current"), "contribution")
        self.assertEqual((self.local / "draft").read_text(), "staged work")
        self.assertEqual((self.local / "notes").read_text(), "untracked notes")

    def test_discovers_upstream_default_branch_instead_of_assuming_main(self):
        self.git(self.origin, "branch", "-m", "trunk")
        latest = self.advance()
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), latest)
        self.assertEqual(self.git(self.local, "branch", "--show-current"), "main")
        self.assertIn('"branch": "trunk"', result.stderr)

    def test_local_commits_ahead_of_upstream_are_preserved(self):
        (self.local / "local-contribution").write_text("keep me")
        self.commit(self.local, "Local contribution")
        head = self.git(self.local, "rev-parse", "HEAD")
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), head)
        self.assertEqual(json.loads(result.stdout)["version"], "old")

    def test_project_override_updates_selected_checkout_and_reloads_its_cli(self):
        latest = self.advance()
        arguments = ["--project", str(self.local), "run", "--name", "fresh"]
        result = subprocess.run([sys.executable, str(PROJECT / "build.py"), *arguments],
                                cwd=self.local, capture_output=True, text=True, timeout=15,
                                env={**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), latest)
        self.assertEqual(json.loads(result.stdout)["arguments"], arguments)
        self.assertEqual(json.loads(result.stdout)["version"], "new")

    def test_other_commands_do_not_update_the_checkout(self):
        self.advance()
        self.origin.rename(self.root / "unavailable")
        result = subprocess.run([sys.executable, str(self.local / "build.py"), "validate"],
                                cwd=self.local, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), self.initial)

    def test_overlapping_edit_stops_before_cli_without_losing_work(self):
        (self.local / "tracked").write_text("local draft")
        self.advance()
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("without overwriting local work", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), self.initial)
        self.assertEqual((self.local / "tracked").read_text(), "local draft")

    def test_divergent_history_stops_without_reset_or_cli(self):
        (self.local / "local-contribution").write_text("keep me")
        self.commit(self.local, "Local contribution")
        head = self.git(self.local, "rev-parse", "HEAD")
        self.advance()
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("history diverges", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), head)

    def test_offline_and_help_do_not_fetch_or_advance_newer_cached_upstream(self):
        self.advance()
        self.git(self.local, "fetch", "origin")
        self.origin.rename(self.root / "unavailable")
        for flag in ("--offline", "--help", "-h"):
            with self.subTest(flag=flag):
                result = self.launch(flag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["version"], "old")
                self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), self.initial)
                self.assertNotIn("distro-sync", result.stderr)

    def test_wrong_origin_and_network_failure_stop_without_using_stale_cli(self):
        self.git(self.local, "remote", "set-url", "origin", str(self.origin))
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("canonical", result.stderr)
        self.assertEqual(result.stdout, "")
        self.git(self.local, "remote", "set-url", "origin", CANONICAL)
        self.origin.rename(self.root / "unavailable")
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("git ls-remote failed", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
