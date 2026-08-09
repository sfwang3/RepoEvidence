from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from repoevidence import __version__
from repoevidence.cli import _interactive_available, create_app
from repoevidence.user_config import UserSettings

runner = CliRunner()


def test_any_ci_environment_disables_full_screen_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "repoevidence.cli.sys.stdin", SimpleNamespace(isatty=lambda: True)
    )
    monkeypatch.setattr(
        "repoevidence.cli.sys.stdout", SimpleNamespace(isatty=lambda: True)
    )
    monkeypatch.setenv("CI", "0")

    assert not _interactive_available(UserSettings())


def _flyway_repository(root: Path) -> Path:
    migration = root / "src/main/resources/db/migration/V1__init.sql"
    migration.parent.mkdir(parents=True)
    migration.write_text("CREATE TABLE sample (id BIGINT PRIMARY KEY);\n", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("language", "args", "purpose"),
    [
        ("en", [], "Understand what a repository declares"),
        ("zh-CN", ["--lang", "zh-CN"], "检查仓库源码所声明的内容"),
    ],
)
def test_empty_entry_is_successful_and_side_effect_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    args: list[str],
    purpose: str,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(create_app(language), args)

    assert result.exit_code == 0
    assert purpose in result.stdout
    assert "repoevidence inspect ." in result.stdout
    assert result.stderr == ""
    assert not (tmp_path / ".repoevidence").exists()


def test_empty_entry_never_imports_interactive_ui_in_non_tty_subprocess(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path("src").resolve())
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from repoevidence.cli import main; "
                "status=0\n"
                "try: main()\n"
                "except SystemExit as exc: status=exc.code or 0\n"
                "print('interactive_loaded=' + str(any(name.startswith('repoevidence.interactive') "
                "for name in sys.modules)))\n"
                "raise SystemExit(status)"
            ),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "interactive_loaded=False" in result.stdout


@pytest.mark.parametrize(
    ("language", "args", "expected"),
    [
        ("en", ["insepct", "."], "Unknown command"),
        ("zh-CN", ["--lang", "zh-CN", "insepct", "."], "未知命令"),
        ("en", ["--unknown-option"], "Unknown option"),
        ("zh-CN", ["--lang", "zh-CN", "--unknown-option"], "未知选项"),
    ],
)
def test_command_and_option_errors_stay_nonzero_and_localized(
    language: str,
    args: list[str],
    expected: str,
) -> None:
    result = runner.invoke(create_app(language), args)

    assert result.exit_code != 0
    assert expected in result.stderr
    assert "repoevidence --help" in result.stderr
    assert result.stdout == ""
    if language == "zh-CN":
        assert "Error:" not in result.stderr
        assert "Usage:" not in result.stderr


@pytest.mark.parametrize("command", ["inspect", "scan", "report", "reconcile"])
def test_missing_repository_path_is_a_nonzero_recoverable_error(
    tmp_path: Path,
    command: str,
) -> None:
    missing = tmp_path / "does-not-exist"

    result = runner.invoke(create_app("en"), [command, str(missing)])

    assert result.exit_code != 0
    assert "Repository path not found" in result.stderr
    assert str(missing) in result.stderr
    assert "repoevidence inspect" in result.stderr
    assert "repository_path_missing" in result.stderr
    assert result.stdout == ""


def test_file_input_is_a_nonzero_recoverable_error(tmp_path: Path) -> None:
    file_path = tmp_path / "pom.xml"
    file_path.write_text("<project/>", encoding="utf-8")

    result = runner.invoke(create_app("en"), ["inspect", str(file_path)])

    assert result.exit_code != 0
    assert "Repository path is not a directory" in result.stderr
    assert str(file_path) in result.stderr
    assert "repository_path_not_directory" in result.stderr
    assert result.stdout == ""


