# ruff: noqa: E501

import hashlib
import json
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoevidence.cli import app
from repoevidence.reporting import ReportGenerationError, ReportGenerator


def _fact(
    facts: list[dict[str, object]],
    evidence: list[dict[str, object]],
    *,
    fact_id: str,
    name: str,
    value: object,
    status: str,
    evidence_id: str,
    evidence_value: object,
    kind: str = "fixture",
    source: str = "fixture.json",
) -> None:
    evidence.append(
        {
            "id": evidence_id,
            "kind": kind,
            "source": source,
            "value": evidence_value,
        }
    )
    facts.append(
        {
            "id": fact_id,
            "name": name,
            "value": value,
            "status": status,
            "evidence_ids": [evidence_id],
        }
    )


def static_payload(root: Path, *, malicious: bool = False) -> dict[str, object]:
    facts: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    root_text = "<script>alert(1)</script>" if malicious else str(root)
    branch = "branch<&\"" if malicious else "main"
    _fact(
        facts,
        evidence,
        fact_id="fact.repository.root",
        name="Repository root",
        value=root_text,
        status="verified",
        evidence_id="ev.repository.root",
        evidence_value=root_text,
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.git.head_commit",
        name="HEAD commit",
        value="abc123",
        status="verified",
        evidence_id="ev.git.head_commit",
        evidence_value={"stdout": "abc123\n"},
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.git.current_branch",
        name="Current branch",
        value=branch,
        status="verified",
        evidence_id="ev.git.current_branch",
        evidence_value={"stdout": f"{branch}\n"},
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.spring.endpoint.fixture%2FApi.java:ApiController:10:list:GET:%2Fapi%2Fitems",
        name="GET /api/items",
        value={
            "method": "GET",
            "path": "/api/items<script>alert(1)</script>" if malicious else "/api/items",
            "controller": "ApiController",
            "handler": "list",
        },
        status="inferred",
        evidence_id="ev.spring.endpoint",
        evidence_value={
            "source_file": "src/Api.java",
            "class_name": "ApiController",
            "method_name": "list",
            "annotation_type": "GetMapping",
            "annotation_text": '@GetMapping("/api/items")',
            "start_line": 10,
            "end_line": 10,
            "arguments": {"value": '"/api/items"'},
        },
        kind="spring_annotation",
        source="src/Api.java",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.maven.project.fixture%2Fpom.xml.group_id",
        name="Maven project declared groupId",
        value={
            "pom": "pom.xml",
            "module": "pom.xml",
            "declared_field": "groupId",
            "declared_value": "com.example",
            "resolved_value": "com.example",
        },
        status="declared",
        evidence_id="ev.maven.project",
        evidence_value={"source_file": "pom.xml", "xml_path": "/project/groupId"},
        kind="maven_declaration",
        source="pom.xml",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.maven.java_baseline.fixture%2Fpom.xml.java.version",
        name="Java baseline declaration java.version",
        value={
            "pom": "pom.xml",
            "source": "java.version",
            "declared_value": "21",
            "resolved_value": "21",
        },
        status="declared",
        evidence_id="ev.maven.java",
        evidence_value={"source_file": "pom.xml", "xml_path": "/project/properties/java.version"},
        kind="maven_declaration",
        source="pom.xml",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.maven.parent.fixture%2Fpom.xml.declaration",
        name="Maven parent declaration",
        value={
            "pom": "pom.xml",
            "declared_group_id": "org.springframework.boot",
            "declared_artifact_id": "spring-boot-starter-parent",
            "declared_version": "3.3.0",
            "resolved_group_id": "org.springframework.boot",
            "resolved_artifact_id": "spring-boot-starter-parent",
            "resolved_version": "3.3.0",
        },
        status="declared",
        evidence_id="ev.maven.parent",
        evidence_value={"source_file": "pom.xml", "xml_path": "/project/parent"},
        kind="maven_declaration",
        source="pom.xml",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.maven.dependency.fixture%2Fpom.xml.dependencies%3Aorg.example%3Acore",
        name="Maven dependencies dependency declaration",
        value={
            "module": "pom.xml",
            "group_id": "org.example",
            "artifact_id": "core",
            "declared_version": "1.2.0",
            "resolved_version": "1.2.0",
            "scope": None,
            "optional": False,
            "location": "dependencies",
        },
        status="declared",
        evidence_id="ev.maven.dependency",
        evidence_value={"source_file": "pom.xml", "xml_path": "/project/dependencies/dependency"},
        kind="maven_declaration",
        source="pom.xml",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.maven.dependencyManagement.fixture%2Fpom.xml.dependencies%3Aorg.example%3Abom",
        name="Maven dependencyManagement dependency declaration",
        value={
            "module": "pom.xml",
            "group_id": "org.example",
            "artifact_id": "bom",
            "declared_version": "2.0.0",
            "resolved_version": "2.0.0",
            "scope": "import",
            "optional": False,
            "location": "dependencyManagement",
        },
        status="declared",
        evidence_id="ev.maven.management",
        evidence_value={"source_file": "pom.xml", "xml_path": "/project/dependencyManagement"},
        kind="maven_declaration",
        source="pom.xml",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.maven.plugin.fixture%2Fpom.xml.org.example%3Amaven-plugin",
        name="Maven build plugin declaration",
        value={
            "module": "pom.xml",
            "group_id": "org.example",
            "artifact_id": "maven-plugin",
            "declared_version": "4.0.0",
            "resolved_version": "4.0.0",
        },
        status="declared",
        evidence_id="ev.maven.plugin",
        evidence_value={"source_file": "pom.xml", "xml_path": "/project/build/plugins/plugin"},
        kind="maven_declaration",
        source="pom.xml",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.maven.module.fixture%2Fpom.xml.backend%2Fpom.xml",
        name="Maven module declaration",
        value={"parent": "example", "module": "backend", "pom": "backend/pom.xml", "exists": True},
        status="declared",
        evidence_id="ev.maven.module",
        evidence_value={"source_file": "pom.xml", "xml_path": "/project/modules/module"},
        kind="maven_declaration",
        source="pom.xml",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.flyway.migration.fixture%2Fsrc%2Fmain%2Fresources%2Fdb%2Fmigration%2FV1__init.sql",
        name="Flyway migration declaration",
        value={
            "migration_set": "src/main/resources/db/migration",
            "type": "versioned",
            "version": "1",
            "description": "init<script>alert(1)</script>" if malicious else "init",
            "source_file": "src/main/resources/db/migration/V1__init.sql",
            "file_sha256": "a" * 64,
        },
        status="declared",
        evidence_id="ev.flyway.migration",
        evidence_value={"source_file": "src/main/resources/db/migration/V1__init.sql"},
        kind="flyway_migration_file",
        source="src/main/resources/db/migration/V1__init.sql",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.flyway.migration_set.fixture",
        name="Flyway migration set summary",
        value={
            "migration_set": "src/main/resources/db/migration",
            "versioned_count": 1,
            "repeatable_count": 1,
            "ordered_versions": ["1"],
        },
        status="inferred",
        evidence_id="ev.flyway.set",
        evidence_value={"migration_set": "src/main/resources/db/migration"},
        kind="flyway_migration_file",
        source="src/main/resources/db/migration",
    )
    return {
        "schema_version": "0.1",
        "repository_root": str(root),
        "metadata": {
            "tool_version": "0.1.0",
            "started_at": "2026-08-09T00:00:00Z",
            "finished_at": "2026-08-09T00:00:01Z",
        },
        "collectors": ["repository_metadata", "spring_api", "maven_project", "flyway_migration"],
        "evidence": evidence,
        "facts": facts,
        "conflicts": [],
        "warnings": [],
        "errors": [],
    }


