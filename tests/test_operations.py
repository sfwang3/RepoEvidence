from __future__ import annotations

import threading
from pathlib import Path

import pytest

from repoevidence.operations import (
    OperationBusyError,
    OperationEvent,
    OperationRunner,
    WorkspaceOperationService,
)


def test_operation_event_drops_secrets_and_unsafe_values() -> None:
    event = OperationEvent(
        operation_id="op-1",
        operation_kind="runtime.verify_mysql",
        phase_id="preflight",
        event_kind="started",
        monotonic_timestamp=1.0,
        safe_metadata={
            "path": "/tmp/project",
            "password": "do-not-leak",
            "dsn": "mysql://secret",
            "exception": RuntimeError("do-not-leak"),
            "count": 2,
        },
    )

    assert event.safe_metadata == {"path": "/tmp/project", "count": 2}
    assert "do-not-leak" not in repr(event)


def test_operation_runner_is_single_flight_and_reports_safe_failure() -> None:
    runner = OperationRunner()
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def long_operation() -> str:
        entered.set()
        release.wait(timeout=2)
        return "done"

    def run() -> None:
        try:
            runner.execute("source.inspect", long_operation)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(timeout=2)
    with pytest.raises(OperationBusyError):
        runner.execute("report.generate", lambda: "should not run")
    release.set()
    thread.join(timeout=2)
    assert errors == []


def test_operation_runner_keeps_operation_result_when_listener_fails() -> None:
    runner = OperationRunner()

    def broken_listener(event: OperationEvent) -> None:
        del event
        raise RuntimeError("presentation failure")

    assert runner.execute(
        "source.inspect",
        lambda: "completed",
        listener=broken_listener,
    ) == "completed"


def test_operation_event_drops_metadata_outside_safe_key_allowlist() -> None:
    event = OperationEvent(
        operation_id="op-allowlist",
        operation_kind="source.inspect",
        phase_id="execute",
        event_kind="started",
        monotonic_timestamp=1.0,
        safe_metadata={
            "path": "/tmp/project",
            "count": 2,
            "database": "business-db",
            "value": "unreviewed",
        },
    )

    assert event.safe_metadata == {"path": "/tmp/project", "count": 2}


def test_workspace_operation_service_dispatches_existing_application_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Path, str]] = []

    def fake_inspect(root: str | Path, *, language: str) -> str:
        calls.append(("inspect", Path(root), language))
        return "inspect-result"

    def fake_report(root: str | Path, *, language: str) -> str:
        calls.append(("report", Path(root), language))
        return "report-result"

    def fake_open(root: str | Path) -> str:
        calls.append(("open", Path(root), ""))
        return "open-result"

    def fake_verify(root: str | Path):
        calls.append(("verify", Path(root), ""))
        return "verify-result"

    def fake_reconcile(root: str | Path):
        calls.append(("reconcile", Path(root), ""))
        return "reconcile-result"

    monkeypatch.setattr("repoevidence.operations.inspect_repository", fake_inspect)
    monkeypatch.setattr("repoevidence.operations.generate_report", fake_report)
    monkeypatch.setattr("repoevidence.operations.open_report", fake_open)
    monkeypatch.setattr("repoevidence.operations.verify_mysql_repository", fake_verify)
    monkeypatch.setattr("repoevidence.operations.reconcile_repository", fake_reconcile)
    service = WorkspaceOperationService(str(tmp_path), language="zh-CN")

    assert service.execute("source.inspect").value == "inspect-result"
    assert service.execute("report.refresh").value == "report-result"
    assert service.execute("report.open").value == "open-result"
    assert service.execute("runtime.verify_mysql").value == "verify-result"
    assert service.execute("comparison.reconcile").value == "reconcile-result"
    assert calls == [
        ("inspect", tmp_path, "zh-CN"),
        ("report", tmp_path, "zh-CN"),
        ("open", tmp_path, ""),
        ("verify", tmp_path, ""),
        ("reconcile", tmp_path, ""),
    ]
