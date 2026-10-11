#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
import shutil

b.scanner()
# Build tic privately from the same pinned source as the target terminfo tools.
# Host terminfo data and host ncurses libraries never enter the target package.
source = b.secondary("ncurses")
native_build = b.work / "native-ncurses"
native_build.mkdir()
b.host_run([str(source / "configure"), f"--prefix={b.native}", "--without-shared",
            "--without-debug", "--without-cxx", "--without-cxx-binding", "--without-ada",
            "--without-tests", "--without-manpages", "--disable-db-install"], native_build)
b.host_run(["make", f"-j{b.jobs}"], native_build)
b.host_run(["make", "install"], native_build)
b.meson(["-Ddocs=disabled", "-Dtests=false", "-Dterminfo=enabled",
         "-Dcustom-terminfo-install-location=share/foot/terminfo",
         "-Dgrapheme-clustering=enabled", "-Dutmp-backend=none",
         "-Dutmp-default-helper-path=none"])
b.license("foot", ["LICENSE"])
# The desktop exposes the standalone terminal; server/client remain CLI options.
for name in ("foot-server.desktop", "footclient.desktop"):
    entry = b.stage / "usr/share/applications" / name
    entry.write_text(entry.read_text() + "NoDisplay=true\n")
config = b.stage / "etc/xdg/foot/foot.ini"
config.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(Path(__file__).parent / "foot.ini", config)
b.closed_probe(b.stage / "usr/bin/foot", "--version")

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
