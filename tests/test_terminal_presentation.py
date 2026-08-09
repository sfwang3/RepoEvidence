from __future__ import annotations

import re
import shlex
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest

from repoevidence import __version__
from repoevidence.application import (
    ReconciliationApplicationResult,
    VerificationApplicationResult,
    inspect_repository,
    scan_repository,
)
from repoevidence.assessment import (
    ArtifactSnapshot,
    CheckAssessment,
    CheckState,
    ConclusionKind,
    RepositoryAssessment,
    assess_repository,
)
from repoevidence.models import (
    ReconciliationResult,
    ReconciliationSummary,
    VerificationError,
    VerificationMetadata,
    VerificationResult,
)
from repoevidence.presentation.terminal import ErrorView, TerminalPresenter

FIXED_TIME = datetime(2026, 8, 9, tzinfo=timezone.utc)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _presenter(
    language: str = "en",
    *,
    force_terminal: bool = False,
    width: int = 100,
    no_color: bool = False,
) -> tuple[TerminalPresenter, StringIO, StringIO]:
    stdout = StringIO()
    stderr = StringIO()
    presenter = TerminalPresenter(
        language,
        stdout=stdout,
        stderr=stderr,
        force_terminal=force_terminal,
        width=width,
        no_color=no_color,
    )
    return presenter, stdout, stderr


def _static_inspect_result(root: Path, *, language: str = "en"):
    migration = root / "src/main/resources/db/migration/V1__init.sql"
    migration.parent.mkdir(parents=True)
    migration.write_text("CREATE TABLE sample (id BIGINT PRIMARY KEY);\n", encoding="utf-8")
    return inspect_repository(root, language=language)


def _failed_verification(root: Path) -> VerificationApplicationResult:
    result = VerificationResult(
        verifier="mysql",
        repository_root=str(root.resolve()),
        metadata=VerificationMetadata(
            tool_version=__version__,
            started_at=FIXED_TIME,
            finished_at=FIXED_TIME,
            observed_at=FIXED_TIME,
        ),
        errors=[
            VerificationError(
                code="mysql_connection_failed",
                message="Unable to connect to MySQL.",
            )
        ],
    )
    path = root / ".repoevidence/verification/mysql.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return VerificationApplicationResult(result, path)


def _reconciliation_assessment(
    root: Path,
    *,
    drift: bool,
) -> tuple[ReconciliationApplicationResult, RepositoryAssessment]:
    reconciliation = ReconciliationResult(
        repository_root=str(root.resolve()),
        summary=ReconciliationSummary(
            repository_versioned=2,
            runtime_successful_versioned=2 if not drift else 3,
            matched=2,
            runtime_only=1 if drift else 0,
            drift_detected=drift,
        ),
    )
    static_path = root / ".repoevidence/evidence.json"
    runtime_path = root / ".repoevidence/verification/mysql.json"
    reconciliation_path = root / ".repoevidence/reconciliation.json"
    snapshots = {
        "static": ArtifactSnapshot(
            "static_scan",
            ".repoevidence/evidence.json",
            static_path,
            True,
            "a" * 64,
            "0.1",
            None,
        ),
        "runtime": ArtifactSnapshot(
            "mysql_verification",
            ".repoevidence/verification/mysql.json",
            runtime_path,
            True,
            "b" * 64,
            "0.1",
            None,
        ),
        "reconciliation": ArtifactSnapshot(
            "reconciliation",
            ".repoevidence/reconciliation.json",
            reconciliation_path,
            True,
            "c" * 64,
            "0.1",
            reconciliation,
        ),
    }
    assessment = RepositoryAssessment(
        repository_root=root.resolve(),
        static_artifact=snapshots["static"],
        runtime_artifact=snapshots["runtime"],
        reconciliation_artifact=snapshots["reconciliation"],
        source=CheckAssessment(
            "source_inspection", CheckState.CURRENT, static_path, True, FIXED_TIME
        ),
        mysql=CheckAssessment(
            "mysql_verification", CheckState.CURRENT, runtime_path, True, FIXED_TIME
        ),
        reconciliation=CheckAssessment(
            "source_database_comparison",
            CheckState.CURRENT,
            reconciliation_path,
            True,
        ),
        conclusion=ConclusionKind.DRIFT if drift else ConclusionKind.NO_DRIFT,
    )
    return (
        ReconciliationApplicationResult(reconciliation, reconciliation_path),
        assessment,
    )


def test_english_static_inspect_names_result_scope_and_next_action(
    tmp_path: Path,
) -> None:
    result = _static_inspect_result(tmp_path)
    presenter, stdout, stderr = _presenter()

    presenter.inspect_finished(result)

    output = stdout.getvalue()
    assert "Source inspection complete" in output
    assert "1 Flyway migration" in output
    assert "Database not verified" in output
    assert "Source and database agreement cannot be determined" in output
    assert "Next step" in output
    assert f"repoevidence verify mysql {tmp_path.resolve()}" in output
    assert str(result.summary.report_path) in output
    assert stderr.getvalue() == ""


