"""Read-only prerequisite checks for the host build environment."""
from __future__ import annotations

import json
import subprocess

from .model import BuildError


def python_venv_report() -> dict:
    # Package builds use this interpreter from their restricted /usr/bin PATH,
    # even if the Python CLI itself was launched from a user's virtualenv.
    python = "/usr/bin/python3"
    probe = subprocess.run([python, "-I", "-c",
        "import importlib.util,json,sys; "
        "print(json.dumps({'python':sys.executable,'version':sys.version.split()[0],"
        "'modules':{name:importlib.util.find_spec(name) is not None "
        "for name in ('venv','ensurepip','pip','setuptools','pyexpat')}}))"],
        text=True, capture_output=True, timeout=10)
    if probe.returncode:
        raise BuildError(f"cannot inspect host Python virtual-environment support: {probe.stderr.strip()}")
    report = json.loads(probe.stdout)
    modules = report["modules"]
    # QEMU's mkvenv accepts either ensurepip or an existing pip + setuptools.
    inherited_pip = modules["pip"] and modules["setuptools"]
    if not modules["venv"] or not (inherited_pip or (modules["ensurepip"] and modules["pyexpat"])):
        raise BuildError(
            f"QEMU Guest Agent requires host Python virtual-environment support for {python}; "
            "on Ubuntu/Debian install python3-venv (sudo apt install python3-venv), "
            "then rerun python3 build.py doctor")
    report["pip_bootstrap"] = "system pip and setuptools" if inherited_pip else "ensurepip"
    return report
