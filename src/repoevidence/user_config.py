"""Small, user-level UI preference store kept outside project artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

from repoevidence.artifact_io import atomic_write_text

SETTINGS_SCHEMA_VERSION = 1
_LANGUAGES = {"auto", "en", "zh-CN"}
_THEMES = {"auto", "dark", "light"}
_INTERACTIONS = {"auto", "workspace", "plain"}


class SettingsLoadStatus(StrEnum):
    DEFAULT = "default"
    LOADED = "loaded"
    CORRUPT = "corrupt"
    UNSUPPORTED = "unsupported"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class UserSettings:
    schema_version: int = SETTINGS_SCHEMA_VERSION
    language: str = "auto"
    theme: str = "auto"
    interaction: str = "auto"
    reduced_motion: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != SETTINGS_SCHEMA_VERSION:
            raise ValueError("Unsupported settings schema")
        if self.language not in _LANGUAGES:
            raise ValueError("Unsupported settings language")
        if self.theme not in _THEMES:
            raise ValueError("Unsupported settings theme")
        if self.interaction not in _INTERACTIONS:
            raise ValueError("Unsupported settings interaction")
        if not isinstance(self.reduced_motion, bool):
            raise ValueError("reduced_motion must be a boolean")


DEFAULT_SETTINGS = UserSettings()


@dataclass(frozen=True)
class UserSettingsLoad:
    settings: UserSettings
    status: SettingsLoadStatus
    path: Path


def settings_path() -> Path:
    """Return the platform-standard user configuration path."""

    return Path(user_config_path("repoevidence", appauthor=False)) / "settings.json"


def load_user_settings(path: str | Path | None = None) -> UserSettingsLoad:
    target = Path(path).expanduser() if path is not None else settings_path()
    if not target.is_file():
        return UserSettingsLoad(DEFAULT_SETTINGS, SettingsLoadStatus.DEFAULT, target)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return UserSettingsLoad(DEFAULT_SETTINGS, SettingsLoadStatus.CORRUPT, target)
    if not isinstance(payload, dict):
        return UserSettingsLoad(DEFAULT_SETTINGS, SettingsLoadStatus.CORRUPT, target)
    if payload.get("schema_version") != SETTINGS_SCHEMA_VERSION:
        return UserSettingsLoad(DEFAULT_SETTINGS, SettingsLoadStatus.UNSUPPORTED, target)
    try:
        settings = _settings_from_mapping(payload)
    except (TypeError, ValueError):
        return UserSettingsLoad(DEFAULT_SETTINGS, SettingsLoadStatus.CORRUPT, target)
    return UserSettingsLoad(settings, SettingsLoadStatus.LOADED, target)


def save_user_settings(
    settings: UserSettings,
    path: str | Path | None = None,
) -> Path:
    target = Path(path).expanduser() if path is not None else settings_path()
    payload = json.dumps(
        asdict(settings),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    return atomic_write_text(target, payload)


def _settings_from_mapping(payload: dict[str, Any]) -> UserSettings:
    # Deliberately allowlist fields. Unknown future fields are not copied into
    # a rewrite, and credential/project state can never enter this object.
    return UserSettings(
        schema_version=payload["schema_version"],
        language=payload.get("language", "auto"),
        theme=payload.get("theme", "auto"),
        interaction=payload.get("interaction", "auto"),
        reduced_motion=payload.get("reduced_motion", False),
    )
