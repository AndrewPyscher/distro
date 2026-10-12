#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
b.env["CFLAGS"] += " -std=gnu17"
b.autotools(["--disable-static", "--disable-external-libs", "--disable-mpeg", "--disable-alsa", "--disable-sqlite", "--disable-full-suite"])
b.license("libsndfile", ["COPYING"])
for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
