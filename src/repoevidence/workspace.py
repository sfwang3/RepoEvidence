"""Presentation-neutral projection for the persistent interactive workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from repoevidence.assessment import (
    ArtifactSnapshot,
    CheckState,
    RepositoryAssessment,
)
from repoevidence.models import Fact, ReconciliationResult, ScanResult, VerificationResult
from repoevidence.project_context import ProjectContext
from repoevidence.status import (
    ArtifactLifecycle,
    DomainOutcome,
    Freshness,
    OperationState,
)

if TYPE_CHECKING:
    from repoevidence.report_manifest import ReportAssessment


@dataclass(frozen=True)
class WorkspaceCheck:
    id: str
    lifecycle: ArtifactLifecycle
    freshness: Freshness
    operation: OperationState
    outcome: DomainOutcome
    observed_at: datetime | None
    provenance_summary: tuple[str, ...]
    reason_codes: tuple[str, ...]
    artifact_path: Path
    available_actions: tuple[str, ...]
    safety_level: str


@dataclass(frozen=True)
class WorkspaceSession:
    """Ephemeral facts known only during this process."""

    inspected_source_at: datetime | None = None
    inspected_project_root: Path | None = None
    inspected_head: str | None = None
    inspected_status_fingerprint: str | None = None


@dataclass(frozen=True)
class WorkspaceProjection:
    project: ProjectContext
    source: WorkspaceCheck
    runtime: WorkspaceCheck
    comparison: WorkspaceCheck
    report: WorkspaceCheck
    primary_action: str
    secondary_action: str | None
    selected_id: str = "source"
    active_operation: str | None = None
    active_phase: str | None = None


# Re-export the state dimensions from the projection module for callers that
# only need the workspace vocabulary.
__all__ = [
    "ArtifactLifecycle",
    "DomainOutcome",
    "Freshness",
    "OperationState",
    "WorkspaceCheck",
    "WorkspaceProjection",
    "WorkspaceSession",
    "build_workspace_projection",
]


def build_workspace_projection(
    context: ProjectContext,
    assessment: RepositoryAssessment,
    *,
    report_assessment: ReportAssessment | None,
    session: WorkspaceSession | None = None,
    language: str = "en",
) -> WorkspaceProjection:
    """Derive UI-neutral status without executing any operation."""

    source = _source_check(context, assessment, session)
    runtime = _runtime_check(context, assessment)
    comparison = _comparison_check(assessment, source, runtime)
    report = _report_check(assessment, report_assessment, language)
    primary, secondary = _next_actions(context, source, runtime, comparison, report)
    return WorkspaceProjection(
        project=context,
        source=source,
        runtime=runtime,
        comparison=comparison,
        report=report,
        primary_action=primary,
        secondary_action=secondary,
    )


def _source_check(
    context: ProjectContext,
    assessment: RepositoryAssessment,
    session: WorkspaceSession | None,
) -> WorkspaceCheck:
    artifact = assessment.static_artifact
    if not artifact.present:
        return _missing_check("source", artifact.path, "source.inspect")
    if artifact.parsed is None:
        return _invalid_check("source", artifact, "source.inspect")
    if not isinstance(artifact.parsed, ScanResult):
        return _invalid_check("source", artifact, "source.inspect")
    if artifact.parsed.errors:
        return WorkspaceCheck(
            id="source",
            lifecycle=ArtifactLifecycle.FAILED,
            freshness=Freshness.NOT_APPLICABLE,
            operation=OperationState.FAILED,
            outcome=DomainOutcome.NOT_AVAILABLE,
            observed_at=artifact.parsed.metadata.finished_at,
            provenance_summary=(),
            reason_codes=("operation_errors",),
            artifact_path=artifact.path,
            available_actions=("source.inspect",),
            safety_level="write_project_artifact",
        )
    freshness, reasons, provenance = _source_freshness(context, artifact.parsed, session)
    return WorkspaceCheck(
        id="source",
        lifecycle=ArtifactLifecycle.VALID,
        freshness=freshness,
        operation=OperationState.SUCCEEDED,
        outcome=DomainOutcome.SOURCE_ONLY,
        observed_at=artifact.parsed.metadata.finished_at,
        provenance_summary=provenance,
        reason_codes=reasons,
        artifact_path=artifact.path,
        available_actions=("view.source", "source.inspect"),
        safety_level="write_project_artifact",
    )


def _source_freshness(
    context: ProjectContext,
    result: ScanResult,
    session: WorkspaceSession | None,
) -> tuple[Freshness, tuple[str, ...], tuple[str, ...]]:
    stored_head = _fact_string(result.facts, "fact.git.head_commit")
    session_matches = (
        session is not None
        and session.inspected_project_root == context.project_root
        and session.inspected_head == context.git.commit
        and session.inspected_source_at is not None
        and context.git.status_known
        and session.inspected_status_fingerprint == context.git.status_fingerprint
    )
    if session_matches:
        if not context.git.repository:
            return Freshness.UNCERTAIN, (
                "session_inspected",
                "source_provenance_missing",
            ), ("inspected_this_session", "non_git_snapshot")
        if context.git.dirty is True:
            # A porcelain-status fingerprint is not content provenance for a
            # dirty tree: a file can change while its status line stays the
            # same. Keep the useful session qualifier, but never promote it
            # to current/fresh.
            return Freshness.UNCERTAIN, (
                "session_inspected",
                "dirty_worktree_provenance_insufficient",
            ), ("inspected_this_session", "worktree_dirty")
        return Freshness.FRESH, ("session_inspected",), ("inspected_this_session",)
    if not context.git.repository:
        if context.git.status_known:
            return Freshness.UNCERTAIN, ("source_provenance_missing",), ("non_git_snapshot",)
        return Freshness.UNCERTAIN, ("git_status_unknown",), ()
    if context.git.dirty is True:
        return (
            Freshness.UNCERTAIN,
            ("dirty_worktree_provenance_insufficient",),
            ("worktree_dirty",),
        )
    if context.git.dirty is None or not context.git.status_known:
        return Freshness.UNCERTAIN, ("git_status_unknown",), ()
    if stored_head is None:
        return Freshness.UNCERTAIN, ("source_provenance_missing",), ()
    if stored_head != context.git.commit:
        return Freshness.STALE, ("stored_head_mismatch",), ("stored_head_differs",)
    return Freshness.FRESH, ("current_clean_head",), ("HEAD_matches", "worktree_clean")


def _runtime_check(context: ProjectContext, assessment: RepositoryAssessment) -> WorkspaceCheck:
    artifact = assessment.runtime_artifact
    parsed = artifact.parsed
    if not artifact.present:
        return _missing_check(
            "runtime", artifact.path, "runtime.verify_mysql", safety="external_read"
        )
    if not isinstance(parsed, VerificationResult):
        return _invalid_check(
            "runtime", artifact, "runtime.verify_mysql", safety="external_read"
        )
    timestamp = parsed.metadata.observed_at or parsed.metadata.finished_at
    if parsed.errors:
        error_codes = tuple(error.code for error in parsed.errors)
        return WorkspaceCheck(
            id="runtime",
            lifecycle=ArtifactLifecycle.FAILED,
            freshness=Freshness.NOT_APPLICABLE,
            operation=OperationState.FAILED,
            outcome=DomainOutcome.RUNTIME_FAILED,
            observed_at=timestamp,
            provenance_summary=("timestamped_snapshot",),
            reason_codes=(*error_codes, "operation_errors"),
            artifact_path=artifact.path,
            available_actions=("view.runtime", "runtime.verify_mysql", "help.open"),
            safety_level="external_read",
        )
    if Path(parsed.repository_root).resolve() != context.project_root:
        return _invalid_check(
            "runtime",
            artifact,
            "runtime.verify_mysql",
            safety="external_read",
            reasons=("repository_root_mismatch",),
        )
    return WorkspaceCheck(
        id="runtime",
        lifecycle=ArtifactLifecycle.VALID,
        freshness=Freshness.FRESH,
        operation=OperationState.SUCCEEDED,
        outcome=DomainOutcome.MATCHED,
        observed_at=timestamp,
        provenance_summary=("timestamped_snapshot",),
        reason_codes=(),
        artifact_path=artifact.path,
        available_actions=("view.runtime", "runtime.verify_mysql"),
        safety_level="external_read",
    )


def _comparison_check(
    assessment: RepositoryAssessment,
    source: WorkspaceCheck,
    runtime: WorkspaceCheck,
) -> WorkspaceCheck:
    artifact = assessment.reconciliation_artifact
    parsed = artifact.parsed
    if not artifact.present:
        return _missing_check("comparison", artifact.path, "comparison.reconcile")
    if not isinstance(parsed, ReconciliationResult):
        return _invalid_check("comparison", artifact, "comparison.reconcile")
    if parsed.errors:
        return WorkspaceCheck(
            id="comparison",
            lifecycle=ArtifactLifecycle.FAILED,
            freshness=Freshness.NOT_APPLICABLE,
            operation=OperationState.FAILED,
            outcome=DomainOutcome.RUNTIME_FAILED,
            observed_at=None,
            provenance_summary=(),
            reason_codes=("operation_errors",),
            artifact_path=artifact.path,
            available_actions=("comparison.reconcile", "help.open"),
            safety_level="read_only_local",
        )
    if source.freshness is Freshness.STALE or runtime.freshness is Freshness.STALE:
        return _comparison_state(
            artifact,
            Freshness.STALE,
            ("upstream_input_stale",),
            parsed,
        )
    if source.freshness is not Freshness.FRESH or runtime.freshness is not Freshness.FRESH:
        return _comparison_state(
            artifact,
            Freshness.UNCERTAIN,
            ("upstream_input_uncertain",),
            parsed,
        )
    if assessment.reconciliation.state is CheckState.STALE:
        return _comparison_state(
            artifact, Freshness.STALE, assessment.reconciliation.reason_codes, parsed
        )
    if assessment.reconciliation.state is not CheckState.CURRENT:
        return _comparison_state(
            artifact, Freshness.UNKNOWN, assessment.reconciliation.reason_codes, parsed
        )
    outcome = (
        DomainOutcome.DRIFT_DETECTED
        if parsed.summary.drift_detected
        else DomainOutcome.MATCHED
    )
    return WorkspaceCheck(
        id="comparison",
        lifecycle=ArtifactLifecycle.VALID,
        freshness=Freshness.FRESH,
        operation=OperationState.SUCCEEDED,
        outcome=outcome,
        observed_at=None,
        provenance_summary=("exact_inputs_match",),
        reason_codes=(),
        artifact_path=artifact.path,
        available_actions=("view.finding", "view.comparison", "comparison.reconcile"),
        safety_level="read_only_local",
    )


def _comparison_state(
    artifact: ArtifactSnapshot,
    freshness: Freshness,
    reasons: tuple[str, ...],
    parsed: ReconciliationResult,
) -> WorkspaceCheck:
    return WorkspaceCheck(
        id="comparison",
        lifecycle=ArtifactLifecycle.VALID,
        freshness=freshness,
        operation=OperationState.SUCCEEDED,
        outcome=(
            DomainOutcome.DRIFT_DETECTED
            if parsed.summary.drift_detected
            else DomainOutcome.MATCHED
        ),
        observed_at=None,
        provenance_summary=(),
        reason_codes=reasons,
        artifact_path=artifact.path,
        available_actions=("comparison.reconcile", "view.comparison"),
        safety_level="read_only_local",
    )


def _report_check(
    assessment: RepositoryAssessment,
    report_assessment: ReportAssessment | None,
    language: str,
) -> WorkspaceCheck:
    path = assessment.repository_root / ".repoevidence/report/index.html"
    if report_assessment is None:
        return _missing_check("report", path, "report.generate", safety="write_project_artifact")
    actions = ["view.report"]
    if report_assessment.freshness is Freshness.STALE or not report_assessment.language_matches:
        actions.append("report.refresh")
    actions.append("report.open")
    lifecycle = report_assessment.lifecycle
    operation = OperationState.FAILED if lifecycle in {
        ArtifactLifecycle.CORRUPT,
        ArtifactLifecycle.UNSUPPORTED,
    } else OperationState.SUCCEEDED if lifecycle is ArtifactLifecycle.VALID else OperationState.IDLE
    outcome = DomainOutcome.NOT_AVAILABLE
    return WorkspaceCheck(
        id="report",
        lifecycle=lifecycle,
        freshness=report_assessment.freshness,
        operation=operation,
        outcome=outcome,
        observed_at=report_assessment.generated_at,
        provenance_summary=tuple(
            item for item in (report_assessment.language,) if item is not None
        ),
        reason_codes=report_assessment.reason_codes,
        artifact_path=report_assessment.artifact_path,
        available_actions=tuple(actions),
        safety_level=(
            "open_external_app"
            if lifecycle is ArtifactLifecycle.VALID
            else "write_project_artifact"
        ),
    )


def _next_actions(
    context: ProjectContext,
    source: WorkspaceCheck,
    runtime: WorkspaceCheck,
    comparison: WorkspaceCheck,
    report: WorkspaceCheck,
) -> tuple[str, str | None]:
    if source.lifecycle is not ArtifactLifecycle.VALID or source.freshness in {
        Freshness.STALE,
        Freshness.UNCERTAIN,
        Freshness.UNKNOWN,
    }:
        return "source.inspect", "help.open"
    if runtime.lifecycle is ArtifactLifecycle.MISSING:
        return "runtime.verify_mysql", "view.source"
    if runtime.lifecycle in {
        ArtifactLifecycle.FAILED,
        ArtifactLifecycle.CORRUPT,
        ArtifactLifecycle.UNSUPPORTED,
    }:
        return "runtime.verify_mysql", "help.open"
    if (
        comparison.freshness
        in {Freshness.STALE, Freshness.UNCERTAIN, Freshness.UNKNOWN}
        or comparison.lifecycle is ArtifactLifecycle.MISSING
    ):
        return "comparison.reconcile", "view.runtime"
    if comparison.outcome is DomainOutcome.DRIFT_DETECTED:
        return (
            "view.finding",
            "report.refresh"
            if report.lifecycle is ArtifactLifecycle.VALID
            else "report.generate",
        )
    if report.lifecycle is ArtifactLifecycle.MISSING:
        return "report.generate", "view.comparison"
    if report.freshness is Freshness.STALE or "language_mismatch" in report.reason_codes:
        return "report.refresh", "report.open"
    return "view.source", "report.open"


def _missing_check(
    check_id: str,
    path: Path,
    action: str,
    *,
    safety: str = "write_project_artifact",
) -> WorkspaceCheck:
    return WorkspaceCheck(
        id=check_id,
        lifecycle=ArtifactLifecycle.MISSING,
        freshness=Freshness.NOT_APPLICABLE,
        operation=OperationState.IDLE,
        outcome=DomainOutcome.NOT_AVAILABLE,
        observed_at=None,
        provenance_summary=(),
        reason_codes=("artifact_missing",),
        artifact_path=path,
        available_actions=(action,),
        safety_level=safety,
    )


def _invalid_check(
    check_id: str,
    artifact: ArtifactSnapshot,
    action: str,
    *,
    safety: str = "write_project_artifact",
    reasons: tuple[str, ...] | None = None,
) -> WorkspaceCheck:
    lifecycle = (
        ArtifactLifecycle.UNSUPPORTED
        if "unsupported_schema" in artifact.reason_codes
        else ArtifactLifecycle.CORRUPT
    )
    return WorkspaceCheck(
        id=check_id,
        lifecycle=lifecycle,
        freshness=Freshness.UNKNOWN,
        operation=OperationState.FAILED,
        outcome=DomainOutcome.NOT_AVAILABLE,
        observed_at=None,
        provenance_summary=(),
        reason_codes=reasons or artifact.reason_codes or ("artifact_unreadable",),
        artifact_path=artifact.path,
        available_actions=(action, "help.open"),
        safety_level=safety,
    )


def _fact_string(facts: list[Fact], fact_id: str) -> str | None:
    fact = next((item for item in facts if item.id == fact_id), None)
    return fact.value if fact is not None and isinstance(fact.value, str) else None
