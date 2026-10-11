#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
b.gperf()
b.env["PATH"] = str(b.native / "bin") + ":" + b.env["PATH"]
b.meson(["-Ddoc=disabled", "-Dnls=disabled", "-Dtests=disabled", "-Dtools=enabled",
         "-Dcache-build=disabled", "-Dxml-backend=expat", "-Dfontations=disabled"])
b.license("fontconfig", ["COPYING"])
b.closed_probe(b.stage / "usr/bin/fc-list", "--version")

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
