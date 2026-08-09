"""Read-only application/presentation assessment of existing artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import ValidationError

from repoevidence.models import ReconciliationResult, ScanResult, VerificationResult

SUPPORTED_SCHEMA_VERSION = "0.1"
STATIC_RELATIVE_PATH = ".repoevidence/evidence.json"
RUNTIME_RELATIVE_PATH = ".repoevidence/verification/mysql.json"
RECONCILIATION_RELATIVE_PATH = ".repoevidence/reconciliation.json"

ParsedArtifact = ScanResult | VerificationResult | ReconciliationResult


class CheckState(StrEnum):
    """Presentation state derived from artifacts without changing machine status."""

    NOT_RUN = "not_run"
    FAILED = "failed"
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


class ConclusionKind(StrEnum):
    """Factual top-level conclusion supported by the available snapshots."""

    SOURCE_ONLY = "source_only"
    SOURCE_AND_DATABASE_NOT_COMPARED = "source_and_database_not_compared"
    NO_DRIFT = "no_drift"
    DRIFT = "drift"
    DATABASE_VERIFICATION_FAILED = "database_verification_failed"
    COMPARISON_FAILED = "comparison_failed"
    COMPARISON_STALE = "comparison_stale"
    UNABLE_TO_DETERMINE = "unable_to_determine"


class ArtifactAssessmentError(Exception):
    """Structured failure to load the required static artifact."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ArtifactSnapshot:
    """Exact read-only state of one artifact on disk."""

    artifact: str
    relative_path: str
    path: Path
    present: bool
    sha256: str | None
    schema_version: str | None
    parsed: ParsedArtifact | None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckAssessment:
    """Presentation-neutral state for one user-visible check."""

    check: str
    state: CheckState
    artifact_path: Path
    artifact_present: bool
    timestamp: datetime | None = None
    reason_codes: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepositoryAssessment:
    """Current relationship among source, runtime, and comparison snapshots."""

    repository_root: Path
    static_artifact: ArtifactSnapshot
    runtime_artifact: ArtifactSnapshot
    reconciliation_artifact: ArtifactSnapshot
    source: CheckAssessment
    mysql: CheckAssessment
    reconciliation: CheckAssessment
    conclusion: ConclusionKind

    @property
    def static_result(self) -> ScanResult | None:
        parsed = self.static_artifact.parsed
        return parsed if isinstance(parsed, ScanResult) else None

    @property
    def verification_result(self) -> VerificationResult | None:
        parsed = self.runtime_artifact.parsed
        return parsed if isinstance(parsed, VerificationResult) else None

    @property
    def reconciliation_result(self) -> ReconciliationResult | None:
        parsed = self.reconciliation_artifact.parsed
        return parsed if isinstance(parsed, ReconciliationResult) else None


def assess_repository(
    repo_path: str | Path,
    *,
    require_static: bool = True,
) -> RepositoryAssessment:
    """Assess existing artifacts without executing or modifying any operation."""

    root = Path(repo_path).expanduser().resolve()
    static_artifact = _load_artifact(
        root,
        artifact="static_scan",
        relative_path=STATIC_RELATIVE_PATH,
        parser=ScanResult,
        required=require_static,
    )
    runtime_artifact = _load_artifact(
        root,
        artifact="mysql_verification",
        relative_path=RUNTIME_RELATIVE_PATH,
        parser=VerificationResult,
        required=False,
    )
    reconciliation_artifact = _load_artifact(
        root,
        artifact="reconciliation",
        relative_path=RECONCILIATION_RELATIVE_PATH,
        parser=ReconciliationResult,
        required=False,
    )

    source = _assess_source(root, static_artifact)
    mysql = _assess_mysql(root, runtime_artifact)
    reconciliation = _assess_reconciliation(
        root,
        reconciliation_artifact,
        static_artifact,
        runtime_artifact,
        source,
        mysql,
    )
    conclusion = _derive_conclusion(
        source,
        mysql,
        reconciliation,
        reconciliation_artifact,
    )
    return RepositoryAssessment(
        repository_root=root,
        static_artifact=static_artifact,
        runtime_artifact=runtime_artifact,
        reconciliation_artifact=reconciliation_artifact,
        source=source,
        mysql=mysql,
        reconciliation=reconciliation,
        conclusion=conclusion,
    )


