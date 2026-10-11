#!/usr/bin/env python3
from pathlib import Path
import shutil
import os
source = Path(os.environ["CD_SOURCE_DIR"])
stage = Path(os.environ["CD_STAGE_DIR"])
fonts = stage / "usr/share/fonts/dejavu"
fonts.mkdir(parents=True)
for path in (source / "ttf").glob("*.ttf"):
    shutil.copy2(path, fonts / path.name)
license_dir = stage / "usr/share/licenses/fonts-dejavu"
license_dir.mkdir(parents=True)
shutil.copy2(source / "LICENSE", license_dir / "LICENSE")
