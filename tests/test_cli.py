import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from repoevidence.cli import app


def test_scan_command_writes_evidence_inside_scanned_repository(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["scan", str(tmp_path)])

    assert result.exit_code == 0, result.output
    output_path = tmp_path / ".repoevidence" / "evidence.json"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["repository_root"] == str(tmp_path.resolve())


def test_root_help_lists_scan_command() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "scan" in result.output


def test_root_help_lists_inspect_command() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "inspect" in result.output


def test_inspect_command_writes_static_evidence_and_existing_report(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["inspect", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".repoevidence/evidence.json").is_file()
    assert (tmp_path / ".repoevidence/report/index.html").is_file()
    assert "Source inspection complete" in result.stdout
    assert "Database not verified" in result.stdout
    assert ".repoevidence/report/index.html" in result.stdout


def test_scan_report_and_inspect_commands_delegate_to_application_services(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, Path]] = []
    evidence_path = tmp_path / "evidence.json"
    report_path = tmp_path / "report.html"

    def fake_scan(repo_path: Path) -> SimpleNamespace:
        calls.append(("scan", repo_path))
        return SimpleNamespace(
            evidence_path=evidence_path,
            scan_result=SimpleNamespace(warnings=[], errors=[]),
        )

    def fake_report(repo_path: Path, *, language: str) -> SimpleNamespace:
        calls.append((f"report:{language}", repo_path))
        return SimpleNamespace(report_path=report_path)

    def fake_inspect(repo_path: Path, *, language: str) -> SimpleNamespace:
        calls.append((f"inspect:{language}", repo_path))
        return SimpleNamespace(
            summary=SimpleNamespace(report_path=report_path, warnings=(), errors=())
        )

    class SilentPresenter:
        def __init__(self, language: str) -> None:
            self.language = language

        def scan_started(self, root: Path) -> None:
            pass

        def scan_finished(self, result: object) -> None:
            pass

        def report_started(self, root: Path) -> None:
            pass

        def report_finished(self, result: object) -> None:
            pass

        def inspect_started(self, root: Path) -> None:
            pass

        def inspect_finished(self, result: object) -> None:
            pass

    monkeypatch.setattr("repoevidence.cli.scan_repository", fake_scan)
    monkeypatch.setattr("repoevidence.cli.generate_report", fake_report)
    monkeypatch.setattr("repoevidence.cli.inspect_repository", fake_inspect)
    monkeypatch.setattr("repoevidence.cli.TerminalPresenter", SilentPresenter)

    assert CliRunner().invoke(app, ["scan", str(tmp_path)]).exit_code == 0
    assert CliRunner().invoke(app, ["report", str(tmp_path)]).exit_code == 0
    assert CliRunner().invoke(app, ["inspect", str(tmp_path)]).exit_code == 0

    root = tmp_path.resolve()
    assert calls == [
        ("scan", root),
        ("report:en", root),
        ("inspect:en", root),
    ]


def test_scan_help_is_flat_and_names_repository_argument() -> None:
    result = CliRunner().invoke(app, ["scan", "--help"])

    assert result.exit_code == 0
    assert "REPO_PATH" in result.output
    assert "COMMAND [ARGS]" not in result.output
