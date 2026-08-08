from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping
from urllib.parse import quote

from repoevidence import __version__
from repoevidence.models import (
    Evidence,
    Fact,
    VerificationError,
    VerificationMetadata,
    VerificationResult,
)

MYSQL_CONNECTION_TIMEOUT = 5

MYSQL_QUERIES: Mapping[str, str] = MappingProxyType(
    {
        "set_read_only": "SET TRANSACTION READ ONLY",
        "server_version": "SELECT VERSION() AS server_version",
        "database_name": "SELECT DATABASE() AS database_name",
        "tables": (
            "SELECT TABLE_SCHEMA AS table_schema, TABLE_NAME AS table_name, ENGINE AS engine "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_SCHEMA, TABLE_NAME"
        ),
        "columns": (
            "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name, "
            "ORDINAL_POSITION AS ordinal_position, DATA_TYPE AS data_type, "
            "COLUMN_TYPE AS column_type, IS_NULLABLE AS is_nullable, "
            "COLUMN_DEFAULT AS column_default, EXTRA AS extra "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION"
        ),
        "constraints": (
            "SELECT kcu.TABLE_SCHEMA AS table_schema, kcu.TABLE_NAME AS table_name, "
            "kcu.CONSTRAINT_NAME AS constraint_name, tc.CONSTRAINT_TYPE AS constraint_type, "
            "kcu.ORDINAL_POSITION AS ordinal_position, kcu.COLUMN_NAME AS column_name, "
            "kcu.REFERENCED_TABLE_SCHEMA AS referenced_table_schema, "
            "kcu.REFERENCED_TABLE_NAME AS referenced_table_name, "
            "kcu.REFERENCED_COLUMN_NAME AS referenced_column_name "
            "FROM information_schema.KEY_COLUMN_USAGE AS kcu "
            "JOIN information_schema.TABLE_CONSTRAINTS AS tc "
            "ON tc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA "
            "AND tc.TABLE_NAME = kcu.TABLE_NAME "
            "AND tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
            "WHERE kcu.TABLE_SCHEMA = DATABASE() "
            "AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY') "
            "ORDER BY kcu.TABLE_SCHEMA, kcu.TABLE_NAME, kcu.CONSTRAINT_NAME, "
            "kcu.ORDINAL_POSITION"
        ),
        "indexes": (
            "SELECT TABLE_SCHEMA AS table_schema, TABLE_NAME AS table_name, "
            "INDEX_NAME AS index_name, NON_UNIQUE AS non_unique, "
            "SEQ_IN_INDEX AS seq_in_index, COLUMN_NAME AS column_name, "
            "INDEX_TYPE AS index_type "
            "FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "ORDER BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX"
        ),
        "flyway_history_present": (
            "SELECT TABLE_NAME AS table_name FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'flyway_schema_history' "
            "AND TABLE_TYPE = 'BASE TABLE'"
        ),
        "flyway_history": (
            "SELECT installed_rank, version, description, type, script, checksum, success, "
            "installed_on FROM flyway_schema_history ORDER BY installed_rank"
        ),
    }
)


@dataclass(frozen=True)
class MySQLSettings:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "MySQLSettings | None":
        values = {
            "host": environment.get("REPOEVIDENCE_MYSQL_HOST", ""),
            "port": environment.get("REPOEVIDENCE_MYSQL_PORT", ""),
            "user": environment.get("REPOEVIDENCE_MYSQL_USER", ""),
            "password": environment.get("REPOEVIDENCE_MYSQL_PASSWORD", ""),
            "database": environment.get("REPOEVIDENCE_MYSQL_DATABASE", ""),
        }
        if not all(values.values()):
            return None
        try:
            port = int(values["port"])
        except ValueError:
            return None
        if not 1 <= port <= 65535:
            return None
        return cls(
            host=values["host"],
            port=port,
            user=values["user"],
            password=values["password"],
            database=values["database"],
        )