def _load_artifact(
    root: Path,
    *,
    artifact: str,
    relative_path: str,
    parser: type[ScanResult] | type[VerificationResult] | type[ReconciliationResult],
    required: bool,
) -> ArtifactSnapshot:
    path = root / relative_path
    if not path.is_file():
        if required:
            raise ArtifactAssessmentError(
                f"missing_{artifact}",
                f"Required {artifact} artifact is missing.",
            )
        return ArtifactSnapshot(
            artifact=artifact,
            relative_path=relative_path,
            path=path,
            present=False,
            sha256=None,
            schema_version=None,
            parsed=None,
            reason_codes=("artifact_missing",),
        )

    try:
        raw = path.read_bytes()
    except OSError:
        if required:
            raise ArtifactAssessmentError(
                f"invalid_{artifact}_json",
                f"Required {artifact} artifact is not valid JSON.",
            ) from None
        return ArtifactSnapshot(
            artifact=artifact,
            relative_path=relative_path,
            path=path,
            present=True,
            sha256=None,
            schema_version=None,
            parsed=None,
            reason_codes=("unreadable",),
        )

    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        if required:
            raise ArtifactAssessmentError(
                f"invalid_{artifact}_json",
                f"Required {artifact} artifact is not valid JSON.",
            ) from None
        return ArtifactSnapshot(
            artifact=artifact,
            relative_path=relative_path,
            path=path,
            present=True,
            sha256=digest,
            schema_version=None,
            parsed=None,
            reason_codes=("invalid_json",),
        )
    if not isinstance(payload, dict):
        if required:
            raise ArtifactAssessmentError(
                f"invalid_{artifact}_json",
                f"Required {artifact} artifact must contain a JSON object.",
            )
        return ArtifactSnapshot(
            artifact=artifact,
            relative_path=relative_path,
            path=path,
            present=True,
            sha256=digest,
            schema_version=None,
            parsed=None,
            reason_codes=("invalid_object",),
        )

    schema_version = payload.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        if required:
            raise ArtifactAssessmentError(
                f"unsupported_{artifact}_schema",
                f"Required {artifact} artifact schema is unsupported.",
            )
        return ArtifactSnapshot(
            artifact=artifact,
            relative_path=relative_path,
            path=path,
            present=True,
            sha256=digest,
            schema_version=str(schema_version) if schema_version is not None else None,
            parsed=None,
            reason_codes=("unsupported_schema",),
        )

    try:
        parsed = parser.model_validate(payload)
    except ValidationError:
        if required:
            raise ArtifactAssessmentError(
                f"invalid_{artifact}",
                f"Required {artifact} artifact is invalid.",
            ) from None
        return ArtifactSnapshot(
            artifact=artifact,
            relative_path=relative_path,
            path=path,
            present=True,
            sha256=digest,
            schema_version=str(schema_version),
            parsed=None,
            reason_codes=("invalid_schema",),
        )

    return ArtifactSnapshot(
        artifact=artifact,
        relative_path=relative_path,
        path=path,
        present=True,
        sha256=digest,
        schema_version=str(schema_version),
        parsed=parsed,
    )


def _assess_source(root: Path, artifact: ArtifactSnapshot) -> CheckAssessment:
    parsed = artifact.parsed
    if not isinstance(parsed, ScanResult):
        return _unknown_check("source_inspection", artifact)
    if Path(parsed.repository_root).resolve() != root:
        return _unknown_check(
            "source_inspection",
            artifact,
            reason_codes=("repository_root_mismatch",),
        )
    if parsed.errors:
        return CheckAssessment(
            check="source_inspection",
            state=CheckState.FAILED,
            artifact_path=artifact.path,
            artifact_present=True,
            timestamp=parsed.metadata.finished_at,
            reason_codes=("operation_errors",),
        )
    return CheckAssessment(
        check="source_inspection",
        state=CheckState.CURRENT,
        artifact_path=artifact.path,
        artifact_present=True,
        timestamp=parsed.metadata.finished_at,
    )


def _assess_mysql(root: Path, artifact: ArtifactSnapshot) -> CheckAssessment:
    if not artifact.present:
        return CheckAssessment(
            check="mysql_verification",
            state=CheckState.NOT_RUN,
            artifact_path=artifact.path,
            artifact_present=False,
            reason_codes=artifact.reason_codes,
        )
    parsed = artifact.parsed
    if not isinstance(parsed, VerificationResult):
        return _unknown_check("mysql_verification", artifact)
    timestamp = parsed.metadata.observed_at or parsed.metadata.finished_at
    if Path(parsed.repository_root).resolve() != root:
        return _unknown_check(
            "mysql_verification",
            artifact,
            reason_codes=("repository_root_mismatch",),
            timestamp=timestamp,
        )
    if parsed.errors:
        return CheckAssessment(
            check="mysql_verification",
            state=CheckState.FAILED,
            artifact_path=artifact.path,
            artifact_present=True,
            timestamp=timestamp,
            reason_codes=("operation_errors",),
            error_codes=tuple(error.code for error in parsed.errors),
        )
    return CheckAssessment(
        check="mysql_verification",
        state=CheckState.CURRENT,
        artifact_path=artifact.path,
        artifact_present=True,
        timestamp=timestamp,
    )


