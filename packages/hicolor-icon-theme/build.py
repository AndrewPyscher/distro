#!/usr/bin/env python3
"""Install the upstream fallback index shared by desktop application icons."""
from pathlib import Path
import os
import shutil

source = Path(os.environ["CD_SOURCE_DIR"])
stage = Path(os.environ["CD_STAGE_DIR"])
theme = stage / "usr/share/icons/hicolor"
theme.mkdir(parents=True)
shutil.copy2(source / "index.theme", theme / "index.theme")
license_dir = stage / "usr/share/licenses/hicolor-icon-theme"
license_dir.mkdir(parents=True)
shutil.copy2(source / "COPYING", license_dir / "COPYING")
