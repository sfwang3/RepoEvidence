from pathlib import Path

from repoevidence import __version__
from repoevidence.collectors.base import Collector
from repoevidence.models import CollectorResult, Conflict, Evidence, Fact
from repoevidence.registry import CollectorRegistry
from repoevidence.scanner import Scanner


class TestCollector(Collector):
    name = "test"

    def collect(self, repo_root: Path) -> CollectorResult:
        return CollectorResult(
            evidence=[Evidence(id="ev.test", kind="test", source=str(repo_root), value=1)],
            facts=[
                Fact(
                    id="fact.test",
                    name="Test fact",
                    value=1,
                    status="verified",
                    evidence_ids=["ev.test"],
                )
            ],
            conflicts=[Conflict(id="conflict.test", message="test conflict")],
            warnings=["test warning"],
            errors=["test error"],
        )


def test_scanner_aggregates_every_collector_result_channel(tmp_path: Path) -> None:
    registry = CollectorRegistry()
    registry.register(TestCollector())

    result = Scanner(registry).scan(tmp_path)

    assert result.repository_root == str(tmp_path.resolve())
    assert result.collectors == ["test"]
    assert result.evidence[0].id == "ev.test"
    assert result.facts[0].id == "fact.test"
    assert result.conflicts[0].id == "conflict.test"
    assert result.warnings == ["test warning"]
    assert result.errors == ["test error"]


def test_default_registry_runs_repository_metadata_collector(tmp_path: Path) -> None:
    result = Scanner.default().scan(tmp_path)

    assert result.collectors == [
        "repository_metadata",
        "spring_api",
        "maven_project",
        "flyway_migration",
    ]
    assert any(fact.id == "fact.repository.root" for fact in result.facts)
    assert not any(fact.id.startswith("fact.spring.endpoint.") for fact in result.facts)
    assert result.errors == []


def test_scanner_adds_scan_metadata_with_utc_timestamps(tmp_path: Path) -> None:
    result = Scanner.default().scan(tmp_path)

    assert result.schema_version == "0.1"
    assert result.metadata.tool_version == __version__
    assert result.metadata.started_at.utcoffset().total_seconds() == 0
    assert result.metadata.finished_at.utcoffset().total_seconds() == 0
    assert result.metadata.finished_at >= result.metadata.started_at