def _assess_reconciliation(
    root: Path,
    artifact: ArtifactSnapshot,
    static_artifact: ArtifactSnapshot,
    runtime_artifact: ArtifactSnapshot,
    source: CheckAssessment,
    mysql: CheckAssessment,
) -> CheckAssessment:
    if not artifact.present:
        return CheckAssessment(
            check="source_database_comparison",
            state=CheckState.NOT_RUN,
            artifact_path=artifact.path,
            artifact_present=False,
            reason_codes=artifact.reason_codes,
        )
    parsed = artifact.parsed
    if not isinstance(parsed, ReconciliationResult):
        return _unknown_check("source_database_comparison", artifact)
    if Path(parsed.repository_root).resolve() != root:
        return _unknown_check(
            "source_database_comparison",
            artifact,
            reason_codes=("repository_root_mismatch",),
        )
    if parsed.errors:
        return CheckAssessment(
            check="source_database_comparison",
            state=CheckState.FAILED,
            artifact_path=artifact.path,
            artifact_present=True,
            reason_codes=("operation_errors",),
            error_codes=tuple(error.code for error in parsed.errors),
        )
    if source.state is not CheckState.CURRENT or mysql.state is not CheckState.CURRENT:
        return _unknown_check(
            "source_database_comparison",
            artifact,
            reason_codes=("prerequisite_not_current",),
        )

    inputs = {item.artifact: item.sha256 for item in parsed.inputs}
    if len(inputs) != len(parsed.inputs) or set(inputs) != {
        "static_scan",
        "mysql_verification",
    }:
        return _unknown_check(
            "source_database_comparison",
            artifact,
            reason_codes=("input_provenance_invalid",),
        )
    if static_artifact.sha256 is None or runtime_artifact.sha256 is None:
        return _unknown_check(
            "source_database_comparison",
            artifact,
            reason_codes=("input_hash_unavailable",),
        )
    if (
        inputs["static_scan"] != static_artifact.sha256
        or inputs["mysql_verification"] != runtime_artifact.sha256
    ):
        return CheckAssessment(
            check="source_database_comparison",
            state=CheckState.STALE,
            artifact_path=artifact.path,
            artifact_present=True,
            reason_codes=("input_hash_mismatch",),
        )
    return CheckAssessment(
        check="source_database_comparison",
        state=CheckState.CURRENT,
        artifact_path=artifact.path,
        artifact_present=True,
    )


def _derive_conclusion(
    source: CheckAssessment,
    mysql: CheckAssessment,
    reconciliation: CheckAssessment,
    reconciliation_artifact: ArtifactSnapshot,
) -> ConclusionKind:
    if source.state is not CheckState.CURRENT:
        return ConclusionKind.UNABLE_TO_DETERMINE
    if mysql.state is CheckState.FAILED:
        return ConclusionKind.DATABASE_VERIFICATION_FAILED
    if mysql.state is CheckState.UNKNOWN:
        return ConclusionKind.UNABLE_TO_DETERMINE
    if mysql.state is CheckState.NOT_RUN:
        return ConclusionKind.SOURCE_ONLY
    if reconciliation.state is CheckState.NOT_RUN:
        return ConclusionKind.SOURCE_AND_DATABASE_NOT_COMPARED
    if reconciliation.state is CheckState.FAILED:
        return ConclusionKind.COMPARISON_FAILED
    if reconciliation.state is CheckState.STALE:
        return ConclusionKind.COMPARISON_STALE
    if reconciliation.state is CheckState.UNKNOWN:
        return ConclusionKind.UNABLE_TO_DETERMINE

    parsed = reconciliation_artifact.parsed
    if not isinstance(parsed, ReconciliationResult):
        return ConclusionKind.UNABLE_TO_DETERMINE
    return (
        ConclusionKind.DRIFT
        if parsed.summary.drift_detected
        else ConclusionKind.NO_DRIFT
    )


def _unknown_check(
    check: str,
    artifact: ArtifactSnapshot,
    *,
    reason_codes: tuple[str, ...] | None = None,
    timestamp: datetime | None = None,
) -> CheckAssessment:
    return CheckAssessment(
        check=check,
        state=CheckState.UNKNOWN,
        artifact_path=artifact.path,
        artifact_present=artifact.present,
        timestamp=timestamp,
        reason_codes=reason_codes or artifact.reason_codes or ("unable_to_assess",),
    )