def runtime_payload(root: Path, *, include_secret: bool = False) -> dict[str, object]:
    facts: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    _fact(
        facts,
        evidence,
        fact_id="fact.mysql.server.version",
        name="MySQL server version",
        value={"server_version": "9.7.0"},
        status="verified",
        evidence_id="ev.mysql.server.version",
        evidence_value={"result": {"server_version": "9.7.0"}},
        kind="mysql.server",
        source="mysql.query.server_version",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.mysql.database.name",
        name="Selected MySQL database",
        value={"database_name": "charge_safe_dev"},
        status="verified",
        evidence_id="ev.mysql.database.name",
        evidence_value={"result": {"database_name": "charge_safe_dev"}},
        kind="mysql.database",
        source="mysql.query.database_name",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.mysql.table.charge_safe_dev.users",
        name="MySQL base table",
        value={"schema": "charge_safe_dev", "table_name": "users", "engine": "InnoDB"},
        status="verified",
        evidence_id="ev.mysql.table.users",
        evidence_value={"result": {"table_name": "users"}},
        kind="mysql.table",
        source="mysql.query.tables",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.mysql.column.charge_safe_dev.users.id",
        name="MySQL column",
        value={
            "schema": "charge_safe_dev",
            "table_name": "users",
            "column_name": "id",
            "ordinal_position": 1,
            "data_type": "bigint",
            "column_type": "bigint",
            "nullable": False,
            "default": None,
            "extra": "auto_increment",
        },
        status="verified",
        evidence_id="ev.mysql.column.users.id",
        evidence_value={"result": {"column_name": "id"}},
        kind="mysql.column",
        source="mysql.query.columns",
    )
    for fact_id, name, value, evidence_id in [
        (
            "fact.mysql.constraint.charge_safe_dev.users.PRIMARY",
            "MySQL constraint",
            {
                "schema": "charge_safe_dev",
                "table_name": "users",
                "constraint_name": "PRIMARY",
                "constraint_type": "PRIMARY KEY",
                "columns": [{"column_name": "id", "ordinal_position": 1}],
            },
            "ev.mysql.constraint.users.primary",
        ),
        (
            "fact.mysql.constraint.charge_safe_dev.users.uq_email",
            "MySQL constraint",
            {
                "schema": "charge_safe_dev",
                "table_name": "users",
                "constraint_name": "uq_email",
                "constraint_type": "UNIQUE",
                "columns": [{"column_name": "email", "ordinal_position": 1}],
            },
            "ev.mysql.constraint.users.unique",
        ),
        (
            "fact.mysql.constraint.charge_safe_dev.users.fk_tenant",
            "MySQL constraint",
            {
                "schema": "charge_safe_dev",
                "table_name": "users",
                "constraint_name": "fk_tenant",
                "constraint_type": "FOREIGN KEY",
                "columns": [{"column_name": "tenant_id", "ordinal_position": 1}],
            },
            "ev.mysql.constraint.users.foreign",
        ),
    ]:
        _fact(
            facts,
            evidence,
            fact_id=fact_id,
            name=name,
            value=value,
            status="verified",
            evidence_id=evidence_id,
            evidence_value={"result": value},
            kind="mysql.constraint",
            source="mysql.query.constraints",
        )
    _fact(
        facts,
        evidence,
        fact_id="fact.mysql.index.charge_safe_dev.users.PRIMARY",
        name="MySQL index",
        value={
            "schema": "charge_safe_dev",
            "table_name": "users",
            "index_name": "PRIMARY",
            "unique": True,
            "index_kind": "primary",
            "columns": [{"column_name": "id", "sequence": 1}],
        },
        status="verified",
        evidence_id="ev.mysql.index.users.primary",
        evidence_value={"result": {"index_name": "PRIMARY"}},
        kind="mysql.index",
        source="mysql.query.indexes",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.mysql.flyway.history.1",
        name="Flyway runtime migration history",
        value={
            "installed_rank": 1,
            "version": "0",
            "description": "<< Flyway Baseline >>",
            "type": "BASELINE",
            "script": "<< Flyway Baseline >>",
            "checksum": None,
            "success": True,
            "installed_on": "2026-08-09T00:00:00Z",
        },
        status="verified",
        evidence_id="ev.mysql.flyway.history.1",
        evidence_value={"result": {"version": "0"}},
        kind="mysql.flyway_history",
        source="mysql.query.flyway_history",
    )
    _fact(
        facts,
        evidence,
        fact_id="fact.mysql.flyway.history.2",
        name="Flyway runtime migration history",
        value={
            "installed_rank": 2,
            "version": "1",
            "description": "init",
            "type": "SQL",
            "script": "V1__init.sql",
            "checksum": 123,
            "success": True,
            "installed_on": "2026-08-09T00:00:00Z",
        },
        status="verified",
        evidence_id="ev.mysql.flyway.history.2",
        evidence_value={"result": {"version": "1"}},
        kind="mysql.flyway_history",
        source="mysql.query.flyway_history",
    )
    if include_secret:
        _fact(
            facts,
            evidence,
            fact_id="fact.mysql.secret.fixture",
            name="MySQL secret fixture",
            value={"password": "dont-render-me"},
            status="verified",
            evidence_id="ev.mysql.secret.fixture",
            evidence_value={"password": "dont-render-me", "nested": {"token": "also-secret"}},
            kind="mysql.fixture",
            source="mysql://password=dont-render-me",
        )
    return {
        "schema_version": "0.1",
        "verifier": "mysql",
        "repository_root": str(root),
        "metadata": {
            "tool_version": "0.1.0",
            "started_at": "2026-08-09T00:01:00Z",
            "finished_at": "2026-08-09T00:01:01Z",
            "observed_at": "2026-08-09T00:01:00Z",
        },
        "evidence": evidence,
        "facts": facts,
        "conflicts": [],
        "warnings": [],
        "errors": [],
    }


