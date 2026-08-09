from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repoevidence.project_context import (
    ProjectPathError,
    discover_project_context,
)


def _git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "tests@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "RepoEvidence Tests"],
        check=True,
    )
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return root


def test_no_path_uses_git_top_level_but_preserves_opened_from(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    nested = root / "packages" / "service"
    nested.mkdir(parents=True)

    context = discover_project_context(cwd=nested)

    assert context.project_root == root.resolve()
    assert context.opened_from == nested.resolve()
    assert context.git.repository is True
    assert context.git.top_level == root.resolve()
    assert context.git.commit
    assert context.git.branch == "master" or context.git.branch == "main"
    assert context.git.dirty is False
    assert context.git.status_known is True


def test_explicit_path_always_wins_over_git_top_level(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    nested = root / "packages" / "service"
    nested.mkdir(parents=True)

    context = discover_project_context(nested, cwd=root)

    assert context.project_root == nested.resolve()
    assert context.opened_from == root.resolve()
    assert context.git.repository is True
    assert context.git.top_level == root.resolve()


def test_dirty_worktree_is_observable_without_scanning_source(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    (root / "README.md").write_text("changed\n", encoding="utf-8")

    context = discover_project_context(root, cwd=root)

    assert context.git.dirty is True
    assert context.git.status_known is True
    assert context.markers == ("README.md",)


def test_non_git_directory_is_valid_project_context(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "pom.xml").write_text("<project />", encoding="utf-8")

    context = discover_project_context(root, cwd=root)

    assert context.project_root == root.resolve()
    assert context.opened_from == root.resolve()
    assert context.git.repository is False
    assert context.git.status_known is True
    assert context.markers == ("pom.xml",)


def test_missing_path_has_a_stable_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(ProjectPathError) as exc_info:
        discover_project_context(missing)

    assert exc_info.value.code == "repository_path_missing"
    assert exc_info.value.path == missing.resolve()
