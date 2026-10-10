"""Live build-stage progress, kept separate from artifact and cache decisions."""
from __future__ import annotations

from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import tomllib


_active: ContextVar[RunProgress | None] = ContextVar("run_progress", default=None)
_stages = [
    ("doctor", "Host checks"), ("validate", "Recipe validation"),
    ("fetch", "Source downloads"), ("bootstrap", "Toolchain"),
    ("bootstrap-check", "Toolchain verification"), ("native-toolkit", "Package tools"),
    ("build", "OS packages"), ("loader", "Bootloader"),
    ("sdk", "Desktop SDK"), ("apps", "Desktop applications"),
    ("image", "OS image"), ("vm", "VM preparation and startup"),
]
_groups = {"essentials": [key for key, _ in _stages[:7]],
           "loader": ["loader"], "sdk": ["sdk"], "apps": ["apps"], "image": ["image"]}


def stage(key: str) -> None:
    if reporter := _active.get():
        reporter.begin(key)


def complete(key: str, *, cached: bool = False) -> None:
    if reporter := _active.get():
        reporter.complete(key, cached=cached)


def detail(text: str, *, log: Path | None = None) -> None:
    if reporter := _active.get():
        reporter.detail(text, log=log)


def item(name: str, index: int, total: int, *, done: bool = False) -> None:
    if reporter := _active.get():
        reporter.item(name, index, total, done=done)


def message(text: str) -> None:
    reporter = _active.get()
    if reporter is None:
        print(text, file=sys.stderr, flush=True)
        return
    with reporter.lock:
        reporter._record({"event": "message", "message": text})
        if reporter.terminal and not reporter.finished:
            print("\r\033[2K", end="", file=reporter.stream, flush=True)
        print(text, file=reporter.stream, flush=True)
        if reporter.terminal and not reporter.finished:
            reporter._render()


def event(value: object) -> bool:
    """Consume run events; callers retain their original output outside ./run."""
    reporter = _active.get()
    if reporter is None:
        return False
    reporter.event(value)
    return True


