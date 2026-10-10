"""Package builds must not pull disabled tests through Meson test prerequisites."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build.desktop_native import DesktopBuild


@unittest.skipUnless(all(shutil.which(tool) for tool in ("meson", "ninja", "gcc")),
                     "native fixture requires Meson, Ninja and GCC")
class MesonTargetTests(unittest.TestCase):
    def fixture_build(self, root, source):
        build = DesktopBuild.__new__(DesktopBuild)
        build.source = source
        build.work = root / "work"
        build.work.mkdir()
        build.stage = root / "stage"
        build.sysroot = root / "sysroot"
        build.sysroot.mkdir()
        build.tools = root / "tools"
        build.wrapper = Path(shutil.which("gcc"))
        build.target = "x86_64-fixture-linux-gnu"
        build.jobs = "2"
        build.env = dict(os.environ, AR="/usr/bin/ar", STRIP="/usr/bin/strip")
        build.native_file = build.work / "native.ini"
        build.native_file.write_text("[binaries]\nc = '/usr/bin/gcc'\n")

        def run(arguments, cwd=None):
            result = subprocess.run(arguments, cwd=cwd or source, env=build.env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        build.run = run
        return build

    @unittest.skipUnless(shutil.which("g++"), "fixture requires an inherited C++ compiler")
    def test_c_package_ignores_inherited_cpp_for_optional_language_and_iconv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "payload.c").write_text("int payload(void) { return 42; }\n")
            (source / "meson.build").write_text("""project('fixture', 'c')
have_cpp = add_languages('cpp', native: false, required: false)
assert(not have_cpp, 'C package inherited an undeclared C++ compiler')
iconv = dependency('iconv')
shared_library('payload', 'payload.c', dependencies: iconv, install: true)
""")
            build = self.fixture_build(root, source)
            build.env["CXX"] = shutil.which("g++")
            build.meson([])
            self.assertTrue((build.stage / "usr/lib/libpayload.so").is_file())

    @unittest.skipUnless(shutil.which("g++"), "fixture requires a C++ compiler")
    def test_cpp_package_uses_explicit_wrapper_despite_inherited_cpp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "payload.cpp").write_text('extern "C" int payload(void) { return 42; }\n')
            (source / "meson.build").write_text("""project('fixture', 'c', 'cpp')
shared_library('payload', 'payload.cpp', install: true)
""")
            build = self.fixture_build(root, source)
            # This is a host compiler fixture, not a target package build.
            build.sysroot = Path("/")
            pass2 = build.tools / "pass2"
            (pass2 / "bin").mkdir(parents=True)
            (pass2 / ".runtime-validated.json").write_text("{}\n")
            (pass2 / "bin" / f"{build.target}-g++").symlink_to(shutil.which("g++"))
            build.env["CXX"] = str(root / "missing-inherited-cxx")
            build.meson([], cpp=True)
            self.assertTrue((build.stage / "usr/lib/libpayload.so").is_file())
            compilers = subprocess.check_output(
                ["meson", "introspect", "--compilers", str(build.work / "target-build")],
                env=build.env, text=True)
            self.assertIn(str(build.work / "target-cxx"), compilers)

    def test_installed_payload_build_avoids_broken_disabled_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "payload.c").write_text("int payload(void) { return 42; }\n")
            (source / "broken.c").write_text(
                "extern void test_setup_logging(void);\n"
                "int main(void) { test_setup_logging(); return 0; }\n")
            (source / "meson.build").write_text("""project('fixture', 'c')
shared_library('payload', 'payload.c', install: true)
broken = executable('disabled-test', 'broken.c', build_by_default: false, install: false)
test('symbol-audit', find_program('true'), depends: broken)
custom_target('generated-data', output: 'generated.txt',
  command: [find_program('python3'), '-c', 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("generated payload")', '@OUTPUT@'],
  install: true, install_dir: get_option('datadir') / 'fixture', build_by_default: false)
""")
            build = self.fixture_build(root, source)
            build.meson([], installed_only=True)
            self.assertTrue((build.stage / "usr/lib/libpayload.so").is_file())
            self.assertEqual((build.stage / "usr/share/fixture/generated.txt").read_text(),
                             "generated payload")
            self.assertFalse((build.work / "target-build/disabled-test").exists())
            self.assertFalse((build.stage / "usr/bin/disabled-test").exists())

            # Prove that this fixture's disabled test really is broken, without
            # relying on Meson-version-specific default test prerequisites.
            default = subprocess.run(["ninja", "-C", str(build.work / "target-build"), "disabled-test"],
                                     env=build.env, capture_output=True, text=True)
            self.assertNotEqual(default.returncode, 0)
            self.assertIn("test_setup_logging", default.stdout + default.stderr)


if __name__ == "__main__":
    unittest.main()
