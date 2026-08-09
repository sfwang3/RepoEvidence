"""Presentation-neutral state dimensions used by interactive projections."""

from __future__ import annotations

from enum import StrEnum


class ArtifactLifecycle(StrEnum):
    MISSING = "missing"
    VALID = "valid"
    FAILED = "failed"
    CORRUPT = "corrupt"
    UNSUPPORTED = "unsupported"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class OperationState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class DomainOutcome(StrEnum):
    NOT_AVAILABLE = "not_available"
    MATCHED = "matched"
    DRIFT_DETECTED = "drift_detected"
    RUNTIME_FAILED = "runtime_failed"
    SOURCE_ONLY = "source_only"
    VERSION_MISMATCH = "version_mismatch"
    AMBIGUOUS = "ambiguous"
