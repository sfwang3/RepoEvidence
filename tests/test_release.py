from __future__ import annotations

import importlib.metadata
import json
import tomllib
from importlib.resources import files
from pathlib import Path

from typer.testing import CliRunner

from repoevidence import __version__
from repoevidence.application import inspect_repository
from repoevidence.cli import app


def _project_metadata() -> dict[str, object]:
    with Path("pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


def test_project_metadata_is_ready_for_public_package() -> None:
    project = _project_metadata()

    assert project["name"] == "repoevidence"
    assert project["version"] == "0.2.0"
    assert project["version"] == __version__ == importlib.metadata.version("repoevidence")
    assert project["description"]
    assert project["readme"] == "README.pypi.md"
    assert project["requires-python"] == ">=3.12"
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert {
        "rich>=13.7",
        "platformdirs>=4,<5",
        "textual>=8.2,<9",
    }.issubset(project["dependencies"])
    assert project["authors"]
    assert project["urls"]["Homepage"] == "https://github.com/sfwang3/RepoEvidence"
    assert project["urls"]["Repository"] == "https://github.com/sfwang3/RepoEvidence"
    assert project["urls"]["Issues"] == "https://github.com/sfwang3/RepoEvidence/issues"
    assert project["urls"]["简体中文文档"] == "https://github.com/sfwang3/RepoEvidence/blob/main/README.zh-CN.md"
    assert "repoevidence = \"repoevidence.cli:main\"" in Path("pyproject.toml").read_text()
    assert "License :: OSI Approved" not in project["classifiers"]


def test_localization_module_is_a_package_resource() -> None:
    assert files("repoevidence").joinpath("i18n.py").is_file()


def test_current_artifacts_use_the_package_version_source(tmp_path: Path) -> None:
    inspect_repository(tmp_path)

    evidence = json.loads((tmp_path / ".repoevidence/evidence.json").read_text())
    manifest = json.loads(
        (tmp_path / ".repoevidence/report/manifest.json").read_text()
    )
    report = (tmp_path / ".repoevidence/report/index.html").read_text()

    assert evidence["metadata"]["tool_version"] == __version__ == "0.2.0"
    assert manifest["generator_version"] == __version__
    assert f"Tool version {__version__}" in report


def test_bilingual_readmes_keep_github_and_pypi_roles_clear() -> None:
    english = Path("README.md").read_text(encoding="utf-8")
    chinese = Path("README.zh-CN.md").read_text(encoding="utf-8")
    pypi = Path("README.pypi.md").read_text(encoding="utf-8")

    assert english.startswith("# RepoEvidence\n\nEnglish | [简体中文](README.zh-CN.md)")
    assert chinese.startswith("# RepoEvidence\n\n[English](README.md) | 简体中文")
    for text in (
        "What RepoEvidence is",
        "Quick Start",
        "Interactive Workspace",
        "repoevidence verify mysql",
        "repoevidence reconcile",
        "repoevidence report",
        "report/manifest.json",
        "Runtime verification safety",
        "Status confidence and snapshots",
        "Security and trust model",
        "Installation and supported environments",
        "License",
        "RepoEvidence 是什么",
        "快速开始",
        "Runtime verification 的安全边界",
        "状态可信度与 snapshot",
        "安装与支持环境",
        "repoevidence --lang zh-CN",
    ):
        assert text in pypi
    for document in (english, chinese, pypi):
        assert "repoevidence" in document
        assert "report/manifest.json" in document
        assert "REPOEVIDENCE_MYSQL_PASSWORD" in document


def test_official_apache_license_is_present() -> None:
    license_text = Path("LICENSE").read_text(encoding="utf-8")

    assert license_text.startswith("\n                                 Apache License\n")
    assert "Version 2.0, January 2004" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
    assert "APPENDIX: How to apply the Apache License to your work." in license_text


def test_public_help_has_stable_commands_without_internal_milestones() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("scan", "verify", "reconcile", "report", "inspect"):
        assert command in result.output
    assert "M0" not in result.output
    assert "M5.5" not in result.output


def test_missing_scan_path_has_clean_nonzero_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    result = CliRunner().invoke(app, ["scan", str(missing)])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "does not exist" in result.output


def test_missing_evidence_report_has_clean_structured_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["report", str(tmp_path)])

    assert result.exit_code != 0
    assert "missing_static_scan" in result.output
    assert "Traceback" not in result.output
    assert "password" not in result.output.lower()


def test_reconcile_missing_artifacts_has_clean_nonzero_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["reconcile", str(tmp_path)])

    assert result.exit_code != 0
    assert "missing_static_scan" in result.output
    assert "missing_mysql_verification" in result.output
    assert "Traceback" not in result.output
    assert "repoevidence inspect" in result.stderr


def test_verify_mysql_missing_environment_has_clean_nonzero_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for key in (
        "REPOEVIDENCE_MYSQL_HOST",
        "REPOEVIDENCE_MYSQL_PORT",
        "REPOEVIDENCE_MYSQL_USER",
        "REPOEVIDENCE_MYSQL_PASSWORD",
        "REPOEVIDENCE_MYSQL_DATABASE",
    ):
        monkeypatch.delenv(key, raising=False)

    result = CliRunner().invoke(app, ["verify", "mysql", str(tmp_path)])

    assert result.exit_code != 0
    assert "mysql_config_missing" in result.output
    assert "Traceback" not in result.output
    assert "REPOEVIDENCE_MYSQL_PASSWORD" in result.stderr
    assert "REPOEVIDENCE_MYSQL_PASSWORD=" not in result.stderr


def test_minimal_static_cli_path_remains_usable(tmp_path: Path) -> None:
    scan = CliRunner().invoke(app, ["scan", str(tmp_path)])
    report = CliRunner().invoke(app, ["report", str(tmp_path)])

    assert scan.exit_code == 0, scan.output
    assert report.exit_code == 0, report.output
    assert json.loads((tmp_path / ".repoevidence/evidence.json").read_text())[
        "schema_version"
    ] == "0.1"
    assert (tmp_path / ".repoevidence/report/index.html").is_file()
