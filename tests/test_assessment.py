from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from repoevidence import __version__
from repoevidence.application import reconcile_repository
from repoevidence.assessment import CheckState, ConclusionKind, assess_repository
from repoevidence.models import (
    Evidence,
    Fact,
    ScanMetadata,
    ScanResult,
    VerificationError,
    VerificationMetadata,
    VerificationResult,
)

FIXED_TIME = datetime(2026, 8, 9, tzinfo=timezone.utc)


def _scan_result(root: Path, version: str = "1") -> ScanResult:
    filename = f"V{version}__migration.sql"
    source_file = f"src/main/resources/db/migration/{filename}"
    evidence = Evidence(
        id=f"ev.flyway.migration.version.{version}",
        kind="flyway_migration_file",
        source=source_file,
        value={"source_file": source_file, "file_sha256": version * 64},
    )
    fact = Fact(
        id=f"fact.flyway.migration.version.{version}",
        name="Flyway migration declaration",
        value={
            "migration_set": "src/main/resources/db/migration",
            "type": "versioned",
            "version": version,
            "source_file": source_file,
            "file_sha256": version * 64,
        },
        status="declared",
        evidence_ids=[evidence.id],
    )
    return ScanResult(
        repository_root=str(root.resolve()),
        metadata=ScanMetadata(
            tool_version=__version__,
            started_at=FIXED_TIME,
            finished_at=FIXED_TIME,
        ),
        collectors=["flyway_migration"],
        evidence=[evidence],
        facts=[fact],
    )


def _verification_result(
    root: Path,
    version: str = "1",
    *,
    errors: list[VerificationError] | None = None,
) -> VerificationResult:
    evidence: list[Evidence] = []
    facts: list[Fact] = []
    if not errors:
        filename = f"V{version}__migration.sql"
        evidence_item = Evidence(
            id="ev.mysql.flyway.history.1",
            kind="mysql.flyway_history",
            source="mysql.query.flyway_history",
            value={"result": {"version": version, "script": filename}},
        )
        fact = Fact(
            id="fact.mysql.flyway.history.1",
            name="Flyway runtime migration history",
            value={
                "installed_rank": 1,
                "version": version,
                "description": "migration",
                "type": "SQL",
                "script": filename,
                "checksum": 123,
                "success": True,
                "installed_on": "2026-08-09T00:00:00Z",
            },
            status="verified",
            evidence_ids=[evidence_item.id],
        )
        evidence.append(evidence_item)
        facts.append(fact)
    return VerificationResult(
        verifier="mysql",
        repository_root=str(root.resolve()),
        metadata=VerificationMetadata(
            tool_version=__version__,
            started_at=FIXED_TIME,
            finished_at=FIXED_TIME,
            observed_at=FIXED_TIME,
        ),
        evidence=evidence,
        facts=facts,
        errors=errors or [],
    )


def _write_static(root: Path, result: ScanResult | None = None) -> Path:
    path = root / ".repoevidence/evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    value = result or _scan_result(root)
    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _write_runtime(root: Path, result: VerificationResult | None = None) -> Path:
    path = root / ".repoevidence/verification/mysql.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    value = result or _verification_result(root)
    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _repository_state(base: Path, state: str) -> Path:
    root = base / state
    root.mkdir()
    _write_static(root)
    if state == "static_only":
        return root
    if state == "failed_runtime":
        _write_runtime(
            root,
            _verification_result(
                root,
                errors=[
                    VerificationError(
                        code="mysql_connection_failed",
                        message="Unable to connect to MySQL.",
                    )
                ],
            ),
        )
        return root

    runtime_version = "2" if state == "drift" else "1"
    _write_runtime(root, _verification_result(root, runtime_version))
    if state == "runtime_no_reconcile":
        return root

    reconcile_repository(root)
    if state == "stale_reconciliation":
        changed = _scan_result(root)
        changed.warnings.append("source snapshot changed")
        _write_static(root, changed)
    return root


