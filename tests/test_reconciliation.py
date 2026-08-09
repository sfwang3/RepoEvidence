import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import pytest
from typer.testing import CliRunner

from repoevidence import __version__
from repoevidence.cli import app
from repoevidence.reconciliation import Reconciler

ROOT = Path("/repo/charge-safe").resolve()


def _source_id(source_file: str) -> str:
    encoded = quote(source_file, safe="")
    return f"fact.flyway.migration.{encoded}"


def _source_evidence_id(source_file: str) -> str:
    encoded = quote(source_file, safe="")
    return f"ev.flyway.migration.{encoded}"


def _runtime_id(rank: int) -> str:
    return f"fact.mysql.flyway.history.{rank}"


def _runtime_evidence_id(rank: int) -> str:
    return f"ev.mysql.flyway.history.{rank}"


def static_payload(
    root: Path,
    migrations: list[tuple[str, str]],
    *,
    schema_version: str = "0.1",
) -> dict[str, object]:
    evidence = []
    facts = []
    migration_set = "src/main/resources/db/migration"
    for version, filename in migrations:
        source_file = f"{migration_set}/{filename}"
        evidence_id = _source_evidence_id(source_file)
        evidence.append(
            {
                "id": evidence_id,
                "kind": "flyway_migration_file",
                "source": source_file,
                "value": {
                    "source_file": source_file,
                    "migration_set": migration_set,
                    "filename": filename,
                    "file_sha256": f"sha-{version}-{filename}",
                },
            }
        )
        facts.append(
            {
                "id": _source_id(source_file),
                "name": "Flyway migration declaration",
                "value": {
                    "migration_set": migration_set,
                    "type": "versioned",
                    "version": version,
                    "description": filename.removeprefix(f"V{version}__").removesuffix(".sql"),
                    "source_file": source_file,
                    "file_sha256": f"sha-{version}-{filename}",
                },
                "status": "declared",
                "evidence_ids": [evidence_id],
            }
        )
    return {
        "schema_version": schema_version,
        "repository_root": str(root),
        "metadata": {
            "tool_version": __version__,
            "started_at": "2026-08-08T00:00:00Z",
            "finished_at": "2026-08-08T00:00:01Z",
        },
        "collectors": ["flyway_migration"],
        "evidence": evidence,
        "facts": facts,
        "conflicts": [],
        "warnings": [],
        "errors": [],
    }


def runtime_payload(
    root: Path,
    rows: list[dict[str, object]],
    *,
    schema_version: str = "0.1",
) -> dict[str, object]:
    evidence = []
    facts = []
    for rank, row in enumerate(rows, start=1):
        evidence_id = _runtime_evidence_id(rank)
        fact_id = _runtime_id(rank)
        evidence.append(
            {
                "id": evidence_id,
                "kind": "mysql.flyway_history",
                "source": "mysql.query.flyway_history",
                "value": {"result": row},
            }
        )
        facts.append(
            {
                "id": fact_id,
                "name": "Flyway runtime migration history",
                "value": row,
                "status": "verified",
                "evidence_ids": [evidence_id],
            }
        )
    return {
        "schema_version": schema_version,
        "verifier": "mysql",
        "repository_root": str(root),
        "metadata": {
            "tool_version": __version__,
            "started_at": "2026-08-08T00:00:00Z",
            "finished_at": "2026-08-08T00:00:01Z",
            "observed_at": "2026-08-08T00:00:00Z",
        },
        "evidence": evidence,
        "facts": facts,
        "conflicts": [],
        "warnings": [],
        "errors": [],
    }


def migration_row(version: str, script: str, *, success: bool = True) -> dict[str, object]:
    return {
        "installed_rank": 1,
        "version": version,
        "description": script.removeprefix("V").split("__", 1)[-1].removesuffix(".sql"),
        "type": "SQL",
        "script": script,
        "checksum": 123,
        "success": success,
        "installed_on": "2026-08-08T00:00:00Z",
    }


def baseline_row() -> dict[str, object]:
    return {
        "installed_rank": 1,
        "version": "0",
        "description": "<< Flyway Baseline >>",
        "type": "BASELINE",
        "script": "<< Flyway Baseline >>",
        "checksum": None,
        "success": True,
        "installed_on": "2026-08-08T00:00:00Z",
    }


def write_artifacts(
    repo_path: Path,
    static: dict[str, object],
    runtime: dict[str, object],
) -> tuple[Path, Path, bytes, bytes]:
    static_path = repo_path / ".repoevidence" / "evidence.json"
    runtime_path = repo_path / ".repoevidence" / "verification" / "mysql.json"
    static_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    static_bytes = (json.dumps(static, indent=2) + "\n").encode()
    runtime_bytes = (json.dumps(runtime, indent=2) + "\n").encode()
    static_path.write_bytes(static_bytes)
    runtime_path.write_bytes(runtime_bytes)
    return static_path, runtime_path, static_bytes, runtime_bytes


