from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from repoevidence import __version__
from repoevidence.assessment import assess_repository
from repoevidence.models import (
    Evidence,
    Fact,
    ReconciliationInputArtifact,
    ReconciliationResult,
    ReconciliationSummary,
    ScanMetadata,
    ScanResult,
    VerificationError,
    VerificationMetadata,
    VerificationResult,
)
from repoevidence.project_context import GitContext, ProjectContext
from repoevidence.workspace import (
    ArtifactLifecycle,
    DomainOutcome,
    Freshness,
    OperationState,
    WorkspaceSession,
    build_workspace_projection,
)

NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


def _context(
    root: Path,
    *,
    dirty: bool | None = False,
    repository: bool = True,
    status_fingerprint: str | None = None,
) -> ProjectContext:
    return ProjectContext(
        project_root=root.resolve(),
        opened_from=root.resolve(),
        repository_name=root.name,
        git=GitContext(
            repository=repository,
            top_level=root.resolve() if repository else None,
            branch="main" if repository else None,
            commit="abc123456789" if repository else None,
            dirty=dirty,
            status_known=True,
            status_fingerprint=status_fingerprint,
        ),
        markers=(),
    )


def _scan(root: Path, *, head: str | None = "abc123456789") -> ScanResult:
    evidence: list[Evidence] = []
    facts: list[Fact] = []
    if head is not None:
        evidence.append(Evidence(id="ev.git.head", kind="git", source="fixture", value=head))
        facts.append(
            Fact(
                id="fact.git.head_commit",
                name="HEAD commit",
                value=head,
                status="verified",
                evidence_ids=["ev.git.head"],
            )
        )
    return ScanResult(
        repository_root=str(root.resolve()),
        metadata=ScanMetadata(tool_version=__version__, started_at=NOW, finished_at=NOW),
        collectors=["fixture"],
        evidence=evidence,
        facts=facts,
    )


def _runtime(root: Path, *, errors: list[VerificationError] | None = None) -> VerificationResult:
    return VerificationResult(
        verifier="mysql",
        repository_root=str(root.resolve()),
        metadata=VerificationMetadata(
            tool_version=__version__, started_at=NOW, finished_at=NOW, observed_at=NOW
        ),
        errors=errors or [],
    )


def _write(root: Path, relative: str, value: object) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _base_root(tmp_path: Path, *, head: str | None = "abc123456789") -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, ".repoevidence/evidence.json", _scan(root, head=head))
    return root


def test_source_from_another_head_is_stale_not_current(tmp_path: Path) -> None:
    root = _base_root(tmp_path, head="old-head")

    projection = build_workspace_projection(
        _context(root),
        assess_repository(root),
        report_assessment=None,
    )

    assert projection.source.lifecycle is ArtifactLifecycle.VALID
    assert projection.source.freshness is Freshness.STALE
    assert projection.source.operation is OperationState.SUCCEEDED
    assert "fresh" not in projection.source.available_actions


def test_dirty_worktree_without_file_provenance_is_uncertain(tmp_path: Path) -> None:
    root = _base_root(tmp_path)

    projection = build_workspace_projection(
        _context(root, dirty=True),
        assess_repository(root),
        report_assessment=None,
    )

    assert projection.source.freshness is Freshness.UNCERTAIN
    assert projection.source.reason_codes == ("dirty_worktree_provenance_insufficient",)


def test_session_inspection_does_not_hide_a_later_worktree_change(tmp_path: Path) -> None:
    root = _base_root(tmp_path)

    projection = build_workspace_projection(
        _context(root, dirty=True, status_fingerprint="same-status"),
        assess_repository(root),
        report_assessment=None,
        session=WorkspaceSession(
            inspected_source_at=NOW,
            inspected_project_root=root.resolve(),
            inspected_head="abc123456789",
            inspected_status_fingerprint="same-status",
        ),
    )

    assert projection.source.freshness is Freshness.UNCERTAIN
    assert projection.source.reason_codes == (
        "session_inspected",
        "dirty_worktree_provenance_insufficient",
    )


