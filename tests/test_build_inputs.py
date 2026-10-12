"""Exercise mutable contributor inputs and concurrent real package exports."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import os
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build.model import Recipe
from distro_build.runner import build_package
from distro_build.cli import reuse_package_set
from distro_build import cli


class BuildInputsTests(unittest.TestCase):
    def setUp(self):
        context = patch.dict(os.environ, {"DISTRO_CCACHE": "0"})
        context.start()
        self.addCleanup(context.stop)

    def fixture(self, root):
        source = root / "source"
        source.mkdir()
        (source / "README").write_text("source fixture\n")
        cache = root / "out/sources/downloads"
        cache.mkdir(parents=True)
        archive = cache / "example.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(source, arcname="example", recursive=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        engine = root / "src/distro_build"
        engine.mkdir(parents=True)
        (engine / "__init__.py").write_text("")
        recipe = root / "packages/example"
        recipe.mkdir(parents=True)
        (recipe / "package.toml").write_text(f'''schema = 1
[package]
name = "example"
version = "1.0"
revision = 1
arch = "any"
description = "Build isolation regression fixture"
license = "MIT"
[[sources]]
name = "main"
url = "https://example.invalid/example.tar.gz"
filename = "example.tar.gz"
sha256 = "{digest}"
[build]
adapter = "script"
commands = [["python3", "{{recipe}}/build.py"]]
''')
        script = '''from pathlib import Path
import os,time
work=Path(os.environ['CD_WORK_DIR'])
(work/'started').touch()
with (work.parents[2]/'calls').open('a') as stream: stream.write('build\\n')
time.sleep(0.4)
stage=Path(os.environ['CD_STAGE_DIR'])
(stage/'payload').write_text(Path(__file__).read_text())
# ORIGINAL_INPUT
'''
        (recipe / "build.py").write_text(script)
        return Recipe.load(recipe / "package.toml"), script

    def test_recipe_snapshot_survives_contributor_edit_during_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe, original = self.fixture(root)
            with patch("distro_build.runner.seed_report", return_value={"kind": "test-seed"}), ThreadPoolExecutor(1) as pool:
                future = pool.submit(build_package, root, recipe, jobs=1, seed_build=True)
                deadline = time.monotonic() + 5
                while not list((root / "out/work/example").glob("*/started")):
                    if time.monotonic() > deadline:
                        self.fail("fixture build did not start")
                    time.sleep(0.01)
                (recipe.path.parent / "build.py").write_text("raise SystemExit('edited input')\n")
                result = future.result(timeout=5)
            self.assertEqual((Path(result["stage"]) / "payload").read_text(), original)
            inputs = Path(result["provenance"]["frozen_inputs"])
            self.assertEqual((inputs / "packages/example/build.py").read_text(), original)

    def test_concurrent_same_package_builds_share_one_verified_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe, _ = self.fixture(root)
            with patch("distro_build.runner.seed_report", return_value={"kind": "test-seed"}), ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(build_package, root, recipe, jobs=1, seed_build=True) for _ in range(2)]
                results = [future.result(timeout=10) for future in futures]
            self.assertEqual(results[0]["sha256"], results[1]["sha256"])
            self.assertEqual((root / "out/calls").read_text(), "build\n")
            state = json.loads((root / "out/state/packages/example.json").read_text())
            self.assertEqual(state["sha256"], results[0]["sha256"])

    def test_rust_seed_changes_invalidate_build_and_cached_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe, _ = self.fixture(root)
            recipe.build["rust_toolchain"] = "nightly-2026-10-06"
            with patch("distro_build.runner.seed_report", return_value={"kind": "test-seed"}), \
                    patch("distro_build.runner.rust_build_seed", return_value={"compiler": "first"}) as rust:
                first = build_package(root, recipe, jobs=1, seed_build=True)
                self.assertIsNotNone(cli.cached_package(root, recipe, {"kind": "test-seed"}, [], seed_build=True))
                rust.return_value = {"compiler": "changed"}
                self.assertIsNone(cli.cached_package(root, recipe, {"kind": "test-seed"}, [], seed_build=True))
                second = build_package(root, recipe, jobs=1, seed_build=True)
            self.assertNotEqual(first["build_identity"], second["build_identity"])
            self.assertEqual(second["provenance"]["seed"]["rust"], {"compiler": "changed"})
            self.assertEqual((root / "out/calls").read_text(), "build\nbuild\n")

    def test_compiler_cache_dispatch_is_used_and_recorded_by_package_builder(self):
        from distro_build.compiler_cache import seed_input
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe, _ = self.fixture(root)
            cache = root / "ccache"
            dispatch = root / "dispatch"
            cache.write_text("#!/usr/bin/python3\nimport os,sys\n"
                             f"open({str(dispatch)!r},'w').write(sys.argv[1])\n"
                             "os.execv(sys.argv[1],sys.argv[1:])\n")
            cache.chmod(0o755)
            (recipe.path.parent / "build.py").write_text('''from pathlib import Path
import os,subprocess
source = Path(os.environ['CD_SOURCE_DIR']) / 'tiny.c'
source.write_text('int value(void) { return 42; }\\n')
subprocess.run([os.environ['CD_CC'], '-c', str(source), '-o',
                str(Path(os.environ['CD_STAGE_DIR']) / 'value.o')], check=True)
''')
            with patch.dict(os.environ, {"DISTRO_CCACHE": str(cache)}):
                seed = {"kind": "test-seed", "compiler_cache": seed_input()}
                with patch("distro_build.runner.seed_report", return_value=seed):
                    result = build_package(root, recipe, jobs=1, seed_build=True)
            self.assertEqual(dispatch.read_text(), "/usr/bin/gcc")
            self.assertEqual(result["provenance"]["seed"]["compiler_cache"], seed["compiler_cache"])
            self.assertEqual(result["provenance"]["supplied_compiler"]["path"], "/usr/bin/gcc")
            self.assertTrue((Path(result["stage"]) / "value.o").read_bytes().startswith(b"\x7fELF"))

    def test_run_reuses_verified_packages_but_rejects_changed_inputs_or_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe, original = self.fixture(root)
            compiler = root / "out/bootstrap/root/tools/bin/x86_64-custom-linux-gnu-gcc"
            compiler.parent.mkdir(parents=True)
            compiler.touch()
            seed = {"kind": "test-seed"}
            with patch("distro_build.runner.seed_report", return_value=seed), patch("distro_build.runner.check_bootstrap") as audit:
                result = build_package(root, recipe, jobs=1)
                self.assertTrue(reuse_package_set(root, {recipe.name: recipe}, [recipe]))
                other = root / "packages/consumer"
                other.mkdir()
                (other / "package.toml").write_text(recipe.path.read_text().replace('name = "example"', 'name = "consumer"'))
                (other / "build.py").write_text(original)
                build_package(root, Recipe.load(other / "package.toml"), jobs=1)
                audit.reset_mock()
                self.assertEqual(cli.main(["--project", str(root), "build", "example", "consumer"], quiet=True), 0)
                audit.assert_called_once()
                (recipe.path.parent / "build.py").write_text(original + "# changed recipe\n")
                self.assertFalse(reuse_package_set(root, {recipe.name: recipe}, [recipe]))
                (recipe.path.parent / "build.py").write_text(original)
                archive = Path(result["path"])
                saved = archive.read_bytes()
                archive.write_bytes(b"tampered archive")
                self.assertFalse(reuse_package_set(root, {recipe.name: recipe}, [recipe]))
                archive.write_bytes(saved)
                with patch("distro_build.runner.seed_report", return_value={"kind": "changed-seed"}):
                    self.assertFalse(reuse_package_set(root, {recipe.name: recipe}, [recipe]))


if __name__ == "__main__":
    unittest.main()
