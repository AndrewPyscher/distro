"""Update the run coordinator before loading its CLI and build catalogs."""
import argparse
import json
import os
from pathlib import Path
import sys

from . import upstream


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Parse only the entry point: upstream may introduce new run options.
    entry = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    entry.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    entry.add_argument("command", nargs="?")
    entry.add_argument("arguments", nargs=argparse.REMAINDER)
    options, _ = entry.parse_known_args(arguments)
    if options.command == "run" and not any(flag in arguments for flag in ("--offline", "--help", "-h")):
        project = options.project.resolve()
        try:
            print("Checking distro updates from canonical upstream...", file=sys.stderr, flush=True)
            result = upstream.synchronize_distro(project)
            print(json.dumps({"event": "distro-sync", **result}), file=sys.stderr, flush=True)
            if result["action"] == "updated":
                # Reload every module, including this launcher, from the updated tree.
                os.execv(sys.executable, [sys.executable, str(project / "build.py"), *arguments])
        except (RuntimeError, OSError) as error:
            print(json.dumps({"error": str(error), "command": "run"}), file=sys.stderr, flush=True)
            return 1
        except KeyboardInterrupt:
            print("Distro update interrupted; rerun ./run to retry.", file=sys.stderr)
            return 130
    from .cli import main as cli_main
    return cli_main(arguments)