def test_non_git_session_inspection_keeps_freshness_uncertain(tmp_path: Path) -> None:
    root = _base_root(tmp_path)

    projection = build_workspace_projection(
        _context(root, repository=False),
        assess_repository(root),
        report_assessment=None,
        session=WorkspaceSession(
            inspected_source_at=NOW,
            inspected_project_root=root.resolve(),
            inspected_head=None,
            inspected_status_fingerprint=None,
        ),
    )

    assert projection.source.freshness is Freshness.UNCERTAIN
    assert projection.source.reason_codes == (
        "session_inspected",
        "source_provenance_missing",
    )


def test_verification_artifact_with_errors_is_failed_not_verified(tmp_path: Path) -> None:
    root = _base_root(tmp_path)
    _write(
        root,
        ".repoevidence/verification/mysql.json",
        _runtime(
            root,
            errors=[VerificationError(code="mysql_connection_failed", message="safe")],
        ),
    )

    projection = build_workspace_projection(
        _context(root),
        assess_repository(root),
        report_assessment=None,
    )

    assert projection.runtime.lifecycle is ArtifactLifecycle.FAILED
    assert projection.runtime.operation is OperationState.FAILED
    assert projection.runtime.outcome is DomainOutcome.RUNTIME_FAILED
    assert projection.runtime.freshness is Freshness.NOT_APPLICABLE


def test_reconciliation_input_hash_change_is_stale(tmp_path: Path) -> None:
    root = _base_root(tmp_path)
    runtime_path = _write(root, ".repoevidence/verification/mysql.json", _runtime(root))
    static_path = root / ".repoevidence/evidence.json"
    reconciliation = ReconciliationResult(
        repository_root=str(root.resolve()),
        inputs=[
            ReconciliationInputArtifact(
                artifact="static_scan",
                relative_path=".repoevidence/evidence.json",
                sha256=hashlib.sha256(static_path.read_bytes()).hexdigest(),
            ),
            ReconciliationInputArtifact(
                artifact="mysql_verification",
                relative_path=".repoevidence/verification/mysql.json",
                sha256="not-the-runtime-hash",
            ),
        ],
    )
    _write(root, ".repoevidence/reconciliation.json", reconciliation)

    projection = build_workspace_projection(
        _context(root),
        assess_repository(root),
        report_assessment=None,
    )

    assert runtime_path.is_file()
    assert projection.comparison.freshness is Freshness.STALE
    assert projection.comparison.reason_codes == ("input_hash_mismatch",)


def test_drift_is_successful_operation_with_domain_outcome(tmp_path: Path) -> None:
    root = _base_root(tmp_path)
    runtime_path = _write(root, ".repoevidence/verification/mysql.json", _runtime(root))
    static_path = root / ".repoevidence/evidence.json"
    reconciliation = ReconciliationResult(
        repository_root=str(root.resolve()),
        inputs=[
            ReconciliationInputArtifact(
                artifact="static_scan",
                relative_path=".repoevidence/evidence.json",
                sha256=hashlib.sha256(static_path.read_bytes()).hexdigest(),
            ),
            ReconciliationInputArtifact(
                artifact="mysql_verification",
                relative_path=".repoevidence/verification/mysql.json",
                sha256=hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
            ),
        ],
        summary=ReconciliationSummary(runtime_only=1, drift_detected=True),
    )
    _write(root, ".repoevidence/reconciliation.json", reconciliation)

    projection = build_workspace_projection(
        _context(root),
        assess_repository(root),
        report_assessment=None,
    )

    assert projection.comparison.freshness is Freshness.FRESH
    assert projection.comparison.operation is OperationState.SUCCEEDED
    assert projection.comparison.outcome is DomainOutcome.DRIFT_DETECTED
    assert projection.primary_action == "view.finding"


def test_fresh_project_has_neutral_missing_ledger_and_inspect_action(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()

    projection = build_workspace_projection(
        _context(root),
        assess_repository(root, require_static=False),
        report_assessment=None,
    )

    assert projection.source.lifecycle is ArtifactLifecycle.MISSING
    assert projection.runtime.lifecycle is ArtifactLifecycle.MISSING
    assert projection.comparison.lifecycle is ArtifactLifecycle.MISSING
    assert projection.primary_action == "source.inspect"
    assert projection.source.outcome is DomainOutcome.NOT_AVAILABLE