def reconciliation_payload(root: Path) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "repository_root": str(root),
        "inputs": [
            {"artifact": "static_scan", "relative_path": ".repoevidence/evidence.json", "sha256": "a" * 64},
            {"artifact": "mysql_verification", "relative_path": ".repoevidence/verification/mysql.json", "sha256": "b" * 64},
        ],
        "summary": {
            "repository_versioned": 1,
            "runtime_successful_versioned": 3,
            "matched": 1,
            "runtime_only": 2,
            "source_only": 0,
            "version_mismatch": 0,
            "runtime_failed": 0,
            "ambiguous": 0,
            "runtime_baseline_version": "0",
            "repository_max_version": "1",
            "runtime_max_successful_version": "3",
            "drift_detected": True,
        },
        "findings": [
            {
                "id": "recon.matched.version.1",
                "kind": "matched",
                "version": "1",
                "version_key": [1],
                "migration_set": "src/main/resources/db/migration",
                "message": "Flyway migration 1 matches source and runtime.",
                "references": [
                    {"artifact": "static_scan", "reference_type": "fact", "id": "fact.flyway.migration.fixture%2Fsrc%2Fmain%2Fresources%2Fdb%2Fmigration%2FV1__init.sql"},
                    {"artifact": "static_scan", "reference_type": "evidence", "id": "ev.flyway.migration"},
                    {"artifact": "mysql_verification", "reference_type": "fact", "id": "fact.mysql.flyway.history.2"},
                    {"artifact": "mysql_verification", "reference_type": "evidence", "id": "ev.mysql.flyway.history.2"},
                ],
                "details": {"source_file": "src/main/resources/db/migration/V1__init.sql", "runtime_script": "V1__init.sql"},
            },
            {
                "id": "recon.runtime_only.version.2",
                "kind": "runtime_only",
                "version": "2",
                "version_key": [2],
                "message": "Flyway runtime migration 2 has no source declaration.",
                "references": [
                    {"artifact": "mysql_verification", "reference_type": "fact", "id": "fact.mysql.flyway.history.3"},
                    {"artifact": "mysql_verification", "reference_type": "evidence", "id": "ev.mysql.flyway.history.3"},
                ],
                "details": {"runtime_script": "V2__runtime.sql"},
            },
            {
                "id": "recon.runtime_only.version.3",
                "kind": "runtime_only",
                "version": "3",
                "version_key": [3],
                "message": "Flyway runtime migration 3 has no source declaration.",
                "references": [
                    {"artifact": "mysql_verification", "reference_type": "fact", "id": "fact.mysql.flyway.history.4"},
                    {"artifact": "mysql_verification", "reference_type": "evidence", "id": "ev.mysql.flyway.history.4"},
                ],
                "details": {"runtime_script": "V3__runtime.sql"},
            },
        ],
        "warnings": [],
        "errors": [],
    }


