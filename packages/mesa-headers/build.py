#!/usr/bin/env python3
from pathlib import Path
import os
import shutil

source = Path(os.environ["CD_SOURCE_DIR"])
stage = Path(os.environ["CD_STAGE_DIR"])
for name in ("EGL", "KHR"):
    shutil.copytree(source / "include" / name, stage / "usr/include" / name)
license_dir = stage / "usr/share/licenses/mesa-headers"
license_dir.mkdir(parents=True)
shutil.copy2(source / "docs/license.rst", license_dir / "license.rst")
