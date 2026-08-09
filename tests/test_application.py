from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from repoevidence import __version__
from repoevidence.application import (
    generate_report,
    inspect_repository,
    open_report,
    reconcile_repository,
    scan_repository,
    verify_mysql_repository,
)
from repoevidence.artifact_io import atomic_write_bytes
from repoevidence.assessment import CheckState
from repoevidence.models import (
    Evidence,
    Fact,
    ReconciliationResult,
    ScanMetadata,
    ScanResult,
    VerificationMetadata,
    VerificationResult,
)
from repoevidence.reconciliation import Reconciler
from repoevidence.verification import mysql as mysql_verification
from repoevidence.verification.mysql import MySQLVerifier


def _scan_result(root: Path, *, warnings: list[str] | None = None) -> ScanResult:
    evidence = [
        Evidence(id="ev.repository.root", kind="path", source="fixture", value=str(root)),
        Evidence(id="ev.git.head_commit", kind="command_output", source="fixture", value={}),
        Evidence(id="ev.git.current_branch", kind="command_output", source="fixture", value={}),
        Evidence(id="ev.spring.endpoint", kind="spring_annotation", source="fixture", value={}),
        Evidence(id="ev.maven.dependency", kind="maven_declaration", source="fixture", value={}),
        Evidence(
            id="ev.flyway.migration",
            kind="flyway_migration_file",
            source="fixture",
            value={},
        ),
    ]
    facts = [
        Fact(
            id="fact.repository.root",
            name="Repository root",
            value=str(root),
            status="verified",
            evidence_ids=["ev.repository.root"],
        ),
        Fact(
            id="fact.git.head_commit",
            name="HEAD commit",
            value="abc123",
            status="verified",
            evidence_ids=["ev.git.head_commit"],
        ),
        Fact(
            id="fact.git.current_branch",
            name="Current branch",
            value="main",
            status="verified",
            evidence_ids=["ev.git.current_branch"],
        ),
        Fact(
            id="fact.spring.endpoint.fixture",
            name="GET /health",
            value={"method": "GET", "path": "/health"},
            status="inferred",
            evidence_ids=["ev.spring.endpoint"],
        ),
        Fact(
            id="fact.maven.dependency.fixture",
            name="Maven dependencies dependency declaration",
            value={"location": "dependencies", "artifact_id": "core"},
            status="declared",
            evidence_ids=["ev.maven.dependency"],
        ),
        Fact(
            id="fact.flyway.migration.fixture",
            name="Flyway migration declaration",
            value={"type": "versioned", "version": "1"},
            status="declared",
            evidence_ids=["ev.flyway.migration"],
        ),
    ]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ScanResult(
        repository_root=str(root),
        metadata=ScanMetadata(
            tool_version=__version__,
            started_at=now,
            finished_at=now,
        ),
        collectors=["repository_metadata", "spring_api", "maven_project", "flyway_migration"],
        evidence=evidence,
        facts=facts,
        warnings=warnings or [],
        errors=[],
    )


class RecordingScanner:
    def __init__(self, events: list[tuple[object, ...]], result: ScanResult) -> None:
        self.events = events
        self.result = result

    def scan(self, repo_path: str | Path) -> ScanResult:
        root = Path(repo_path).resolve()
        self.events.append(("scan", root))
        return self.result


class RecordingReportGenerator:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    def generate(self, repo_path: str | Path, *, language: str) -> Path:
        root = Path(repo_path).resolve()
        self.events.append(("report", root, language))
        output_path = root / ".repoevidence" / "report" / "index.html"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<html></html>", encoding="utf-8")
        return output_path


class RecordingVerifier:
    def __init__(
        self,
        events: list[tuple[object, ...]],
        result: VerificationResult,
    ) -> None:
        self.events = events
        self.result = result

    def verify(
        self,
        repo_path: str | Path,
        environment: dict[str, str] | None = None,
    ) -> VerificationResult:
        root = Path(repo_path).resolve()
        self.events.append(("verify_mysql", root, environment))
        return self.result


class RecordingReconciler:
    def __init__(
        self,
        events: list[tuple[object, ...]],
        result: ReconciliationResult,
    ) -> None:
        self.events = events
        self.result = result

    def reconcile(self, repo_path: str | Path) -> ReconciliationResult:
        root = Path(repo_path).resolve()
        self.events.append(("reconcile", root))
        return self.result


