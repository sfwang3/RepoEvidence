from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

FactStatus = Literal["declared", "inferred", "verified", "conflicted"]
ReconciliationArtifact = Literal["static_scan", "mysql_verification"]
ReconciliationReferenceType = Literal["fact", "evidence"]
ReconciliationFindingKind = Literal[
    "matched",
    "runtime_only",
    "source_only",
    "version_mismatch",
    "runtime_failed",
    "ambiguous",
]


class Evidence(BaseModel):
    """A raw, traceable observation produced by a collector."""

    id: str
    kind: str
    source: str
    value: Any

    @field_validator("id")
    @classmethod
    def require_evidence_id_prefix(cls, value: str) -> str:
        if not value.startswith("ev."):
            raise ValueError("Evidence ID must start with 'ev.'")
        return value


class Fact(BaseModel):
    """A structured statement derived from one or more evidence items."""

    id: str
    name: str
    value: Any
    status: FactStatus
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def require_fact_id_prefix(cls, value: str) -> str:
        if not value.startswith("fact."):
            raise ValueError("Fact ID must start with 'fact.'")
        return value


class Conflict(BaseModel):
    """A disagreement that prevents a fact from being treated as consistent."""

    id: str
    message: str
    fact_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class CollectorResult(BaseModel):
    """The independent output channels returned by one collector."""

    evidence: list[Evidence] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ScanMetadata(BaseModel):
    """Small, timezone-safe metadata describing one scan execution."""

    tool_version: str
    started_at: datetime
    finished_at: datetime

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("Scan timestamps must be timezone-aware UTC datetimes")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def require_finished_after_start(self) -> "ScanMetadata":
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must be after started_at")
        return self


class ScanResult(BaseModel):
    """The aggregate result of scanning one repository."""

    schema_version: Literal["0.1"] = "0.1"
    repository_root: str
    metadata: ScanMetadata
    collectors: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "ScanResult":
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Duplicate evidence ID")

        fact_ids = [item.id for item in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("Duplicate fact ID")

        evidence_id_set = set(evidence_ids)
        fact_id_set = set(fact_ids)
        for fact in self.facts:
            missing = set(fact.evidence_ids) - evidence_id_set
            if missing:
                raise ValueError(
                    f"Fact {fact.id} references unknown evidence ID: {sorted(missing)}"
                )

        for conflict in self.conflicts:
            if conflict.fact_id is not None and conflict.fact_id not in fact_id_set:
                raise ValueError(
                    f"Conflict {conflict.id} references unknown fact ID: {conflict.fact_id}"
                )
            missing = set(conflict.evidence_ids) - evidence_id_set
            if missing:
                raise ValueError(
                    f"Conflict {conflict.id} references unknown evidence ID: {sorted(missing)}"
                )
        return self


class VerificationError(BaseModel):
    """A safe, structured error emitted by an explicit verifier."""

    code: str
    message: str


class VerificationMetadata(BaseModel):
    """Small, timezone-safe metadata describing one runtime verification."""

    tool_version: str
    started_at: datetime
    finished_at: datetime
    observed_at: datetime | None = None

    @field_validator("started_at", "finished_at", "observed_at")
    @classmethod
    def require_utc_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("Verification timestamps must be timezone-aware UTC datetimes")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def require_finished_after_start(self) -> "VerificationMetadata":
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must be after started_at")
        return self


class VerificationResult(BaseModel):
    """The isolated result of one explicit runtime verification."""

    schema_version: Literal["0.1"] = "0.1"
    verifier: str
    repository_root: str
    metadata: VerificationMetadata
    evidence: list[Evidence] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[VerificationError] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "VerificationResult":
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Duplicate evidence ID")

        fact_ids = [item.id for item in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("Duplicate fact ID")

        evidence_id_set = set(evidence_ids)
        fact_id_set = set(fact_ids)
        for fact in self.facts:
            missing = set(fact.evidence_ids) - evidence_id_set
            if missing:
                raise ValueError(
                    f"Fact {fact.id} references unknown evidence ID: {sorted(missing)}"
                )

        for conflict in self.conflicts:
            if conflict.fact_id is not None and conflict.fact_id not in fact_id_set:
                raise ValueError(
                    f"Conflict {conflict.id} references unknown fact ID: {conflict.fact_id}"
                )
            missing = set(conflict.evidence_ids) - evidence_id_set
            if missing:
                raise ValueError(
                    f"Conflict {conflict.id} references unknown evidence ID: {sorted(missing)}"
                )
        return self


class ReconciliationReference(BaseModel):
    """A traceable reference into one of the reconciliation input artifacts."""

    artifact: ReconciliationArtifact
    reference_type: ReconciliationReferenceType
    id: str


class ReconciliationFinding(BaseModel):
    """A deterministic cross-artifact Flyway reconciliation outcome."""

    id: str
    kind: ReconciliationFindingKind
    version: str | None = None
    version_key: list[int] = Field(default_factory=list)
    migration_set: str | None = None
    message: str
    references: list[ReconciliationReference] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def require_reconciliation_id_prefix(cls, value: str) -> str:
        if not value.startswith("recon."):
            raise ValueError("Reconciliation finding ID must start with 'recon.'")
        return value


class ReconciliationSummary(BaseModel):
    """Deterministic aggregate counts for one reconciliation."""

    repository_versioned: int = 0
    runtime_successful_versioned: int = 0
    matched: int = 0
    runtime_only: int = 0
    source_only: int = 0
    version_mismatch: int = 0
    runtime_failed: int = 0
    ambiguous: int = 0
    runtime_baseline_version: str | None = None
    repository_max_version: str | None = None
    runtime_max_successful_version: str | None = None
    drift_detected: bool = False


class ReconciliationInputArtifact(BaseModel):
    """The relative location and exact-byte digest of one input artifact."""

    artifact: ReconciliationArtifact
    relative_path: str
    sha256: str


class ReconciliationError(BaseModel):
    """A safe structured error that prevents or limits reconciliation."""

    code: str
    message: str


class ReconciliationResult(BaseModel):
    """The offline result produced by comparing static and runtime artifacts."""

    schema_version: Literal["0.1"] = "0.1"
    repository_root: str
    inputs: list[ReconciliationInputArtifact] = Field(default_factory=list)
    summary: ReconciliationSummary = Field(default_factory=ReconciliationSummary)
    findings: list[ReconciliationFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ReconciliationError] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_finding_ids_and_references(self) -> "ReconciliationResult":
        finding_ids = [finding.id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("Duplicate reconciliation finding ID")
        for finding in self.findings:
            references = [
                (reference.artifact, reference.reference_type, reference.id)
                for reference in finding.references
            ]
            if len(references) != len(set(references)):
                raise ValueError(f"Duplicate reconciliation reference in {finding.id}")
        return self
