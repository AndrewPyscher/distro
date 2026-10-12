#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
b.glib_generators()
b.meson(["-Dx11=disabled", "-Dintrospection=disabled", "-Ddocs=false", "-Dgtk2_atk_adaptor=false", "-Duse_systemd=true", "-Ddbus_daemon=/usr/bin/dbus-daemon", "-Dsystemd_user_dir=/usr/lib/systemd/user"])
b.license("at-spi2-core", ["COPYING"])

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
