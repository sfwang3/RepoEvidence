from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoevidence import __version__
from repoevidence.application import reconcile_repository, scan_repository
from repoevidence.assessment import ConclusionKind, assess_repository
from repoevidence.cli import create_app
from repoevidence.models import (
    Evidence,
    Fact,
    VerificationError,
    VerificationMetadata,
    VerificationResult,
)
from repoevidence.report_view import (
    AttentionKind,
    NextActionKind,
    ReportViewModelBuilder,
)
from repoevidence.reporting import ReportGenerator

FIXED_TIME = datetime(2026, 8, 9, tzinfo=timezone.utc)


def _write_source(root: Path, version: str = "1") -> None:
    migration = root / f"src/main/resources/db/migration/V{version}__migration.sql"
    migration.parent.mkdir(parents=True, exist_ok=True)
    migration.write_text("SELECT 1;\n", encoding="utf-8")
    scan_repository(root)


def _write_runtime(
    root: Path,
    version: str = "1",
    *,
    errors: list[VerificationError] | None = None,
) -> None:
    evidence: list[Evidence] = []
    facts: list[Fact] = []
    if not errors:
        evidence.append(
            Evidence(
                id="ev.mysql.flyway.history.1",
                kind="mysql.flyway_history",
                source="mysql.query.flyway_history",
                value={"result": {"version": version}},
            )
        )
        facts.append(
            Fact(
                id="fact.mysql.flyway.history.1",
                name="Flyway runtime migration history",
                value={
                    "installed_rank": 1,
                    "version": version,
                    "description": "migration",
                    "type": "SQL",
                    "script": f"V{version}__migration.sql",
                    "checksum": 1,
                    "success": True,
                    "installed_on": "2026-08-09T00:00:00Z",
                },
                status="verified",
                evidence_ids=["ev.mysql.flyway.history.1"],
            )
        )
    result = VerificationResult(
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
    path = root / ".repoevidence/verification/mysql.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _state_repository(base: Path, state: str) -> Path:
    root = base / state
    root.mkdir()
    _write_source(root)
    if state == "static_only":
        return root
    if state == "failed_runtime":
        _write_runtime(
            root,
            errors=[
                VerificationError(
                    code="mysql_connection_failed",
                    message="Unable to connect to MySQL.",
                )
            ],
        )
        return root
    _write_runtime(root, "2" if state == "drift" else "1")
    if state == "runtime_no_reconcile":
        return root
    reconcile_repository(root)
    if state == "stale_reconciliation":
        evidence_path = root / ".repoevidence/evidence.json"
        evidence_path.write_text(
            evidence_path.read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )
    return root


@pytest.mark.parametrize(
    ("state", "expected_conclusion", "expected_action"),
    [
        ("static_only", ConclusionKind.SOURCE_ONLY, NextActionKind.VERIFY_MYSQL),
        (
            "runtime_no_reconcile",
            ConclusionKind.SOURCE_AND_DATABASE_NOT_COMPARED,
            NextActionKind.RECONCILE,
        ),
        ("no_drift", ConclusionKind.NO_DRIFT, NextActionKind.REVIEW_EVIDENCE),
        ("drift", ConclusionKind.DRIFT, NextActionKind.REVIEW_FINDINGS),
        (
            "failed_runtime",
            ConclusionKind.DATABASE_VERIFICATION_FAILED,
            NextActionKind.VERIFY_MYSQL,
        ),
        (
            "stale_reconciliation",
            ConclusionKind.COMPARISON_STALE,
            NextActionKind.RECONCILE,
        ),
    ],
)
def test_report_view_has_one_factual_conclusion_for_each_truth_state(
    tmp_path: Path,
    state: str,
    expected_conclusion: ConclusionKind,
    expected_action: NextActionKind,
) -> None:
    root = _state_repository(tmp_path, state)

    view = ReportViewModelBuilder().build(
        assess_repository(root),
        generated_at=FIXED_TIME,
        language="en",
    )

    assert view.conclusion.kind is expected_conclusion
    assert view.next_action.kind is expected_action
    assert not hasattr(view, "health_score")
    assert view.repository.path == root.resolve()
    assert view.source.flyway_migration_count == 1


def test_failed_runtime_is_an_attention_item_and_not_successful_verification(
    tmp_path: Path,
) -> None:
    root = _state_repository(tmp_path, "failed_runtime")

    view = ReportViewModelBuilder().build(
        assess_repository(root),
        generated_at=FIXED_TIME,
        language="en",
    )

    assert view.runtime.successful is False
    assert view.runtime.artifact_present is True
    assert AttentionKind.DATABASE_VERIFICATION_FAILED in {
        item.kind for item in view.attention_items
    }
    assert view.runtime.error_codes == ("mysql_connection_failed",)


def test_stale_comparison_keeps_old_result_technical_but_never_calls_it_drift(
    tmp_path: Path,
) -> None:
    root = _state_repository(tmp_path, "stale_reconciliation")

    view = ReportViewModelBuilder().build(
        assess_repository(root),
        generated_at=FIXED_TIME,
        language="en",
    )

    assert view.conclusion.kind is ConclusionKind.COMPARISON_STALE
    assert view.conclusion.drift_detected is None
    assert view.reconciliation_result is not None
    assert view.reconciliation_result.summary.drift_detected is False
    assert AttentionKind.COMPARISON_STALE in {
        item.kind for item in view.attention_items
    }


def test_invalid_optional_artifact_is_unknown_not_unperformed(tmp_path: Path) -> None:
    root = tmp_path / "invalid-runtime"
    root.mkdir()
    _write_source(root)
    path = root / ".repoevidence/verification/mysql.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    view = ReportViewModelBuilder().build(
        assess_repository(root),
        generated_at=FIXED_TIME,
        language="en",
    )

    assert view.conclusion.kind is ConclusionKind.UNABLE_TO_DETERMINE
    assert AttentionKind.STATE_UNKNOWN in {item.kind for item in view.attention_items}
    assert view.runtime.artifact_present is True
    assert view.runtime.successful is False