def write_artifacts(
    root: Path,
    *,
    include_runtime: bool = True,
    include_reconciliation: bool = True,
    malicious: bool = False,
    include_secret: bool = False,
) -> dict[str, bytes]:
    paths: dict[str, bytes] = {}
    artifact_dir = root / ".repoevidence"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    static_bytes = (json.dumps(static_payload(root.resolve(), malicious=malicious), indent=2) + "\n").encode()
    (artifact_dir / "evidence.json").write_bytes(static_bytes)
    paths["static"] = static_bytes
    if include_runtime:
        runtime_dir = artifact_dir / "verification"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_bytes = (json.dumps(runtime_payload(root.resolve(), include_secret=include_secret), indent=2) + "\n").encode()
        (runtime_dir / "mysql.json").write_bytes(runtime_bytes)
        paths["runtime"] = runtime_bytes
    if include_reconciliation:
        recon_bytes = (json.dumps(reconciliation_payload(root.resolve()), indent=2) + "\n").encode()
        (artifact_dir / "reconciliation.json").write_bytes(recon_bytes)
        paths["reconciliation"] = recon_bytes
    return paths


def generate(root: Path, **kwargs: object) -> str:
    write_artifacts(root, **kwargs)
    output = ReportGenerator().generate(
        root,
        generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )
    return output.read_text(encoding="utf-8")


