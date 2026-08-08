from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from repoevidence.collectors.flyway_migration import _version_key
from repoevidence.models import (
    Fact,
    ReconciliationError,
    ReconciliationFinding,
    ReconciliationInputArtifact,
    ReconciliationReference,
    ReconciliationResult,
    ReconciliationSummary,
    ScanResult,
    VerificationResult,
)

SUPPORTED_SCHEMA_VERSION = "0.1"
STATIC_RELATIVE_PATH = ".repoevidence/evidence.json"
RUNTIME_RELATIVE_PATH = ".repoevidence/verification/mysql.json"
_BASELINE_MARKER = "<< Flyway Baseline >>"


@dataclass(frozen=True)
class _SourceMigration:
    fact: Fact
    version: str | None
    version_key: tuple[int, ...] | None
    source_file: str
    migration_set: str | None


@dataclass(frozen=True)
class _RuntimeMigration:
    fact: Fact
    version: str | None
    version_key: tuple[int, ...] | None
    script: str | None
    success: bool


class Reconciler:
    """Read existing artifacts and reconcile them without runtime side effects."""

    def reconcile(self, repo_path: str | Path) -> ReconciliationResult:
        root = Path(repo_path).expanduser().resolve()
        static_path = root / STATIC_RELATIVE_PATH
        runtime_path = root / RUNTIME_RELATIVE_PATH
        input_records: list[ReconciliationInputArtifact] = []
        errors: list[ReconciliationError] = []

        static_payload = self._read_json(
            static_path,
            "static_scan",
            input_records,
            errors,
        )
        runtime_payload = self._read_json(
            runtime_path,
            "mysql_verification",
            input_records,
            errors,
        )
        if errors:
            return self._error_result(root, input_records, errors)

        schema_errors = []
        assert static_payload is not None
        assert runtime_payload is not None
        if static_payload.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            schema_errors.append(
                ReconciliationError(
                    code="unsupported_static_schema",
                    message="Static scan artifact schema is unsupported.",
                )
            )
        if runtime_payload.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            schema_errors.append(
                ReconciliationError(
                    code="unsupported_runtime_schema",
                    message="MySQL verification artifact schema is unsupported.",
                )
            )
        if schema_errors:
            return self._error_result(root, input_records, schema_errors)

        try:
            static_result = ScanResult.model_validate(static_payload)
        except ValidationError:
            errors.append(
                ReconciliationError(
                    code="invalid_static_artifact",
                    message="Static scan artifact is invalid.",
                )
            )
            static_result = None
        try:
            runtime_result = VerificationResult.model_validate(runtime_payload)
        except ValidationError:
            errors.append(
                ReconciliationError(
                    code="invalid_runtime_artifact",
                    message="MySQL verification artifact is invalid.",
                )
            )
            runtime_result = None
        if errors or static_result is None or runtime_result is None:
            return self._error_result(root, input_records, errors)
        if static_result.repository_root != runtime_result.repository_root:
            return self._error_result(
                root,
                input_records,
                [
                    ReconciliationError(
                        code="repository_root_mismatch",
                        message="Static and MySQL artifacts have different repository roots.",
                    )
                ],
            )

        return self._reconcile_flyway(
            repository_root=static_result.repository_root,
            input_records=input_records,
            static_result=static_result,
            runtime_result=runtime_result,
        )

    @staticmethod
    def _read_json(
        path: Path,
        artifact: str,
        input_records: list[ReconciliationInputArtifact],
        errors: list[ReconciliationError],
    ) -> dict[str, Any] | None:
        if not path.is_file():
            errors.append(
                ReconciliationError(
                    code=f"missing_{artifact}",
                    message=f"Required {artifact} artifact is missing.",
                )
            )
            return None
        try:
            raw = path.read_bytes()
            payload = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            errors.append(
                ReconciliationError(
                    code=f"invalid_{artifact}_json",
                    message=f"Required {artifact} artifact is not valid JSON.",
                )
            )
            return None
        if not isinstance(payload, dict):
            errors.append(
                ReconciliationError(
                    code=f"invalid_{artifact}_json",
                    message=f"Required {artifact} artifact must contain a JSON object.",
                )
            )
            return None
        input_records.append(
            ReconciliationInputArtifact(
                artifact=artifact,
                relative_path=(
                    STATIC_RELATIVE_PATH
                    if artifact == "static_scan"
                    else RUNTIME_RELATIVE_PATH
                ),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
        return payload

    @staticmethod
    def _error_result(
        root: Path,
        input_records: list[ReconciliationInputArtifact],
        errors: list[ReconciliationError],
    ) -> ReconciliationResult:
        return ReconciliationResult(
            repository_root=str(root),
            inputs=input_records,
            errors=errors,
        )

    @staticmethod
    def _reconcile_flyway(
        repository_root: str,
        input_records: list[ReconciliationInputArtifact],
        static_result: ScanResult,
        runtime_result: VerificationResult,
    ) -> ReconciliationResult:
        source_migrations = Reconciler._source_migrations(static_result)
        runtime_migrations, baseline_version = Reconciler._runtime_migrations(runtime_result)
        source_groups: dict[tuple[str, object], list[_SourceMigration]] = defaultdict(list)
        runtime_groups: dict[tuple[str, object], list[_RuntimeMigration]] = defaultdict(list)
        for migration in source_migrations:
            source_groups[_group_key(migration.version, migration.version_key)].append(migration)
        for migration in runtime_migrations:
            runtime_groups[_group_key(migration.version, migration.version_key)].append(migration)

        findings: list[ReconciliationFinding] = []
        all_keys = sorted(
            set(source_groups) | set(runtime_groups),
            key=_group_sort_key,
        )
        for group_key in all_keys:
            sources = sorted(source_groups.get(group_key, []), key=lambda item: item.fact.id)
            runtimes = sorted(runtime_groups.get(group_key, []), key=lambda item: item.fact.id)
            finding = Reconciler._classify(group_key, sources, runtimes)
            if finding is not None:
                findings.append(finding)

        findings.sort(key=lambda item: (item.version_key, item.id))
        repository_max = _max_version(source_migrations)
        runtime_max = _max_version(
            [migration for migration in runtime_migrations if migration.success]
        )
        summary = ReconciliationSummary(
            repository_versioned=len(source_migrations),
            runtime_successful_versioned=sum(
                1 for migration in runtime_migrations if migration.success
            ),
            matched=sum(finding.kind == "matched" for finding in findings),
            runtime_only=sum(finding.kind == "runtime_only" for finding in findings),
            source_only=sum(finding.kind == "source_only" for finding in findings),
            version_mismatch=sum(
                finding.kind == "version_mismatch" for finding in findings
            ),
            runtime_failed=sum(
                finding.kind == "runtime_failed" for finding in findings
            ),
            ambiguous=sum(finding.kind == "ambiguous" for finding in findings),
            runtime_baseline_version=baseline_version,
            repository_max_version=repository_max[0] if repository_max else None,
            runtime_max_successful_version=runtime_max[0] if runtime_max else None,
            drift_detected=any(
                finding.kind
                in {
                    "runtime_only",
                    "source_only",
                    "version_mismatch",
                    "runtime_failed",
                    "ambiguous",
                }
                for finding in findings
            ),
        )
        return ReconciliationResult(
            repository_root=repository_root,
            inputs=input_records,
            summary=summary,
            findings=findings,
        )

    @staticmethod
    def _source_migrations(result: ScanResult) -> list[_SourceMigration]:
        migrations: list[_SourceMigration] = []
        for fact in result.facts:
            value = fact.value
            if fact.name != "Flyway migration declaration":
                continue
            if not isinstance(value, dict) or value.get("type") != "versioned":
                continue
            version = _raw_string(value.get("version"))
            migrations.append(
                _SourceMigration(
                    fact=fact,
                    version=version,
                    version_key=_safe_version_key(version),
                    source_file=_raw_string(value.get("source_file")) or "",
                    migration_set=_raw_string(value.get("migration_set")),
                )
            )
        return sorted(migrations, key=lambda item: item.fact.id)

    @staticmethod
    def _runtime_migrations(
        result: VerificationResult,
    ) -> tuple[list[_RuntimeMigration], str | None]:
        migrations: list[_RuntimeMigration] = []
        baseline_versions: list[str] = []
        for fact in result.facts:
            value = fact.value
            if fact.name != "Flyway runtime migration history" or not isinstance(value, dict):
                continue
            version = _raw_string(value.get("version"))
            if _is_baseline(value, version):
                if version is not None:
                    baseline_versions.append(version)
                continue
            migrations.append(
                _RuntimeMigration(
                    fact=fact,
                    version=version,
                    version_key=_safe_version_key(version),
                    script=_raw_string(value.get("script")),
                    success=bool(value.get("success")),
                )
            )
        baseline = (
            min(
                baseline_versions,
                key=lambda value: (_safe_version_key(value) or (), value),
            )
            if baseline_versions
            else None
        )
        return sorted(migrations, key=lambda item: item.fact.id), baseline

    @staticmethod
    def _classify(
        group_key: tuple[str, object],
        sources: list[_SourceMigration],
        runtimes: list[_RuntimeMigration],
    ) -> ReconciliationFinding | None:
        version_key = _finding_version_key(group_key)
        version = _finding_version(sources, runtimes, group_key)
        references = _references(sources, runtimes)
        id_part = _group_id_part(group_key)
        finding_id = f"recon.{{kind}}.version.{id_part}"
        migration_set = _single_value([item.migration_set for item in sources])

        if len(sources) > 1 or len(runtimes) > 1:
            return ReconciliationFinding(
                id=finding_id.format(kind="ambiguous"),
                kind="ambiguous",
                version=version,
                version_key=list(version_key),
                migration_set=migration_set,
                message=f"Flyway version {version or '<unknown>'} has duplicate declarations.",
                references=references,
                details={
                    "source_files": sorted(item.source_file for item in sources),
                    "runtime_scripts": sorted(
                        item.script for item in runtimes if item.script is not None
                    ),
                },
            )
        if runtimes and not runtimes[0].success:
            runtime = runtimes[0]
            return ReconciliationFinding(
                id=finding_id.format(kind="runtime_failed"),
                kind="runtime_failed",
                version=version,
                version_key=list(version_key),
                migration_set=migration_set,
                message=f"Flyway runtime migration {version or '<unknown>'} failed.",
                references=references,
                details={"runtime_script": runtime.script, "success": False},
            )
        if sources and runtimes:
            source = sources[0]
            runtime = runtimes[0]
            source_filename = Path(source.source_file).name
            if source_filename == runtime.script:
                kind = "matched"
                message = f"Flyway migration {version or '<unknown>'} matches source and runtime."
            else:
                kind = "version_mismatch"
                message = (
                    f"Flyway version {version or '<unknown>'} has different source and "
                    "runtime scripts."
                )
            return ReconciliationFinding(
                id=finding_id.format(kind=kind),
                kind=kind,
                version=version,
                version_key=list(version_key),
                migration_set=migration_set,
                message=message,
                references=references,
                details={
                    "source_file": source.source_file,
                    "runtime_script": runtime.script,
                },
            )
        if runtimes:
            return ReconciliationFinding(
                id=finding_id.format(kind="runtime_only"),
                kind="runtime_only",
                version=version,
                version_key=list(version_key),
                message=(
                    f"Flyway runtime migration {version or '<unknown>'} has no source "
                    "declaration."
                ),
                references=references,
                details={"runtime_script": runtimes[0].script},
            )
        if sources:
            return ReconciliationFinding(
                id=finding_id.format(kind="source_only"),
                kind="source_only",
                version=version,
                version_key=list(version_key),
                migration_set=migration_set,
                message=(
                    f"Flyway source migration {version or '<unknown>'} has no runtime "
                    "history row."
                ),
                references=references,
                details={"source_file": sources[0].source_file},
            )
        return None


def _raw_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _safe_version_key(version: str | None) -> tuple[int, ...] | None:
    if version is None or not version:
        return None
    try:
        return _version_key(version)
    except (TypeError, ValueError):
        return None


def _is_baseline(value: dict[str, Any], version: str | None) -> bool:
    return (
        _safe_version_key(version) == (0,)
        and (
            str(value.get("type") or "").upper() == "BASELINE"
            or value.get("script") == _BASELINE_MARKER
            or value.get("description") == _BASELINE_MARKER
        )
    )


def _group_key(version: str | None, version_key: tuple[int, ...] | None) -> tuple[str, object]:
    if version_key is not None:
        return "version", version_key
    return "invalid", version or ""


def _group_sort_key(group_key: tuple[str, object]) -> tuple[int, object]:
    if group_key[0] == "version":
        return 0, group_key[1]
    return 1, str(group_key[1])


def _group_id_part(group_key: tuple[str, object]) -> str:
    if group_key[0] == "version":
        value = ".".join(str(part) for part in group_key[1])
    else:
        value = f"invalid.{group_key[1]}"
    return quote(value, safe="")


def _finding_version_key(group_key: tuple[str, object]) -> tuple[int, ...]:
    if group_key[0] == "version":
        return group_key[1]
    return ()


def _finding_version(
    sources: list[_SourceMigration],
    runtimes: list[_RuntimeMigration],
    group_key: tuple[str, object],
) -> str | None:
    versions = [item.version for item in sources] + [item.version for item in runtimes]
    versions = [version for version in versions if version is not None]
    if versions:
        return min(versions)
    if group_key[0] == "invalid":
        return str(group_key[1]) or None
    return None


def _references(
    sources: list[_SourceMigration],
    runtimes: list[_RuntimeMigration],
) -> list[ReconciliationReference]:
    references: list[ReconciliationReference] = []
    for artifact, migrations in (
        ("static_scan", sources),
        ("mysql_verification", runtimes),
    ):
        for migration in migrations:
            references.append(
                ReconciliationReference(
                    artifact=artifact,
                    reference_type="fact",
                    id=migration.fact.id,
                )
            )
            references.extend(
                ReconciliationReference(
                    artifact=artifact,
                    reference_type="evidence",
                    id=evidence_id,
                )
                for evidence_id in sorted(migration.fact.evidence_ids)
            )
    return references


def _single_value(values: list[str | None]) -> str | None:
    non_empty = sorted({value for value in values if value is not None})
    return non_empty[0] if len(non_empty) == 1 else None


def _max_version(
    migrations: list[_SourceMigration] | list[_RuntimeMigration],
) -> tuple[str, tuple[int, ...]] | None:
    valid = [
        (migration.version, migration.version_key)
        for migration in migrations
        if migration.version is not None and migration.version_key is not None
    ]
    if not valid:
        return None
    return max(valid, key=lambda item: (item[1], item[0]))