def _verification_result(root: Path) -> VerificationResult:
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    return VerificationResult(
        verifier="mysql",
        repository_root=str(root.resolve()),
        metadata=VerificationMetadata(
            tool_version=__version__,
            started_at=now,
            finished_at=now,
            observed_at=now,
        ),
    )


def _reconciliation_result(root: Path) -> ReconciliationResult:
    return ReconciliationResult(repository_root=str(root.resolve()))


def test_scan_repository_writes_the_existing_evidence_artifact(tmp_path: Path) -> None:
    result = scan_repository(tmp_path)

    assert result.evidence_path == tmp_path.resolve() / ".repoevidence/evidence.json"
    assert json.loads(result.evidence_path.read_text(encoding="utf-8")) == json.loads(
        result.scan_result.model_dump_json()
    )


def test_generate_report_delegates_language_and_returns_path(tmp_path: Path) -> None:
    scan_repository(tmp_path)

    result = generate_report(tmp_path, language="zh-CN")

    assert result.report_path == tmp_path.resolve() / ".repoevidence/report/index.html"
    assert '<html lang="zh-CN">' in result.report_path.read_text(encoding="utf-8")
    assert result.assessment.repository_root == tmp_path.resolve()
    assert result.view_model.language == "zh-CN"
    assert result.view_model.source.fact_count == len(result.assessment.static_result.facts)
    assert (tmp_path / ".repoevidence/report/manifest.json").is_file()


def test_atomic_write_preserves_previous_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "artifact.json"
    path.write_bytes(b"previous\n")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("controlled replace failure")

    monkeypatch.setattr("repoevidence.artifact_io.os.replace", fail_replace)

    with pytest.raises(OSError, match="controlled replace failure"):
        atomic_write_bytes(path, b"new\n")

    assert path.read_bytes() == b"previous\n"


def test_verify_mysql_repository_writes_the_existing_verification_artifact(
    tmp_path: Path,
) -> None:
    events: list[tuple[object, ...]] = []
    expected = _verification_result(tmp_path)
    environment = {"REPOEVIDENCE_MYSQL_HOST": "db.example.test"}

    result = verify_mysql_repository(
        tmp_path,
        verifier=RecordingVerifier(events, expected),
        environment=environment,
    )

    assert events == [("verify_mysql", tmp_path.resolve(), environment)]
    assert result.verification_result is expected
    assert result.verification_path == (
        tmp_path.resolve() / ".repoevidence/verification/mysql.json"
    )
    assert result.verification_path.read_text(encoding="utf-8") == (
        expected.model_dump_json(indent=2) + "\n"
    )


def test_reconcile_repository_writes_the_existing_reconciliation_artifact(
    tmp_path: Path,
) -> None:
    events: list[tuple[object, ...]] = []
    expected = _reconciliation_result(tmp_path)

    result = reconcile_repository(
        tmp_path,
        reconciler=RecordingReconciler(events, expected),
    )

    assert events == [("reconcile", tmp_path.resolve())]
    assert result.reconciliation_result is expected
    assert result.reconciliation_path == (
        tmp_path.resolve() / ".repoevidence/reconciliation.json"
    )
    assert result.reconciliation_path.read_text(encoding="utf-8") == (
        expected.model_dump_json(indent=2) + "\n"
    )


def test_inspect_repository_runs_scan_then_report_and_builds_summary(tmp_path: Path) -> None:
    events: list[tuple[object, ...]] = []
    scan_result = _scan_result(tmp_path, warnings=["fixture warning"])
    scanner = RecordingScanner(events, scan_result)
    report_generator = RecordingReportGenerator(events)

    result = inspect_repository(
        tmp_path,
        language="en",
        scanner=scanner,
        report_generator=report_generator,
    )

    assert events == [
        ("scan", tmp_path.resolve()),
        ("report", tmp_path.resolve(), "en"),
    ]
    assert result.summary.repository_name == tmp_path.name
    assert result.summary.repository_path == tmp_path.resolve()
    assert result.summary.git_commit == "abc123"
    assert result.summary.branch == "main"
    assert result.summary.detected_capabilities == (
        "repository_metadata",
        "spring_api",
        "maven_project",
        "flyway_migration",
    )
    assert result.summary.spring_endpoint_count == 1
    assert result.summary.maven_dependency_count == 1
    assert result.summary.flyway_migration_count == 1
    assert result.summary.mysql_runtime_verification_artifact_present is False
    assert result.summary.reconciliation_artifact_present is False
    assert result.summary.report_path == tmp_path.resolve() / ".repoevidence/report/index.html"
    assert result.summary.evidence_path == tmp_path.resolve() / ".repoevidence/evidence.json"
    assert result.summary.warnings == ("fixture warning",)
    assert result.summary.errors == ()
    assert result.summary.failed_checks == ()
    assert result.summary.completed_checks == ("static_scan", "report_generation")
    assert result.summary.pending_checks == (
        "mysql_verification",
        "reconciliation",
        "target_project_execution",
        "database_connection",
    )
    assert result.summary.assessment.source.state is CheckState.CURRENT
    assert result.summary.assessment.mysql.state is CheckState.NOT_RUN
    assert result.summary.assessment.reconciliation.state is CheckState.NOT_RUN


