from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

FactStatus = Literal["declared", "inferred", "verified", "conflicted"]


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
