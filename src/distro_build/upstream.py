"""Check contributor checkouts without merging or moving source pins."""
from pathlib import Path
import configparser
import re
import subprocess

from .source_projects import relative_path


def git(path: Path, *arguments: str, check: bool = True):
    result = subprocess.run(["git", "-C", str(path), *arguments], capture_output=True,
                            text=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError(f"{path.name}: git {arguments[0]} failed: {result.stderr.strip()}")
    return result


def normalized_url(url: str) -> str:
    return url.strip().removesuffix("/").removesuffix(".git").replace("git@github.com:", "https://github.com/")


def check_repository(path: Path, expected_url: str, *, offline: bool = False) -> dict:
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
    modules = configparser.ConfigParser(interpolation=None)
    modules.read(project / ".gitmodules")
    registered = {}
    for section in modules.sections():
        path = Path(relative_path(modules[section]["path"]))
        if path.parent != Path("sources"):
            raise RuntimeError("Source submodules must be registered under sources/")
        registered[path.name] = modules[section]["url"]
    missing = projects - registered.keys()
    if missing:
        raise RuntimeError(f"Register source repositories in .gitmodules: {sorted(missing)}")
    repositories = [(project, "https://github.com/WIPOperatingSystemName/distro.git")]
    repositories += [(source_root / name, registered[name]) for name in sorted(projects)]
    return [check_repository(path, url, offline=offline) for path, url in repositories]