class RunProgress:
    def __init__(self, project: Path, profile: str, *, enabled: bool = True):
        self.project = project
        self.profile = profile
        self.enabled = enabled
        self.stages = [(key, label) for key, label in _stages
                       if profile in {"desktop-use", "desktop-dev"} or key not in {"sdk", "apps"}]
        self.labels = dict(self.stages)
        self.stream = sys.stderr
        self.terminal = self.stream.isatty() and os.environ.get("TERM") != "dumb"
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.completed: set[str] = set()
        self.key = "doctor"
        self.text = ""
        self.item_label = ""
        self.fraction = 0.0
        self.started = time.monotonic()
        self.last_render = 0.0
        self.frame = 0
        self.finished = False
        self.watch = None
        self.token = None
        self.thread = None
        self.events = None

    def __enter__(self):
        if not self.enabled:
            return self
        logs = self.project / "out/logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.path = logs / f"run-{self.profile}-{time.time_ns()}.jsonl"
        self.events = self.path.open("w", buffering=1)
        self.token = _active.set(self)
        print("Build progress counts completed steps; step durations vary.", file=self.stream, flush=True)
        print(f"Detailed build events: {self.path}", file=self.stream, flush=True)
        self._record({"event": "run-progress-start", "profile": self.profile, "steps": self.stages})
        self._render()
        self.thread = threading.Thread(target=self._heartbeat, name="build-progress", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, kind, error, traceback):
        if not self.enabled:
            return
        self.stop.set()
        if self.thread is not None:
            self.thread.join()
        with self.lock:
            if kind is not None or not self.finished:
                self.text = "Interrupted" if kind is KeyboardInterrupt else "Failed"
                self.watch = None
                self._record({"event": "run-progress-failed", "stage": self.key, "status": self.text})
                self._render()
                if self.terminal:
                    print(file=self.stream, flush=True)
            _active.reset(self.token)
            self.events.close()

    def _record(self, value: object) -> None:
        self.events.write(json.dumps(value, default=str) + "\n")

    def _render(self) -> None:
        elapsed = int(time.monotonic() - self.started)
        percent = min(99, int((len(self.completed) + self.fraction) * 100 / len(self.stages)))
        if self.finished:
            percent = 100
        filled = percent * 18 // 100
        bar = "#" * filled + "-" * (18 - filled)
        activity = "|/-\\"[self.frame % 4] if not self.finished else " "
        self.frame += 1
        label = self.labels[self.key]
        if self.text:
            label += f": {self.text}"
        prefix = f"{activity} [{bar}] {percent:3d}% {len(self.completed)}/{len(self.stages)} steps | "
        suffix = f" | {elapsed // 60:02d}:{elapsed % 60:02d} elapsed"
        if self.terminal:
            width = shutil.get_terminal_size(fallback=(100, 24)).columns
            prefix = f"{activity} [{bar}] {percent:3d}% {len(self.completed)}/{len(self.stages)} | "
            suffix = f" | {elapsed // 60:02d}:{elapsed % 60:02d}"
            if width < 100:
                short = {"apps": "Apps", "vm": "VM", "bootstrap-check": "Verify toolchain",
                         "validate": "Recipes", "fetch": "Downloads", "sdk": "SDK"}
                label = short.get(self.key, self.labels[self.key]) + (f": {self.text}" if self.text else "")
            label = label[:max(0, width - len(prefix) - len(suffix) - 1)]
        line = prefix + label + suffix
        if self.terminal:
            line = line[:max(1, width - 1)]
        print(("\r\033[2K" if self.terminal else "") + line,
              end="" if self.terminal else "\n", file=self.stream, flush=True)
        self.last_render = time.monotonic()

    def _heartbeat(self) -> None:
        while not self.stop.wait(0.25):
            with self.lock:
                self._read_bootstrap()
                if time.monotonic() - self.last_render >= (0.25 if self.terminal else 30):
                    self._render()

    def begin(self, key: str) -> None:
        with self.lock:
            if self.finished or key not in self.labels:
                return
            self._read_bootstrap()
            self.key, self.text, self.fraction, self.watch = key, "", 0.0, None
            self.item_label = ""
            self._record({"event": "progress-stage", "stage": key})
            self._render()

    def complete(self, key: str, *, cached: bool = False) -> None:
        with self.lock:
            if self.finished or key not in self.labels or key in self.completed:
                return
            self._read_bootstrap()
            self.completed.add(key)
            self.key, self.text, self.fraction, self.watch = key, "Reused verified cache" if cached else "Done", 0.0, None
            self.item_label = ""
            self._record({"event": "progress-complete", "stage": key, "cached": cached})
            if key == "vm":
                self.finished = True
                self.text = "Build complete; VM started" if self.profile.startswith("desktop") else "Build and boot check complete"
                self.stop.set()
            self._render()
            if self.finished and self.terminal:
                print(file=self.stream, flush=True)

    def detail(self, text: str, *, log: Path | None = None) -> None:
        with self.lock:
            if self.finished:
                return
            self.text = f"{self.item_label} | {text}" if self.item_label else text
            self._record({"event": "progress-detail", "stage": self.key, "detail": text, "log": log})
            self._render()

    def item(self, name: str, index: int, total: int, *, done: bool = False) -> None:
        with self.lock:
            if self.finished or not total:
                return
            self.text = f"{name} ({index}/{total})" + (" done" if done else "")
            self.item_label = self.text
            self.fraction = (index if done else index - 1) / total
            self._record({"event": "progress-item", "stage": self.key, "name": name,
                          "index": index, "total": total, "done": done})
            self._render()

    def event(self, value: object) -> None:
        with self.lock:
            self._record(value)
            original = value
            value = value if isinstance(value, dict) else {}
            name = value.get("event")
            if name in {"stage-start", "stage-cached", "stage-done"}:
                group = _groups.get(value.get("stage"), [])
                if name == "stage-start" and group:
                    self.begin(group[0])
                elif name != "stage-start":
                    for key in group:
                        self.complete(key, cached=name == "stage-cached")
            elif name == "command" and not self.finished:
                arguments = [str(argument) for argument in value["argv"]]
                if self.key == "bootstrap" and "--check" not in arguments:
                    manifest = self.project / "bootstrap/stages.toml"
                    if manifest.is_file():
                        names = [row["name"] for row in tomllib.loads(manifest.read_text())["stages"]]
                        log = Path(value["log"])
                        offset = log.stat().st_size if log.exists() else 0
                        self.watch = {"path": log, "offset": offset, "buffer": "", "names": names, "done": set()}
                else:
                    command = Path(arguments[0]).name
                    self.detail(command, log=Path(value["log"]))
            elif name is None:
                # Preserve diagnostic/preflight reports and final VM receipts.
                if self.terminal and not self.finished:
                    print("\r\033[2K", end="", file=self.stream, flush=True)
                print(json.dumps(original, indent=2, default=str), flush=True)
                if self.terminal and not self.finished:
                    self._render()

    def _read_bootstrap(self) -> None:
        if not self.watch:
            return
        watch = self.watch
        try:
            with watch["path"].open("rb") as stream:
                stream.seek(watch["offset"])
                data = stream.read(64 * 1024)
                watch["offset"] = stream.tell()
        except FileNotFoundError:
            return
        lines = (watch["buffer"] + data.decode(errors="replace")).split("\n")
        watch["buffer"] = lines.pop()[-4096:]
        for line in lines:
            match = re.match(r"^([a-z0-9-]+): (building; log |complete in |up to date|verified existing receipts)", line)
            if not match or match[1] not in watch["names"]:
                continue
            name = match[1]
            done = not match[2].startswith("building")
            if done:
                watch["done"].add(name)
            index, total = watch["names"].index(name) + 1, len(watch["names"])
            self.text = f"{name} ({index}/{total})" + (" done" if done else "")
            self.fraction = len(watch["done"]) / total
            self._record({"event": "progress-bootstrap", "stage": name, "done": done})
            self._render()
