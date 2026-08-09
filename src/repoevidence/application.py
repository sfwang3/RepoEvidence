"""Reusable application services for repository inspection workflows."""

from __future__ import annotations

import webbrowser
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from repoevidence.artifact_io import atomic_write_text
from repoevidence.assessment import RepositoryAssessment, assess_repository
from repoevidence.i18n import resolve_language
from repoevidence.models import (
    Fact,
    ReconciliationResult,
    ScanResult,
    VerificationResult,
)
from repoevidence.reconciliation import Reconciler
from repoevidence.report_view import ReportViewModel, ReportViewModelBuilder
from repoevidence.reporting import (
    RECONCILIATION_RELATIVE_PATH,
    RUNTIME_RELATIVE_PATH,
    STATIC_RELATIVE_PATH,
    ReportGenerator,
)
from repoevidence.scanner import Scanner
from repoevidence.verification.mysql import MySQLVerifier

_COMPLETED_INSPECT_CHECKS = ("static_scan", "report_generation")
_PENDING_INSPECT_CHECKS = (
    "mysql_verification",
    "reconciliation",
    "target_project_execution",
    "database_connection",
)


class RepositoryPathError(Exception):
    """A presentation-neutral repository input error."""

    def __init__(self, code: str, path: Path) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code}: {path}")


@dataclass(frozen=True)
class ScanApplicationResult:
    """The existing static scan result and its persisted artifact path."""

    scan_result: ScanResult
    evidence_path: Path
    assessment: RepositoryAssessment


@dataclass(frozen=True)
class ReportApplicationResult:
    """The existing report output path produced from existing artifacts."""

    report_path: Path
    assessment: RepositoryAssessment
    view_model: ReportViewModel


class ReportOpenError(Exception):
    """A report cannot be opened because its local artifact is unavailable."""

    def __init__(self, code: str, path: Path) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code}: {path}")


@dataclass(frozen=True)
class ReportOpenApplicationResult:
    """Opening a browser is best effort; the report path always remains available."""

    report_path: Path
    browser_opened: bool


@dataclass(frozen=True)
class VerificationApplicationResult:
    """The existing MySQL verification result and persisted artifact path."""

    verification_result: VerificationResult
    verification_path: Path


@dataclass(frozen=True)
class ReconciliationApplicationResult:
    """The existing reconciliation result and persisted artifact path."""

    reconciliation_result: ReconciliationResult
    reconciliation_path: Path


@dataclass(frozen=True)
class InspectSummary:
    """Presentation-neutral summary of one static inspect workflow."""

    repository_name: str
    repository_path: Path
    git_commit: str | None
    branch: str | None
    detected_capabilities: tuple[str, ...]
    spring_endpoint_count: int
    maven_dependency_count: int
    flyway_migration_count: int
    mysql_runtime_verification_artifact_present: bool
    reconciliation_artifact_present: bool
    report_path: Path
    evidence_path: Path
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    completed_checks: tuple[str, ...]
    failed_checks: tuple[str, ...]
    pending_checks: tuple[str, ...]
    assessment: RepositoryAssessment


@dataclass(frozen=True)
class InspectResult:
    """Reusable result returned after static scan and report generation."""

    summary: InspectSummary
    scan_result: ScanResult


def scan_repository(
    repo_path: str | Path,
    *,
    scanner: Scanner | None = None,
) -> ScanApplicationResult:
    """Run the existing static scanner and persist the existing evidence artifact."""

    root = _resolve_repository(repo_path)
    scan_result = (scanner or Scanner.default()).scan(root)
    evidence_path = root / STATIC_RELATIVE_PATH
    _write_model_json(evidence_path, scan_result)
    return ScanApplicationResult(
        scan_result=scan_result,
        evidence_path=evidence_path,
        assessment=assess_repository(root),
    )


def verify_mysql_repository(
    repo_path: str | Path,
    *,
    verifier: MySQLVerifier | None = None,
    environment: Mapping[str, str] | None = None,
) -> VerificationApplicationResult:
    """Run the existing explicit MySQL verifier and persist its existing artifact."""

    root = _resolve_repository(repo_path)
    verification_result = (verifier or MySQLVerifier()).verify(
        root,
        environment=environment,
    )
    verification_path = root / RUNTIME_RELATIVE_PATH
    _write_model_json(verification_path, verification_result)
    return VerificationApplicationResult(
        verification_result=verification_result,
        verification_path=verification_path,
    )


def reconcile_repository(
    repo_path: str | Path,
    *,
    reconciler: Reconciler | None = None,
) -> ReconciliationApplicationResult:
    """Run the existing offline reconciler and persist its existing artifact."""

    root = _resolve_repository(repo_path)
    reconciliation_result = (reconciler or Reconciler()).reconcile(root)
    reconciliation_path = root / RECONCILIATION_RELATIVE_PATH
    _write_model_json(reconciliation_path, reconciliation_result)
    return ReconciliationApplicationResult(
        reconciliation_result=reconciliation_result,
        reconciliation_path=reconciliation_path,
    )