def reconcile_with(
    tmp_path: Path,
    source: list[tuple[str, str]],
    runtime: list[dict[str, object]],
) -> object:
    write_artifacts(
        tmp_path,
        static_payload(tmp_path.resolve(), source),
        runtime_payload(tmp_path.resolve(), runtime),
    )
    return Reconciler().reconcile(tmp_path)


def test_exact_versions_are_matched_with_cross_artifact_references(tmp_path: Path) -> None:
    result = reconcile_with(
        tmp_path,
        [("1", "V1__one.sql"), ("2", "V2__two.sql"), ("3", "V3__three.sql")],
        [
            migration_row("1", "V1__one.sql"),
            migration_row("2", "V2__two.sql"),
            migration_row("3", "V3__three.sql"),
        ],
    )

    assert result.errors == []
    assert result.summary.matched == 3
    assert result.summary.drift_detected is False
    assert [finding.kind for finding in result.findings] == ["matched"] * 3
    assert all(
        {reference.artifact for reference in finding.references}
        == {"static_scan", "mysql_verification"}
        for finding in result.findings
    )


def test_runtime_only_and_source_only_are_distinct_findings(tmp_path: Path) -> None:
    result = reconcile_with(
        tmp_path,
        [("1", "V1__one.sql"), ("2", "V2__two.sql")],
        [migration_row("1", "V1__one.sql"), migration_row("3", "V3__three.sql")],
    )

    assert [(finding.kind, finding.version) for finding in result.findings] == [
        ("matched", "1"),
        ("source_only", "2"),
        ("runtime_only", "3"),
    ]
    assert result.summary.source_only == 1
    assert result.summary.runtime_only == 1
    assert result.summary.drift_detected is True


def test_baseline_zero_is_summary_only_and_not_runtime_only(tmp_path: Path) -> None:
    result = reconcile_with(
        tmp_path,
        [("1", "V1__one.sql")],
        [baseline_row(), migration_row("1", "V1__one.sql")],
    )

    assert result.summary.runtime_baseline_version == "0"
    assert result.summary.runtime_successful_versioned == 1
    assert [finding.kind for finding in result.findings] == ["matched"]
    assert not any(finding.version == "0" for finding in result.findings)


def test_chargesafe_drift_has_v7_v8_v9_runtime_only(tmp_path: Path) -> None:
    source = [(str(version), f"V{version}__migration.sql") for version in range(1, 7)]
    runtime = [baseline_row()] + [
        migration_row(str(version), f"V{version}__migration.sql")
        for version in range(1, 10)
    ]
    result = reconcile_with(tmp_path, source, runtime)

    assert result.summary.model_dump() == {
        "repository_versioned": 6,
        "runtime_successful_versioned": 9,
        "matched": 6,
        "runtime_only": 3,
        "source_only": 0,
        "version_mismatch": 0,
        "runtime_failed": 0,
        "ambiguous": 0,
        "runtime_baseline_version": "0",
        "repository_max_version": "6",
        "runtime_max_successful_version": "9",
        "drift_detected": True,
    }
    assert [(finding.kind, finding.version) for finding in result.findings[-3:]] == [
        ("runtime_only", "7"),
        ("runtime_only", "8"),
        ("runtime_only", "9"),
    ]


def test_same_version_different_script_is_version_mismatch(tmp_path: Path) -> None:
    result = reconcile_with(
        tmp_path,
        [("1", "V1__source.sql")],
        [migration_row("1", "V1__runtime.sql")],
    )

    assert result.findings[0].kind == "version_mismatch"
    assert result.summary.version_mismatch == 1
    assert "file_sha256" not in result.findings[0].details
    assert "checksum" not in result.findings[0].details


def test_failed_runtime_row_is_runtime_failed(tmp_path: Path) -> None:
    result = reconcile_with(
        tmp_path,
        [("1", "V1__one.sql")],
        [migration_row("1", "V1__one.sql", success=False)],
    )

    assert result.findings[0].kind == "runtime_failed"
    assert result.summary.runtime_failed == 1
    assert result.summary.matched == 0


def test_duplicate_version_is_ambiguous_without_using_conflict(tmp_path: Path) -> None:
    result = reconcile_with(
        tmp_path,
        [("1.0", "V1.0__one.sql"), ("1_0", "V1_0__duplicate.sql")],
        [migration_row("1.0", "V1.0__one.sql")],
    )

    assert result.findings[0].kind == "ambiguous"
    assert result.summary.ambiguous == 1
    assert result.findings[0].id == "recon.ambiguous.version.1.0"
    assert not hasattr(result, "conflicts")


