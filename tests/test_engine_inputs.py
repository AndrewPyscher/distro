"""Code changes invalidate only the stages and recipes which consume them."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build.build_inputs import engine_inputs
from distro_build.runner import build_identity


class EngineInputsTests(unittest.TestCase):
    def test_native_identity_tracks_transitive_helpers_not_development_or_app_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = root / "src/distro_build"
            engine.mkdir(parents=True)
            (engine / "__init__.py").write_text("")
            (engine / "runner.py").write_text("from .packaging import export_package\n")
            (engine / "packaging").mkdir()
            (engine / "packaging/__init__.py").write_text("from .archive import export_package\n")
            (engine / "packaging/archive.py").write_text("export_package = None\n")
            (engine / "packaging/native_install.c").write_text("/* source input */\n")
            (engine / "helper.py").write_text("from . import nested\n")
            (engine / "nested.py").write_text("VALUE = 1\n")
            recipe = root / "packages/native"
            recipe.mkdir(parents=True)
            (recipe / "package.toml").touch()
            (recipe / "build.py").write_text("from distro_build.helper import build\n")
            item = SimpleNamespace(path=recipe / "package.toml", sources=[], build={})

            def identity():
                return build_identity(root, item, {}, [], root / "stamps", seed_build=True)

            original = identity()
            (engine / "development.py").write_text("# New helper unrelated to native compilation\n")
            app = root / "packages/new-app"
            app.mkdir()
            (app / "application.toml").write_text("# Application registration\n")
            self.assertEqual(identity(), original)
            (engine / "nested.py").write_text("VALUE = 2\n")
            self.assertNotEqual(identity(), original)
            (engine / "nested.py").write_text("VALUE = 1\n")
            (engine / "packaging/native_install.c").write_text("/* changed source input */\n")
            self.assertNotEqual(identity(), original)
            (engine / "packaging/native_install.c").write_text("/* source input */\n")
            (engine / "packaging/archive.py").write_text("export_package = 'changed'\n")
            self.assertNotEqual(identity(), original)

    def test_boot_stage_is_independent_of_native_and_cli_helpers(self):
        root = Path(__file__).resolve().parents[1]
        files = engine_inputs(root, ["boot"])
        self.assertIn(root / "src/distro_build/boot.py", files)
        for name in ("cli", "development", "upstream", "runner", "desktop_native"):
            self.assertNotIn(root / f"src/distro_build/{name}.py", files)

    def test_removed_or_new_local_helper_changes_inventory(self):
        from distro_build.cli import DevelopmentCache
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = root / "src/distro_build"
            engine.mkdir(parents=True)
            (engine / "runner.py").write_text("from .future_helper import build\n")
            first = DevelopmentCache.inventory(engine_inputs(root, ["runner"]))
            (engine / "future_helper.py").write_text("build = None\n")
            self.assertNotEqual(first, DevelopmentCache.inventory(engine_inputs(root, ["runner"])))

    def test_computed_imports_use_conservative_consumer_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = root / "src/distro_build"
            engine.mkdir(parents=True)
            (engine / "consumer.py").write_text("import importlib\nimportlib.import_module(module_name)\n")
            (engine / "future.py").write_text("VALUE = 1\n")
            (engine / "static.py").write_text("VALUE = 2\n")
            self.assertIn(engine / "future.py", engine_inputs(root, ["consumer"]))
            self.assertNotIn(engine / "future.py", engine_inputs(root, ["static"]))
