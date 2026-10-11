"""Exercise live-main selection with real local repositories and pending work."""
from pathlib import Path
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build import upstream, cli, apps, source_bundle


class SourceSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.origin = self.root / "origin"
        self.local = self.root / "sources/component"
        self.git(self.root, "init", "-b", "main", str(self.origin))
        self.git(self.origin, "config", "user.name", "Fixture")
        self.git(self.origin, "config", "user.email", "fixture@example.invalid")
        (self.origin / "code").write_text("initial")
        self.git(self.origin, "add", ".")
        self.git(self.origin, "commit", "-m", "Initial")
        self.initial = self.git(self.origin, "rev-parse", "HEAD")

    def git(self, path, *args):
        return subprocess.run(["git", "-C", str(path), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def sync(self, **options):
        return upstream.synchronize_repository(self.local, str(self.origin), **options)

    def advance(self):
        (self.origin / "code").write_text("new upstream")
        self.git(self.origin, "commit", "-am", "Upstream update")
        return self.git(self.origin, "rev-parse", "HEAD")

    def test_fresh_clone_and_existing_detached_checkout_follow_main(self):
        self.assertEqual(self.sync()["head"], self.initial)
        self.git(self.local, "switch", "--detach")
        self.git(self.local, "branch", "-D", "main")
        latest = self.advance()
        result = self.sync()
        self.assertEqual(result["head"], latest)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(self.git(self.local, "branch", "--show-current"), "main")

    def test_unrelated_staged_and_untracked_work_survives_fast_forward(self):
        self.sync()
        self.git(self.local, "switch", "-c", "contribution")
        (self.local / "draft").write_text("staged local edit")
        self.git(self.local, "add", "draft")
        (self.local / "notes").write_text("untracked local notes")
        status = self.git(self.local, "status", "--porcelain")
        latest = self.advance()
        self.assertEqual(self.sync()["head"], latest)
        self.assertEqual(self.git(self.local, "status", "--porcelain"), status)
        self.assertEqual(self.git(self.local, "branch", "--show-current"), "contribution")
        self.assertEqual((self.local / "draft").read_text(), "staged local edit")
        self.assertEqual((self.local / "notes").read_text(), "untracked local notes")

    def test_overlapping_dirty_work_blocks_update_without_losing_any_bytes(self):
        self.sync()
        (self.local / "code").write_text("local draft")
        self.advance()
        with self.assertRaisesRegex(RuntimeError, "without overwriting local work"):
            self.sync()
        self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), self.initial)
        self.assertEqual((self.local / "code").read_text(), "local draft")

    def test_divergent_commits_require_deliberate_merge(self):
        self.sync()
        (self.local / "draft").write_text("local contribution")
        self.git(self.local, "add", "draft")
        self.git(self.local, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-m", "Contribution")
        local_head = self.git(self.local, "rev-parse", "HEAD")
        self.advance()
        with self.assertRaisesRegex(RuntimeError, "history diverges"):
            self.sync()
        self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), local_head)
        self.assertEqual((self.local / "draft").read_text(), "local contribution")

    def test_offline_does_not_fetch_or_move_even_when_cached_reference_is_newer(self):
        self.sync()
        self.advance()
        self.git(self.local, "fetch", "origin")
        with patch.object(upstream, "git", wraps=upstream.git) as commands:
            self.assertEqual(self.sync(offline=True)["head"], self.initial)
        self.assertFalse(any(call.args[1] in {"fetch", "merge", "switch"} for call in commands.call_args_list))

    def test_missing_checkout_offline_and_wrong_origin_are_actionable(self):
        with self.assertRaisesRegex(RuntimeError, "sources sync online"):
            self.sync(offline=True)
        self.sync()
        with self.assertRaisesRegex(RuntimeError, "canonical"):
            upstream.synchronize_repository(self.local, "https://example.invalid/other")
        self.assertEqual(self.git(self.local, "rev-parse", "HEAD"), self.initial)

    def test_nested_cli_session_updates_once_but_next_invocation_fetches_again(self):
        record = {"component": {"repository": str(self.origin), "branch": "main"}}
        with patch.object(upstream, "catalog", return_value=record), upstream.session():
            self.assertEqual(upstream.synchronize(self.root)["repositories"][0]["head"], self.initial)
            latest = self.advance()
            with upstream.session():
                self.assertEqual(upstream.synchronize(self.root)["repositories"][0]["head"], self.initial)
        with patch.object(upstream, "catalog", return_value=record), upstream.session():
            self.assertEqual(upstream.synchronize(self.root)["repositories"][0]["head"], latest)

    def test_explicit_portable_bundle_is_replayed_without_git_updates(self):
        bundle = self.root / "bundle"
        bundle.mkdir()
        (bundle / "source-manifest.json").write_text("{}")
        with patch.object(upstream, "synchronize_repository") as sync:
            result = upstream.synchronize(self.root, bundle)
        self.assertEqual(result["action"], "portable-source-replay")
        sync.assert_not_called()

    def test_apps_build_updates_and_snapshots_current_source_instead_of_reusing_old_manifest(self):
        calls = []
        with patch.object(upstream, "synchronize", side_effect=lambda *a, **k: calls.append("sync")), \
             patch.object(apps, "prepare", side_effect=lambda *a, **k: calls.append("snapshot")) as prepare, \
             patch.object(apps, "build_app", side_effect=lambda *a, **k: calls.append("build")) as build, \
             patch.object(cli, "emit"):
            result = cli.main(["--project", str(self.root), "apps", "build", "settings",
                               "--source-root", str(self.local), "--offline"])
        self.assertEqual(result, 0)
        self.assertEqual(calls, ["sync", "snapshot", "build"])
        prepare.assert_called_once_with(self.root, source_root=self.local)
        self.assertTrue(build.call_args.kwargs["offline"])

    def test_apps_build_default_fetches_main_and_locked_cargo_dependencies(self):
        with patch.object(upstream, "synchronize") as sync, \
             patch.object(apps, "prepare"), patch.object(apps, "build_app") as build, \
             patch.object(cli, "emit"):
            self.assertEqual(cli.main(["--project", str(self.root), "apps", "build", "settings"]), 0)
        self.assertFalse(sync.call_args.kwargs["offline"])
        self.assertFalse(build.call_args.kwargs["offline"])

    def test_source_export_stdout_remains_one_json_receipt_when_sync_emits_status(self):
        def sync(*args, emit, **kwargs):
            emit({"event": "source-sync-start", "source": "component"})
            emit({"event": "source-sync-done", "source": "component"})
        with patch.object(upstream, "synchronize", side_effect=sync), \
             patch.object(source_bundle, "export_bundle", return_value={"archive": "bundle.tar.xz", "sha256": "hash"}), \
             patch("sys.stdout", new=io.StringIO()) as output, \
             patch("sys.stderr", new=io.StringIO()) as diagnostics:
            self.assertEqual(cli.main(["--project", str(self.root), "source-bundle", "export"]), 0)
        self.assertEqual(json.loads(output.getvalue())["archive"], "bundle.tar.xz")
        self.assertIn("source-sync-done", diagnostics.getvalue())