def test_missing_command_argument_remains_nonzero_in_chinese() -> None:
    result = runner.invoke(
        create_app("zh-CN"),
        ["--lang", "zh-CN", "inspect"],
    )

    assert result.exit_code != 0
    assert "缺少仓库路径" in result.stderr
    assert "repoevidence inspect" in result.stderr
    assert "Missing argument" not in result.stderr


def test_inspect_stdout_explains_result_scope_and_next_action(tmp_path: Path) -> None:
    root = _flyway_repository(tmp_path)

    result = runner.invoke(create_app("en"), ["inspect", str(root)])

    assert result.exit_code == 0, result.stderr
    assert "Source inspection complete" in result.stdout
    assert "Database not verified" in result.stdout
    assert "Source and database agreement cannot be determined" in result.stdout
    assert "repoevidence verify mysql" in result.stdout
    assert ".repoevidence/report/index.html" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("language", "args", "expected"),
    [
        (
            "en",
            [],
            "Git metadata is unavailable because this directory is not a Git repository",
        ),
        (
            "zh-CN",
            ["--lang", "zh-CN"],
            "此目录不是 Git 仓库，因此无法获取 commit 和 branch",
        ),
    ],
)
def test_non_git_repository_is_explained_as_a_localized_source_limit(
    tmp_path: Path,
    language: str,
    args: list[str],
    expected: str,
) -> None:
    result = runner.invoke(
        create_app(language),
        [*args, "inspect", str(tmp_path)],
    )

    assert result.exit_code == 0, result.stderr
    assert expected in result.stdout
    assert result.stderr == ""


def test_mysql_configuration_failure_uses_stderr_and_never_claims_success(
    tmp_path: Path,
) -> None:
    environment = {
        "REPOEVIDENCE_MYSQL_HOST": "",
        "REPOEVIDENCE_MYSQL_PORT": "",
        "REPOEVIDENCE_MYSQL_USER": "",
        "REPOEVIDENCE_MYSQL_PASSWORD": "",
        "REPOEVIDENCE_MYSQL_DATABASE": "",
    }

    result = runner.invoke(
        create_app("en"),
        ["verify", "mysql", str(tmp_path)],
        env=environment,
    )

    assert result.exit_code != 0
    assert "Reads schema metadata and Flyway history only" in result.stdout
    assert "Database verification complete" not in result.stdout
    assert "Database verification did not complete" in result.stderr
    assert "mysql_config_missing" in result.stderr
    for name in (
        "REPOEVIDENCE_MYSQL_HOST",
        "REPOEVIDENCE_MYSQL_PORT",
        "REPOEVIDENCE_MYSQL_USER",
        "REPOEVIDENCE_MYSQL_PASSWORD",
        "REPOEVIDENCE_MYSQL_DATABASE",
    ):
        assert name in result.stderr
    assert (tmp_path / ".repoevidence/verification/mysql.json").is_file()


def test_reconcile_with_failed_verification_is_nonzero_and_not_no_drift(
    tmp_path: Path,
) -> None:
    inspect = runner.invoke(create_app("en"), ["scan", str(tmp_path)])
    assert inspect.exit_code == 0
    verify = runner.invoke(
        create_app("en"),
        ["verify", "mysql", str(tmp_path)],
        env={
            "REPOEVIDENCE_MYSQL_HOST": "",
            "REPOEVIDENCE_MYSQL_PORT": "",
            "REPOEVIDENCE_MYSQL_USER": "",
            "REPOEVIDENCE_MYSQL_PASSWORD": "",
            "REPOEVIDENCE_MYSQL_DATABASE": "",
        },
    )
    assert verify.exit_code != 0

    result = runner.invoke(create_app("en"), ["reconcile", str(tmp_path)])

    assert result.exit_code != 0
    assert "No Flyway differences found" not in result.stdout
    assert "Source and database comparison did not complete" in result.stderr
    assert "repoevidence verify mysql" in result.stderr