@pytest.mark.parametrize(
    ("fixture_name", "mysql_state", "reconciliation_state", "conclusion"),
    [
        (
            "static_only",
            CheckState.NOT_RUN,
            CheckState.NOT_RUN,
            ConclusionKind.SOURCE_ONLY,
        ),
        (
            "runtime_no_reconcile",
            CheckState.CURRENT,
            CheckState.NOT_RUN,
            ConclusionKind.SOURCE_AND_DATABASE_NOT_COMPARED,
        ),
        (
            "no_drift",
            CheckState.CURRENT,
            CheckState.CURRENT,
            ConclusionKind.NO_DRIFT,
        ),
        (
            "drift",
            CheckState.CURRENT,
            CheckState.CURRENT,
            ConclusionKind.DRIFT,
        ),
        (
            "failed_runtime",
            CheckState.FAILED,
            CheckState.NOT_RUN,
            ConclusionKind.DATABASE_VERIFICATION_FAILED,
        ),
        (
            "stale_reconciliation",
            CheckState.CURRENT,
            CheckState.STALE,
            ConclusionKind.COMPARISON_STALE,
        ),
    ],
)
def test_assessment_distinguishes_user_truth_states(
    tmp_path: Path,
    fixture_name: str,
    mysql_state: CheckState,
    reconciliation_state: CheckState,
    conclusion: ConclusionKind,
) -> None:
    root = _repository_state(tmp_path, fixture_name)

    result = assess_repository(root)

    assert result.source.state is CheckState.CURRENT
    assert result.mysql.state is mysql_state
    assert result.reconciliation.state is reconciliation_state
    assert result.conclusion is conclusion


def test_failed_verification_uses_artifact_contents_not_file_presence(
    tmp_path: Path,
) -> None:
    root = _repository_state(tmp_path, "failed_runtime")

    result = assess_repository(root)

    assert result.runtime_artifact.present is True
    assert result.mysql.state is CheckState.FAILED
    assert result.mysql.error_codes == ("mysql_connection_failed",)
    assert result.mysql.reason_codes == ("operation_errors",)


def test_stale_reconciliation_is_derived_without_mutating_artifacts(
    tmp_path: Path,
) -> None:
    root = _repository_state(tmp_path, "stale_reconciliation")
    paths = (
        root / ".repoevidence/evidence.json",
        root / ".repoevidence/verification/mysql.json",
        root / ".repoevidence/reconciliation.json",
    )
    before = {path: path.read_bytes() for path in paths}

    result = assess_repository(root)

    assert result.reconciliation.state is CheckState.STALE
    assert result.conclusion is ConclusionKind.COMPARISON_STALE
    assert result.reconciliation_result is not None
    assert result.reconciliation_result.summary.drift_detected is False
    assert result.reconciliation.reason_codes == ("input_hash_mismatch",)
    assert {path: path.read_bytes() for path in paths} == before


def test_current_reconciliation_hashes_match_current_snapshot_bytes(
    tmp_path: Path,
) -> None:
    root = _repository_state(tmp_path, "no_drift")

    result = assess_repository(root)

    input_hashes = {
        item.artifact: item.sha256 for item in result.reconciliation_result.inputs
    }
    assert input_hashes == {
        "static_scan": hashlib.sha256(
            (root / ".repoevidence/evidence.json").read_bytes()
        ).hexdigest(),
        "mysql_verification": hashlib.sha256(
            (root / ".repoevidence/verification/mysql.json").read_bytes()
        ).hexdigest(),
    }


def test_invalid_optional_artifact_is_unknown_not_not_run(tmp_path: Path) -> None:
    root = tmp_path / "invalid-runtime"
    root.mkdir()
    _write_static(root)
    runtime_path = root / ".repoevidence/verification/mysql.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text("{not-json", encoding="utf-8")

    result = assess_repository(root)

    assert result.mysql.state is CheckState.UNKNOWN
    assert result.mysql.reason_codes == ("invalid_json",)
    assert result.conclusion is ConclusionKind.UNABLE_TO_DETERMINE


def test_runtime_repository_mismatch_is_unknown(tmp_path: Path) -> None:
    root = tmp_path / "root-mismatch"
    root.mkdir()
    _write_static(root)
    _write_runtime(root, _verification_result(tmp_path / "another-repository"))

    result = assess_repository(root)

    assert result.mysql.state is CheckState.UNKNOWN
    assert result.mysql.reason_codes == ("repository_root_mismatch",)
    assert result.conclusion is ConclusionKind.UNABLE_TO_DETERMINE
