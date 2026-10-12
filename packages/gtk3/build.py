#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
b.scanner()
b.glib_generators()
b.gettext_generators()
b.meson(["-Dx11_backend=false", "-Dwayland_backend=true", "-Dbroadway_backend=false", "-Dwin32_backend=false", "-Dquartz_backend=false", "-Dintrospection=false", "-Dgtk_doc=false", "-Dman=false", "-Ddemos=false", "-Dexamples=false", "-Dtests=false", "-Dinstalled_tests=false", "-Dprint_backends=file", "-Dcolord=no", "-Dbuiltin_immodules=wayland"])
b.license("gtk3", ["COPYING"])

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
