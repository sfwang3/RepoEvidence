"""Read-only project identity and Git capability discovery for the workspace."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ProjectPathError(Exception):
    """A stable, presentation-neutral project path problem."""

    def __init__(self, code: str, path: Path) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code}: {path}")


@dataclass(frozen=True)
class GitContext:
    """The bounded Git metadata read during workspace startup."""

    repository: bool
    top_level: Path | None
    branch: str | None
    commit: str | None
    dirty: bool | None
    status_known: bool
    status_fingerprint: str | None = None

    @property
    def short_commit(self) -> str | None:
        return self.commit[:8] if self.commit else None


@dataclass(frozen=True)
class ProjectContext:
    """The project subject and the path from which the user opened it."""

    project_root: Path
    opened_from: Path
    repository_name: str
    git: GitContext
    markers: tuple[str, ...] = ()


_PROJECT_MARKERS = (
    "README.md",
    "README.rst",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "package.json",
    "docker-compose.yml",
)


def discover_project_context(
    path: str | Path | None = None,
    *,
    cwd: str | Path | None = None,
) -> ProjectContext:
    """Discover a project without invoking collectors or mutating the filesystem.

    An explicit path is always the project root. Without a path, a cwd inside a
    Git worktree uses the Git top-level; otherwise the cwd itself is retained.
    """

    invocation_cwd = Path(cwd or Path.cwd()).expanduser().resolve()
    if not invocation_cwd.exists():
        raise ProjectPathError("repository_path_missing", invocation_cwd)
    if not invocation_cwd.is_dir():
        raise ProjectPathError("repository_path_not_directory", invocation_cwd)
    explicit_root = None if path is None else Path(path).expanduser().resolve()
    if explicit_root is not None:
        _validate_path(explicit_root)
        project_root = explicit_root
        opened_from = invocation_cwd
    else:
        project_root = invocation_cwd
        opened_from = invocation_cwd

    git = _discover_git(project_root)
    if explicit_root is None and git.top_level is not None:
        project_root = git.top_level
        # Re-read status against the selected root so the project header and
        # the artifact location describe the same repository subject.
        git = _discover_git(project_root)

    markers = tuple(
        marker for marker in _PROJECT_MARKERS if (project_root / marker).is_file()
    )
    return ProjectContext(
        project_root=project_root,
        opened_from=opened_from,
        repository_name=project_root.name or str(project_root),
        git=git,
        markers=markers,
    )


def _validate_path(path: Path) -> None:
    if not path.exists():
        raise ProjectPathError("repository_path_missing", path)
    if not path.is_dir():
        raise ProjectPathError("repository_path_not_directory", path)


def _discover_git(root: Path) -> GitContext:
    top_level_output = _run_git(root, ["rev-parse", "--show-toplevel"])
    if top_level_output is None:
        return GitContext(
            repository=False,
            top_level=None,
            branch=None,
            commit=None,
            dirty=None,
            status_known=False,
            status_fingerprint=None,
        )
    if top_level_output.returncode != 0:
        return GitContext(
            repository=False,
            top_level=None,
            branch=None,
            commit=None,
            dirty=False,
            status_known=True,
            status_fingerprint=None,
        )

    top_level = Path(top_level_output.stdout.strip()).expanduser().resolve()
    commit = _git_value(root, ["rev-parse", "HEAD"])
    branch = _git_value(root, ["symbolic-ref", "--short", "-q", "HEAD"])
    status = _run_git(root, ["status", "--porcelain=v1", "--untracked-files=normal"])
    return GitContext(
        repository=True,
        top_level=top_level,
        branch=branch,
        commit=commit,
        dirty=(bool(status.stdout) if status is not None and status.returncode == 0 else None),
        status_known=status is not None and status.returncode == 0,
        status_fingerprint=(
            hashlib.sha256(status.stdout.encode("utf-8")).hexdigest()
            if status is not None and status.returncode == 0
            else None
        ),
    )


def _git_value(root: Path, args: list[str]) -> str | None:
    result = _run_git(root, args)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
