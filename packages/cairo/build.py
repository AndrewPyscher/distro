#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
b.meson(["-Dxlib=disabled", "-Dxcb=disabled", "-Dtests=disabled", "-Dgtk_doc=false", "-Dlzo=disabled", "-Dspectre=disabled", "-Dsymbol-lookup=disabled"])
b.license("cairo", ["COPYING", "COPYING-LGPL-2.1", "COPYING-MPL-1.1"])

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
