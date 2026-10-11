#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
b.meson(["-Dharfbuzz=disabled", "-Dbrotli=disabled", "-Dbzip2=disabled",
         "-Dzlib=system", "-Dpng=enabled", "-Dtests=disabled"])
b.license("freetype", ["docs/FTL.TXT", "docs/GPLv2.TXT", "LICENSE.TXT"])

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