def test_chinese_static_inspect_uses_user_task_language(tmp_path: Path) -> None:
    result = _static_inspect_result(tmp_path, language="zh-CN")
    presenter, stdout, stderr = _presenter("zh-CN")

    presenter.inspect_finished(result)

    output = stdout.getvalue()
    assert "已完成源码检查" in output
    assert "1 个 Flyway 迁移" in output
    assert "尚未验证数据库" in output
    assert "源码与数据库是否一致：暂时无法判断" in output
    assert "下一步" in output
    assert "Evidence" not in output
    assert "Fact" not in output
    assert stderr.getvalue() == ""


def test_recommended_commands_quote_repository_paths_with_spaces(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository with spaces"
    root.mkdir()
    result = _static_inspect_result(root)
    presenter, stdout, _ = _presenter()

    presenter.inspect_finished(result)

    expected = shlex.join(("repoevidence", "verify", "mysql", str(root.resolve())))
    assert expected in stdout.getvalue()


def test_failed_verification_is_diagnostic_not_completion(tmp_path: Path) -> None:
    scan_repository(tmp_path)
    verification = _failed_verification(tmp_path)
    assessment = assess_repository(tmp_path)
    presenter, stdout, stderr = _presenter()

    presenter.verify_finished(verification, assessment)

    assert "Database verification complete" not in stdout.getvalue()
    assert "Database verification did not complete" in stderr.getvalue()
    assert "mysql_connection_failed" in stderr.getvalue()
    assert "No database changes were made" in stderr.getvalue()


def test_scan_with_errors_never_claims_source_inspection_completed(
    tmp_path: Path,
) -> None:
    application_result = scan_repository(tmp_path)
    application_result.scan_result.errors.append("collector could not read pom.xml")
    presenter, stdout, stderr = _presenter()

    presenter.scan_finished(application_result)

    assert "Source inspection complete" not in stdout.getvalue()
    assert "Source inspection did not complete" in stderr.getvalue()
    assert "collector could not read pom.xml" in stderr.getvalue()


def test_inspect_without_flyway_does_not_recommend_impossible_reconciliation(
    tmp_path: Path,
) -> None:
    result = inspect_repository(tmp_path)
    presenter, stdout, stderr = _presenter()

    presenter.inspect_finished(result)

    assert "Review source details in the report below" in stdout.getvalue()
    assert "repoevidence reconcile" not in stdout.getvalue()
    assert stderr.getvalue() == ""


@pytest.mark.parametrize(
    ("drift", "expected", "unexpected"),
    [
        (True, "Source and database differ", "No Flyway differences found"),
        (False, "No Flyway differences found", "Source and database differ"),
    ],
)
def test_reconcile_answers_the_primary_question(
    tmp_path: Path,
    drift: bool,
    expected: str,
    unexpected: str,
) -> None:
    result, assessment = _reconciliation_assessment(tmp_path, drift=drift)
    presenter, stdout, stderr = _presenter()

    presenter.reconcile_finished(result, assessment)

    assert expected in stdout.getvalue()
    assert unexpected not in stdout.getvalue()
    assert "Flyway" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_reconcile_does_not_claim_no_drift_when_runtime_verification_failed(
    tmp_path: Path,
) -> None:
    scan_repository(tmp_path)
    _failed_verification(tmp_path)
    reconciliation = ReconciliationResult(repository_root=str(tmp_path.resolve()))
    path = tmp_path / ".repoevidence/reconciliation.json"
    path.write_text(reconciliation.model_dump_json(indent=2) + "\n", encoding="utf-8")
    assessment = assess_repository(tmp_path)
    presenter, stdout, stderr = _presenter()

    presenter.reconcile_finished(
        ReconciliationApplicationResult(reconciliation, path),
        assessment,
    )

    assert "No Flyway differences found" not in stdout.getvalue()
    assert "Source and database comparison did not complete" in stderr.getvalue()
    assert "repoevidence verify mysql" in stderr.getvalue()


def test_plain_tty_narrow_and_no_color_keep_the_same_semantics(tmp_path: Path) -> None:
    result = _static_inspect_result(tmp_path)
    outputs = []
    configurations = (
        {"force_terminal": True, "width": 100, "no_color": False},
        {"force_terminal": False, "width": 100, "no_color": False},
        {"force_terminal": True, "width": 40, "no_color": True},
    )
    for configuration in configurations:
        presenter, stdout, _ = _presenter(**configuration)
        presenter.inspect_finished(result)
        outputs.append(stdout.getvalue())

    for output in outputs:
        plain = ANSI.sub("", output)
        assert "Source inspection complete" in plain
        assert "Database not verified" in plain
        assert "Next step" in plain
    assert ANSI.search(outputs[0]) is not None
    assert ANSI.search(outputs[1]) is None
    assert ANSI.search(outputs[2]) is None


def test_error_view_writes_only_to_stderr() -> None:
    presenter, stdout, stderr = _presenter("en")
    error = ErrorView(
        title_key="error.repository_path_missing.title",
        reason_key="error.repository_path_missing.reason",
        recovery_key="error.repository_path_missing.recovery",
        technical_code="repository_path_missing",
        path=Path("/missing/repository"),
        command="repoevidence inspect /existing/repository",
    )

    presenter.error(error)

    assert stdout.getvalue() == ""
    assert "Repository path not found" in stderr.getvalue()
    assert "/missing/repository" in stderr.getvalue()
    assert "repoevidence inspect /existing/repository" in stderr.getvalue()
    assert "repository_path_missing" in stderr.getvalue()
