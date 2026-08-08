from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from repoevidence.models import (
    CollectorResult,
    Conflict,
    Evidence,
    Fact,
    ScanMetadata,
    ScanResult,
)


def test_fact_accepts_only_supported_statuses_and_keeps_evidence_references() -> None:
    fact = Fact(
        id="fact.git.repository_exists",
        name="Git repository exists",
        value=True,
        status="verified",
        evidence_ids=["ev.git.repository_check"],
    )

    assert fact.status == "verified"
    assert fact.evidence_ids == ["ev.git.repository_check"]

    with pytest.raises(ValidationError):
        Fact(
            id="fact.invalid",
            name="Invalid status",
            value=True,
            status="unsupported",
        )


def test_collector_result_has_independent_aggregate_channels() -> None:
    result = CollectorResult(
        evidence=[Evidence(id="ev.test", kind="test", source="test", value="raw")],
        warnings=["warning"],
        errors=["error"],
    )

    assert result.evidence[0].value == "raw"
    assert result.facts == []
    assert result.conflicts == []
    assert result.warnings == ["warning"]
    assert result.errors == ["error"]


def test_scan_result_contains_versioned_utc_scan_metadata() -> None:
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    finished_at = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)

    result = ScanResult(
        repository_root="/repo",
        metadata=ScanMetadata(
            tool_version="0.1.0",
            started_at=started_at,
            finished_at=finished_at,
        ),
    )

    assert result.schema_version == "0.1"
    assert result.metadata.tool_version == "0.1.0"
    assert result.metadata.started_at.tzinfo is not None
    assert result.metadata.started_at.utcoffset().total_seconds() == 0
    assert result.metadata.finished_at.utcoffset().total_seconds() == 0


def test_scan_result_rejects_duplicate_and_dangling_references() -> None:
    metadata = ScanMetadata(
        tool_version="0.1.0",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    evidence = Evidence(id="ev.test", kind="test", source="test", value="raw")

    with pytest.raises(ValidationError, match="Duplicate evidence ID"):
        ScanResult(
            repository_root="/repo",
            metadata=metadata,
            evidence=[evidence, evidence],
        )

    with pytest.raises(ValidationError, match="unknown evidence ID"):
        ScanResult(
            repository_root="/repo",
            metadata=metadata,
            evidence=[evidence],
            facts=[
                Fact(
                    id="fact.test",
                    name="Test fact",
                    value=True,
                    status="verified",
                    evidence_ids=["ev.missing"],
                )
            ],
        )

    with pytest.raises(ValidationError, match="unknown fact ID"):
        ScanResult(
            repository_root="/repo",
            metadata=metadata,
            evidence=[evidence],
            conflicts=[
                Conflict(
                    id="conflict.test",
                    message="missing fact",
                    fact_id="fact.missing",
                )
            ],
        )

    with pytest.raises(ValidationError, match="unknown evidence ID"):
        ScanResult(
            repository_root="/repo",
            metadata=metadata,
            evidence=[evidence],
            conflicts=[
                Conflict(
                    id="conflict.test",
                    message="missing evidence",
                    evidence_ids=["ev.missing"],
                )
            ],
        )
