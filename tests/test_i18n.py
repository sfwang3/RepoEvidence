# ruff: noqa: E501

from __future__ import annotations

import locale

import pytest

from repoevidence.i18n import (
    _CATALOGS,
    SUPPORTED_LANGUAGES,
    InvalidLanguageError,
    finding_label,
    message,
    message_key,
    resolve_language,
    status_label,
)


def test_english_and_chinese_catalogs_have_identical_keys() -> None:
    assert set(_CATALOGS["en"]) == set(_CATALOGS["zh-CN"])


def test_first_layer_report_language_describes_user_tasks() -> None:
    assert message("report.conclusion.source_only.title", "en") == (
        "Source inspection is complete"
    )
    assert message("report.conclusion.source_only.title", "zh-CN") == "已完成源码检查"
    assert "Evidence" not in message("report.conclusion.source_only.body", "en")
    assert "Fact" not in message("report.conclusion.source_only.body", "en")


def test_supported_languages_are_exactly_english_and_simplified_chinese() -> None:
    assert SUPPORTED_LANGUAGES == ("en", "zh-CN")


def test_explicit_language_wins_over_environment_and_locale() -> None:
    assert resolve_language("zh-CN", environ={"REPOEVIDENCE_LANG": "en"}, locale_values=["en_US"]) == "zh-CN"
    assert resolve_language("en", environ={"REPOEVIDENCE_LANG": "zh-CN"}, locale_values=["zh_CN"]) == "en"


def test_environment_language_wins_over_system_locale() -> None:
    assert resolve_language("auto", environ={"REPOEVIDENCE_LANG": "zh-CN"}, locale_values=["en_US"]) == "zh-CN"
    assert resolve_language("auto", environ={"REPOEVIDENCE_LANG": "en"}, locale_values=["zh_CN"]) == "en"


def test_user_config_language_wins_over_system_locale_but_not_environment() -> None:
    assert resolve_language(
        "auto",
        environ={},
        user_language="zh-CN",
        locale_values=["en_US"],
    ) == "zh-CN"
    assert resolve_language(
        "auto",
        environ={"REPOEVIDENCE_LANG": "en"},
        user_language="zh-CN",
        locale_values=["zh_CN"],
    ) == "en"


@pytest.mark.parametrize("locale_value", ["zh_CN", "zh-CN", "Chinese (Simplified)_China.utf8"])
def test_auto_detects_supported_chinese_locale_forms(locale_value: str) -> None:
    assert resolve_language("auto", environ={}, locale_values=[locale_value]) == "zh-CN"


def test_locale_detection_failure_falls_back_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE", "REPOEVIDENCE_LANG"):
        monkeypatch.delenv(key, raising=False)

    def fail_getlocale(*args: object, **kwargs: object) -> tuple[str | None, str | None]:
        raise ValueError("locale unavailable")

    monkeypatch.setattr(locale, "getlocale", fail_getlocale)
    assert resolve_language("auto") == "en"


@pytest.mark.parametrize("invalid", ["zh-TW", "fr", "", "AUTO-INVALID"])
def test_invalid_explicit_language_is_rejected(invalid: str) -> None:
    with pytest.raises(InvalidLanguageError):
        resolve_language(invalid)


def test_invalid_environment_language_is_rejected() -> None:
    with pytest.raises(InvalidLanguageError):
        resolve_language("auto", environ={"REPOEVIDENCE_LANG": "zh-TW"}, locale_values=["en_US"])


def test_catalog_and_canonical_labels_preserve_machine_values() -> None:
    assert message_key("cli.scan.complete").startswith("__repoevidence_message_key__:")
    assert message("cli.scan.complete", "en", path="/tmp/repo") == "Scan complete. Evidence written to /tmp/repo"
    assert message("cli.scan.complete", "zh-CN", path="/tmp/repo") == "扫描完成。证据已写入：/tmp/repo"
    assert status_label("verified", "zh-CN") == "已验证（verified）"
    assert finding_label("runtime_only", "zh-CN") == "仅存在于运行环境（runtime_only）"
    assert status_label("verified", "en") == "verified"
    assert finding_label("runtime_only", "en") == "runtime_only"


def test_inspect_completion_message_is_available_in_both_languages() -> None:
    assert message("cli.inspect.complete", "en", path="/tmp/report") == (
        "Inspect complete. Report written to /tmp/report"
    )
    assert message("cli.inspect.complete", "zh-CN", path="/tmp/report") == (
        "检查完成。报告已生成：/tmp/report"
    )


def test_report_not_available_and_mysql_error_are_natural_in_chinese() -> None:
    assert message("report.not_available", "zh-CN") == "暂无数据"
    assert message("error.mysql_config_missing", "zh-CN") == "缺少 MySQL 连接配置。"
    assert message("error.mysql_config_missing", "en") == "Required MySQL verification environment variables are missing or invalid."
