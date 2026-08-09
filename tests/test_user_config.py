from __future__ import annotations

import json
from pathlib import Path

from repoevidence.user_config import (
    DEFAULT_SETTINGS,
    SettingsLoadStatus,
    UserSettings,
    load_user_settings,
    save_user_settings,
    settings_path,
)


def test_settings_use_platformdirs_path_without_project_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    path = settings_path()

    assert path == tmp_path / "config" / "repoevidence" / "settings.json"


def test_corrupt_settings_fall_back_without_deleting_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")

    loaded = load_user_settings(path)

    assert loaded.settings == DEFAULT_SETTINGS
    assert loaded.status is SettingsLoadStatus.CORRUPT
    assert path.read_text(encoding="utf-8") == "{broken"


def test_settings_round_trip_is_allowlisted_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "settings.json"
    settings = UserSettings(
        language="zh-CN",
        theme="light",
        interaction="plain",
        reduced_motion=True,
    )

    saved = save_user_settings(settings, path)
    loaded = load_user_settings(path)
    payload = json.loads(saved.read_text(encoding="utf-8"))

    assert saved == path
    assert loaded.settings == settings
    assert payload == {
        "schema_version": 1,
        "language": "zh-CN",
        "theme": "light",
        "interaction": "plain",
        "reduced_motion": True,
    }
    assert "password" not in payload
    assert "repository" not in payload


def test_unknown_schema_is_non_blocking(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 99, "language": "zh-CN"}), encoding="utf-8")

    loaded = load_user_settings(path)

    assert loaded.settings == DEFAULT_SETTINGS
    assert loaded.status is SettingsLoadStatus.UNSUPPORTED
