import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from repoevidence.cli import app
from repoevidence.verification.mysql import (
    MYSQL_CONNECTION_TIMEOUT,
    MYSQL_QUERIES,
    MySQLSettings,
    MySQLVerifier,
    default_connection_factory,
)

ENV = {
    "REPOEVIDENCE_MYSQL_HOST": "db.example.test",
    "REPOEVIDENCE_MYSQL_PORT": "3306",
    "REPOEVIDENCE_MYSQL_USER": "readonly",
    "REPOEVIDENCE_MYSQL_PASSWORD": "test-password-secret",
    "REPOEVIDENCE_MYSQL_DATABASE": "charge_safe",
}


class FakeCursor:
    def __init__(self, rows_by_query: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_query = rows_by_query
        self.executed: list[str] = []
        self.rows: list[dict[str, object]] = []

    def execute(self, operation: str, params: object = None) -> None:
        assert params is None
        self.executed.append(operation)
        if operation == MYSQL_QUERIES["set_read_only"]:
            self.rows = []
            return
        self.rows = self.rows_by_query[operation]

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.rows)

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, rows_by_query: dict[str, list[dict[str, object]]]) -> None:
        self.cursor_instance = FakeCursor(rows_by_query)
        self.started_transaction = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, **kwargs: object) -> FakeCursor:
        assert kwargs == {"dictionary": True}
        return self.cursor_instance

    def start_transaction(self) -> None:
        self.started_transaction = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def rows_for_schema() -> dict[str, list[dict[str, object]]]:
    return {
        MYSQL_QUERIES["server_version"]: [{"server_version": "8.0.36"}],
        MYSQL_QUERIES["database_name"]: [{"database_name": "charge_safe"}],
        MYSQL_QUERIES["tables"]: [
            {"table_schema": "charge_safe", "table_name": "users", "engine": "InnoDB"}
        ],
        MYSQL_QUERIES["columns"]: [
            {
                "table_name": "users",
                "column_name": "id",
                "ordinal_position": 1,
                "data_type": "bigint",
                "column_type": "bigint unsigned",
                "is_nullable": "NO",
                "column_default": None,
                "extra": "auto_increment",
            },
            {
                "table_name": "users",
                "column_name": "tenant_id",
                "ordinal_position": 2,
                "data_type": "bigint",
                "column_type": "bigint",
                "is_nullable": "NO",
                "column_default": 1,
                "extra": "",
            },
        ],
        MYSQL_QUERIES["constraints"]: [
            {
                "table_schema": "charge_safe",
                "table_name": "users",
                "constraint_name": "PRIMARY",
                "constraint_type": "PRIMARY KEY",
                "ordinal_position": 1,
                "column_name": "id",
                "referenced_table_schema": None,
                "referenced_table_name": None,
                "referenced_column_name": None,
            },
            {
                "table_schema": "charge_safe",
                "table_name": "users",
                "constraint_name": "uq_users_tenant_id",
                "constraint_type": "UNIQUE",
                "ordinal_position": 1,
                "column_name": "tenant_id",
                "referenced_table_schema": None,
                "referenced_table_name": None,
                "referenced_column_name": None,
            },
            {
                "table_schema": "charge_safe",
                "table_name": "users",
                "constraint_name": "fk_users_tenant",
                "constraint_type": "FOREIGN KEY",
                "ordinal_position": 1,
                "column_name": "tenant_id",
                "referenced_table_schema": "charge_safe",
                "referenced_table_name": "tenants",
                "referenced_column_name": "id",
            },
        ],
        MYSQL_QUERIES["indexes"]: [
            {
                "table_schema": "charge_safe",
                "table_name": "users",
                "index_name": "PRIMARY",
                "non_unique": 0,
                "seq_in_index": 1,
                "column_name": "id",
                "index_type": "BTREE",
            },
            {
                "table_schema": "charge_safe",
                "table_name": "users",
                "index_name": "idx_users_tenant",
                "non_unique": 1,
                "seq_in_index": 1,
                "column_name": "tenant_id",
                "index_type": "BTREE",
            },
            {
                "table_schema": "charge_safe",
                "table_name": "users",
                "index_name": "idx_users_tenant",
                "non_unique": 1,
                "seq_in_index": 2,
                "column_name": "id",
                "index_type": "BTREE",
            },
        ],
        MYSQL_QUERIES["flyway_history_present"]: [{"table_name": "flyway_schema_history"}],
        MYSQL_QUERIES["flyway_history"]: [
            {
                "installed_rank": 1,
                "version": "1",
                "description": "init",
                "type": "SQL",
                "script": "V1__init.sql",
                "checksum": 123,
                "success": 1,
                "installed_on": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "installed_rank": 2,
                "version": "2",
                "description": "failed",
                "type": "SQL",
                "script": "V2__failed.sql",
                "checksum": 456,
                "success": 0,
                "installed_on": datetime(2026, 1, 2, tzinfo=timezone.utc),
            },
        ],
    }


