#!/usr/bin/env python3
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from distro_build.desktop_services import ServiceBuild

b = ServiceBuild()
# Meson rejects an empty dependency string when no GL provider is linked.
# A list preserves the optional provider requirements, including the empty case.
rules = b.source / "src/meson.build"
before = rules.read_text()
old = "requires_private: ' '.join(gl_reqs),"
if before.count(old) != 1:
    raise RuntimeError("Pinned libepoxy pkg-config rules changed")
after = before.replace(old, "requires_private: gl_reqs,")
rules.write_text(after)
(b.work / "source-overlays.json").write_text(json.dumps({
    "path": "src/meson.build", "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
    "after_sha256": hashlib.sha256(after.encode()).hexdigest()}, indent=2) + "\n")
b.meson(["-Dx11=false", "-Dglx=no", "-Degl=yes", "-Dtests=false", "-Ddocs=false"])
b.license("libepoxy", ["COPYING"])

for path in b.stage.rglob("*.la"):
    path.unlink()
b.audit()
b.audit_payload_paths()
