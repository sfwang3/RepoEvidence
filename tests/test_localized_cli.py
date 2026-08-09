from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoevidence.cli import create_app, main


def test_chinese_help_keeps_command_and_option_names() -> None:
    result = CliRunner().invoke(create_app("zh-CN"), ["--lang", "zh-CN", "--help"])

    assert result.exit_code == 0, result.output
    assert "安全检查仓库源码" in result.output
    assert "建议首次运行" in result.output
    assert "scan" in result.output
    assert "verify" in result.output
    assert "--lang" in result.output
    assert "用法：" in result.output
    assert "选项：" in result.output
    assert "命令：" in result.output
    assert "显示此帮助信息并退出。" in result.output
    assert "Show completion" not in result.output
    assert "REPOEVIDENCE_LANG" not in result.output or "auto" in result.output


def test_chinese_subcommand_help_localizes_framework_headings() -> None:
    result = CliRunner().invoke(
        create_app("zh-CN"),
        ["--lang", "zh-CN", "scan", "--help"],
    )

    assert result.exit_code == 0, result.output
    assert "用法：" in result.output
    assert "参数：" in result.output
    assert "选项：" in result.output
    assert "REPO_PATH" in result.output
    assert "只检查源码" in result.output


def test_chinese_inspect_uses_selected_language_and_existing_report(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        create_app("zh-CN"),
        ["--lang", "zh-CN", "inspect", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "已完成源码检查" in result.stdout
    assert "尚未验证数据库" in result.stdout
    assert ".repoevidence/report/index.html" in result.stdout
    html = (tmp_path / ".repoevidence/report/index.html").read_text(encoding="utf-8")
    assert '<html lang="zh-CN">' in html


def test_main_inspect_uses_explicit_cli_language(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--lang", "zh-CN", "inspect", str(tmp_path)])

    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "已完成源码检查" in output
    assert "尚未验证数据库" in output
    html = (tmp_path / ".repoevidence/report/index.html").read_text(encoding="utf-8")
    assert '<html lang="zh-CN">' in html


def test_inspect_uses_environment_language(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("REPOEVIDENCE_LANG", "zh-CN")

    with pytest.raises(SystemExit) as raised:
        main(["inspect", str(tmp_path)])

    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "已完成源码检查" in output
    assert "尚未验证数据库" in output


def test_main_preparses_cli_language_before_building_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--lang", "zh-CN", "--help"])

    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "安全检查仓库源码" in output
    assert "建议首次运行" in output
    assert "scan" in output


def test_main_uses_environment_language_when_cli_option_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("REPOEVIDENCE_LANG", "zh-CN")

    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    assert "安全检查仓库源码" in capsys.readouterr().out


def test_cli_language_has_priority_over_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("REPOEVIDENCE_LANG", "zh-CN")

    with pytest.raises(SystemExit) as raised:
        main(["--lang", "en", "--help"])

    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "Inspect repository source safely" in output
    assert "安全检查仓库源码" not in output


def test_invalid_cli_language_fails_clearly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--lang", "fr", "--help"])

    assert raised.value.code == 2
    output = capsys.readouterr().err
    assert "Unsupported language" in output
    assert "fr" in output


def test_chinese_scan_output_does_not_translate_artifact_contract(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        create_app("zh-CN"),
        ["--lang", "zh-CN", "scan", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "已完成源码检查" in result.stdout
    assert str(tmp_path.resolve()) in result.output
    payload = json.loads(
        (tmp_path / ".repoevidence" / "evidence.json").read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == "0.1"
    assert "扫描完成" not in json.dumps(payload, ensure_ascii=False)


def test_english_and_chinese_report_commands_use_selected_presentation_language(
    tmp_path: Path,
) -> None:
    english = CliRunner().invoke(create_app("en"), ["scan", str(tmp_path)])
    assert english.exit_code == 0, english.output
    assert "Source inspection complete" in english.stdout
    assert ".repoevidence/evidence.json" in english.stdout

    chinese = CliRunner().invoke(
        create_app("zh-CN"),
        ["--lang", "zh-CN", "report", str(tmp_path)],
    )
    assert chinese.exit_code == 0, chinese.output
    assert "报告已生成" in chinese.stdout
    assert ".repoevidence/report/index.html" in chinese.stdout
    html = (tmp_path / ".repoevidence" / "report" / "index.html").read_text(
        encoding="utf-8"
    )
    assert '<html lang="zh-CN">' in html
    assert "暂无数据" in html


def test_chinese_mysql_error_preserves_canonical_error_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "REPOEVIDENCE_MYSQL_HOST",
        "REPOEVIDENCE_MYSQL_PORT",
        "REPOEVIDENCE_MYSQL_USER",
        "REPOEVIDENCE_MYSQL_PASSWORD",
        "REPOEVIDENCE_MYSQL_DATABASE",
    ):
        monkeypatch.delenv(key, raising=False)

    result = CliRunner().invoke(
        create_app("zh-CN"),
        ["--lang", "zh-CN", "verify", "mysql", str(tmp_path)],
    )

    assert result.exit_code != 0
    assert "数据库验证未完成" in result.stderr
    assert "缺少 MySQL 连接配置" in result.stderr
    assert "mysql_config_missing" in result.stderr
    assert "REPOEVIDENCE_MYSQL_PASSWORD" in result.stderr
    assert "REPOEVIDENCE_MYSQL_PASSWORD=" not in result.stderr