def test_mysql_verifier_collects_runtime_schema_and_flyway_history(tmp_path: Path) -> None:
    connection = FakeConnection(rows_for_schema())
    result = MySQLVerifier(
        connection_factory=lambda settings: connection,
        clock=lambda: datetime(2026, 1, 3, tzinfo=timezone.utc),
    ).verify(tmp_path, environment=ENV)

    assert result.errors == []
    assert connection.started_transaction
    assert connection.rolled_back
    assert connection.closed
    assert [fact.status for fact in result.facts] == ["verified"] * len(result.facts)
    assert next(f for f in result.facts if f.id == "fact.mysql.server.version").value == {
        "server_version": "8.0.36"
    }
    table = next(f for f in result.facts if f.id.endswith("table.charge_safe.users"))
    assert table.value["engine"] == "InnoDB"
    column = next(f for f in result.facts if f.id.endswith("column.charge_safe.users.id"))
    assert column.value["nullable"] is False
    assert column.value["extra"] == "auto_increment"
    primary = next(f for f in result.facts if ".constraint." in f.id and "PRIMARY" in f.id)
    assert primary.value["columns"] == [{"column_name": "id", "ordinal_position": 1}]
    foreign_key = next(f for f in result.facts if "fk_users_tenant" in f.id)
    assert foreign_key.value["referenced_table_name"] == "tenants"
    assert foreign_key.value["columns"] == [
        {
            "column_name": "tenant_id",
            "ordinal_position": 1,
            "referenced_column_name": "id",
        }
    ]
    index = next(f for f in result.facts if ".index." in f.id and "idx_users_tenant" in f.id)
    assert index.value["columns"] == [
        {"column_name": "tenant_id", "sequence": 1},
        {"column_name": "id", "sequence": 2},
    ]
    failed = next(f for f in result.facts if ".flyway.history.2" in f.id)
    assert failed.value["success"] is False
    assert failed.value["checksum"] == 456

    assert set(connection.cursor_instance.executed) <= set(MYSQL_QUERIES.values())
    assert MYSQL_QUERIES["set_read_only"] in connection.cursor_instance.executed


def test_mysql_verifier_keeps_composite_order_and_stable_ids(tmp_path: Path) -> None:
    rows = rows_for_schema()
    rows[MYSQL_QUERIES["constraints"]] = [
        {
            "table_schema": "charge_safe",
            "table_name": "users",
            "constraint_name": "PRIMARY",
            "constraint_type": "PRIMARY KEY",
            "ordinal_position": 1,
            "column_name": "tenant_id",
            "referenced_table_schema": None,
            "referenced_table_name": None,
            "referenced_column_name": None,
        },
        {
            "table_schema": "charge_safe",
            "table_name": "users",
            "constraint_name": "PRIMARY",
            "constraint_type": "PRIMARY KEY",
            "ordinal_position": 2,
            "column_name": "id",
            "referenced_table_schema": None,
            "referenced_table_name": None,
            "referenced_column_name": None,
        },
    ]
    first = MySQLVerifier(
        connection_factory=lambda settings: FakeConnection(rows),
        clock=lambda: datetime(2026, 1, 3, tzinfo=timezone.utc),
    ).verify(tmp_path, environment=ENV)
    second = MySQLVerifier(
        connection_factory=lambda settings: FakeConnection(rows),
        clock=lambda: datetime(2026, 1, 4, tzinfo=timezone.utc),
    ).verify(tmp_path, environment=ENV)

    assert [fact.id for fact in first.facts] == [fact.id for fact in second.facts]
    primary = next(f for f in first.facts if ".constraint." in f.id)
    assert primary.value["columns"] == [
        {"column_name": "tenant_id", "ordinal_position": 1},
        {"column_name": "id", "ordinal_position": 2},
    ]
    assert [fact.id for fact in first.facts] == sorted(fact.id for fact in first.facts)


def test_missing_flyway_history_is_a_verified_fact_not_an_error(tmp_path: Path) -> None:
    rows = rows_for_schema()
    rows[MYSQL_QUERIES["flyway_history_present"]] = []
    rows[MYSQL_QUERIES["flyway_history"]] = []
    result = MySQLVerifier(
        connection_factory=lambda settings: FakeConnection(rows),
    ).verify(tmp_path, environment=ENV)

    fact = next(f for f in result.facts if f.id == "fact.mysql.flyway_history.present")
    assert fact.value == {"present": False}
    assert not any("flyway.history." in f.id for f in result.facts)
    assert MYSQL_QUERIES["flyway_history"] not in (result.metadata.model_dump_json())


def test_missing_config_does_not_attempt_connection(tmp_path: Path) -> None:
    called = False

    def factory(settings: object) -> FakeConnection:
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    result = MySQLVerifier(connection_factory=factory).verify(tmp_path, environment={})

    assert not called
    assert result.errors[0].code == "mysql_config_missing"
    assert "password" not in result.model_dump_json().lower()


