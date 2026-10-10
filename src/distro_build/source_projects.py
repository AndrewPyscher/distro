"""Declarative source inputs shared by snapshots, bundles and development."""
from pathlib import Path
import re
import tomllib


DEFAULT_PROJECT = Path(__file__).resolve().parents[2]


def relative_path(value: str) -> str:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() == ".":
        raise RuntimeError(f"Unsafe catalog path: {value}")
    return value


def catalog(project: Path) -> dict:
    path = project / "source-projects.toml"
    # Small fixture workspaces may use the distribution's catalog.
    if not path.exists():
        path = DEFAULT_PROJECT / "source-projects.toml"
    document = tomllib.loads(path.read_text())
    if document.get("schema") != 1:
        raise RuntimeError(f"Unsupported source catalog: {path}")
    projects = document["projects"]
    for name, record in projects.items():
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
            raise RuntimeError(f"Invalid source project: {name}")
        if record.get("update", "package") not in {"package", "base"}:
            raise RuntimeError(f"Invalid source update policy: {name}")
        inputs = record["inputs"]
        if not isinstance(inputs, list) or not {"Cargo.toml", "Cargo.lock"} <= set(inputs):
            raise RuntimeError(f"Missing Cargo source inputs: {name}")
        for item in inputs:
            relative_path(item)
        if record.get("overlay") not in {None, "telorgon-shell"}:
            raise RuntimeError(f"Unsupported source overlay: {name}")
    return projects


def inputs(project: Path, *, include_base: bool = False) -> dict:
    return {name: tuple(record["inputs"]) for name, record in catalog(project).items()
            if include_base or record.get("update", "package") == "package"}