def generate_report(
    repo_path: str | Path,
    *,
    language: str = "en",
    report_generator: ReportGenerator | None = None,
) -> ReportApplicationResult:
    """Generate the existing offline report from existing repository artifacts."""

    root = _resolve_repository(repo_path)
    report_path = (report_generator or ReportGenerator()).generate(
        root,
        language=resolve_language(language),
    )
    assessment = assess_repository(root)
    view_model = ReportViewModelBuilder().build(
        assessment,
        generated_at=datetime.now(timezone.utc),
        language=language,
    )
    return ReportApplicationResult(
        report_path=report_path,
        assessment=assessment,
        view_model=view_model,
    )


def open_report(repo_path: str | Path) -> ReportOpenApplicationResult:
    """Open an existing report only after the user explicitly chooses the action."""

    root = _resolve_repository(repo_path)
    report_path = root / ".repoevidence/report/index.html"
    if not report_path.is_file():
        raise ReportOpenError("report_missing", report_path)
    try:
        browser_opened = bool(webbrowser.open(report_path.as_uri()))
    except (OSError, webbrowser.Error):
        browser_opened = False
    return ReportOpenApplicationResult(
        report_path=report_path,
        browser_opened=browser_opened,
    )


def inspect_repository(
    repo_path: str | Path,
    *,
    language: str = "en",
    scanner: Scanner | None = None,
    report_generator: ReportGenerator | None = None,
) -> InspectResult:
    """Run the safe static inspect workflow in the fixed scan-then-report order."""

    root = _resolve_repository(repo_path)
    scan_result = scan_repository(root, scanner=scanner)
    report_result = generate_report(
        root,
        language=language,
        report_generator=report_generator,
    )
    summary = _build_inspect_summary(root, scan_result, report_result)
    return InspectResult(summary=summary, scan_result=scan_result.scan_result)


def _build_inspect_summary(
    root: Path,
    scan_result: ScanApplicationResult,
    report_result: ReportApplicationResult,
) -> InspectSummary:
    result = scan_result.scan_result
    facts = result.facts
    return InspectSummary(
        repository_name=root.name or str(root),
        repository_path=root,
        git_commit=_fact_string(facts, "fact.git.head_commit"),
        branch=_fact_string(facts, "fact.git.current_branch"),
        detected_capabilities=tuple(result.collectors),
        spring_endpoint_count=sum(
            fact.id.startswith("fact.spring.endpoint.") for fact in facts
        ),
        maven_dependency_count=sum(_is_direct_maven_dependency(fact) for fact in facts),
        flyway_migration_count=sum(_is_versioned_flyway_migration(fact) for fact in facts),
        mysql_runtime_verification_artifact_present=(
            root / RUNTIME_RELATIVE_PATH
        ).is_file(),
        reconciliation_artifact_present=(root / RECONCILIATION_RELATIVE_PATH).is_file(),
        report_path=report_result.report_path,
        evidence_path=scan_result.evidence_path,
        warnings=tuple(result.warnings),
        errors=tuple(result.errors),
        completed_checks=(
            _COMPLETED_INSPECT_CHECKS
            if not result.errors
            else ("report_generation",)
        ),
        failed_checks=(("static_scan",) if result.errors else ()),
        pending_checks=_PENDING_INSPECT_CHECKS,
        assessment=report_result.assessment,
    )


def _resolve_repository(repo_path: str | Path) -> Path:
    return resolve_repository_path(repo_path)


def resolve_repository_path(repo_path: str | Path) -> Path:
    """Resolve and validate a repository directory for every application service."""

    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        raise RepositoryPathError("repository_path_missing", root)
    if not root.is_dir():
        raise RepositoryPathError("repository_path_not_directory", root)
    return root


def _write_model_json(
    path: Path,
    result: ScanResult | VerificationResult | ReconciliationResult,
) -> None:
    atomic_write_text(path, result.model_dump_json(indent=2) + "\n")


def _fact_string(facts: list[Fact], fact_id: str) -> str | None:
    fact = next((item for item in facts if item.id == fact_id), None)
    return fact.value if fact is not None and isinstance(fact.value, str) else None


def _is_direct_maven_dependency(fact: Fact) -> bool:
    return (
        fact.id.startswith("fact.maven.dependency.")
        and isinstance(fact.value, dict)
        and fact.value.get("location") == "dependencies"
    )


def _is_versioned_flyway_migration(fact: Fact) -> bool:
    return (
        fact.name == "Flyway migration declaration"
        and isinstance(fact.value, dict)
        and fact.value.get("type") == "versioned"
    )
