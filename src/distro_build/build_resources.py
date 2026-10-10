"""Conservative defaults and a shared budget for independent package builds."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import os
from pathlib import Path

from .model import BuildError


def default_jobs() -> int:
    """Respect Linux affinity and cgroup v2 limits; reserve memory per compiler."""
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    memory = None
    try:
        memory = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                          if line.startswith("MemTotal:"))) * 1024
    except (OSError, ValueError, StopIteration):
        pass
    try:
        relative = next(line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines()
                        if line.startswith("0::"))
        group = Path("/sys/fs/cgroup") / relative.lstrip("/")
        for parent in [group, *group.parents]:
            if not parent.is_relative_to("/sys/fs/cgroup"):
                break
            try:
                quota, period = (parent / "cpu.max").read_text().split()
                if quota != "max":
                    cpus = min(cpus, max(1, int(quota) // int(period)))
            except (OSError, ValueError):
                pass
            try:
                limit = int((parent / "memory.max").read_text())
                memory = min(memory, limit) if memory is not None else limit
            except (OSError, ValueError):
                pass
    except (OSError, StopIteration):
        pass
    # Eight jobs is the default ceiling; --jobs explicitly overrides this policy.
    memory_jobs = max(1, (memory - 512 * 1024**2) // (1536 * 1024**2)) if memory else 2
    return max(1, min(cpus, 8, memory_jobs))


def build_packages(ordered, *, jobs: int, workers: int, action):
    """Run ready packages only; sum of assigned compiler jobs never exceeds jobs.

    Runtime dependencies may form cycles and do not block compilation. Failed
    tasks stop new submissions; already running private builds finish normally.
    """
    if jobs < 1 or workers < 1:
        raise BuildError("build jobs and package workers must be positive")
    pending = list(ordered)
    artifacts = {}
    running = {}
    workers = min(workers, jobs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while pending or running:
            free = jobs - sum(budget for _, budget in running.values())
            ready = [recipe for recipe in pending if all(
                dependency in artifacts for role in ("native", "target")
                for dependency in recipe.dependencies.get(role, ()))]
            count = min(len(ready), workers - len(running), free)
            for index, recipe in enumerate(ready[:count]):
                budget = free // (count - index)
                free -= budget
                # Each worker gets a stable snapshot of completed dependencies.
                future = pool.submit(action, recipe, dict(artifacts), budget)
                running[future] = (recipe, budget)
                pending.remove(recipe)
            if not running:
                raise BuildError("no buildable packages remain; check target dependencies")
            completed, _ = wait(running, return_when=FIRST_COMPLETED)
            # Observe all failures before scheduling dependents or other work.
            for future in completed:
                future.result()
            for future in completed:
                recipe, _ = running.pop(future)
                artifacts[recipe.name] = future.result()
    return {recipe.name: artifacts[recipe.name] for recipe in ordered}