def test_report_view_contains_structured_values_not_rendered_sentences(
    tmp_path: Path,
) -> None:
    root = _state_repository(tmp_path, "drift")

    view = ReportViewModelBuilder().build(
        assess_repository(root),
        generated_at=FIXED_TIME,
        language="zh-CN",
    )

    assert view.language == "zh-CN"
    assert view.conclusion.kind is ConclusionKind.DRIFT
    assert view.conclusion.drift_count == 2
    assert view.next_action.command is None
    assert all(isinstance(item.kind, AttentionKind) for item in view.attention_items)


def _render_state(root: Path, *, language: str = "en") -> str:
    path = ReportGenerator().generate(
        root,
        generated_at=FIXED_TIME,
        language=language,
    )
    return path.read_text(encoding="utf-8")


def test_human_summary_precedes_technical_evidence(tmp_path: Path) -> None:
    root = _state_repository(tmp_path, "drift")

    html = _render_state(root)

    ordered_ids = (
        'id="summary"',
        'id="coverage"',
        'id="attention"',
        'id="project"',
        'id="reconciliation"',
        'id="flyway"',
        'id="ledger"',
        'id="provenance"',
    )
    positions = [html.index(item) for item in ordered_ids]
    assert positions == sorted(positions)


@pytest.mark.parametrize(
    ("state", "expected", "excluded"),
    [
        (
            "static_only",
            "Database verification has not been run",
            "Database metadata verified",
        ),
        (
            "runtime_no_reconcile",
            "Source and database snapshots have not been compared",
            "No Flyway differences were found",
        ),
        (
            "no_drift",
            "No Flyway differences were found in the compared snapshots",
            "Flyway differences need attention",
        ),
        (
            "drift",
            "2 Flyway differences need attention",
            "No Flyway differences were found in the compared snapshots",
        ),
        (
            "failed_runtime",
            "Database verification did not complete",
            "Verified runtime observation",
        ),
        (
            "stale_reconciliation",
            "The existing source/database comparison is out of date",
            "No Flyway differences were found in the compared snapshots",
        ),
    ],
)
def test_html_has_distinct_non_misleading_conclusions_for_all_truth_states(
    tmp_path: Path,
    state: str,
    expected: str,
    excluded: str,
) -> None:
    root = _state_repository(tmp_path, state)

    html = _render_state(root)

    assert expected in html
    assert excluded not in html
    for unsupported_claim in ("80/100", "Healthy", "Risk score", "health score"):
        assert unsupported_claim not in html