def default_connection_factory(settings: MySQLSettings) -> Any:
    """Connect using the official connector; imported only for explicit verify."""

    import mysql.connector

    return mysql.connector.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        connection_timeout=MYSQL_CONNECTION_TIMEOUT,
        autocommit=False,
    )


class _QueryFailure(Exception):
    pass


class MySQLVerifier:
    """Read-only, fixed-query MySQL runtime verifier."""

    def __init__(
        self,
        connection_factory: Callable[[MySQLSettings], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.connection_factory = connection_factory or default_connection_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def verify(
        self,
        repo_path: str | Path,
        environment: Mapping[str, str] | None = None,
    ) -> VerificationResult:
        root = Path(repo_path).expanduser().resolve()
        started_at = self.clock().astimezone(timezone.utc)
        observed_at = started_at
        evidence: list[Evidence] = []
        facts: list[Fact] = []
        warnings: list[str] = []
        errors: list[VerificationError] = []
        connection: Any = None
        cursor: Any = None

        runtime_environment = os.environ if environment is None else environment
        settings = MySQLSettings.from_environment(runtime_environment)
        if settings is None:
            errors.append(
                VerificationError(
                    code="mysql_config_missing",
                    message=(
                        "Required MySQL verification environment variables are missing or invalid."
                    ),
                )
            )
        else:
            try:
                connection = self.connection_factory(settings)
            except Exception:
                errors.append(
                    VerificationError(
                        code="mysql_connection_failed",
                        message="Unable to connect to MySQL.",
                    )
                )
            else:
                try:
                    cursor = connection.cursor(dictionary=True)
                    try:
                        cursor.execute(MYSQL_QUERIES["set_read_only"])
                    except Exception as exc:
                        raise _QueryFailure from exc
                    connection.start_transaction()
                    self._collect(cursor, observed_at, evidence, facts)
                except _QueryFailure:
                    errors.append(
                        VerificationError(
                            code="mysql_query_failed",
                            message="A fixed read-only MySQL metadata query failed.",
                        )
                    )
                except Exception:
                    errors.append(
                        VerificationError(
                            code="mysql_verification_failed",
                            message="MySQL runtime verification failed.",
                        )
                    )
                finally:
                    if cursor is not None:
                        try:
                            cursor.close()
                        except Exception:
                            pass
                    if connection is not None:
                        try:
                            connection.rollback()
                        except Exception:
                            pass
                        try:
                            connection.close()
                        except Exception:
                            pass

        finished_at = self.clock().astimezone(timezone.utc)
        return VerificationResult(
            verifier="mysql",
            repository_root=str(root),
            metadata=VerificationMetadata(
                tool_version=__version__,
                started_at=started_at,
                finished_at=finished_at,
                observed_at=observed_at,
            ),
            evidence=sorted(evidence, key=lambda item: item.id),
            facts=sorted(facts, key=lambda item: item.id),
            conflicts=[],
            warnings=sorted(warnings),
            errors=errors,
        )

    def _collect(
        self,
        cursor: Any,
        observed_at: datetime,
        evidence: list[Evidence],
        facts: list[Fact],
    ) -> None:
        server_row = self._one(cursor, "server_version")
        database_row = self._one(cursor, "database_name")
        server_evidence_id = "ev.mysql.server.version"
        database_evidence_id = "ev.mysql.database.name"
        evidence.extend(
            [
                self._evidence(
                    server_evidence_id,
                    "mysql.server",
                    "server_version",
                    observed_at,
                    {"server_version": server_row.get("server_version")},
                ),
                self._evidence(
                    database_evidence_id,
                    "mysql.database",
                    "database_name",
                    observed_at,
                    {"database_name": database_row.get("database_name")},
                ),
            ]
        )
        facts.extend(
            [
                Fact(
                    id="fact.mysql.server.version",
                    name="MySQL server version",
                    value={"server_version": server_row.get("server_version")},
                    status="verified",
                    evidence_ids=[server_evidence_id],
                ),
                Fact(
                    id="fact.mysql.database.name",
                    name="Selected MySQL database",
                    value={"database_name": database_row.get("database_name")},
                    status="verified",
                    evidence_ids=[database_evidence_id],
                ),
            ]
        )

        tables = self._many(cursor, "tables")
        for row in tables:
            schema = str(row.get("table_schema") or database_row.get("database_name") or "")
            table_name = str(row.get("table_name") or "")
            key = _key(schema, table_name)
            evidence_id = f"ev.mysql.table.{key}"
            value = {
                "schema": schema,
                "table_name": table_name,
                "engine": row.get("engine"),
            }
            evidence.append(
                self._evidence(evidence_id, "mysql.table", "tables", observed_at, value)
            )
            facts.append(
                Fact(
                    id=f"fact.mysql.table.{key}",
                    name="MySQL base table",
                    value=value,
                    status="verified",
                    evidence_ids=[evidence_id],
                )
            )

        for row in self._many(cursor, "columns"):
            schema = str(database_row.get("database_name") or "")
            table_name = str(row.get("table_name") or "")
            column_name = str(row.get("column_name") or "")
            key = _key(schema, table_name, column_name)
            evidence_id = f"ev.mysql.column.{key}"
            value = {
                "schema": schema,
                "table_name": table_name,
                "column_name": column_name,
                "ordinal_position": row.get("ordinal_position"),
                "data_type": row.get("data_type"),
                "column_type": row.get("column_type"),
                "nullable": str(row.get("is_nullable") or "").upper() == "YES",
                "default": row.get("column_default"),
                "extra": row.get("extra"),
            }
            evidence.append(
                self._evidence(evidence_id, "mysql.column", "columns", observed_at, value)
            )
            facts.append(
                Fact(
                    id=f"fact.mysql.column.{key}",
                    name="MySQL column",
                    value=value,
                    status="verified",
                    evidence_ids=[evidence_id],
                )
            )

        self._collect_constraints(cursor, database_row, observed_at, evidence, facts)
        self._collect_indexes(cursor, observed_at, evidence, facts)
        self._collect_flyway(cursor, observed_at, evidence, facts)

    def _collect_constraints(
        self,
        cursor: Any,
        database_row: dict[str, Any],
        observed_at: datetime,
        evidence: list[Evidence],
        facts: list[Fact],
    ) -> None:
        grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        default_schema = str(database_row.get("database_name") or "")
        for row in self._many(cursor, "constraints"):
            key = (
                str(row.get("table_schema") or default_schema),
                str(row.get("table_name") or ""),
                str(row.get("constraint_type") or ""),
                str(row.get("constraint_name") or ""),
            )
            grouped[key].append(row)

        for (schema, table_name, constraint_type, constraint_name), rows in sorted(grouped.items()):
            rows.sort(key=lambda row: int(row.get("ordinal_position") or 0))
            key = _key(schema, table_name, constraint_type, constraint_name)
            evidence_id = f"ev.mysql.constraint.{key}"
            first = rows[0]
            columns = []
            for row in rows:
                column = {
                    "column_name": row.get("column_name"),
                    "ordinal_position": row.get("ordinal_position"),
                }
                if row.get("referenced_column_name") is not None:
                    column["referenced_column_name"] = row.get("referenced_column_name")
                columns.append(column)
            value = {
                "schema": schema,
                "table_name": table_name,
                "constraint_name": constraint_name,
                "constraint_type": constraint_type,
                "columns": columns,
                "referenced_table_schema": first.get("referenced_table_schema"),
                "referenced_table_name": first.get("referenced_table_name"),
            }
            evidence.append(
                self._evidence(evidence_id, "mysql.constraint", "constraints", observed_at, value)
            )
            facts.append(
                Fact(
                    id=f"fact.mysql.constraint.{key}",
                    name="MySQL constraint",
                    value=value,
                    status="verified",
                    evidence_ids=[evidence_id],
                )
            )

    def _collect_indexes(
        self,
        cursor: Any,
        observed_at: datetime,
        evidence: list[Evidence],
        facts: list[Fact],
    ) -> None:
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in self._many(cursor, "indexes"):
            key = (
                str(row.get("table_schema") or ""),
                str(row.get("table_name") or ""),
                str(row.get("index_name") or ""),
            )
            grouped[key].append(row)

        for (schema, table_name, index_name), rows in sorted(grouped.items()):
            rows.sort(key=lambda row: int(row.get("seq_in_index") or 0))
            key = _key(schema, table_name, index_name)
            evidence_id = f"ev.mysql.index.{key}"
            first = rows[0]
            value = {
                "schema": schema,
                "table_name": table_name,
                "index_name": index_name,
                "unique": not bool(first.get("non_unique")),
                "non_unique": bool(first.get("non_unique")),
                "index_type": first.get("index_type"),
                "index_kind": "primary" if index_name == "PRIMARY" else "secondary",
                "columns": [
                    {
                        "column_name": row.get("column_name"),
                        "sequence": row.get("seq_in_index"),
                    }
                    for row in rows
                ],
            }
            evidence.append(
                self._evidence(evidence_id, "mysql.index", "indexes", observed_at, value)
            )
            facts.append(
                Fact(
                    id=f"fact.mysql.index.{key}",
                    name="MySQL index",
                    value=value,
                    status="verified",
                    evidence_ids=[evidence_id],
                )
            )

    def _collect_flyway(
        self,
        cursor: Any,
        observed_at: datetime,
        evidence: list[Evidence],
        facts: list[Fact],
    ) -> None:
        present = bool(self._many(cursor, "flyway_history_present"))
        evidence_id = "ev.mysql.flyway.history.present"
        value = {"present": present}
        evidence.append(
            self._evidence(
                evidence_id,
                "mysql.flyway_history",
                "flyway_history_present",
                observed_at,
                value,
            )
        )
        facts.append(
            Fact(
                id="fact.mysql.flyway_history.present",
                name="Flyway schema history present",
                value=value,
                status="verified",
                evidence_ids=[evidence_id],
            )
        )
        if not present:
            return

        for row in self._many(cursor, "flyway_history"):
            installed_rank = row.get("installed_rank")
            key = _key(installed_rank)
            evidence_id = f"ev.mysql.flyway.history.{key}"
            value = {
                "installed_rank": installed_rank,
                "version": row.get("version"),
                "description": row.get("description"),
                "type": row.get("type"),
                "script": row.get("script"),
                "checksum": row.get("checksum"),
                "success": bool(row.get("success")),
                "installed_on": row.get("installed_on"),
            }
            evidence.append(
                self._evidence(
                    evidence_id,
                    "mysql.flyway_history",
                    "flyway_history",
                    observed_at,
                    value,
                )
            )
            facts.append(
                Fact(
                    id=f"fact.mysql.flyway.history.{key}",
                    name="Flyway runtime migration history",
                    value=value,
                    status="verified",
                    evidence_ids=[evidence_id],
                )
            )

    @staticmethod
    def _one(cursor: Any, query_name: str) -> dict[str, Any]:
        rows = MySQLVerifier._execute(cursor, query_name, one=True)
        return rows[0] if rows else {}

    @staticmethod
    def _many(cursor: Any, query_name: str) -> list[dict[str, Any]]:
        return MySQLVerifier._execute(cursor, query_name, one=False)

    @staticmethod
    def _execute(cursor: Any, query_name: str, one: bool) -> list[dict[str, Any]]:
        query = MYSQL_QUERIES[query_name]
        try:
            cursor.execute(query)
            if one:
                row = cursor.fetchone()
                return [row] if row is not None else []
            return list(cursor.fetchall())
        except Exception as exc:
            raise _QueryFailure from exc

    @staticmethod
    def _evidence(
        evidence_id: str,
        kind: str,
        query_name: str,
        observed_at: datetime,
        value: dict[str, Any],
    ) -> Evidence:
        return Evidence(
            id=evidence_id,
            kind=kind,
            source=f"mysql.query.{query_name}",
            value={
                "query_name": query_name,
                "observed_at": observed_at,
                "result": value,
            },
        )


def _key(*parts: object) -> str:
    return ".".join(quote(str(part), safe="-_~") for part in parts)
