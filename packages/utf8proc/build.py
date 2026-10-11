#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
b.run(["make", f"-j{b.jobs}", f"CC={b.wrapper}", "libutf8proc.so", "libutf8proc.pc"])
b.run(["make", f"CC={b.wrapper}", "prefix=/usr", f"DESTDIR={b.stage}", "install"])
b.license("utf8proc", ["LICENSE.md"])

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
