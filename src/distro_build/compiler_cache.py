"""Optional, declared host ccache input for trusted native package builds."""
import os
from pathlib import Path
import shutil

from .model import BuildError
from .sources import sha256


def executable() -> Path | None:
    selection = os.environ.get("DISTRO_CCACHE")
    if selection == "0":
        return None
    path = shutil.which(selection or "ccache")
    if selection and not path:
        raise BuildError(f"DISTRO_CCACHE is not an executable: {selection}")
    return Path(path).resolve() if path else None


def seed_input() -> dict:
    path = executable()
    return {"path": str(path), "sha256": sha256(path)} if path else {"available": False}


def wrapper(path: Path, compiler: Path, cache: Path) -> Path:
    """Pass the actual compiler to ccache so compiler hashing remains effective."""
    path.write_text("#!/usr/bin/python3\nimport os,sys\n"
                    f"os.execv({str(cache)!r}, [{str(cache)!r}, {str(compiler)!r}, *sys.argv[1:]])\n")
    path.chmod(0o755)
    return path


def environment(project: Path, work: Path, inputs: dict) -> dict:
    # Preprocessor mode observes header additions/removals too. No sloppiness,
    # path rewriting, host config or remote cache is inherited by package builds.
    import json
    record = work / "compiler-cache-inputs.json"
    record.write_text(json.dumps(inputs, sort_keys=True) + "\n")
    return {"CCACHE_DIR": str(project / "out/compiler-cache"),
            "CCACHE_CONFIGPATH": "/dev/null", "CCACHE_COMPILERCHECK": "content",
            "CCACHE_NODIRECT": "1", "CCACHE_EXTRAFILES": str(record), "CCACHE_MAXSIZE": "5G"}
