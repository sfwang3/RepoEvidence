"""Structured application-to-report bridge derived from existing artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from repoevidence.assessment import (
    CheckState,
    ConclusionKind,
    RepositoryAssessment,
)
from repoevidence.i18n import Language, resolve_language
from repoevidence.models import Fact, ReconciliationResult, ScanResult, VerificationResult


class AttentionKind(StrEnum):
    """A presentation-neutral reason that deserves user attention."""

    DATABASE_NOT_VERIFIED = "database_not_verified"
    DATABASE_VERIFICATION_FAILED = "database_verification_failed"
    COMPARISON_NOT_RUN = "comparison_not_run"
    COMPARISON_FAILED = "comparison_failed"
    COMPARISON_STALE = "comparison_stale"
    STATE_UNKNOWN = "state_unknown"
    DRIFT = "drift"
    SOURCE_WARNINGS = "source_warnings"
    RUNTIME_WARNINGS = "runtime_warnings"
    RECONCILIATION_WARNINGS = "reconciliation_warnings"
    GIT_METADATA_UNAVAILABLE = "git_metadata_unavailable"


class SourceNoticeKind(StrEnum):
    """Stable presentation hints derived from source warning categories."""

    GIT_METADATA_UNAVAILABLE = "git_metadata_unavailable"
    OTHER_WARNINGS = "other_warnings"


class NextActionKind(StrEnum):
    """The next useful task; command tokens are carried separately."""

    INSPECT = "inspect"
    VERIFY_MYSQL = "verify_mysql"
    RECONCILE = "reconcile"
    REVIEW_FINDINGS = "review_findings"
    REVIEW_EVIDENCE = "review_evidence"


@dataclass(frozen=True)
class RepositoryIdentity:
    name: str
    path: Path
    git_commit: str | None
    branch: str | None


@dataclass(frozen=True)
class SourceOverview:
    collector_ids: tuple[str, ...]
    fact_count: int
    evidence_count: int
    spring_endpoint_count: int
    maven_dependency_count: int
    flyway_migration_count: int
    warning_count: int
    error_count: int
    notice_kinds: tuple[SourceNoticeKind, ...]


@dataclass(frozen=True)
class RuntimeOverview:
    successful: bool
    artifact_present: bool
    verified_fact_count: int
    mysql_table_count: int
    flyway_history_count: int
    warning_count: int
    error_codes: tuple[str, ...]


@dataclass(frozen=True)
class ConclusionView:
    kind: ConclusionKind
    drift_detected: bool | None
    drift_count: int
    matched_count: int


@dataclass(frozen=True)
class AttentionItem:
    kind: AttentionKind
    check: str
    state: CheckState
    count: int | None = None
    reason_codes: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class NextAction:
    kind: NextActionKind
    command: tuple[str, ...] | None


@dataclass(frozen=True)
class ReportViewModel:
    """Complete structured input for human Report presentation."""

    repository: RepositoryIdentity
    generated_at: datetime
    language: Language
    assessment: RepositoryAssessment
    source: SourceOverview
    runtime: RuntimeOverview
    conclusion: ConclusionView
    attention_items: tuple[AttentionItem, ...]
    next_action: NextAction
    static_result: ScanResult
    runtime_result: VerificationResult | None
    reconciliation_result: ReconciliationResult | None

    @property
    def root(self) -> str:
        return str(self.repository.path)


class ReportViewModelBuilder:
    """Derive report semantics without localizing or mutating machine data."""

    def build(
        self,
        assessment: RepositoryAssessment,
        *,
        generated_at: datetime,
        language: str = "en",
    ) -> ReportViewModel:
        static_result = assessment.static_result
        if static_result is None:
            raise ValueError("A valid static scan result is required for a report view.")

        timestamp = generated_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)

        source = SourceOverview(
            collector_ids=tuple(static_result.collectors),
            fact_count=len(static_result.facts),
            evidence_count=len(static_result.evidence),
            spring_endpoint_count=sum(
                fact.id.startswith("fact.spring.endpoint.")
                for fact in static_result.facts
            ),
            maven_dependency_count=sum(
                _is_direct_maven_dependency(fact) for fact in static_result.facts
            ),
            flyway_migration_count=sum(
                _is_versioned_flyway_migration(fact)
                for fact in static_result.facts
            ),
            warning_count=len(static_result.warnings),
            error_count=len(static_result.errors),
            notice_kinds=classify_source_notices(static_result.warnings),
        )
        runtime_result = assessment.verification_result
        runtime_successful = assessment.mysql.state is CheckState.CURRENT
        runtime = RuntimeOverview(
            successful=runtime_successful,
            artifact_present=assessment.runtime_artifact.present,
            verified_fact_count=(
                sum(fact.status == "verified" for fact in runtime_result.facts)
                if runtime_successful and runtime_result is not None
                else 0
            ),
            mysql_table_count=(
                sum(fact.name == "MySQL base table" for fact in runtime_result.facts)
                if runtime_successful and runtime_result is not None
                else 0
            ),
            flyway_history_count=(
                sum(
                    fact.name == "Flyway runtime migration history"
                    for fact in runtime_result.facts
                )
                if runtime_successful and runtime_result is not None
                else 0
            ),
            warning_count=(len(runtime_result.warnings) if runtime_result else 0),
            error_codes=assessment.mysql.error_codes,
        )
        reconciliation_result = assessment.reconciliation_result
        conclusion = _build_conclusion(assessment, reconciliation_result)
        attention_items = _build_attention_items(
            assessment,
            static_result,
            runtime_result,
            reconciliation_result,
            conclusion,
        )
        next_action = _build_next_action(assessment, source, conclusion)
        return ReportViewModel(
            repository=RepositoryIdentity(
                name=assessment.repository_root.name or str(assessment.repository_root),
                path=assessment.repository_root,
                git_commit=_fact_string(static_result.facts, "fact.git.head_commit"),
                branch=_fact_string(static_result.facts, "fact.git.current_branch"),
            ),
            generated_at=timestamp,
            language=resolve_language(language),
            assessment=assessment,
            source=source,
            runtime=runtime,
            conclusion=conclusion,
            attention_items=attention_items,
            next_action=next_action,
            static_result=static_result,
            runtime_result=runtime_result,
            reconciliation_result=reconciliation_result,
        )


def _build_conclusion(
    assessment: RepositoryAssessment,
    reconciliation: ReconciliationResult | None,
) -> ConclusionView:
    if (
        assessment.reconciliation.state is CheckState.CURRENT
        and reconciliation is not None
    ):
        summary = reconciliation.summary
        drift_count = sum(
            (
                summary.runtime_only,
                summary.source_only,
                summary.version_mismatch,
                summary.runtime_failed,
                summary.ambiguous,
            )
        )
        return ConclusionView(
            kind=assessment.conclusion,
            drift_detected=summary.drift_detected,
            drift_count=drift_count,
            matched_count=summary.matched,
        )
    return ConclusionView(
        kind=assessment.conclusion,
        drift_detected=None,
        drift_count=0,
        matched_count=0,
    )


def _build_attention_items(
    assessment: RepositoryAssessment,
    static_result: ScanResult,
    runtime_result: VerificationResult | None,
    reconciliation_result: ReconciliationResult | None,
    conclusion: ConclusionView,
) -> tuple[AttentionItem, ...]:
    items: list[AttentionItem] = []
    notice_kinds = classify_source_notices(static_result.warnings)
    if SourceNoticeKind.GIT_METADATA_UNAVAILABLE in notice_kinds:
        items.append(
            AttentionItem(
                AttentionKind.GIT_METADATA_UNAVAILABLE,
                assessment.source.check,
                assessment.source.state,
            )
        )
    if SourceNoticeKind.OTHER_WARNINGS in notice_kinds:
        items.append(
            AttentionItem(
                AttentionKind.SOURCE_WARNINGS,
                assessment.source.check,
                assessment.source.state,
                count=len(static_result.warnings),
            )
        )

    mysql_kind = {
        CheckState.NOT_RUN: AttentionKind.DATABASE_NOT_VERIFIED,
        CheckState.FAILED: AttentionKind.DATABASE_VERIFICATION_FAILED,
        CheckState.UNKNOWN: AttentionKind.STATE_UNKNOWN,
        CheckState.STALE: AttentionKind.STATE_UNKNOWN,
    }.get(assessment.mysql.state)
    if mysql_kind is not None:
        items.append(
            AttentionItem(
                mysql_kind,
                assessment.mysql.check,
                assessment.mysql.state,
                reason_codes=assessment.mysql.reason_codes,
                error_codes=assessment.mysql.error_codes,
            )
        )
    if runtime_result is not None and runtime_result.warnings:
        items.append(
            AttentionItem(
                AttentionKind.RUNTIME_WARNINGS,
                assessment.mysql.check,
                assessment.mysql.state,
                count=len(runtime_result.warnings),
            )
        )

    reconciliation_kind = {
        CheckState.NOT_RUN: AttentionKind.COMPARISON_NOT_RUN,
        CheckState.FAILED: AttentionKind.COMPARISON_FAILED,
        CheckState.STALE: AttentionKind.COMPARISON_STALE,
        CheckState.UNKNOWN: AttentionKind.STATE_UNKNOWN,
    }.get(assessment.reconciliation.state)
    if reconciliation_kind is not None:
        items.append(
            AttentionItem(
                reconciliation_kind,
                assessment.reconciliation.check,
                assessment.reconciliation.state,
                reason_codes=assessment.reconciliation.reason_codes,
                error_codes=assessment.reconciliation.error_codes,
            )
        )
    if reconciliation_result is not None and reconciliation_result.warnings:
        items.append(
            AttentionItem(
                AttentionKind.RECONCILIATION_WARNINGS,
                assessment.reconciliation.check,
                assessment.reconciliation.state,
                count=len(reconciliation_result.warnings),
            )
        )
    if conclusion.kind is ConclusionKind.DRIFT:
        items.append(
            AttentionItem(
                AttentionKind.DRIFT,
                assessment.reconciliation.check,
                assessment.reconciliation.state,
                count=conclusion.drift_count,
            )
        )
    return tuple(items)


def classify_source_notices(
    warnings: list[str] | tuple[str, ...],
) -> tuple[SourceNoticeKind, ...]:
    """Collapse machine warning text into stable, non-localized presentation hints."""

    kinds: list[SourceNoticeKind] = []
    git_warnings = [warning for warning in warnings if "not a Git repository" in warning]
    if git_warnings:
        kinds.append(SourceNoticeKind.GIT_METADATA_UNAVAILABLE)
    if len(git_warnings) != len(warnings):
        kinds.append(SourceNoticeKind.OTHER_WARNINGS)
    return tuple(kinds)


def _build_next_action(
    assessment: RepositoryAssessment,
    source: SourceOverview,
    conclusion: ConclusionView,
) -> NextAction:
    root = str(assessment.repository_root)
    if assessment.source.state is not CheckState.CURRENT:
        return NextAction(NextActionKind.INSPECT, ("repoevidence", "inspect", root))
    if assessment.mysql.state is not CheckState.CURRENT:
        if (
            assessment.mysql.state is CheckState.NOT_RUN
            and source.flyway_migration_count == 0
        ):
            return NextAction(NextActionKind.REVIEW_EVIDENCE, None)
        return NextAction(
            NextActionKind.VERIFY_MYSQL,
            ("repoevidence", "verify", "mysql", root),
        )
    if assessment.reconciliation.state is not CheckState.CURRENT:
        return NextAction(
            NextActionKind.RECONCILE,
            ("repoevidence", "reconcile", root),
        )
    if conclusion.kind is ConclusionKind.DRIFT:
        return NextAction(NextActionKind.REVIEW_FINDINGS, None)
    return NextAction(NextActionKind.REVIEW_EVIDENCE, None)


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
