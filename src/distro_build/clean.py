"""Clear generated outputs for a rebuild, with entry-based progress."""
from __future__ import annotations

from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import stat
import sys
import time

from .model import BuildError


class Progress:
    def __init__(self):
        self.terminal = sys.stdout.isatty()
        self.updated = 0.0
        self.bucket = -1

    def scanning(self, count: int) -> None:
        now = time.monotonic()
        if self.terminal and now - self.updated >= 0.1:
            print(f"\rScanning out/: {count:,} entries...", end="", flush=True)
            self.updated = now

    def deleting(self, done: int, total: int) -> None:
        percent = done * 100 // total
        now = time.monotonic()
        if done != total:
            if self.terminal and done and now - self.updated < 0.1:
                return
            if not self.terminal and percent // 5 == self.bucket:
                return
        filled = percent * 24 // 100
        bar = "#" * filled + "-" * (24 - filled)
        prefix = "\r" if self.terminal else ""
        print(f"{prefix}[{bar}] {percent:3d}%  {done:,}/{total:,} entries",
              end="" if self.terminal else "\n", flush=True)
        self.updated = now
        self.bucket = percent // 5

    def newline(self) -> None:
        if self.terminal:
            print(flush=True)


def _raise(error: OSError) -> None:
    raise error


def _entries(name: str, output_fd: int):
    """Yield children before parents, using directory FDs and no symlink traversal."""
    info = os.stat(name, dir_fd=output_fd, follow_symlinks=False)
    is_directory = stat.S_ISDIR(info.st_mode)
    device = os.fstat(output_fd).st_dev
    if is_directory:
        for directory, directories, files, directory_fd in os.fwalk(
                name, topdown=False, onerror=_raise, follow_symlinks=False, dir_fd=output_fd):
            if os.fstat(directory_fd).st_dev != device:
                raise BuildError(f"refusing to clean another filesystem at out/{directory}")
            for child in files + directories:
                child_info = os.stat(child, dir_fd=directory_fd, follow_symlinks=False)
                yield directory_fd, child, stat.S_ISDIR(child_info.st_mode)
    yield output_fd, name, is_directory


def _lock_paths(output: Path):
    state = output / "state"
    if not state.is_symlink():
        yield state / "run.lock"
        if not (state / "locks").is_symlink():
            yield from (state / "locks").glob("*.lock")
    if not (output / "locks").is_symlink():
        yield from (output / "locks").glob("*.lock")
    vms = output / "vms"
    if vms.is_dir() and not vms.is_symlink():
        for vm in vms.iterdir():
            if vm.is_dir() and not vm.is_symlink():
                yield vm / "vm.lock"
                yield vm / "deploy.lock"


def _hold_locks(output: Path, stack: ExitStack) -> None:
    for path in _lock_paths(output):
        if path.is_symlink():
            continue
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            continue
        stack.callback(os.close, descriptor)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BuildError(f"expected a regular lock file: {path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BuildError(f"build, deployment or VM is active ({path}); stop it before cleaning") from error


def clean(project: Path, *, all_outputs: bool = False, dry_run: bool = False) -> int:
    output = project / "out"
    progress = Progress()
    with ExitStack() as stack:
        # Never resolve out/: a symlink must not redirect cleanup outside the checkout.
        try:
            output_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            print("Nothing to clean: out/ does not exist.")
            return 0
        except OSError as error:
            raise BuildError(f"out/ must be a real directory, not a symlink: {error}") from error
        stack.callback(os.close, output_fd)
        if not dry_run:
            _hold_locks(output, stack)
        with os.scandir(output_fd) as entries:
            names = sorted(entry.name for entry in entries if all_outputs or entry.name != "vms")
        print(f"{'Previewing' if dry_run else 'Cleaning'} {output}")
        print("Including saved VMs." if all_outputs else "Keeping out/vms/ (use --all to remove saved VMs too).")
        print("Scanning files and directories...", flush=True)
        counts = {}
        total = 0
        try:
            for name in names:
                count = 0
                for _ in _entries(name, output_fd):
                    count += 1
                    total += 1
                    progress.scanning(total)
                counts[name] = count
        finally:
            progress.newline()
        if dry_run:
            for name, count in counts.items():
                print(f"  out/{name}: {count:,} entries")
            print(f"Would remove {total:,} files, directories and symlinks. No changes made.")
            return 0
        if not total:
            print("Nothing to clean.")
            return 0
        done = 0
        progress.deleting(done, total)
        try:
            for name in names:
                for directory_fd, child, is_directory in _entries(name, output_fd):
                    if is_directory:
                        os.rmdir(child, dir_fd=directory_fd)
                    else:
                        os.unlink(child, dir_fd=directory_fd)
                    done += 1
                    progress.deleting(done, total)
        finally:
            progress.newline()
        print(f"Cleaned {done:,} entries. Ready to rebuild with ./run.")
    return 0
