#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
b.meson(["-Dglib=disabled", "-Dgobject=disabled", "-Dcairo=disabled", "-Dchafa=disabled",
         "-Dicu=disabled", "-Dfreetype=enabled", "-Dtests=disabled", "-Dutilities=disabled",
         "-Ddocs=disabled", "-Dintrospection=disabled"], cpp=True)
b.license("harfbuzz", ["COPYING"])

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
