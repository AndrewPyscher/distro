#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
b.glib_generators()
b.meson(["-Dintrospection=disabled", "-Ddocumentation=false", "-Dman-pages=false", "-Dbuild-testsuite=false", "-Dbuild-examples=false", "-Dlibthai=disabled", "-Dxft=disabled"], cpp=True)
b.license("pango", ["COPYING"])

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