def test_inspect_summary_distinguishes_failed_from_completed_source_check(
    tmp_path: Path,
) -> None:
    events: list[tuple[object, ...]] = []
    scan_result = _scan_result(tmp_path)
    scan_result.errors.append("source collector failed")

    result = inspect_repository(
        tmp_path,
        scanner=RecordingScanner(events, scan_result),
        report_generator=RecordingReportGenerator(events),
    )

    assert result.summary.completed_checks == ("report_generation",)
    assert result.summary.failed_checks == ("static_scan",)
    assert result.summary.assessment.source.state is CheckState.FAILED


def test_inspect_forwards_zh_cn_language_to_report_service(tmp_path: Path) -> None:
    events: list[tuple[object, ...]] = []

    inspect_repository(
        tmp_path,
        language="zh-CN",
        scanner=RecordingScanner(events, _scan_result(tmp_path)),
        report_generator=RecordingReportGenerator(events),
    )

    assert events[-1] == ("report", tmp_path.resolve(), "zh-CN")


def test_inspect_does_not_call_runtime_operations_or_execute_target_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_script = tmp_path / "target-script"
    marker = tmp_path / "target-executed"
    target_script.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
    target_script.chmod(target_script.stat().st_mode | stat.S_IXUSR)

    def fail_verify(*args: object, **kwargs: object) -> None:
        raise AssertionError("inspect called MySQL verification")

    def fail_reconcile(*args: object, **kwargs: object) -> None:
        raise AssertionError("inspect called reconciliation")

    monkeypatch.setattr(MySQLVerifier, "verify", fail_verify)
    monkeypatch.setattr(Reconciler, "reconcile", fail_reconcile)
    monkeypatch.setattr(mysql_verification, "default_connection_factory", fail_verify)

    result = inspect_repository(tmp_path)

    assert result.summary.mysql_runtime_verification_artifact_present is False
    assert result.summary.reconciliation_artifact_present is False
    assert not (tmp_path / ".repoevidence/verification/mysql.json").exists()
    assert not (tmp_path / ".repoevidence/reconciliation.json").exists()
    assert not marker.exists()


def test_inspect_reports_preexisting_runtime_artifacts_without_modifying_them(
    tmp_path: Path,
) -> None:
    runtime_path = tmp_path / ".repoevidence" / "verification" / "mysql.json"
    reconciliation_path = tmp_path / ".repoevidence" / "reconciliation.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text("runtime fixture", encoding="utf-8")
    reconciliation_path.write_text("reconciliation fixture", encoding="utf-8")

    result = inspect_repository(tmp_path)

    assert result.summary.mysql_runtime_verification_artifact_present is True
    assert result.summary.reconciliation_artifact_present is True
    assert result.summary.assessment.mysql.state is CheckState.UNKNOWN
    assert result.summary.assessment.reconciliation.state is CheckState.UNKNOWN
    assert runtime_path.read_text(encoding="utf-8") == "runtime fixture"
    assert reconciliation_path.read_text(encoding="utf-8") == "reconciliation fixture"


def test_open_report_is_explicit_and_keeps_path_when_browser_integration_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / ".repoevidence/report/index.html"
    report.parent.mkdir(parents=True)
    report.write_text("<html></html>\n", encoding="utf-8")
    calls: list[str] = []

    def fake_open(url: str) -> bool:
        calls.append(url)
        return False

    monkeypatch.setattr("repoevidence.application.webbrowser.open", fake_open)

    result = open_report(tmp_path)

    assert result.report_path == report
    assert result.browser_opened is False
    assert calls == [report.as_uri()]
