import subprocess
from pathlib import Path

from repoevidence.collectors.repository_metadata import RepositoryMetadataCollector


def create_git_repository(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    (path / "pom.xml").write_text("<project />", encoding="utf-8")
    (path / "build.gradle").write_text("plugins {}", encoding="utf-8")
    (path / "package.json").write_text("{}", encoding="utf-8")
    (path / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=M0 Test",
            "-c",
            "user.email=m0@example.com",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )


def test_collects_git_and_build_metadata(tmp_path: Path) -> None:
    create_git_repository(tmp_path)

    result = RepositoryMetadataCollector().collect(tmp_path)
    evidence = {item.id: item for item in result.evidence}
    facts = {item.id: item for item in result.facts}

    assert evidence["ev.repository.root"].value == str(tmp_path.resolve())
    assert evidence["ev.git.repository_check"].value["stdout"].strip() == "true"
    assert facts["fact.git.repository_exists"].value is True
    assert facts["fact.git.repository_exists"].evidence_ids == ["ev.git.repository_check"]
    assert len(facts["fact.git.head_commit"].value) == 40
    assert facts["fact.git.current_branch"].value == "main"
    assert facts["fact.file.pom_xml_exists"].value is True
    assert facts["fact.file.build_gradle_exists"].value is True
    assert facts["fact.file.package_json_exists"].value is True
    assert facts["fact.file.docker_compose_yml_exists"].value is True
    assert all(item.id.startswith("ev.") for item in result.evidence)
    assert all(item.id.startswith("fact.") for item in result.facts)
    assert not result.errors


def test_non_git_directory_reports_false_without_failing_scan(tmp_path: Path) -> None:
    result = RepositoryMetadataCollector().collect(tmp_path)
    evidence = {item.id: item for item in result.evidence}
    facts = {item.id: item for item in result.facts}

    assert facts["fact.git.repository_exists"].value is False
    assert "fact.git.head_commit" not in facts
    assert "fact.git.current_branch" not in facts
    assert evidence["ev.git.head_commit"].value["reason"] == "not a Git repository"
    assert evidence["ev.git.current_branch"].value["reason"] == "not a Git repository"
    assert result.warnings
    assert not result.errors
