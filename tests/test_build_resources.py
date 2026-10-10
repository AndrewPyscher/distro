"""Dependency ordering, bounded concurrency and resource defaults."""
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build.build_resources import build_packages, default_jobs


def recipe(name, target=(), runtime=()):
    return SimpleNamespace(name=name, dependencies={"target": target, "runtime": runtime})


class ResourceTests(unittest.TestCase):
    def test_ready_packages_overlap_within_budget_and_dependency_waits(self):
        lock = threading.Lock()
        active = maximum = count = parallel = 0
        rendezvous = threading.Barrier(2)

        def build(item, artifacts, jobs):
            nonlocal active, maximum, count, parallel
            if item.name == "consumer":
                self.assertEqual(set(artifacts), {"first", "second"})
            with lock:
                active += jobs
                count += 1
                maximum = max(maximum, active)
                parallel = max(parallel, count)
            if item.name != "consumer":
                rendezvous.wait(timeout=3)
            time.sleep(0.01)
            with lock:
                active -= jobs
                count -= 1
            return {"name": item.name, "jobs": jobs}

        result = build_packages([recipe("first", runtime=("second",)), recipe("second", runtime=("first",)),
                                 recipe("consumer", target=("first", "second"))],
                                jobs=5, workers=2, action=build)
        self.assertEqual(parallel, 2)
        self.assertEqual(maximum, 5)
        self.assertEqual(result["consumer"]["jobs"], 5)

    def test_failure_stops_dependents_and_queued_packages(self):
        called = []

        def fail(item, artifacts, jobs):
            called.append(item.name)
            raise RuntimeError("failed compile")

        with self.assertRaisesRegex(RuntimeError, "failed compile"):
            build_packages([recipe("bad"), recipe("dependent", target=("bad",)), recipe("queued")],
                           jobs=1, workers=4, action=fail)
        self.assertEqual(called, ["bad"])

    def test_serial_override_and_single_job(self):
        for jobs, workers in [(7, 1), (1, 8)]:
            budgets = []
            build_packages([recipe("a"), recipe("b")], jobs=jobs, workers=workers,
                           action=lambda item, artifacts, budget: budgets.append(budget))
            self.assertEqual(budgets, [jobs, jobs])

    def test_defaults_respect_memory_affinity_and_parent_cgroup_quota(self):
        files = {"/proc/meminfo": "MemTotal: 16777216 kB\n", "/proc/self/cgroup": "0::/limited/child\n",
                 "/sys/fs/cgroup/limited/memory.max": str(4 * 1024**3),
                 "/sys/fs/cgroup/limited/cpu.max": "100000 100000"}

        def read(path, *args, **kwargs):
            if str(path) not in files:
                raise FileNotFoundError(path)
            return files[str(path)]

        with patch.object(Path, "read_text", read), patch("os.sched_getaffinity", return_value=set(range(24))):
            self.assertEqual(default_jobs(), 1)
            files["/sys/fs/cgroup/limited/cpu.max"] = "max 100000"
            self.assertEqual(default_jobs(), 2)
            files["/sys/fs/cgroup/limited/memory.max"] = "max"
            self.assertEqual(default_jobs(), 8)
        with patch.object(Path, "read_text", side_effect=OSError), patch("os.sched_getaffinity", return_value={0}):
            self.assertEqual(default_jobs(), 1)
