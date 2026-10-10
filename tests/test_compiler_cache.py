"""Exercise cache dispatch with a real compiler and preserve sysroot guards."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build import compiler_cache
from distro_build.desktop_native import _link_wrapper
from distro_build.model import BuildError


class CompilerCacheTests(unittest.TestCase):
    def test_optional_selection_and_seed_changes_follow_executable_bytes(self):
        with patch.dict(os.environ, {"DISTRO_CCACHE": "0"}):
            self.assertIsNone(compiler_cache.executable())
        with patch.dict(os.environ, {"DISTRO_CCACHE": "/missing/ccache"}):
            with self.assertRaises(BuildError):
                compiler_cache.executable()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "ccache"
            cache.write_text("#!/bin/sh\nexit 0\n")
            cache.chmod(0o755)
            with patch.dict(os.environ, {"DISTRO_CCACHE": str(cache)}):
                first = compiler_cache.seed_input()
                cache.write_text("#!/bin/sh\nexit 1\n")
                self.assertNotEqual(first["sha256"], compiler_cache.seed_input()["sha256"])

    @unittest.skipUnless(shutil.which("gcc"), "host seed gcc unavailable")
    def test_cache_receives_real_compiler_and_guard_precedes_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "ccache"
            log = root / "dispatch.log"
            cache.write_text("#!/usr/bin/python3\nimport os,sys\n"
                             f"with open({str(log)!r},'a') as stream: stream.write(repr(sys.argv[1:])+'\\n')\n"
                             "os.execv(sys.argv[1], sys.argv[1:])\n")
            cache.chmod(0o755)
            compiler = Path(shutil.which("gcc"))
            source = root / "tiny.c"
            source.write_text("int value(void) { return 42; }\n")
            env = os.environ | compiler_cache.environment(root, root, {"toolchain": "fixture"})
            direct = compiler_cache.wrapper(root / "cached-cc", compiler, cache)
            subprocess.run([str(direct), "-c", str(source), "-o", str(root / "direct.o")], env=env, check=True)
            guarded = root / "guarded-cc"
            _link_wrapper(guarded, compiler, root / "sysroot", [root])
            env["CD_CCACHE"] = str(cache)
            subprocess.run([str(guarded), "-c", str(source), "-o", str(root / "guarded.o")], env=env, check=True)
            self.assertTrue((root / "guarded.o").read_bytes().startswith(b"\x7fELF"))
            self.assertEqual(len(log.read_text().splitlines()), 2)
            self.assertTrue(all(str(compiler) in line for line in log.read_text().splitlines()))
            rejected = subprocess.run([str(guarded), "-I/usr/include", "-c", str(source)],
                                      env=env, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("refused a host", rejected.stderr)
            self.assertEqual(len(log.read_text().splitlines()), 2)
            self.assertEqual(env["CCACHE_CONFIGPATH"], "/dev/null")
            self.assertEqual(env["CCACHE_COMPILERCHECK"], "content")
            self.assertEqual(env["CCACHE_NODIRECT"], "1")
            self.assertEqual(env["CCACHE_DIR"], str(root / "out/compiler-cache"))
