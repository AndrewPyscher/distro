#!/usr/bin/python3
"""Private unzip helper for Mozilla's build, using the declared Python seed."""
import argparse
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument("-d", default=".", dest="directory")
parser.add_argument("-o", action="store_true", help="replace existing files")
parser.add_argument("-q", action="store_true")
parser.add_argument("-t", action="store_true", help="test archive integrity")
parser.add_argument("archive")
args = parser.parse_args()
with zipfile.ZipFile(args.archive) as archive:
    if args.t:
        bad = archive.testzip()
        if bad:
            raise SystemExit(f"Corrupt ZIP member: {bad}")
    else:
        destination = Path(args.directory).resolve()
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination):
                raise SystemExit(f"Unsafe ZIP member: {member.filename}")
            if target.exists() and not member.is_dir() and not args.o:
                raise SystemExit(f"ZIP destination exists: {target}; use -o")
        archive.extractall(destination)
