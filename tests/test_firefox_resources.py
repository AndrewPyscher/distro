import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location(
    "firefox_resource_audit", Path(__file__).resolve().parents[1] / "packages/firefox/audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class FirefoxResourcesTest(unittest.TestCase):
    def scan(self, members):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            with zipfile.ZipFile(stage / "omni.ja", "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in members.items():
                    archive.writestr(name, content)
            return audit.archive_paths(stage)

    def test_build_configuration_is_diagnostic(self):
        diagnostics, rejected, archives = self.scan({
            audit.BUILD_CONFIG: "<td>/home/builder/out/work/firefox/target-cc</td>"})
        self.assertFalse(rejected)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(archives, ["omni.ja"])

    def test_generated_comment_does_not_allow_executable_paths(self):
        diagnostics, rejected, _ = self.scan({audit.RFP_CONSTANTS:
            "// See extract_rfp_targets.py, /home/builder/out/source/RFPTargets.inc\n"
            "const runtimePath = '/home/builder/out/work/runtime';\n"})
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(len(rejected), 1)
        self.assertIn("runtime", rejected[0]["value"])

    def test_compressed_runtime_resource_is_checked(self):
        diagnostics, rejected, _ = self.scan({
            "modules/loader.sys.mjs": "load('/home/builder/out/work/runtime.js');"})
        self.assertFalse(diagnostics)
        self.assertEqual(len(rejected), 1)

    def test_archive_traversal_is_rejected(self):
        _, rejected, _ = self.scan({"../outside": "data"})
        self.assertEqual(rejected[0]["reason"], "unsafe resource archive path")
