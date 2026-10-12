#!/usr/bin/env python3
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
# All installed client libraries use the distro's standard library directory.
# Keep the private common implementation alongside them without an ELF RUNPATH.
overlays = []
for relative, old, new, count in [
    ("meson.build", "privlibdir = join_paths(libdir, 'pulseaudio')", "privlibdir = libdir", 1),
    ("src/pulse/meson.build", "install_rpath : privlibdir,", "install_rpath : '',", 3),
    ("src/utils/meson.build", "install_rpath : privlibdir,", "install_rpath : '',", 6),
]:
    path = b.source / relative
    before = path.read_text()
    if before.count(old) != count:
        raise RuntimeError(f"Pinned PulseAudio library layout changed: {relative}")
    after = before.replace(old, new)
    path.write_text(after)
    overlays.append({"path": relative, "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                     "after_sha256": hashlib.sha256(after.encode()).hexdigest()})
(b.work / "source-overlays.json").write_text(json.dumps(overlays, indent=2) + "\n")
b.gettext_generators()
b.meson(["-Ddaemon=false", "-Dclient=true", "-Ddatabase=simple", "-Dtests=false", "-Ddoxygen=false", "-Dman=false", "-Dx11=disabled", "-Dgtk=disabled", "-Dalsa=disabled", "-Dasyncns=disabled", "-Davahi=disabled", "-Dbluez5=disabled", "-Dconsolekit=disabled", "-Delogind=disabled", "-Dfftw=disabled", "-Dgsettings=disabled", "-Dgstreamer=disabled", "-Djack=disabled", "-Dlirc=disabled", "-Dopenssl=disabled", "-Dorc=disabled", "-Doss-output=disabled", "-Dsoxr=disabled", "-Dspeex=disabled", "-Dudev=disabled", "-Dvalgrind=disabled", "-Dwebrtc-aec=disabled", "-Dsystemd=enabled", "-Ddbus=enabled", "-Dglib=enabled"])
b.license("libpulse", ["LICENSE", "LGPL"])
# The server diagnostic script requires Bash and host administration tools.
(b.stage / "usr/bin/pa-info").unlink()
for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
