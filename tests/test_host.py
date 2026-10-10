"""Detect QEMU's missing Python venv prerequisite before package compilation."""
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build import cli
from distro_build.host import python_venv_report
from distro_build.model import BuildError


class HostPythonTests(unittest.TestCase):
    def probe(self, **modules):
        available = dict(venv=True, ensurepip=False, pip=False, setuptools=True, pyexpat=True)
        available.update(modules)
        return subprocess.CompletedProcess([], 0, json.dumps({
            "python": "/usr/bin/python3", "version": "3.14.4", "modules": available}), "")

    def test_missing_ensurepip_stops_doctor_with_setup_command(self):
        with patch("distro_build.runner.seed_report", return_value={}), \
             patch("distro_build.host.subprocess.run", return_value=self.probe()), \
             patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(cli.main(["doctor"], quiet=True), 1)
        self.assertIn("sudo apt install python3-venv", stderr.getvalue())

    def test_system_python_with_ensurepip_is_accepted(self):
        with patch("distro_build.host.subprocess.run", return_value=self.probe(ensurepip=True)) as run:
            report = python_venv_report()
        self.assertEqual(report["pip_bootstrap"], "ensurepip")
        self.assertEqual(run.call_args.args[0][:2], ["/usr/bin/python3", "-I"])

    def test_existing_pip_and_setuptools_are_accepted_without_ensurepip(self):
        with patch("distro_build.host.subprocess.run", return_value=self.probe(pip=True)):
            self.assertEqual(python_venv_report()["pip_bootstrap"], "system pip and setuptools")

    def test_missing_venv_or_ensurepip_expat_is_rejected(self):
        for missing in ({"venv": False, "pip": True}, {"ensurepip": True, "pyexpat": False}):
            with self.subTest(missing=missing), \
                 patch("distro_build.host.subprocess.run", return_value=self.probe(**missing)):
                with self.assertRaisesRegex(BuildError, "python3-venv"):
                    python_venv_report()


if __name__ == "__main__":
    unittest.main()
