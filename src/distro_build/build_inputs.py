"""Content dependencies of build stages, without importing executable recipes."""
from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path


def engine_inputs(project: Path, modules: list[str], scripts: list[Path] = ()) -> list[Path]:
    """Follow local Python imports, including imports inside build functions.

    Include package initializers and missing local modules too: introducing a
    previously absent helper must invalidate the receipt. External modules are
    declared host seeds, rather than part of this source graph.
    """
    root = project / "src"
    paths = set()
    visited = set()

    def module(name):
        if not (name == "distro_build" or name.startswith("distro_build.")) or name in visited:
            return
        visited.add(name)
        parts = name.split(".")
        for length in range(1, len(parts)):
            module(".".join(parts[:length]))
        base = root.joinpath(*parts)
        path = base / "__init__.py" if base.is_dir() else base.with_suffix(".py")
        scan(path, name if path.name == "__init__.py" else name.rpartition(".")[0])

    def scan(path, package):
        paths.add(path)
        if not path.is_file():
            return
        # Native helpers can carry adjacent C sources or other non-Python data.
        paths.update(child for child in path.parent.iterdir()
                     if child.is_file() and child.suffix not in {".py", ".pyc"})
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module(alias.name)
            elif isinstance(node, ast.ImportFrom):
                parent = node.module or ""
                if node.level:
                    prefix = package.split(".")
                    parent = ".".join(prefix[:len(prefix) - node.level + 1] + ([parent] if parent else []))
                module(parent)
                for alias in node.names:
                    child = root.joinpath(*parent.split("."), alias.name)
                    if child.with_suffix(".py").is_file() or child.is_dir():
                        module(parent + "." + alias.name)
            elif isinstance(node, ast.Call):
                function = node.func
                name = function.id if isinstance(function, ast.Name) else (
                    function.attr if isinstance(function, ast.Attribute) else "")
                if name in {"__import__", "import_module"}:
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        value = node.args[0].value
                        if value.startswith("."):
                            value = resolve_name(value, package)
                        module(value)
                    else:
                        # Computed imports cannot be resolved statically. Retain
                        # a conservative boundary for this particular consumer.
                        for helper in sorted((root / "distro_build").rglob("*.py")):
                            relative = helper.relative_to(root).with_suffix("")
                            parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
                            module(".".join(parts))

    for name in modules:
        module("distro_build." + name)
    for path in scripts:
        scan(path, "")
    # Changes to the dependency selection policy itself affect every receipt.
    paths.add(project / "src/distro_build/build_inputs.py")
    return sorted(paths)


def recipe_inputs(project: Path, recipe) -> list[Path]:
    helpers = engine_inputs(project, ["runner"], sorted(recipe.path.parent.rglob("*.py")))
    return [recipe.path.parent, *(path for path in helpers if not path.is_relative_to(recipe.path.parent))]