def test_versions_are_ordered_by_numeric_segments_and_normalized(tmp_path: Path) -> None:
    result = reconcile_with(
        tmp_path,
        [("1", "V1__one.sql"), ("2", "V2__two.sql"), ("10", "V10__ten.sql")],
        [
            migration_row("1", "V1__one.sql"),
            migration_row("2", "V2__two.sql"),
            migration_row("10", "V10__ten.sql"),
        ],
    )
    assert [finding.version for finding in result.findings] == ["1", "2", "10"]

    normalized = reconcile_with(
        tmp_path,
        [("1.0_2", "V1.0_2__one.sql")],
        [migration_row("1_0.2", "V1.0_2__one.sql")],
    )
    assert normalized.summary.matched == 1


def test_missing_input_returns_structured_error(tmp_path: Path) -> None:
    result = Reconciler().reconcile(tmp_path)

    assert result.errors[0].code == "missing_static_scan"
    assert result.findings == []


def test_repository_root_mismatch_stops_reconciliation(tmp_path: Path) -> None:
    static = static_payload(tmp_path.resolve(), [("1", "V1__one.sql")])
    runtime = runtime_payload(ROOT, [migration_row("1", "V1__one.sql")])
    write_artifacts(tmp_path, static, runtime)

    result = Reconciler().reconcile(tmp_path)

    assert result.errors[0].code == "repository_root_mismatch"
    assert result.findings == []


def test_unsupported_schema_returns_structured_error(tmp_path: Path) -> None:
    static = static_payload(tmp_path.resolve(), [], schema_version="9.9")
    runtime = runtime_payload(tmp_path.resolve(), [])
    write_artifacts(tmp_path, static, runtime)

    result = Reconciler().reconcile(tmp_path)

    assert result.errors[0].code == "unsupported_static_schema"
    assert result.findings == []


def test_reconcile_is_deterministic_and_records_input_hashes(tmp_path: Path) -> None:
    static_path, runtime_path, static_bytes, runtime_bytes = write_artifacts(
        tmp_path,
        static_payload(tmp_path.resolve(), [("1", "V1__one.sql")]),
        runtime_payload(tmp_path.resolve(), [migration_row("1", "V1__one.sql")]),
    )
    first = Reconciler().reconcile(tmp_path)
    second = Reconciler().reconcile(tmp_path)

    assert first.model_dump_json() == second.model_dump_json()
    assert [(item.relative_path, item.sha256) for item in first.inputs] == [
        (".repoevidence/evidence.json", hashlib.sha256(static_bytes).hexdigest()),
        (".repoevidence/verification/mysql.json", hashlib.sha256(runtime_bytes).hexdigest()),
    ]
    assert static_path.read_bytes() == static_bytes
    assert runtime_path.read_bytes() == runtime_bytes


def test_reconcile_does_not_construct_mysql_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_artifacts(
        tmp_path,
        static_payload(tmp_path.resolve(), [("1", "V1__one.sql")]),
        runtime_payload(tmp_path.resolve(), [migration_row("1", "V1__one.sql")]),
    )
    called = False

    def fail_connection(settings: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("reconcile must not construct a MySQL connection")

    from repoevidence.verification import mysql

    monkeypatch.setattr(mysql, "default_connection_factory", fail_connection)
    result = Reconciler().reconcile(tmp_path)

    assert result.errors == []
    assert called is False


def test_finding_references_are_present_in_their_source_artifacts(tmp_path: Path) -> None:
    static = static_payload(tmp_path.resolve(), [("1", "V1__one.sql")])
    runtime = runtime_payload(tmp_path.resolve(), [migration_row("2", "V2__two.sql")])
    write_artifacts(tmp_path, static, runtime)
    result = Reconciler().reconcile(tmp_path)

    ids_by_artifact = {
        "static_scan": {
            "fact": {item["id"] for item in static["facts"]},
            "evidence": {item["id"] for item in static["evidence"]},
        },
        "mysql_verification": {
            "fact": {item["id"] for item in runtime["facts"]},
            "evidence": {item["id"] for item in runtime["evidence"]},
        },
    }
    for finding in result.findings:
        for reference in finding.references:
            assert reference.id in ids_by_artifact[reference.artifact][reference.reference_type]


def test_reconcile_cli_writes_reconciliation_artifact(tmp_path: Path) -> None:
    write_artifacts(
        tmp_path,
        static_payload(tmp_path.resolve(), [("1", "V1__one.sql")]),
        runtime_payload(tmp_path.resolve(), [migration_row("1", "V1__one.sql")]),
    )

    result = CliRunner().invoke(app, ["reconcile", str(tmp_path)])

    assert result.exit_code == 0, result.output
    output_path = tmp_path / ".repoevidence" / "reconciliation.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["matched"] == 1
