from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from repoevidence import __version__
from repoevidence.application import (
    reconcile_repository,
    scan_repository,
    verify_mysql_repository,
)
from repoevidence.models import (
    Evidence,
    Fact,
    ScanMetadata,
    ScanResult,
    VerificationMetadata,
    VerificationResult,
)
from repoevidence.reconciliation import Reconciler

FIXED_TIME = datetime(2026, 8, 9, tzinfo=timezone.utc)


class FixedScanner:
    def __init__(self, result: ScanResult) -> None:
        self.result = result

    def scan(self, repo_path: str | Path) -> ScanResult:
        assert Path(repo_path).resolve() == Path(self.result.repository_root)
        return self.result


class FixedVerifier:
    def __init__(self, result: VerificationResult) -> None:
        self.result = result

    def verify(
        self,
        repo_path: str | Path,
        environment: object = None,
    ) -> VerificationResult:
        assert Path(repo_path).resolve() == Path(self.result.repository_root)
        return self.result


def _scan_result(root: Path) -> ScanResult:
    source_file = "src/main/resources/db/migration/V1__init.sql"
    evidence = Evidence(
        id="ev.flyway.migration.fixture",
        kind="flyway_migration_file",
        source=source_file,
        value={"source_file": source_file, "file_sha256": "a" * 64},
    )
    fact = Fact(
        id="fact.flyway.migration.fixture",
        name="Flyway migration declaration",
        value={
            "migration_set": "src/main/resources/db/migration",
            "type": "versioned",
            "version": "1",
            "source_file": source_file,
            "file_sha256": "a" * 64,
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


def _verification_result(root: Path) -> VerificationResult:
    evidence = Evidence(
        id="ev.mysql.flyway.history.1",
        kind="mysql.flyway_history",
        source="mysql.query.flyway_history",
        value={"result": {"version": "1", "script": "V1__init.sql"}},
    )
    fact = Fact(
        id="fact.mysql.flyway.history.1",
        name="Flyway runtime migration history",
        value={
            "installed_rank": 1,
            "version": "1",
            "description": "init",
            "type": "SQL",
            "script": "V1__init.sql",
            "checksum": 123,
            "success": True,
            "installed_on": "2026-08-09T00:00:00Z",
        },
        status="verified",
        evidence_ids=[evidence.id],
    )
    return VerificationResult(
        verifier="mysql",
        repository_root=str(root.resolve()),
        metadata=VerificationMetadata(
            tool_version=__version__,
            started_at=FIXED_TIME,
            finished_at=FIXED_TIME,
            observed_at=FIXED_TIME,
        ),
        evidence=[evidence],
        facts=[fact],
    )


def test_scan_application_keeps_legacy_json_bytes_and_path(tmp_path: Path) -> None:
    expected = _scan_result(tmp_path)

    result = scan_repository(tmp_path, scanner=FixedScanner(expected))

    assert result.evidence_path == tmp_path.resolve() / ".repoevidence/evidence.json"
    assert result.evidence_path.read_bytes() == (
        expected.model_dump_json(indent=2) + "\n"
    ).encode()


def test_verify_application_keeps_legacy_json_bytes_and_path(tmp_path: Path) -> None:
    expected = _verification_result(tmp_path)

    result = verify_mysql_repository(
        tmp_path,
        verifier=FixedVerifier(expected),
        environment={},
    )

    assert result.verification_path == (
        tmp_path.resolve() / ".repoevidence/verification/mysql.json"
    )
    assert result.verification_path.read_bytes() == (
        expected.model_dump_json(indent=2) + "\n"
    ).encode()


def test_reconcile_application_matches_direct_machine_result_exactly(
    tmp_path: Path,
) -> None:
    scan = _scan_result(tmp_path)
    verification = _verification_result(tmp_path)
    evidence_path = tmp_path / ".repoevidence/evidence.json"
    verification_path = tmp_path / ".repoevidence/verification/mysql.json"
    evidence_path.parent.mkdir(parents=True)
    verification_path.parent.mkdir(parents=True)
    evidence_path.write_text(scan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    verification_path.write_text(
        verification.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    direct = Reconciler().reconcile(tmp_path)

    application = reconcile_repository(tmp_path)

    assert application.reconciliation_path == (
        tmp_path.resolve() / ".repoevidence/reconciliation.json"
    )
    assert json.loads(application.reconciliation_path.read_text(encoding="utf-8")) == (
        direct.model_dump(mode="json")
    )
    assert application.reconciliation_path.read_bytes() == (
        direct.model_dump_json(indent=2) + "\n"
    ).encode()
