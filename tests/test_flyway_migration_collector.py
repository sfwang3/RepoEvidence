import hashlib
import json
from pathlib import Path

import pytest

import repoevidence.collectors.flyway_migration as flyway_migration
from repoevidence.collectors.flyway_migration import FlywayMigrationCollector
from repoevidence.scanner import Scanner

MIGRATION_SUFFIX = Path("src/main/resources/db/migration")


def write_migration(root: Path, relative_set: str, filename: str, content: str = "-- sql") -> Path:
    path = root / relative_set / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def migration_facts(result):
    return [fact for fact in result.facts if fact.id.startswith("fact.flyway.migration.")]


def set_facts(result):
    return [fact for fact in result.facts if fact.id.startswith("fact.flyway.migration_set.")]


def test_collects_versioned_repeatable_files_description_hash_and_set_fact(tmp_path: Path) -> None:
    versioned = write_migration(
        tmp_path, str(MIGRATION_SUFFIX), "V1__init.sql", "CREATE TABLE demo;"
    )
    repeatable = write_migration(
        tmp_path, str(MIGRATION_SUFFIX), "R__views.sql", "CREATE VIEW demo_view;"
    )

    result = FlywayMigrationCollector().collect(tmp_path)
    facts = {fact.value["source_file"]: fact for fact in migration_facts(result)}
    evidence = {item.id: item for item in result.evidence}

    assert facts["src/main/resources/db/migration/V1__init.sql"].value == {
        "migration_set": "src/main/resources/db/migration",
        "type": "versioned",
        "version": "1",
        "description": "init",
        "source_file": "src/main/resources/db/migration/V1__init.sql",
        "file_sha256": hashlib.sha256(versioned.read_bytes()).hexdigest(),
    }
    assert facts["src/main/resources/db/migration/R__views.sql"].value == {
        "migration_set": "src/main/resources/db/migration",
        "type": "repeatable",
        "version": None,
        "description": "views",
        "source_file": "src/main/resources/db/migration/R__views.sql",
        "file_sha256": hashlib.sha256(repeatable.read_bytes()).hexdigest(),
    }
    assert all(fact.status == "declared" for fact in facts.values())
    assert all(ref in evidence for fact in facts.values() for ref in fact.evidence_ids)

    set_fact = set_facts(result)[0]
    assert set_fact.status == "inferred"
    assert set_fact.value == {
        "migration_set": "src/main/resources/db/migration",
        "versioned_count": 1,
        "repeatable_count": 1,
        "ordered_versions": ["1"],
    }
    assert set(set_fact.evidence_ids) == set(evidence)


def test_orders_numeric_dotted_and_underscore_versions_without_requiring_continuity(
    tmp_path: Path,
) -> None:
    for filename in (
        "V10__ten.sql",
        "V2__two.sql",
        "V1__one.sql",
        "V1.2__dotted.sql",
        "V1_3__underscored.sql",
        "V8__eight.sql",
    ):
        write_migration(tmp_path, str(MIGRATION_SUFFIX), filename)

    result = FlywayMigrationCollector().collect(tmp_path)
    set_fact = set_facts(result)[0]

    assert set_fact.value["ordered_versions"] == ["1", "1.2", "1_3", "2", "8", "10"]
    assert result.conflicts == []


def test_unsupported_sql_has_file_evidence_warning_and_no_fact(tmp_path: Path) -> None:
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "Vbad__unknown.sql")
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "V1_bad.sql")
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "V1___triple.sql")
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "U1__unknown.sql")
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "Rviews.sql")
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "README.txt")

    result = FlywayMigrationCollector().collect(tmp_path)
    unsupported = [
        item
        for item in result.evidence
        if item.value.get("unsupported") is True
    ]

    assert len(unsupported) == 5
    assert all(item.value["migration_type"] is None for item in unsupported)
    assert all(item.value["raw_version"] is None for item in unsupported)
    assert all(item.value["description"] is None for item in unsupported)
    assert all(item.value["unsupported_reason"] == "unsupported_filename" for item in unsupported)
    assert migration_facts(result) == []
    assert result.errors == []
    assert result.warnings == sorted(result.warnings)
    assert all("unsupported_filename" in warning for warning in result.warnings)


def test_empty_migration_set_and_non_flyway_repository_are_normal(tmp_path: Path) -> None:
    (tmp_path / MIGRATION_SUFFIX).mkdir(parents=True)
    result = FlywayMigrationCollector().collect(tmp_path)

    assert migration_facts(result) == []
    assert len(set_facts(result)) == 1
    assert set_facts(result)[0].value == {
        "migration_set": "src/main/resources/db/migration",
        "versioned_count": 0,
        "repeatable_count": 0,
        "ordered_versions": [],
    }
    assert result.warnings == []
    assert result.errors == []

    non_maven = tmp_path / "other-repo"
    non_maven.mkdir()
    empty_result = FlywayMigrationCollector().collect(non_maven)
    assert empty_result.evidence == []
    assert empty_result.facts == []
    assert empty_result.warnings == []
    assert empty_result.errors == []