def test_evidence_only_report_is_self_contained_and_optional_sections_are_unavailable(
    tmp_path: Path,
) -> None:
    html = generate(tmp_path, include_runtime=False, include_reconciliation=False)

    assert "RepoEvidence report" in html
    assert "Spring API" in html
    assert "Not available" in html
    assert "<style>" in html
    assert "<script>" in html
    assert "href=\"http" not in html
    assert "src=\"http" not in html


def test_evidence_and_mysql_report_keeps_reconciliation_unavailable(tmp_path: Path) -> None:
    html = generate(tmp_path, include_reconciliation=False)

    assert "Verified runtime observation" in html
    assert "charge_safe_dev" in html
    assert "Not available" in html


def test_missing_evidence_is_a_safe_structured_error(tmp_path: Path) -> None:
    with pytest.raises(ReportGenerationError) as raised:
        ReportGenerator().generate(tmp_path)

    assert raised.value.code == "missing_static_scan"
    assert "password" not in str(raised.value).lower()
    assert not (tmp_path / ".repoevidence" / "report" / "index.html").exists()


def test_cli_missing_evidence_returns_structured_error_without_scanning(tmp_path: Path) -> None:
    from repoevidence.reconciliation import Reconciler
    from repoevidence.scanner import Scanner
    from repoevidence.verification.mysql import MySQLVerifier

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("report must not execute scan, verify, or reconcile")

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(Scanner, "scan", fail)
        monkeypatch.setattr(MySQLVerifier, "verify", fail)
        monkeypatch.setattr(Reconciler, "reconcile", fail)
        result = CliRunner().invoke(app, ["report", str(tmp_path)])
    finally:
        monkeypatch.undo()

    assert result.exit_code == 1
    assert "missing_static_scan" in result.output
    assert "password" not in result.output.lower()


def test_full_report_renders_overview_domains_and_provenance(tmp_path: Path) -> None:
    html = generate(tmp_path)

    for text in (
        "abc123",
        "main",
        "Static Facts",
        "Runtime Verified Facts",
        "Spring Endpoints",
        "Maven Dependencies",
        "Repository Flyway Migrations",
        "MySQL Tables",
        "Drift Findings",
        "Spring API",
        "Maven declarations",
        "Flyway source",
        "MySQL runtime",
        "Artifact provenance",
        "SHA-256",
        "evidence.json",
        "0.1",
    ):
        assert text in html
    assert ">Generated</span>" in html
    assert "2026-08-09T00:00:00+00:00" in html


def test_reconciliation_drift_renders_findings_and_baseline_without_fake_source_refs(
    tmp_path: Path,
) -> None:
    html = generate(tmp_path)

    assert "DRIFT DETECTED" in html
    assert "Runtime baseline" in html
    assert "Baseline 0" in html
    assert "recon.runtime_only.version.2" in html
    assert "V2__runtime.sql" in html
    assert "mysql_verification" in html
    runtime_only_position = html.index("recon.runtime_only.version.2")
    runtime_block = html[runtime_only_position : runtime_only_position + 1800]
    assert "fact.mysql.flyway.history.3" in runtime_block
    assert "ev.mysql.flyway.history.3" in runtime_block
    assert "fact.flyway.migration" not in runtime_block