def test_report_links_domain_result_to_fact_evidence_and_artifact(
    tmp_path: Path,
) -> None:
    root = _state_repository(tmp_path, "no_drift")

    html = _render_state(root)

    assert 'href="#fact-fact.flyway.migration.' in html
    assert 'id="fact-fact.flyway.migration.' in html
    assert "ev.flyway.migration." in html
    assert "src/main/resources/db/migration/V1__migration.sql" in html
    report_directory = root / ".repoevidence/report"
    artifact_links = {
        "../evidence.json": root / ".repoevidence/evidence.json",
        "../verification/mysql.json": root / ".repoevidence/verification/mysql.json",
        "../reconciliation.json": root / ".repoevidence/reconciliation.json",
    }
    for href, artifact_path in artifact_links.items():
        assert f'href="{href}"' in html
        assert (report_directory / href).resolve() == artifact_path.resolve()
        assert artifact_path.is_file()


def test_stale_recorded_findings_are_disclosed_as_outdated_technical_data(
    tmp_path: Path,
) -> None:
    root = _state_repository(tmp_path, "stale_reconciliation")

    html = _render_state(root)

    assert "Recorded comparison — out of date" in html
    assert "This recorded result is retained for traceability" in html
    assert "DRIFT DETECTED" not in html


def test_report_has_offline_accessible_responsive_foundations(tmp_path: Path) -> None:
    root = _state_repository(tmp_path, "static_only")

    html = _render_state(root)

    assert 'class="skip-link" href="#main"' in html
    assert "@media (prefers-color-scheme: dark)" in html
    assert "@media (prefers-reduced-motion: reduce)" in html
    assert "@media print" in html
    assert ":focus-visible" in html
    assert 'href="http' not in html
    assert 'src="http' not in html


def test_chinese_first_layer_uses_user_task_language(tmp_path: Path) -> None:
    root = _state_repository(tmp_path, "static_only")

    html = _render_state(root, language="zh-CN")

    assert "已完成源码检查" in html
    assert "尚未验证数据库" in html
    assert "当前无法判断源码与数据库是否一致" in html
    assert "下一步" in html
    summary = html[html.index('id="summary"') : html.index('id="project"')]
    assert "Evidence ID" not in summary
    assert "Fact ID" not in summary
    assert ">not run<" not in summary
    assert "artifact_missing" not in summary
    assert "尚未执行" in summary


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("static_only", "Database not verified"),
        (
            "runtime_no_reconcile",
            "Source and database snapshots are available, but they have not been compared",
        ),
        ("no_drift", "No Flyway differences found in the compared snapshots"),
        ("drift", "Source and database differ in the compared Flyway migrations"),
        ("failed_runtime", "database verification failed"),
        ("stale_reconciliation", "comparison because it is out of date"),
    ],
)
def test_report_command_uses_the_same_six_state_truth_model(
    tmp_path: Path,
    state: str,
    expected: str,
) -> None:
    root = _state_repository(tmp_path, state)

    result = CliRunner().invoke(create_app("en"), ["report", str(root)])

    assert result.exit_code == 0, result.stderr
    assert expected in result.stdout
    assert "Coverage" in result.stdout
    assert "Next step" in result.stdout
    assert ".repoevidence/report/index.html" in result.stdout
    assert result.stderr == ""
