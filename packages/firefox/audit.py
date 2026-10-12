"""Check Firefox resources as well as its allocated ELF sections."""
import json
from pathlib import PurePosixPath
import re
import zipfile

BUILD_PATH = re.compile(rb"/[^\x00\n\r\t ]*/out/[^\x00\n\r\t ]+")
BUILD_CONFIG = "chrome/toolkit/content/global/buildconfig.html"
RFP_CONSTANTS = "modules/RFPTargetConstants.sys.mjs"
VR_ACTIONS = {"/actions/firefox/out/LHand_haptic", "/actions/firefox/out/RHand_haptic"}


def archive_paths(stage):
    diagnostics, rejected, archives = [], [], []
    for path in sorted(stage.rglob("*.ja")):
        relative = path.relative_to(stage).as_posix()
        archives.append(relative)
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                name = PurePosixPath(member.filename)
                if name.is_absolute() or ".." in name.parts:
                    rejected.append({"path": relative, "member": member.filename,
                                     "reason": "unsafe resource archive path"})
                for line in archive.read(member).splitlines():
                    for match in BUILD_PATH.finditer(line):
                        record = {"path": relative, "member": member.filename,
                                  "value": match[0].decode("utf-8", "replace")}
                        if member.filename == BUILD_CONFIG:
                            diagnostics.append({**record, "kind": "about:buildconfig compiler diagnostics"})
                        elif (member.filename == RFP_CONSTANTS
                              and line.startswith(b"// See extract_rfp_targets.py, ")):
                            diagnostics.append({**record, "kind": "generated source provenance comment"})
                        else:
                            rejected.append({**record, "reason": "build path in runtime resource"})
    return diagnostics, rejected, archives


def audit_payload(build):
    # The common check scans installed paths, symlinks and allocated ELF data.
    # Its generic /out/ pattern also matches OpenVR's virtual action namespace
    # and the uncompressed records inside Mozilla's optimized ZIP resources.
    try:
        build.audit_payload_paths()
    except RuntimeError:
        report = json.loads((build.work / "target-payload-path-audit.json").read_text())
    else:
        report = json.loads((build.work / "target-payload-path-audit.json").read_text())
    diagnostics, rejected, archives = archive_paths(build.stage)
    virtual_paths = []
    for item in report["rejected"]:
        if item["reason"] == "build directory in runtime payload":
            if (item["path"] == "usr/lib/firefox/libxul.so"
                    and item["value"].rstrip('\",') in VR_ACTIONS):
                virtual_paths.append({**item, "kind": "OpenVR virtual action name"})
                continue
            if item["path"] in archives:
                # Every member was checked after decompression above.
                continue
        rejected.append(item)
    report.update({"passed": not rejected, "rejected": rejected,
                   "diagnostic_resources": diagnostics, "virtual_paths": virtual_paths,
                   "resource_archives": archives,
                   "scope": report["scope"] + "; decompressed JAR members checked; "
                            "about:buildconfig, generated provenance comments and "
                            "exact OpenVR action names classified separately"})
    (build.work / "target-payload-path-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    if rejected:
        raise RuntimeError("Firefox contains runtime build paths: " + json.dumps(rejected))