def test_query_exception_is_redacted_and_resources_are_closed(tmp_path: Path) -> None:
    secret = "query-password-secret"

    class FailingCursor(FakeCursor):
        def execute(self, operation: str, params: object = None) -> None:
            if operation == MYSQL_QUERIES["server_version"]:
                raise RuntimeError(f"query failed password={secret}")
            super().execute(operation, params)

    connection = FakeConnection(rows_for_schema())
    connection.cursor_instance = FailingCursor(rows_for_schema())
    result = MySQLVerifier(
        connection_factory=lambda settings: connection,
    ).verify(tmp_path, environment=ENV)

    assert result.errors[0].code == "mysql_query_failed"
    assert secret not in result.model_dump_json()
    assert connection.closed
    assert connection.rolled_back


def test_connection_exception_is_redacted_from_result_and_cli_output(tmp_path: Path) -> None:
    secret = "test-password-secret"

    def factory(settings: object) -> FakeConnection:
        raise RuntimeError(f"driver leaked password={secret} secret=token-value")

    verifier_result = MySQLVerifier(connection_factory=factory).verify(tmp_path, environment=ENV)
    assert verifier_result.errors[0].code == "mysql_connection_failed"
    assert secret not in verifier_result.model_dump_json()
    assert "driver leaked" not in verifier_result.model_dump_json()

    from repoevidence.verification import mysql

    original = mysql.default_connection_factory
    mysql.default_connection_factory = factory
    try:
        result = CliRunner().invoke(app, ["verify", "mysql", str(tmp_path)])
    finally:
        mysql.default_connection_factory = original
    assert result.exit_code == 0, result.output
    assert secret not in result.output
    payload = json.loads(
        (tmp_path / ".repoevidence" / "verification" / "mysql.json").read_text(encoding="utf-8")
    )
    assert secret not in json.dumps(payload)


def test_mysql_verification_writes_separate_output_and_scan_never_connects(
    tmp_path: Path, monkeypatch: object
) -> None:
    for key in ENV:
        monkeypatch.delenv(key, raising=False)
    connection = FakeConnection(rows_for_schema())
    result = CliRunner().invoke(app, ["verify", "mysql", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".repoevidence" / "verification" / "mysql.json").exists()
    assert not (tmp_path / ".repoevidence" / "evidence.json").exists()

    static_result = CliRunner().invoke(app, ["scan", str(tmp_path)])
    assert static_result.exit_code == 0, static_result.output
    assert (tmp_path / ".repoevidence" / "evidence.json").exists()
    assert connection.closed is False


def test_cli_success_uses_fake_connection_and_keeps_static_output_separate(
    tmp_path: Path, monkeypatch: object
) -> None:
    from repoevidence.verification import mysql

    connection = FakeConnection(rows_for_schema())
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    original = mysql.default_connection_factory
    mysql.default_connection_factory = lambda settings: connection
    try:
        result = CliRunner().invoke(app, ["verify", "mysql", str(tmp_path)])
    finally:
        mysql.default_connection_factory = original

    assert result.exit_code == 0, result.output
    payload = json.loads(
        (tmp_path / ".repoevidence" / "verification" / "mysql.json").read_text(encoding="utf-8")
    )
    assert payload["verifier"] == "mysql"
    assert not (tmp_path / ".repoevidence" / "evidence.json").exists()


def test_scan_does_not_construct_or_connect_mysql_even_when_env_is_present(
    tmp_path: Path, monkeypatch: object
) -> None:
    from repoevidence.verification import mysql

    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    def must_not_connect(settings: object) -> FakeConnection:
        raise AssertionError("static scan attempted a MySQL connection")

    original = mysql.default_connection_factory
    mysql.default_connection_factory = must_not_connect
    try:
        result = CliRunner().invoke(app, ["scan", str(tmp_path)])
    finally:
        mysql.default_connection_factory = original

    assert result.exit_code == 0, result.output


def test_mysql_help_has_no_password_option() -> None:
    result = CliRunner().invoke(app, ["verify", "mysql", "--help"])

    assert result.exit_code == 0
    assert "--password" not in result.output


def test_default_connector_uses_timeout_and_explicit_settings(monkeypatch: object) -> None:
    captured: dict[str, object] = {}

    def connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("mysql.connector.connect", connect)
    settings = MySQLSettings(
        host="db.example.test",
        port=3306,
        user="readonly",
        password="private-test-secret",
        database="charge_safe",
    )
    connection = default_connection_factory(settings)

    assert connection is not None
    assert captured["connection_timeout"] == MYSQL_CONNECTION_TIMEOUT
    assert captured["autocommit"] is False
    assert captured["host"] == settings.host
    assert captured["database"] == settings.database
