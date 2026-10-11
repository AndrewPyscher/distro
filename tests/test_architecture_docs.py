"""Coverage checks and safe regeneration for the architecture reference."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_architecture", ROOT / "tools/render-architecture.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)

DETAILS = '''
[packages.example]
kind = "Library"
purpose = "Provides a public interface."
use = "Used by the desktop."
parts = { helper = "Assists the library." }
[projects.telorgon]
kind = "SDK source"
purpose = "Shared interface implementation."
use = "Linked into applications."
[sdk_crates]
telorgon = "Shared SDK."
[sdk_modules]
ui = "User interface."
[policy]
"system/init" = "Starts early userspace."
'''


class ArchitectureDocsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(renderer, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        (self.root / "docs").mkdir()
        (self.root / "system").mkdir()
        (self.root / "system/init").write_text("early init\n")
        self.notes = self.root / "docs/component-details.toml"
        self.notes.write_text(DETAILS)
        self.packages = {"example": Path("packages/example/package.toml")}
        self.projects = {"telorgon": {"repository": "https://example.com/telorgon.git", "branch": "main"}}

    def test_missing_and_unknown_explanations_fail(self):
        cases = [
            ("[packages.example]", "[packages.other]", "packages explanations"),
            ("[projects.telorgon]", "[projects.other]", "projects explanations"),
            ('"system/init"', '"system/other"', "policy explanations"),
        ]
        for original, replacement, expected in cases:
            with self.subTest(expected=expected):
                self.notes.write_text(DETAILS.replace(original, replacement))
                with self.assertRaisesRegex(ValueError, expected):
                    renderer.component_details(self.packages, self.projects)

    def test_empty_component_fields_and_bundle_descriptions_fail(self):
        cases = [
            ('kind = "Library"', 'kind = ""', "kind must be nonempty"),
            ('purpose = "Provides a public interface."', 'purpose = ""', "purpose must be nonempty"),
            ('use = "Used by the desktop."', 'use = ""', "use must be nonempty"),
            ('helper = "Assists the library."', 'helper = ""', "empty purpose for helper"),
        ]
        for original, replacement, expected in cases:
            with self.subTest(expected=expected):
                self.notes.write_text(DETAILS.replace(original, replacement))
                with self.assertRaisesRegex(ValueError, expected):
                    renderer.component_details(self.packages, self.projects)

    def test_dangling_policy_symlinks_require_explanations(self):
        (self.root / "system/activation").symlink_to("future-service")
        with self.assertRaisesRegex(ValueError, "system/activation"):
            renderer.component_details(self.packages, self.projects)
        self.notes.write_text(DETAILS + '"system/activation" = "Enables a service."\n')
        details = renderer.component_details(self.packages, self.projects)
        self.assertIn("system/activation", details["policy"])

    def test_reference_replacement_preserves_authored_sections(self):
        before = "# Architecture\n\nAuthored introduction.\n\n"
        after = "\n\n## Boot\n\nAuthored boot explanation.\n"
        source = before + "<!-- BEGIN COMPONENT REFERENCE -->\nold\n<!-- END COMPONENT REFERENCE -->" + after
        updated = renderer.update_reference(source, "new reference\n")
        self.assertTrue(updated.startswith(before))
        self.assertTrue(updated.endswith(after))
        self.assertIn("new reference", updated)
        self.assertNotIn("\nold\n", updated)
        self.assertEqual(renderer.update_reference(updated, "new reference\n"), updated)

    def test_missing_or_duplicate_markers_fail(self):
        for source in ("no markers", "<!-- BEGIN COMPONENT REFERENCE -->" * 2):
            with self.subTest(source=source), self.assertRaises(ValueError):
                renderer.update_reference(source, "reference")

    def test_stale_reference_check_does_not_write(self):
        (self.root / "packages/example").mkdir(parents=True)
        (self.root / self.packages["example"]).write_text('[package]\nname="example"\n')
        (self.root / "source-projects.toml").write_text(
            '[projects.telorgon]\nrepository="https://example.com/telorgon.git"\nbranch="main"\n')
        (self.root / "docs/architecture-components.toml").write_text(
            '[[layers]]\ntitle="Layer"\ndescription="Layer purpose"\ncolor="#2563eb"\n'
            '[[layers.groups]]\ntitle="Group"\ndescription="Group purpose"\n'
            'packages=["example"]\nprojects=["telorgon"]\n')
        architecture = self.root / "docs/architecture.md"
        architecture.write_text("Authored introduction\n<!-- BEGIN COMPONENT REFERENCE -->\n"
                                "<!-- END COMPONENT REFERENCE -->\nAuthored ending\n")
        with patch.object(renderer, "profile_membership", return_value=({}, {})), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with patch("sys.argv", ["render-architecture.py"]):
                self.assertEqual(renderer.main(), 0)
            with patch("sys.argv", ["render-architecture.py", "--check"]):
                self.assertEqual(renderer.main(), 0)
                architecture.write_text(architecture.read_text().replace("Used by the desktop.", "Stale explanation."))
                files = [path for path in (self.root / "docs").rglob("*") if path.is_file()]
                before = {path: path.read_bytes() for path in files}
                self.assertEqual(renderer.main(), 1)
                self.assertEqual(before, {path: path.read_bytes() for path in files})
            with patch("sys.argv", ["render-architecture.py"]):
                self.assertEqual(renderer.main(), 0)
        self.assertTrue(architecture.read_text().startswith("Authored introduction\n"))
        self.assertTrue(architecture.read_text().endswith("Authored ending\n"))
        self.assertNotIn("Stale explanation", architecture.read_text())


if __name__ == "__main__":
    unittest.main()
