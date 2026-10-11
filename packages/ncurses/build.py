#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
# Compile the database with a private host tic from this package's source.
native_build = b.work / "native-ncurses"
native_build.mkdir()
b.host_run([str(b.source / "configure"), f"--prefix={b.native}", "--without-shared",
            "--without-debug", "--without-cxx", "--without-cxx-binding", "--without-ada",
            "--without-tests", "--without-manpages", "--disable-db-install"], native_build)
b.host_run(["make", f"-j{b.jobs}"], native_build)
b.host_run(["make", "install"], native_build)
b.env["TIC_PATH"] = str(b.native / "bin/tic")
b.autotools(["--with-shared", "--without-normal", "--without-debug", "--enable-widec",
             "--without-cxx", "--without-cxx-binding", "--without-ada", "--without-tests",
             "--without-manpages", "--disable-stripping", "--with-build-cc=/usr/bin/gcc",
             "--enable-pc-files", "--with-pkg-config-libdir=/usr/lib/pkgconfig"])
b.license("ncurses", ["COPYING"])
b.closed_probe(b.stage / "usr/bin/tic", "-V")
# Generated header comments name the build-time Caps inputs. Keep their source
# names while removing the private extraction directory from the exported SDK.
header = b.stage / "usr/include/curses.h"
header.write_text(header.read_text().replace(str(b.source) + "/", ""))

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