def test_duplicate_version_conflict_is_scoped_to_one_migration_set(tmp_path: Path) -> None:
    write_migration(tmp_path, "module-a/src/main/resources/db/migration", "V1.2__users.sql")
    write_migration(tmp_path, "module-a/src/main/resources/db/migration", "V1_2__orders.sql")
    write_migration(tmp_path, "module-b/src/main/resources/db/migration", "V1.2__other.sql")

    result = FlywayMigrationCollector().collect(tmp_path)
    conflicts = result.conflicts
    facts = migration_facts(result)
    evidence_ids = {item.id for item in result.evidence}
    fact_ids = {fact.id for fact in facts}

    assert len(conflicts) == 1
    assert conflicts[0].fact_id in fact_ids
    assert len(conflicts[0].evidence_ids) == 2
    assert all(evidence_id in evidence_ids for evidence_id in conflicts[0].evidence_ids)
    assert {fact.value["migration_set"] for fact in facts} == {
        "module-a/src/main/resources/db/migration",
        "module-b/src/main/resources/db/migration",
    }


def test_nested_migration_sets_have_independent_order_and_no_cross_module_conflict(
    tmp_path: Path,
) -> None:
    write_migration(tmp_path, "backend/src/main/resources/db/migration", "V1__backend.sql")
    write_migration(
        tmp_path,
        "backend/module-a/src/main/resources/db/migration",
        "V1__nested.sql",
    )

    result = FlywayMigrationCollector().collect(tmp_path)
    assert len(set_facts(result)) == 2
    assert len(result.conflicts) == 0
    assert {
        fact.value["migration_set"] for fact in migration_facts(result)
    } == {
        "backend/src/main/resources/db/migration",
        "backend/module-a/src/main/resources/db/migration",
    }


def test_oversized_sql_is_not_hashed_but_retains_filename_fact(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(flyway_migration, "MAX_SQL_BYTES", 32)
    path = write_migration(tmp_path, str(MIGRATION_SUFFIX), "V1__large.sql", "x" * 128)

    result = FlywayMigrationCollector().collect(tmp_path)
    oversized = next(item for item in result.evidence if item.value["filename"] == path.name)

    assert oversized.value["size_bytes"] == 128
    assert oversized.value["file_sha256"] is None
    assert migration_facts(result)[0].value["file_sha256"] is None
    assert set_facts(result)[0].value["versioned_count"] == 1
    assert set_facts(result)[0].value["ordered_versions"] == ["1"]
    assert any("size limit" in warning and "hash" in warning for warning in result.warnings)


def test_oversized_versioned_file_still_participates_in_duplicate_conflict(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(flyway_migration, "MAX_SQL_BYTES", 32)
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "V2__large.sql", "x" * 128)
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "V2__normal.sql", "small")

    result = FlywayMigrationCollector().collect(tmp_path)

    assert len(migration_facts(result)) == 2
    assert set_facts(result)[0].value["versioned_count"] == 2
    assert set_facts(result)[0].value["ordered_versions"] == ["2", "2"]
    assert len(result.conflicts) == 1
    assert len(result.conflicts[0].evidence_ids) == 2


def test_symlinked_sql_does_not_escape_repository(tmp_path: Path) -> None:
    outside = tmp_path.parent / "flyway-outside.sql"
    outside.write_text("-- outside", encoding="utf-8")
    link = tmp_path / MIGRATION_SUFFIX / "V9__outside.sql"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")

    result = FlywayMigrationCollector().collect(tmp_path)

    assert not any(
        "outside" in fact.value.get("source_file", "")
        for fact in migration_facts(result)
    )
    assert not any("outside" in item.value.get("source_file", "") for item in result.evidence)


def test_default_scanner_runs_flyway_after_existing_collectors_and_references_are_valid(
    tmp_path: Path,
) -> None:
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "V1__init.sql")

    result = Scanner.default().scan(tmp_path)
    evidence_ids = {item.id for item in result.evidence}
    fact_ids = {item.id for item in result.facts}

    assert result.collectors == [
        "repository_metadata",
        "spring_api",
        "maven_project",
        "flyway_migration",
    ]
    assert all(ref in evidence_ids for fact in result.facts for ref in fact.evidence_ids)
    assert all(
        conflict.fact_id in fact_ids
        for conflict in result.conflicts
        if conflict.fact_id
    )
    assert any(fact.id.startswith("fact.flyway.migration.") for fact in result.facts)


def test_collector_double_scan_is_deterministic(tmp_path: Path) -> None:
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "V10__ten.sql")
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "V1__one.sql")
    write_migration(tmp_path, str(MIGRATION_SUFFIX), "R__views.sql")

    first = FlywayMigrationCollector().collect(tmp_path).model_dump(mode="json")
    second = FlywayMigrationCollector().collect(tmp_path).model_dump(mode="json")

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
