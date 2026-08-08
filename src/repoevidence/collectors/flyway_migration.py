import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from repoevidence.collectors.base import Collector
from repoevidence.models import CollectorResult, Conflict, Evidence, Fact

MAX_SQL_BYTES = 5 * 1024 * 1024
_SKIPPED_DIRECTORIES = {".git", ".repoevidence", "target"}
_MIGRATION_SUFFIX = ("src", "main", "resources", "db", "migration")
_VERSIONED_PATTERN = re.compile(
    r"^V(?P<version>[0-9]+(?:[._][0-9]+)*)__" r"(?P<description>[^_].*)\.sql$"
)
_REPEATABLE_PATTERN = re.compile(r"^R__(?P<description>[^_].*)\.sql$")


@dataclass(frozen=True)
class _FilenameDeclaration:
    migration_type: str | None
    raw_version: str | None
    description: str | None
    version_key: tuple[int, ...] | None
    unsupported: bool


@dataclass(frozen=True)
class _MigrationFile:
    source_file: str
    migration_set: str
    filename: str
    size_bytes: int
    file_sha256: str | None
    declaration: _FilenameDeclaration
    evidence_id: str
    fact_id: str | None = None


class FlywayMigrationCollector(Collector):
    """Collect static Flyway SQL migration filenames and ordering facts."""

    name = "flyway_migration"

    def collect(self, repo_root: Path) -> CollectorResult:
        root = repo_root.resolve()
        result = CollectorResult()
        for migration_directory in self._migration_directories(root):
            self._collect_migration_set(root, migration_directory, result)
        return result

    @classmethod
    def _migration_directories(cls, root: Path) -> list[Path]:
        directories: list[Path] = []
        for current, directory_names, _ in os.walk(root, followlinks=False):
            current_path = Path(current)
            directory_names[:] = sorted(
                directory_name
                for directory_name in directory_names
                if directory_name not in _SKIPPED_DIRECTORIES
                and not (current_path / directory_name).is_symlink()
            )
            relative_parts = current_path.relative_to(root).parts
            if relative_parts[-5:] == _MIGRATION_SUFFIX:
                directories.append(current_path)
                directory_names[:] = []
        return sorted(directories, key=lambda path: path.relative_to(root).as_posix())

    def _collect_migration_set(
        self,
        root: Path,
        migration_directory: Path,
        result: CollectorResult,
    ) -> None:
        migration_set = migration_directory.relative_to(root).as_posix()
        migration_files: list[_MigrationFile] = []
        try:
            directory_entries = sorted(migration_directory.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            result.warnings.append(f"Unable to read Flyway migration set {migration_set}: {exc}")
            directory_entries = []

        for path in directory_entries:
            if path.is_symlink() or not path.is_file() or path.suffix != ".sql":
                continue
            source_file = path.relative_to(root).as_posix()
            declaration = self._parse_filename(path.name)
            size_bytes, file_sha256, read_error = self._read_bounded(path)
            evidence_id = f"ev.flyway.migration.{_id_part(source_file)}"
            evidence_value = {
                "source_file": source_file,
                "migration_set": migration_set,
                "filename": path.name,
                "file_sha256": file_sha256,
                "size_bytes": size_bytes,
                "migration_type": declaration.migration_type,
                "raw_version": declaration.raw_version,
                "description": declaration.description,
            }
            if declaration.unsupported:
                evidence_value.update(
                    {
                        "unsupported": True,
                        "unsupported_reason": "unsupported_filename",
                    }
                )
            if read_error == "oversized":
                evidence_value["oversized"] = True
            elif read_error is not None:
                evidence_value["read_error"] = read_error
            result.evidence.append(
                Evidence(
                    id=evidence_id,
                    kind="flyway_migration_file",
                    source=source_file,
                    value=evidence_value,
                )
            )
            migration_file = _MigrationFile(
                source_file=source_file,
                migration_set=migration_set,
                filename=path.name,
                size_bytes=size_bytes,
                file_sha256=file_sha256,
                declaration=declaration,
                evidence_id=evidence_id,
            )
            migration_files.append(migration_file)
            if declaration.unsupported:
                result.warnings.append(
                    f"Unsupported Flyway SQL filename {source_file}: unsupported_filename."
                )
            if read_error == "oversized":
                result.warnings.append(
                    f"Flyway migration {source_file} exceeds the {MAX_SQL_BYTES}-byte size "
                    "limit; content hash unavailable and filename declaration retained."
                )
            elif read_error is not None:
                result.warnings.append(
                    f"Unable to read Flyway migration {source_file}: {read_error}."
                )

        versioned = [
            item
            for item in migration_files
            if item.declaration.migration_type == "versioned"
        ]
        repeatable = [
            item
            for item in migration_files
            if item.declaration.migration_type == "repeatable"
        ]
        for migration_file in [*versioned, *repeatable]:
            fact_id = f"fact.flyway.migration.{_id_part(migration_file.source_file)}"
            declaration = migration_file.declaration
            result.facts.append(
                Fact(
                    id=fact_id,
                    name="Flyway migration declaration",
                    value={
                        "migration_set": migration_set,
                        "type": declaration.migration_type,
                        "version": declaration.raw_version,
                        "description": declaration.description,
                        "source_file": migration_file.source_file,
                        "file_sha256": migration_file.file_sha256,
                    },
                    status="declared",
                    evidence_ids=[migration_file.evidence_id],
                )
            )

        ordered_versioned = sorted(
            versioned,
            key=lambda item: (item.declaration.version_key or (), item.source_file),
        )
        result.facts.append(
            Fact(
                id=f"fact.flyway.migration_set.{_id_part(migration_set)}",
                name="Flyway migration set summary",
                value={
                    "migration_set": migration_set,
                    "versioned_count": len(versioned),
                    "repeatable_count": len(repeatable),
                    "ordered_versions": [
                        item.declaration.raw_version for item in ordered_versioned
                    ],
                },
                status="inferred",
                evidence_ids=[item.evidence_id for item in migration_files],
            )
        )
        self._add_duplicate_conflicts(migration_set, versioned, result)

    @staticmethod
    def _parse_filename(filename: str) -> _FilenameDeclaration:
        versioned_match = _VERSIONED_PATTERN.fullmatch(filename)
        if versioned_match:
            raw_version = versioned_match.group("version")
            return _FilenameDeclaration(
                migration_type="versioned",
                raw_version=raw_version,
                description=versioned_match.group("description"),
                version_key=_version_key(raw_version),
                unsupported=False,
            )
        repeatable_match = _REPEATABLE_PATTERN.fullmatch(filename)
        if repeatable_match:
            return _FilenameDeclaration(
                migration_type="repeatable",
                raw_version=None,
                description=repeatable_match.group("description"),
                version_key=None,
                unsupported=False,
            )
        return _FilenameDeclaration(
            migration_type=None,
            raw_version=None,
            description=None,
            version_key=None,
            unsupported=True,
        )

    @staticmethod
    def _read_bounded(path: Path) -> tuple[int, str | None, str | None]:
        try:
            size_bytes = path.stat().st_size
        except OSError as exc:
            return 0, None, str(exc)
        if size_bytes > MAX_SQL_BYTES:
            return size_bytes, None, "oversized"
        try:
            with path.open("rb") as stream:
                content = stream.read(MAX_SQL_BYTES + 1)
        except OSError as exc:
            return size_bytes, None, str(exc)
        if len(content) > MAX_SQL_BYTES:
            return max(size_bytes, len(content)), None, "oversized"
        return size_bytes, hashlib.sha256(content).hexdigest(), None

    @staticmethod
    def _add_duplicate_conflicts(
        migration_set: str,
        versioned: list[_MigrationFile],
        result: CollectorResult,
    ) -> None:
        by_version: dict[tuple[int, ...], list[_MigrationFile]] = {}
        for migration_file in versioned:
            version_key = migration_file.declaration.version_key
            if version_key is not None:
                by_version.setdefault(version_key, []).append(migration_file)
        facts_by_source = {
            fact.value["source_file"]: fact
            for fact in result.facts
            if fact.id.startswith("fact.flyway.migration.")
        }
        for version_key, duplicates in sorted(by_version.items()):
            if len(duplicates) < 2:
                continue
            duplicates = sorted(duplicates, key=lambda item: item.source_file)
            normalized = ".".join(str(part) for part in version_key)
            result.conflicts.append(
                Conflict(
                    id=(
                        f"conflict.flyway.migration.{_id_part(migration_set)}."
                        f"version.{_id_part(normalized)}"
                    ),
                    message=(
                        f"Duplicate version {normalized} in Flyway migration set "
                        f"{migration_set}: "
                        f"{', '.join(item.source_file for item in duplicates)}"
                    ),
                    fact_id=facts_by_source[duplicates[0].source_file].id,
                    evidence_ids=[item.evidence_id for item in duplicates],
                )
            )


def _version_key(raw_version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.split(r"[._]", raw_version))


def _id_part(value: str) -> str:
    return quote(value, safe="")
