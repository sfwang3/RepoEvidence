import json
from pathlib import Path

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


def test_scan_help_is_flat_and_names_repository_argument() -> None:
    result = CliRunner().invoke(app, ["scan", "--help"])

    assert result.exit_code == 0
    assert "REPO_PATH" in result.output
    assert "COMMAND [ARGS]" not in result.output
