from datetime import datetime, timezone
from pathlib import Path

from repoevidence import __version__
from repoevidence.collectors.flyway_migration import FlywayMigrationCollector
from repoevidence.collectors.maven_project import MavenProjectCollector
from repoevidence.collectors.repository_metadata import RepositoryMetadataCollector
from repoevidence.collectors.spring_api import SpringApiCollector
from repoevidence.models import (
    ScanMetadata,
    ScanResult,
)
from repoevidence.registry import CollectorRegistry


class Scanner:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry

    @classmethod
    def default(cls) -> "Scanner":
        registry = CollectorRegistry()
        registry.register(RepositoryMetadataCollector())
        registry.register(SpringApiCollector())
        registry.register(MavenProjectCollector())
        registry.register(FlywayMigrationCollector())
        return cls(registry)

    def scan(self, repo_path: str | Path) -> ScanResult:
        root = Path(repo_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Repository path is not a directory: {root}")

        started_at = datetime.now(timezone.utc)
        collectors: list[str] = []
        evidence = []
        facts = []
        conflicts = []
        warnings = []
        errors = []
        for collector in self.registry.collectors:
            collectors.append(collector.name)
            try:
                collector_result = collector.collect(root)
            except Exception as exc:  # pragma: no cover - defensive collector boundary
                errors.append(f"{collector.name}: {type(exc).__name__}: {exc}")
                continue
            evidence.extend(collector_result.evidence)
            facts.extend(collector_result.facts)
            conflicts.extend(collector_result.conflicts)
            warnings.extend(collector_result.warnings)
            errors.extend(collector_result.errors)

        return ScanResult(
            repository_root=str(root),
            metadata=ScanMetadata(
                tool_version=__version__,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            ),
            collectors=collectors,
            evidence=evidence,
            facts=facts,
            conflicts=conflicts,
            warnings=warnings,
            errors=errors,
        )
