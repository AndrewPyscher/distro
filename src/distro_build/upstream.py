"""Follow component main branches while preserving local contribution work."""
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import os
from pathlib import Path
import re
import subprocess

from .source_projects import catalog


_session = ContextVar("source_sync_session", default=None)


@contextmanager
def session():
    """Fetch each source root once across nested CLI stages in one invocation."""
    if _session.get() is not None:
        yield
        return
    token = _session.set({})
    try:
        yield
    finally:
        _session.reset(token)


def git(path: Path, *arguments: str, check: bool = True):
    try:
        result = subprocess.run(["git", "-C", str(path), *arguments], capture_output=True,
                                text=True, timeout=120,
                                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{path.name}: git {arguments[0]} timed out; check connectivity and retry") from error
    if check and result.returncode:
        raise RuntimeError(f"{path.name}: git {arguments[0]} failed: {result.stderr.strip()}")
    return result


def normalized_url(url: str) -> str:
    return url.strip().removesuffix("/").removesuffix(".git").replace("git@github.com:", "https://github.com/")


def check_repository(path: Path, expected_url: str, *, offline: bool = False) -> dict:
    root = git(path, "rev-parse", "--show-toplevel").stdout.strip()
    if Path(root).resolve() != path.resolve():
        raise RuntimeError(f"{path}: expected a separate component repository")
    actual = git(path, "remote", "get-url", "origin").stdout.strip()
    if normalized_url(actual) != normalized_url(expected_url):
        raise RuntimeError(f"{path}: origin differs from its canonical organization repository")
    if offline:
        reference = git(path, "symbolic-ref", "refs/remotes/origin/HEAD").stdout.strip()
        branch = reference.removeprefix("refs/remotes/origin/")
    else:
        advertised = git(path, "ls-remote", "--symref", "origin", "HEAD").stdout
        match = re.search(r"^ref: refs/heads/(.+)\s+HEAD$", advertised, re.M)
        if not match:
            raise RuntimeError(f"{path}: cannot discover organization's default branch")
        branch = match.group(1)
        reference = "refs/remotes/origin/" + branch
        git(path, "fetch", "--no-tags", "origin", f"+refs/heads/{branch}:{reference}")
        git(path, "symbolic-ref", "refs/remotes/origin/HEAD", reference)
    ahead, behind = map(int, git(path, "rev-list", "--left-right", "--count", f"HEAD...{reference}").stdout.split())
    return {"path": str(path), "url": expected_url, "branch": branch,
            "upstream_commit": git(path, "rev-parse", reference).stdout.strip(),
            "head": git(path, "rev-parse", "HEAD").stdout.strip(),
            "ahead": ahead, "behind": behind, "fetched": not offline,
            "action": "integrate upstream in owning repository, adapt local changes and retry" if behind else "ready"}


def check(project: Path, source_root: Path, projects: set[str], *, offline: bool = False) -> list[dict]:
    registered = catalog(project)
    missing = projects - registered.keys()
    if missing:
        raise RuntimeError(f"Register source repositories in source-projects.toml: {sorted(missing)}")
    repositories = [(project, "https://github.com/WIPOperatingSystemName/distro.git")]
    repositories += [(source_root / name, registered[name]["repository"]) for name in sorted(projects)]
    return [check_repository(path, url, offline=offline) for path, url in repositories]


def synchronize_distro(project: Path) -> dict:
    """Fast-forward the coordinator; the caller must reload after an update."""
    result = check_repository(project, "https://github.com/WIPOperatingSystemName/distro.git")
    if result["ahead"] and result["behind"]:
        raise RuntimeError(f"{project}: local distro history diverges from origin/{result['branch']}; "
                           "preserve local work, merge upstream deliberately and rerun ./run")
    if result["behind"]:
        update = git(project, "merge", "--ff-only", "refs/remotes/origin/" + result["branch"], check=False)
        if update.returncode:
            raise RuntimeError(f"{project}: cannot update distro without overwriting local work; "
                               f"resolve the local changes and rerun ./run. {update.stderr.strip()}")
    head = git(project, "rev-parse", "HEAD").stdout.strip()
    return {**result, "previous_head": result["head"], "head": head,
            "action": "updated" if head != result["head"] else "current"}


def synchronize_repository(path: Path, expected_url: str, *, offline: bool = False) -> dict:
    """Clone main or fast-forward; Git refuses updates that overwrite local work."""
    if not path.exists() or (path.is_dir() and not any(path.iterdir())):
        if offline:
            raise RuntimeError(f"{path}: source checkout is missing; run sources sync online")
        path.parent.mkdir(parents=True, exist_ok=True)
        git(path.parent, "clone", "--branch", "main", "--", expected_url, str(path))
    root = git(path, "rev-parse", "--show-toplevel").stdout.strip()
    if Path(root).resolve() != path.resolve():
        raise RuntimeError(f"{path}: expected a separate component repository; existing files were preserved")
    actual = git(path, "remote", "get-url", "origin").stdout.strip()
    if normalized_url(actual) != normalized_url(expected_url):
        raise RuntimeError(f"{path}: origin differs from its canonical organization repository")
    before = git(path, "rev-parse", "HEAD").stdout.strip()
    if offline:
        return {"path": str(path), "head": before, "action": "local-offline", "fetched": False}
    reference = "refs/remotes/origin/main"
    git(path, "fetch", "--no-tags", "origin", f"+refs/heads/main:{reference}")
    target = git(path, "rev-parse", reference).stdout.strip()
    ahead, behind = map(int, git(path, "rev-list", "--left-right", "--count", f"HEAD...{reference}").stdout.split())
    if ahead and behind:
        raise RuntimeError(f"{path}: local history diverges from origin/main ({ahead} local, {behind} upstream commits); "
                           "preserve local work, merge upstream in this repository and retry")
    branch = git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
    if not branch:
        local_main = git(path, "rev-parse", "--verify", "refs/heads/main", check=False)
        if local_main.returncode:
            git(path, "switch", "-c", "main")
        elif git(path, "merge-base", "--is-ancestor", before, "refs/heads/main", check=False).returncode == 0:
            git(path, "switch", "main")
        else:
            raise RuntimeError(f"{path}: detached checkout and local main contain different work; "
                               "select the intended contribution branch and retry")
        branch = "main"
    update = git(path, "merge", "--ff-only", reference, check=False)
    if update.returncode:
        raise RuntimeError(f"{path}: cannot fast-forward to origin/main without overwriting local work; "
                           f"resolve the local changes and retry. {update.stderr.strip()}")
    head = git(path, "rev-parse", "HEAD").stdout.strip()
    return {"path": str(path), "url": expected_url, "branch": branch, "previous_head": before,
            "head": head, "upstream_commit": target, "fetched": True,
            "action": "updated" if head != before else "current"}


def synchronize(project: Path, source_root: Path | None = None, *, offline: bool = False, emit=lambda value: None) -> dict:
    project = project.resolve()
    source_root = (source_root or project / "sources").resolve()
    if (source_root / "source-manifest.json").is_file():
        # Explicit source bundles are immutable replay inputs, never live Git clones.
        return {"source_root": str(source_root), "action": "portable-source-replay", "repositories": []}
    key = (str(project), str(source_root), offline)
    active = _session.get()
    if active is not None and key in active:
        return active[key]
    projects = catalog(project)
    for name, record in projects.items():
        if not record.get("repository") or record.get("branch") != "main":
            raise RuntimeError(f"Register {name}'s organization repository and main branch in source-projects.toml")
    state = project / "out/state/locks"
    state.mkdir(parents=True, exist_ok=True)
    repositories = []
    with (state / "sources.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name, record in projects.items():
            emit({"event": "source-sync-start", "source": name, "offline": offline})
            result = synchronize_repository(source_root / name, record["repository"], offline=offline)
            repositories.append({"name": name, **result})
            emit({"event": "source-sync-done", "source": name, **result})
    result = {"source_root": str(source_root), "offline": offline, "repositories": repositories}
    if active is not None:
        active[key] = result
    return result
