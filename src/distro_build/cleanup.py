"""Live cleanup reporting and descriptor-relative artifact removal."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import time


class CleanupProgress:
    """Count completed targets and entries without an expensive counting pass."""

    def __init__(self, project: Path, total: int, log_directory: Path, *, console: bool = True):
        self.project = project
        self.total = total
        self.completed = 0
        self.entries = 0
        self.started = time.monotonic()
        self.last_update = self.started
        self.current = ""
        self.console = sys.stderr if console else None
        self.terminal = bool(self.console and self.console.isatty())
        self.log = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
            dir=log_directory, prefix=datetime.now(timezone.utc).strftime("clean-%Y%m%dT%H%M%SZ-"), suffix=".log")
        self.log_path = Path(self.log.name)

    def __enter__(self):
        self.update(f"Starting cleanup of {self.total} targets; log: {self.log_path}", force=True)
        return self

    def __exit__(self, kind, error, traceback):
        try:
            if error is not None:
                status = "Interrupted" if isinstance(error, KeyboardInterrupt) else "FAILED"
                self.update(f"{status} at {self.current}: {error}; log: {self.log_path}", force=True, final=True)
            else:
                self.update(f"Cleanup complete; log: {self.log_path}", force=True, final=True)
        finally:
            self.log.close()

    def update(self, message: str, *, force: bool = False, final: bool = False):
        now = time.monotonic()
        if not force and now - self.last_update < (0.2 if self.terminal else 1.0):
            return
        self.last_update = now
        fraction = self.completed / self.total if self.total else 1
        filled = int(fraction * 16)
        bar = "#" * filled + "-" * (16 - filled)
        # Escape unusual path characters so filenames cannot inject terminal controls.
        message = message.encode("unicode_escape").decode("ascii")
        line = (f"[{bar}] {fraction:.0%} ({self.completed}/{self.total} targets) "
                f"{self.entries:,} entries removed | {now - self.started:.1f}s | {message}")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.log.write(f"{timestamp} {line}\n")
        self.log.flush()
        if self.console:
            if self.terminal:
                width = max(20, shutil.get_terminal_size().columns - 1)
                self.console.write("\r\033[2K" + (line + "\n" if force or final else line[:width]))
            else:
                self.console.write(line + "\n")
            self.console.flush()

    def begin(self, path: Path):
        self.current = str(path.relative_to(self.project))
        self.update(f"Cleaning {self.current}", force=True)

    def removed(self, path: Path):
        self.entries += 1
        self.current = str(path.relative_to(self.project))
        self.update(f"Removed {self.current}")

    def removing(self, path: Path):
        self.current = str(path.relative_to(self.project))

    def done(self, path: Path):
        self.completed += 1
        self.current = str(path.relative_to(self.project))
        self.update(f"Finished {self.current}", force=True)


def remove_artifact(path: Path, progress: CleanupProgress):
    """Remove entries through open directory descriptors, never following links.

    fwalk checks opened directories against their original stat information.
    Relative unlink/rmdir calls retain that boundary while reporting actual
    completed deletions, including inside a large individual target.
    """
    if not path.is_dir() or path.is_symlink():
        progress.removing(path)
        path.unlink()
        progress.removed(path)
        return

    def failed(error):
        raise error

    for directory, directories, files, descriptor in os.fwalk(
            path, topdown=False, follow_symlinks=False, onerror=failed):
        for name in files:
            progress.removing(Path(directory) / name)
            os.unlink(name, dir_fd=descriptor)
            progress.removed(Path(directory) / name)
        for name in directories:
            progress.removing(Path(directory) / name)
            if stat.S_ISLNK(os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode):
                os.unlink(name, dir_fd=descriptor)
            else:
                os.rmdir(name, dir_fd=descriptor)
            progress.removed(Path(directory) / name)
    progress.removing(path)
    path.rmdir()
    progress.removed(path)