def test_scan_uses_existing_runtime_artifact_content_for_coverage(
    tmp_path: Path,
) -> None:
    failed_runtime = {
        "schema_version": "0.1",
        "verifier": "mysql",
        "repository_root": str(tmp_path.resolve()),
        "metadata": {
            "tool_version": __version__,
            "started_at": "2026-08-09T00:00:00Z",
            "finished_at": "2026-08-09T00:00:00Z",
            "observed_at": "2026-08-09T00:00:00Z",
        },
        "evidence": [],
        "facts": [],
        "conflicts": [],
        "warnings": [],
        "errors": [
            {
                "code": "mysql_connection_failed",
                "message": "Unable to connect to MySQL.",
            }
        ],
    }
    path = tmp_path / ".repoevidence/verification/mysql.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(failed_runtime, indent=2) + "\n", encoding="utf-8")

    result = runner.invoke(create_app("en"), ["scan", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert "Database verification failed" in result.stdout
    assert "Database not verified" not in result.stdout


def test_invalid_report_artifact_is_nonzero_with_recovery(tmp_path: Path) -> None:
    artifact = tmp_path / ".repoevidence/evidence.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{not-json", encoding="utf-8")

    result = runner.invoke(create_app("en"), ["report", str(tmp_path)])

    assert result.exit_code != 0
    assert "Report could not be generated" in result.stderr
    assert "repoevidence inspect" in result.stderr
    assert "invalid_static_scan_json" in result.stderr
    assert "Report generated" not in result.stdout


def test_repository_permission_error_is_nonzero_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_with_permission_error(repo_path: Path) -> object:
        raise PermissionError("permission denied")

    monkeypatch.setattr("repoevidence.cli.scan_repository", fail_with_permission_error)

    result = runner.invoke(create_app("en"), ["scan", str(tmp_path)])

    assert result.exit_code != 0
    assert "Repository files could not be accessed" in result.stderr
    assert "Check read and write permissions" in result.stderr
    assert "repository_io_error" in result.stderr
    assert "Traceback" not in result.output


def test_help_prioritizes_inspect_and_names_database_boundary() -> None:
    result = runner.invoke(create_app("en"), ["--help"])

    assert result.exit_code == 0
    assert result.stdout.index("inspect") < result.stdout.index("scan")
    assert "recommended first inspection" in result.stdout.lower()
    assert "Only verify mysql connects to a database" in result.stdout


def test_chinese_help_is_task_oriented_without_english_framework_errors() -> None:
    root_result = runner.invoke(
        create_app("zh-CN"),
        ["--lang", "zh-CN", "--help"],
    )
    inspect_result = runner.invoke(
        create_app("zh-CN"),
        ["--lang", "zh-CN", "inspect", "--help"],
    )

    assert root_result.exit_code == 0
    assert "建议首次运行" in root_result.stdout
    assert "只有 verify mysql 会连接数据库" in root_result.stdout
    assert root_result.stdout.index("inspect") < root_result.stdout.index("scan")
    assert "[default:" not in root_result.stdout
    assert inspect_result.exit_code == 0
    assert "[required]" not in inspect_result.stdout


def test_redirected_and_no_color_inspect_output_contains_no_ansi(tmp_path: Path) -> None:
    root = _flyway_repository(tmp_path)

    result = runner.invoke(
        create_app("en"),
        ["inspect", str(root)],
        env={"NO_COLOR": "1"},
        color=False,
    )

    assert result.exit_code == 0, result.stderr
    assert "\x1b[" not in result.stdout
    assert "Source inspection complete" in result.stdout
    assert "Next step" in result.stdout


def test_machine_artifact_remains_canonical_under_new_presentation(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        create_app("zh-CN"),
        ["--lang", "zh-CN", "inspect", str(tmp_path)],
    )

    assert result.exit_code == 0, result.stderr
    payload = json.loads(
        (tmp_path / ".repoevidence/evidence.json").read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == "0.1"
    assert payload["repository_root"] == str(tmp_path.resolve())
    assert "已完成源码检查" not in json.dumps(payload, ensure_ascii=False)