def test_spring_endpoint_drilldown_renders_fact_evidence_source_and_annotation(
    tmp_path: Path,
) -> None:
    html = generate(tmp_path, include_runtime=False, include_reconciliation=False)

    assert "GET /api/items" in html
    assert "ApiController" in html
    assert "list" in html
    assert "fact.spring.endpoint.fixture" in html
    assert "ev.spring.endpoint" in html
    assert "src/Api.java" in html
    assert "GetMapping" in html
    assert "line 10" in html


def test_maven_flyway_and_mysql_sections_preserve_declared_verified_semantics(
    tmp_path: Path,
) -> None:
    html = generate(tmp_path)

    assert "Declared only; no Effective POM resolution" in html
    assert "org.example" in html
    assert "dependencyManagement" in html
    assert "maven-plugin" in html
    assert "V1__init.sql" in html
    assert "file_sha256" in html
    assert "Declared source migration" in html
    assert "Verified runtime observation" in html
    assert "9.7.0" in html
    assert "charge_safe_dev" in html
    assert "PRIMARY KEY" in html
    assert "UNIQUE" in html
    assert "FOREIGN KEY" in html
    assert "index" in html.lower()
    assert "&lt;&lt; Flyway Baseline &gt;&gt;" in html


def test_fact_evidence_drilldown_contains_structured_values_and_references(tmp_path: Path) -> None:
    html = generate(tmp_path)

    assert "Fact and evidence ledger" in html
    assert "fact.maven.project" in html
    assert "Evidence IDs" in html
    assert "structured value" in html.lower()
    assert "ev.maven.project" in html
    assert "xml_path" in html
    for payload in (static_payload(tmp_path.resolve()), runtime_payload(tmp_path.resolve())):
        for item in payload["facts"] + payload["evidence"]:
            assert item["id"] in html
    for fact in reconciliation_payload(tmp_path.resolve())["findings"]:
        for reference in fact["references"]:
            assert reference["id"] in html


def test_html_escapes_untrusted_values_and_redacts_secret_like_values(tmp_path: Path) -> None:
    html = generate(tmp_path, malicious=True, include_secret=True)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "branch&lt;&amp;\"" in html or "branch&lt;&amp;&quot;" in html
    assert "dont-render-me" not in html
    assert "also-secret" not in html
    assert "[redacted]" in html


def test_report_does_not_modify_input_artifacts_and_is_stable_for_fixed_time(
    tmp_path: Path,
) -> None:
    paths = write_artifacts(tmp_path)
    before = {name: hashlib.sha256(value).hexdigest() for name, value in paths.items()}
    first = ReportGenerator().generate(
        tmp_path,
        generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    ).read_bytes()
    second = ReportGenerator().generate(
        tmp_path,
        generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    ).read_bytes()

    assert first == second
    assert {
        "static": hashlib.sha256((tmp_path / ".repoevidence/evidence.json").read_bytes()).hexdigest(),
        "runtime": hashlib.sha256((tmp_path / ".repoevidence/verification/mysql.json").read_bytes()).hexdigest(),
        "reconciliation": hashlib.sha256((tmp_path / ".repoevidence/reconciliation.json").read_bytes()).hexdigest(),
    } == before
    assert all(digest in first.decode("utf-8") for digest in before.values())


def test_cli_report_writes_expected_output_and_does_not_construct_mysql(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_artifacts(tmp_path, include_runtime=False, include_reconciliation=False)
    from repoevidence.reconciliation import Reconciler
    from repoevidence.scanner import Scanner
    from repoevidence.verification import mysql
    from repoevidence.verification.mysql import MySQLVerifier

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("report must not execute scan, verify, or reconcile")

    monkeypatch.setattr(Scanner, "scan", fail)
    monkeypatch.setattr(MySQLVerifier, "verify", fail)
    monkeypatch.setattr(Reconciler, "reconcile", fail)

    monkeypatch.setattr(
        mysql,
        "default_connection_factory",
        lambda settings: (_ for _ in ()).throw(AssertionError("must not connect")),
    )
    result = CliRunner().invoke(app, ["report", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".repoevidence" / "report" / "index.html").is_file()


def test_report_help_is_exposed(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["report", "--help"])

    assert result.exit_code == 0
    assert "REPO_PATH" in result.output


def test_reporting_implementation_is_available_as_a_package_resource() -> None:
    assert files("repoevidence").joinpath("reporting.py").is_file()
