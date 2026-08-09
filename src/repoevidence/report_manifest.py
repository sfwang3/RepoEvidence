"""Versioned application-level provenance for the offline HTML report."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from repoevidence import __version__
from repoevidence.artifact_io import atomic_write_text
from repoevidence.status import ArtifactLifecycle, Freshness

REPORT_RELATIVE_PATH = ".repoevidence/report/index.html"
REPORT_MANIFEST_RELATIVE_PATH = ".repoevidence/report/manifest.json"
STATIC_RELATIVE_PATH = ".repoevidence/evidence.json"
RUNTIME_RELATIVE_PATH = ".repoevidence/verification/mysql.json"
RECONCILIATION_RELATIVE_PATH = ".repoevidence/reconciliation.json"
_ALLOWED_CONSUMED_PATHS = frozenset(
    {
        STATIC_RELATIVE_PATH,
        RUNTIME_RELATIVE_PATH,
        RECONCILIATION_RELATIVE_PATH,
    }
)
REPORT_MANIFEST_SCHEMA_VERSION = 1
REPORT_RENDERER_FORMAT_VERSION = "1"

# Compatibility aliases keep report terminology readable at call sites while
# the projection shares the same lifecycle/freshness dimensions.
ReportLifecycle = ArtifactLifecycle
ReportFreshness = Freshness


class ReportConsumedArtifact(BaseModel):
    path: str
    sha256: str | None = None


class ReportManifest(BaseModel):
    schema_version: Literal[1] = REPORT_MANIFEST_SCHEMA_VERSION
    generator_version: str
    generated_at: datetime
    language: str
    consumed_artifacts: list[ReportConsumedArtifact]
    output_path: str
    output_sha256: str | None = None
    renderer_format_version: str


@dataclass(frozen=True)
class ReportManifestLoad:
    manifest: ReportManifest | None
    lifecycle: ArtifactLifecycle
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ReportAssessment:
    lifecycle: ArtifactLifecycle
    freshness: Freshness
    artifact_path: Path
    generated_at: datetime | None = None
    language: str | None = None
    language_matches: bool | None = None
    reason_codes: tuple[str, ...] = ()


def build_report_manifest(
    root: str | Path,
    *,
    generated_at: datetime,
    language: str,
    output_path: str | Path,
    generator_version: str = __version__,
    renderer_format_version: str = REPORT_RENDERER_FORMAT_VERSION,
) -> ReportManifest:
    repository_root = Path(root).expanduser().resolve()
    timestamp = generated_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    output = Path(output_path).expanduser().resolve()
    consumed = [
        ReportConsumedArtifact(
            path=relative_path,
            sha256=_sha256(repository_root / relative_path),
        )
        for relative_path in (
            STATIC_RELATIVE_PATH,
            RUNTIME_RELATIVE_PATH,
            RECONCILIATION_RELATIVE_PATH,
        )
    ]
    return ReportManifest(
        generator_version=generator_version,
        generated_at=timestamp,
        language=language,
        consumed_artifacts=consumed,
        output_path=_relative_or_absolute(repository_root, output),
        output_sha256=_sha256(output),
        renderer_format_version=renderer_format_version,
    )


def write_report_manifest(root: str | Path, manifest: ReportManifest) -> Path:
    repository_root = Path(root).expanduser().resolve()
    path = repository_root / REPORT_MANIFEST_RELATIVE_PATH
    payload = manifest.model_dump_json(indent=2) + "\n"
    return atomic_write_text(path, payload)


def load_report_manifest(root: str | Path) -> ReportManifestLoad:
    repository_root = Path(root).expanduser().resolve()
    path = repository_root / REPORT_MANIFEST_RELATIVE_PATH
    if not path.is_file():
        return ReportManifestLoad(None, ArtifactLifecycle.MISSING, ("manifest_missing",))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return ReportManifestLoad(None, ArtifactLifecycle.CORRUPT, ("manifest_invalid_json",))
    if not isinstance(payload, dict):
        return ReportManifestLoad(None, ArtifactLifecycle.CORRUPT, ("manifest_invalid_object",))
    if payload.get("schema_version") != REPORT_MANIFEST_SCHEMA_VERSION:
        return ReportManifestLoad(
            None,
            ArtifactLifecycle.UNSUPPORTED,
            ("manifest_unsupported_schema",),
        )
    try:
        manifest = ReportManifest.model_validate(payload)
    except ValidationError:
        return ReportManifestLoad(None, ArtifactLifecycle.CORRUPT, ("manifest_invalid_schema",))
    return ReportManifestLoad(manifest, ArtifactLifecycle.VALID, ())


def assess_report(
    root: str | Path,
    *,
    language: str,
) -> ReportAssessment:
    repository_root = Path(root).expanduser().resolve()
    output_path = repository_root / REPORT_RELATIVE_PATH
    if not output_path.is_file():
        return ReportAssessment(
            lifecycle=ArtifactLifecycle.MISSING,
            freshness=Freshness.NOT_APPLICABLE,
            artifact_path=output_path,
            reason_codes=("report_missing",),
        )

    loaded = load_report_manifest(repository_root)
    if loaded.manifest is None:
        lifecycle = (
            loaded.lifecycle
            if loaded.lifecycle is not ArtifactLifecycle.MISSING
            else ArtifactLifecycle.VALID
        )
        return ReportAssessment(
            lifecycle=lifecycle,
            freshness=Freshness.UNKNOWN,
            artifact_path=output_path,
            reason_codes=loaded.reason_codes,
        )

    manifest = loaded.manifest
    contract_reasons = _manifest_contract_reasons(manifest)
    if contract_reasons:
        return ReportAssessment(
            lifecycle=ArtifactLifecycle.CORRUPT,
            freshness=Freshness.UNKNOWN,
            artifact_path=output_path,
            generated_at=manifest.generated_at,
            language=manifest.language,
            language_matches=manifest.language == language,
            reason_codes=contract_reasons,
        )
    reasons: list[str] = []
    for consumed in manifest.consumed_artifacts:
        current = _sha256(repository_root / consumed.path)
        if current != consumed.sha256:
            reasons.append("input_hash_mismatch")
            break
    if (
        manifest.output_sha256 is not None
        and _sha256(output_path) != manifest.output_sha256
    ):
        reasons.append("output_hash_mismatch")
    language_matches = manifest.language == language
    if not language_matches:
        reasons.append("language_mismatch")
    freshness = (
        Freshness.STALE
        if any(reason in reasons for reason in ("input_hash_mismatch", "output_hash_mismatch"))
        else Freshness.FRESH
    )
    return ReportAssessment(
        lifecycle=ArtifactLifecycle.VALID,
        freshness=freshness,
        artifact_path=output_path,
        generated_at=manifest.generated_at,
        language=manifest.language,
        language_matches=language_matches,
        reason_codes=tuple(reasons),
    )


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except OSError:
        return None


def _manifest_contract_reasons(manifest: ReportManifest) -> tuple[str, ...]:
    reasons: list[str] = []
    consumed_paths = [item.path for item in manifest.consumed_artifacts]
    if (
        len(consumed_paths) != len(set(consumed_paths))
        or set(consumed_paths) != _ALLOWED_CONSUMED_PATHS
    ):
        reasons.append("manifest_unsafe_path")
    if manifest.output_path != REPORT_RELATIVE_PATH:
        reasons.append("manifest_output_mismatch")
    return tuple(reasons)


def _relative_or_absolute(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
