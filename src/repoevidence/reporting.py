# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from repoevidence import __version__
from repoevidence.i18n import (
    Language,
    finding_label,
    finding_message,
    message,
    resolve_language,
    status_label,
)
from repoevidence.models import (
    Evidence,
    Fact,
    ReconciliationResult,
    ScanResult,
    VerificationResult,
)

SUPPORTED_SCHEMA_VERSION = "0.1"
STATIC_RELATIVE_PATH = ".repoevidence/evidence.json"
RUNTIME_RELATIVE_PATH = ".repoevidence/verification/mysql.json"
RECONCILIATION_RELATIVE_PATH = ".repoevidence/reconciliation.json"
REPORT_RELATIVE_PATH = ".repoevidence/report/index.html"

_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|"
    r"connection[_-]?string|authorization)",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?P<key>password|passwd|secret|token|api[_-]?key|authorization)"
    r"(\s*[:=]\s*)(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)


class ReportGenerationError(Exception):
    """A safe, structured error raised when a report cannot be generated."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class _Artifact:
    artifact: str
    relative_path: str
    sha256: str
    schema_version: str | None
    payload: dict[str, Any] | None
    parsed: ScanResult | VerificationResult | ReconciliationResult | None
    time_labels: tuple[tuple[str, str], ...]
    error: str | None = None
    error_key: str | None = None


@dataclass(frozen=True)
class _ReportData:
    root: str
    static: _Artifact
    runtime: _Artifact
    reconciliation: _Artifact
    static_result: ScanResult
    runtime_result: VerificationResult | None
    reconciliation_result: ReconciliationResult | None
    generated_at: datetime
    language: Language


class ReportGenerator:
    """Generate one self-contained report from existing RepoEvidence artifacts."""

    def generate(
        self,
        repo_path: str | Path,
        generated_at: datetime | None = None,
        language: str = "en",
    ) -> Path:
        root = Path(repo_path).expanduser().resolve()
        data = self._load(root, generated_at, resolve_language(language))
        output_path = root / REPORT_RELATIVE_PATH
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self._render(data), encoding="utf-8")
        return output_path

    def _load(
        self,
        root: Path,
        generated_at: datetime | None,
        language: Language,
    ) -> _ReportData:
        static = self._load_artifact(
            root / STATIC_RELATIVE_PATH,
            "static_scan",
            required=True,
            parser=ScanResult,
        )
        if not isinstance(static.parsed, ScanResult):
            raise ReportGenerationError("invalid_static_scan", "Static scan artifact is invalid.")
        runtime = self._load_artifact(
            root / RUNTIME_RELATIVE_PATH,
            "mysql_verification",
            required=False,
            parser=VerificationResult,
        )
        reconciliation = self._load_artifact(
            root / RECONCILIATION_RELATIVE_PATH,
            "reconciliation",
            required=False,
            parser=ReconciliationResult,
        )
        timestamp = generated_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)
        return _ReportData(
            root=static.parsed.repository_root,
            static=static,
            runtime=runtime,
            reconciliation=reconciliation,
            static_result=static.parsed,
            runtime_result=(
                runtime.parsed if isinstance(runtime.parsed, VerificationResult) else None
            ),
            reconciliation_result=(
                reconciliation.parsed
                if isinstance(reconciliation.parsed, ReconciliationResult)
                else None
            ),
            generated_at=timestamp,
            language=language,
        )

    @staticmethod
    def _load_artifact(
        path: Path,
        artifact: str,
        *,
        required: bool,
        parser: type[ScanResult] | type[VerificationResult] | type[ReconciliationResult],
    ) -> _Artifact:
        relative_path = {
            "static_scan": STATIC_RELATIVE_PATH,
            "mysql_verification": RUNTIME_RELATIVE_PATH,
            "reconciliation": RECONCILIATION_RELATIVE_PATH,
        }[artifact]
        if not path.is_file():
            if required:
                raise ReportGenerationError(
                    f"missing_{artifact}",
                    f"Required {artifact} artifact is missing.",
                )
            return _Artifact(
                artifact=artifact,
                relative_path=relative_path,
                sha256="",
                schema_version=None,
                payload=None,
                parsed=None,
                time_labels=(),
                error="Not available",
                error_key="report.artifact_missing",
            )
        raw = b""
        try:
            raw = path.read_bytes()
            payload = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            if required:
                raise ReportGenerationError(
                    f"invalid_{artifact}_json",
                    f"Required {artifact} artifact is not valid JSON.",
                ) from None
            return _Artifact(
                artifact=artifact,
                relative_path=relative_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                schema_version=None,
                payload=None,
                parsed=None,
                time_labels=(),
                error="Artifact is not valid JSON",
                error_key="report.artifact_invalid_json",
            )
        if not isinstance(payload, dict):
            if required:
                raise ReportGenerationError(
                    f"invalid_{artifact}_json",
                    f"Required {artifact} artifact must contain a JSON object.",
                )
            return _Artifact(
                artifact=artifact,
                relative_path=relative_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                schema_version=None,
                payload=None,
                parsed=None,
                time_labels=(),
                error="Artifact must contain a JSON object",
                error_key="report.artifact_invalid_object",
            )
        schema_version = payload.get("schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            if required:
                raise ReportGenerationError(
                    f"unsupported_{artifact}_schema",
                    f"Required {artifact} artifact schema is unsupported.",
                )
            return _Artifact(
                artifact=artifact,
                relative_path=relative_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                schema_version=str(schema_version) if schema_version is not None else None,
                payload=payload,
                parsed=None,
                time_labels=(),
                error="Artifact schema is unsupported",
                error_key="report.artifact_schema_unsupported",
            )
        try:
            parsed = parser.model_validate(payload)
        except ValidationError:
            if required:
                raise ReportGenerationError(
                    f"invalid_{artifact}",
                    f"Required {artifact} artifact is invalid.",
                ) from None
            return _Artifact(
                artifact=artifact,
                relative_path=relative_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                schema_version=str(schema_version),
                payload=payload,
                parsed=None,
                time_labels=(),
                error="Artifact failed schema validation",
                error_key="report.artifact_schema_invalid",
            )
        return _Artifact(
            artifact=artifact,
            relative_path=relative_path,
            sha256=hashlib.sha256(raw).hexdigest(),
            schema_version=str(schema_version),
            payload=payload,
            parsed=parsed,
            time_labels=_artifact_times(parsed),
        )

    def _render(self, data: _ReportData) -> str:
        language = data.language
        sections = [
            self._render_overview(data),
            self._render_status(data),
            self._render_reconciliation(data),
            self._render_spring(data),
            self._render_maven(data),
            self._render_flyway(data),
            self._render_mysql(data),
            self._render_ledger(data),
            self._render_provenance(data),
        ]
        body = "\n".join(sections)
        generated = _e(data.generated_at.isoformat())
        repository_name = Path(data.root).name or data.root
        return f"""<!doctype html>
<html lang="{_e(language)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(message("report.title", language, name=repository_name))}</title>
  <style>{_CSS}</style>
</head>
<body>
  <a class="skip-link" href="#main">{_e(message("report.skip_link", language))}</a>
  <header class="hero">
    <div class="hero-grid">
      <div>
        <p class="eyebrow">{_e(message("report.hero.eyebrow", language))}</p>
        <h1>{_e(message("report.hero.title", language))}</h1>
        <p class="hero-copy">{_e(message("report.hero.copy", language))}</p>
      </div>
      <div class="hero-stamp" aria-label="{_e(message("report.generated_aria", language))}">
        <span>{_e(message("report.generated", language))}</span>
        <strong>{generated}</strong>
        <small>{_e(message("report.tool_version", language, version=__version__))}</small>
      </div>
    </div>
  </header>
  <main id="main" class="shell">
    {body}
  </main>
  <footer class="footer">{_e(message("report.footer", language))}</footer>
  <script>{_JS}</script>
</body>
</html>
"""

    def _render_overview(self, data: _ReportData) -> str:
        language = data.language
        facts = data.static_result.facts
        static_collectors = set(data.static_result.collectors)
        runtime = data.runtime_result
        recon = data.reconciliation_result
        git_commit = _fact_value(facts, "HEAD commit")
        branch = _fact_value(facts, "Current branch")
        stats = [
            ("report.static_facts", str(len(facts)), True),
            (
                "report.runtime_verified_facts",
                str(sum(fact.status == "verified" for fact in runtime.facts))
                if runtime is not None
                else message("report.not_available", language),
                runtime is not None,
            ),
            (
                "report.spring_endpoints",
                str(sum(fact.id.startswith("fact.spring.endpoint.") for fact in facts))
                if "spring_api" in static_collectors
                else message("report.not_available", language),
                "spring_api" in static_collectors,
            ),
            (
                "report.maven_dependencies",
                str(sum(_is_direct_maven_dependency(fact) for fact in facts))
                if "maven_project" in static_collectors
                else message("report.not_available", language),
                "maven_project" in static_collectors,
            ),
            (
                "report.repository_flyway_migrations",
                str(sum(_is_source_migration(fact) for fact in facts))
                if "flyway_migration" in static_collectors
                else message("report.not_available", language),
                "flyway_migration" in static_collectors,
            ),
            (
                "report.mysql_tables",
                str(sum(fact.name == "MySQL base table" for fact in runtime.facts))
                if runtime is not None
                else message("report.not_available", language),
                runtime is not None,
            ),
            (
                "report.drift_findings",
                str(len(recon.findings))
                if recon is not None
                else message("report.not_available", language),
                recon is not None,
            ),
        ]
        stat_cards = "".join(
            f'<article class="stat-card {"available" if available else "unavailable"}">'
            f'<span>{_e(message(label_key, language))}</span><strong>{_e(value)}</strong></article>'
            for label_key, value, available in stats
        )
        content = f"""
        <section class="overview section" id="overview">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.overview.eyebrow", language))}</p><h2>{_e(message("report.overview.title", language))}</h2></div><span class="section-index">01</span></div>
          <div class="identity-grid">
            <div><span class="label">{_e(message("report.repository_path", language))}</span><code>{_e(data.root)}</code></div>
            <div><span class="label">{_e(message("report.display_name", language))}</span><strong>{_e(Path(data.root).name or data.root)}</strong></div>
            <div><span class="label">{_e(message("report.git_commit", language))}</span><code>{_display(git_commit, language)}</code></div>
            <div><span class="label">{_e(message("report.branch", language))}</span><code>{_display(branch, language)}</code></div>
          </div>
          <div class="stat-grid">{stat_cards}</div>
        </section>
        """
        return content

    def _render_status(self, data: _ReportData) -> str:
        language = data.language
        static_counts = _status_counts(data.static_result.facts)
        runtime_counts = _status_counts(data.runtime_result.facts) if data.runtime_result else None
        rows = []
        for status in ("declared", "inferred", "verified", "conflicted"):
            runtime_value = (
                str(runtime_counts[status])
                if runtime_counts is not None
                else message("report.not_available", language)
            )
            rows.append(
                f"<tr><th>{_e(status_label(status, language))}</th><td>{static_counts[status]}</td><td>{_e(runtime_value)}</td></tr>"
            )
        return f"""
        <section class="section" id="evidence-status">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.evidence_status.eyebrow", language))}</p><h2>{_e(message("report.evidence_status.title", language))}</h2></div><span class="section-index">02</span></div>
          <p class="section-note">{_e(message("report.evidence_status.note", language))}</p>
          <div class="table-wrap"><table><thead><tr><th>{_e(message("report.status", language))}</th><th>{_e(message("report.static_scan", language))}</th><th>{_e(message("report.mysql_verification", language))}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
        </section>
        """

    def _render_reconciliation(self, data: _ReportData) -> str:
        language = data.language
        recon = data.reconciliation_result
        if recon is None:
            return self._unavailable_section(
                "reconciliation",
                "03",
                message("report.reconciliation.eyebrow", language),
                message("report.not_available", language),
                _artifact_note(data.reconciliation, language),
                language=language,
            )
        summary = recon.summary
        drift = (
            f'<div class="drift-banner"><span class="drift-dot"></span><strong>{_e(message("report.drift.detected", language))}</strong><span>{_e(message("report.drift.detected.note", language))}</span></div>'
            if summary.drift_detected
            else f'<div class="match-banner"><span class="match-dot"></span><strong>{_e(message("report.drift.none", language))}</strong><span>{_e(message("report.drift.none.note", language))}</span></div>'
        )
        summary_values = [
            ("report.matched", summary.matched),
            ("report.runtime_only", summary.runtime_only),
            ("report.source_only", summary.source_only),
            ("report.version_mismatch", summary.version_mismatch),
            ("report.runtime_failed", summary.runtime_failed),
            ("report.ambiguous", summary.ambiguous),
            ("report.repository_max_version", summary.repository_max_version),
            ("report.runtime_max_successful", summary.runtime_max_successful_version),
            ("report.runtime_baseline", summary.runtime_baseline_version),
        ]
        summary_cards = "".join(
            f'<div class="mini-stat"><span>{_e(message(label_key, language))}</span><strong>{_display(value, language)}</strong></div>'
            for label_key, value in summary_values
        )
        source_versions = _source_versions(data.static_result.facts)
        runtime_versions = _runtime_versions(data.runtime_result.facts) if data.runtime_result else []
        narrative = (
            f'<div class="flyway-compare"><div><span class="label">{_e(message("report.repository_flyway", language))}</span><strong>{_e(_version_range(source_versions) or message("report.not_available", language))}</strong></div>'
            f'<div><span class="label">{_e(message("report.runtime_flyway", language))}</span><strong>{_e(_runtime_version_line(summary.runtime_baseline_version, runtime_versions) or message("report.not_available", language))}</strong></div></div>'
        )
        findings = "".join(
            self._render_finding(finding, language)
            for finding in sorted(recon.findings, key=_finding_sort_key)
        )
        findings = findings or f'<p class="empty-note">{_e(message("report.no_reconciliation_findings", language))}</p>'
        return f"""
        <section class="section section-drift" id="reconciliation">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.reconciliation.eyebrow", language))}</p><h2>{_e(message("report.reconciliation.title", language))}</h2></div><span class="section-index">03</span></div>
          {drift}
          <div class="mini-stat-grid">{summary_cards}</div>
          {narrative}
          <div class="finding-list"><div class="subheading"><h3>{_e(message("report.findings", language))}</h3><span>{_e(message("report.total", language, count=len(recon.findings)))}</span></div>{findings}</div>
        </section>
        """

    def _render_finding(self, finding: Any, language: Language) -> str:
        detail_items = []
        for key in ("source_file", "runtime_script"):
            if key in finding.details:
                detail_items.append(
                    f"<dt>{_e(message(f'report.{key}', language))}</dt>"
                    f"<dd><code>{_display(finding.details[key], language)}</code></dd>"
                )
        refs = "".join(
            f'<li><span>{_e(reference.artifact)} / {_e(reference.reference_type)}</span><code>{_e(reference.id)}</code></li>'
            for reference in finding.references
        )
        fallback_message = str(finding.message)
        rendered_message = finding_message(
            finding.kind,
            language,
            version=finding.version,
            fallback=fallback_message,
        )
        return f"""
        <article class="finding finding-{_e(finding.kind)}">
          <div class="finding-top"><strong>V{_display(finding.version, language)}</strong><span class="status-pill">{_e(finding_label(finding.kind, language))}</span><code>{_e(finding.id)}</code></div>
          <p>{_e(rendered_message)}</p>
          {f'<dl class="compact-dl">{"".join(detail_items)}</dl>' if detail_items else ''}
          <div class="reference-block"><span class="label">{_e(message("report.references", language))}</span><ul>{refs}</ul></div>
        </article>
        """

    def _render_spring(self, data: _ReportData) -> str:
        language = data.language
        if "spring_api" not in data.static_result.collectors:
            return self._unavailable_section(
                "spring",
                "04",
                message("report.spring.eyebrow", language),
                message("report.spring.title", language),
                message("report.artifact_missing", language),
                language=language,
            )
        facts = sorted(
            (fact for fact in data.static_result.facts if fact.id.startswith("fact.spring.endpoint.")),
            key=lambda fact: (
                str(fact.value.get("path", "")),
                str(fact.value.get("method", "")),
                str(fact.value.get("controller", "")),
                fact.id,
            ),
        )
        evidence_by_id = {item.id: item for item in data.static_result.evidence}
        endpoints = "".join(
            self._render_endpoint(fact, evidence_by_id, language) for fact in facts
        )
        return f"""
        <section class="section" id="spring-api">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.spring.eyebrow", language))}</p><h2>{_e(message("report.spring.title", language))}</h2></div><span class="section-index">04</span></div>
          <div class="section-toolbar"><p>{_e(message("report.spring.toolbar", language, count=len(facts)))}</p><label>{_e(message("report.filter_endpoints", language))} <input type="search" data-endpoint-filter placeholder="{_e(message("report.filter_placeholder", language))}" aria-label="{_e(message("report.filter_aria", language))}"></label></div>
          <div class="endpoint-list">{endpoints or f'<p class="empty-note">{_e(message("report.no_endpoint_facts", language))}</p>'}</div>
        </section>
        """

    def _render_endpoint(
        self,
        fact: Fact,
        evidence_by_id: Mapping[str, Evidence],
        language: Language,
    ) -> str:
        value = fact.value if isinstance(fact.value, dict) else {}
        linked = [evidence_by_id[item] for item in fact.evidence_ids if item in evidence_by_id]
        source = next((item.value.get("source_file") for item in linked if isinstance(item.value, dict)), None)
        line = next((item.value.get("start_line") for item in linked if isinstance(item.value, dict)), None)
        annotations = "".join(
            f'<li><span>{_e(item.value.get("annotation_type", item.kind))}</span> <code>{_e(item.value.get("annotation_text", ""))}</code></li>'
            for item in linked
            if isinstance(item.value, dict) and item.kind == "spring_annotation"
        )
        evidence_rows = "".join(
            f'<li><code>{_e(item.id)}</code><span>{_e(item.kind)} · {_e(item.source)}</span></li>'
            for item in linked
        )
        return f"""
        <details class="endpoint-row" data-endpoint-row>
          <summary><span class="method method-{_e(str(value.get("method", "")).lower())}">{_e(value.get("method"))}</span><code>{_e(value.get("path"))}</code><span>{_e(value.get("controller"))}</span><span>{_e(value.get("handler"))}</span><span class="status-pill">{_e(status_label(fact.status, language))}</span></summary>
          <div class="detail-grid">
            <div><span class="label">{_e(message("report.fact_id", language))}</span><code>{_e(fact.id)}</code></div>
            <div><span class="label">{_e(message("report.source_location", language))}</span><code>{_display(source, language)}{f' · {_e(message("report.line", language, value=line))}' if line is not None else ''}</code></div>
            <div><span class="label">{_e(message("report.evidence_ids", language))}</span><ul class="plain-list">{evidence_rows}</ul></div>
            <div><span class="label">{_e(message("report.annotation_information", language))}</span><ul class="plain-list">{annotations or f'<li>{_e(message("report.not_available", language))}</li>'}</ul></div>
          </div>
        </details>
        """

    def _render_maven(self, data: _ReportData) -> str:
        language = data.language
        if "maven_project" not in data.static_result.collectors:
            return self._unavailable_section(
                "maven",
                "05",
                message("report.maven.eyebrow", language),
                message("report.maven.title", language),
                message("report.artifact_missing", language),
                language=language,
            )
        facts = sorted((fact for fact in data.static_result.facts if fact.id.startswith("fact.maven.")), key=lambda fact: fact.id)
        groups: list[tuple[str, list[Fact]]] = [
            ("report.project_coordinates", [fact for fact in facts if fact.id.startswith("fact.maven.project.")]),
            ("report.java_declarations", [fact for fact in facts if fact.id.startswith("fact.maven.java_baseline.") or fact.id.startswith("fact.maven.property.")]),
            ("report.spring_boot_parent", [fact for fact in facts if fact.id.startswith("fact.maven.parent.") or fact.id.startswith("fact.maven.spring_boot.")]),
            ("report.dependencies", [fact for fact in facts if fact.id.startswith("fact.maven.dependency.") and fact.value.get("location") == "dependencies"]),
            ("report.dependency_management", [fact for fact in facts if fact.id.startswith("fact.maven.dependency.") and fact.value.get("location") == "dependencyManagement"]),
            ("report.plugins", [fact for fact in facts if fact.id.startswith("fact.maven.plugin.")]),
            ("report.modules", [fact for fact in facts if fact.id.startswith("fact.maven.module.")]),
        ]
        groups_html = "".join(
            f'<div class="maven-group"><div class="subheading"><h3>{_e(message(title_key, language))}</h3><span>{len(items)}</span></div>{self._render_maven_table(items, language)}</div>'
            for title_key, items in groups
        )
        return f"""
        <section class="section" id="maven">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.maven.eyebrow", language))}</p><h2>{_e(message("report.maven.title", language))}</h2></div><span class="section-index">05</span></div>
          <p class="section-note">{_e(message("report.maven.note", language))}</p>
          {groups_html}
        </section>
        """

    @staticmethod
    def _render_maven_table(facts: list[Fact], language: Language) -> str:
        if not facts:
            return f'<p class="empty-note">{_e(message("report.no_declarations", language))}</p>'
        rows = []
        for fact in facts:
            value = fact.value if isinstance(fact.value, dict) else {}
            subject = value.get("artifact_id") or value.get("source") or value.get("declared_field") or fact.name
            detail = value.get("resolved_value") or value.get("declared_value") or value.get("resolved_version") or value.get("declared_version") or value.get("module") or "—"
            rows.append(
                f'<tr><td><strong>{_e(subject)}</strong><br><code>{_e(fact.id)}</code></td><td>{_display(detail, language)}</td><td><span class="status-pill">{_e(status_label(fact.status, language))}</span></td></tr>'
            )
        return f'<div class="table-wrap"><table><thead><tr><th>{_e(message("report.declaration", language))}</th><th>{_e(message("report.value", language))}</th><th>{_e(message("report.status", language))}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'

    def _render_flyway(self, data: _ReportData) -> str:
        language = data.language
        if "flyway_migration" not in data.static_result.collectors:
            return self._unavailable_section(
                "flyway",
                "06",
                message("report.flyway.eyebrow", language),
                message("report.flyway.title", language),
                message("report.artifact_missing", language),
                language=language,
            )
        migration_facts = sorted(
            (fact for fact in data.static_result.facts if _is_source_migration(fact) or _is_repeatable_migration(fact)),
            key=lambda fact: (_version_sort_key(fact.value.get("version")), fact.id),
        )
        rows = []
        for fact in migration_facts:
            value = fact.value if isinstance(fact.value, dict) else {}
            rows.append(
                f'<tr><td><code>{_display(value.get("version"), language)}</code></td><td>{_e(value.get("type"))}</td><td>{_e(value.get("source_file"))}</td><td><code>{_e(value.get("file_sha256"))}</code></td><td><span class="status-pill">{_e(status_label(fact.status, language))}</span></td></tr>'
            )
        set_facts = sorted(
            (fact for fact in data.static_result.facts if fact.name == "Flyway migration set summary"),
            key=lambda fact: fact.id,
        )
        set_rows = "".join(
            f'<tr><td><code>{_e(fact.value.get("migration_set"))}</code></td><td>{_display(fact.value.get("versioned_count"), language)}</td><td>{_display(fact.value.get("repeatable_count"), language)}</td><td><code>{_json_inline(fact.value.get("ordered_versions", []))}</code></td></tr>'
            for fact in set_facts
        )
        return f"""
        <section class="section" id="flyway">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.flyway.eyebrow", language))}</p><h2>{_e(message("report.flyway.title", language))}</h2></div><span class="section-index">06</span></div>
          <p class="section-note">{_e(message("report.flyway.note", language))}</p>
          <div class="table-wrap"><table><thead><tr><th>{_e(message("report.version", language))}</th><th>{_e(message("report.type", language))}</th><th>{_e(message("report.source_filename", language))}</th><th>{_e(message("report.file_sha256", language))}</th><th>{_e(message("report.status", language))}</th></tr></thead><tbody>{"".join(rows) or f'<tr><td colspan="5">{_e(message("report.no_migrations", language))}</td></tr>'}</tbody></table></div>
          <div class="subheading"><h3>{_e(message("report.migration_sets", language))}</h3><span>{len(set_facts)}</span></div>
          <div class="table-wrap"><table><thead><tr><th>{_e(message("report.migration_set", language))}</th><th>{_e(message("report.versioned", language))}</th><th>{_e(message("report.repeatable", language))}</th><th>{_e(message("report.ordered_versions", language))}</th></tr></thead><tbody>{set_rows or f'<tr><td colspan="4">{_e(message("report.no_migration_set_summaries", language))}</td></tr>'}</tbody></table></div>
        </section>
        """

    def _render_mysql(self, data: _ReportData) -> str:
        language = data.language
        runtime = data.runtime_result
        if runtime is None:
            return self._unavailable_section(
                "mysql",
                "07",
                message("report.mysql.eyebrow", language),
                message("report.not_available", language),
                _artifact_note(data.runtime, language),
                language=language,
            )
        facts = runtime.facts
        server = _fact_value(facts, "MySQL server version")
        database = _fact_value(facts, "Selected MySQL database")
        tables = sorted((fact for fact in facts if fact.name == "MySQL base table"), key=lambda fact: fact.id)
        columns = sorted((fact for fact in facts if fact.name == "MySQL column"), key=lambda fact: fact.id)
        constraints = sorted((fact for fact in facts if fact.name == "MySQL constraint"), key=lambda fact: fact.id)
        indexes = sorted((fact for fact in facts if fact.name == "MySQL index"), key=lambda fact: fact.id)
        history = sorted((fact for fact in facts if fact.name == "Flyway runtime migration history"), key=lambda fact: (int(fact.value.get("installed_rank", 0)), fact.id))
        constraint_counts = {kind: sum(fact.value.get("constraint_type") == kind for fact in constraints) for kind in ("PRIMARY KEY", "UNIQUE", "FOREIGN KEY")}
        table_names = "".join(f'<span class="tag"><code>{_e(fact.value.get("table_name"))}</code></span>' for fact in tables)
        history_rows = "".join(
            f'<tr><td>{_display(fact.value.get("installed_rank"), language)}</td><td><code>{_display(fact.value.get("version"), language)}</code></td><td>{_e(fact.value.get("description"))}</td><td><code>{_e(fact.value.get("script"))}</code></td><td>{_e(message("report.success" if fact.value.get("success") else "report.failed", language))}</td></tr>'
            for fact in history
        )
        counts = [
            ("report.tables", len(tables)),
            ("report.columns", len(columns)),
            ("report.primary_key", constraint_counts["PRIMARY KEY"]),
            ("report.unique", constraint_counts["UNIQUE"]),
            ("report.foreign_key", constraint_counts["FOREIGN KEY"]),
            ("report.indexes", len(indexes)),
        ]
        count_html = "".join(
            f'<div class="mini-stat"><span>{_e(message(label_key, language))}</span><strong>{count}</strong></div>'
            for label_key, count in counts
        )
        return f"""
        <section class="section" id="mysql-runtime">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.mysql.eyebrow", language))}</p><h2>{_e(message("report.mysql.title", language))}</h2></div><span class="section-index">07</span></div>
          <div class="runtime-banner"><strong>{_e(message("report.verified_runtime", language))}</strong><span>{_e(message("report.observed", language, value=_display(runtime.metadata.observed_at or runtime.metadata.finished_at, language)))}</span></div>
          <div class="identity-grid"><div><span class="label">{_e(message("report.server_version", language))}</span><strong>{_display(server, language)}</strong></div><div><span class="label">{_e(message("report.selected_database", language))}</span><strong>{_display(database, language)}</strong></div></div>
          <div class="mini-stat-grid">{count_html}</div>
          <div class="subheading"><h3>{_e(message("report.base_tables", language))}</h3><span>{_e(message("report.table_columns", language, tables=len(tables), columns=len(columns)))}</span></div>
          <div class="tag-list">{table_names or f'<span class="empty-note">{_e(message("report.no_tables", language))}</span>'}</div>
          <div class="subheading"><h3>{_e(message("report.flyway_runtime_history", language))}</h3><span>{_e(message("report.rows", language, count=len(history)))}</span></div>
          <div class="table-wrap"><table><thead><tr><th>{_e(message("report.rank", language))}</th><th>{_e(message("report.version", language))}</th><th>{_e(message("report.description", language))}</th><th>{_e(message("report.script", language))}</th><th>{_e(message("report.result", language))}</th></tr></thead><tbody>{history_rows or f'<tr><td colspan="5">{_e(message("report.no_flyway_history", language))}</td></tr>'}</tbody></table></div>
        </section>
        """

    def _render_ledger(self, data: _ReportData) -> str:
        language = data.language
        evidence_by_id = {item.id: item for item in data.static_result.evidence}
        facts = [("static_scan", fact) for fact in sorted(data.static_result.facts, key=lambda fact: fact.id)]
        if data.runtime_result is not None:
            facts.extend(("mysql_verification", fact) for fact in sorted(data.runtime_result.facts, key=lambda fact: fact.id))
            evidence_by_id.update({item.id: item for item in data.runtime_result.evidence})
        blocks = "".join(
            self._render_fact_ledger(artifact, fact, evidence_by_id, language)
            for artifact, fact in facts
        )
        return f"""
        <section class="section" id="ledger">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.ledger.eyebrow", language))}</p><h2>{_e(message("report.ledger.title", language))}</h2></div><span class="section-index">08</span></div>
          <p class="section-note">{_e(message("report.ledger.note", language))}</p>
          <div class="ledger">{blocks or f'<p class="empty-note">{_e(message("report.no_facts", language))}</p>'}</div>
        </section>
        """

    @staticmethod
    def _render_fact_ledger(
        artifact: str,
        fact: Fact,
        evidence_by_id: Mapping[str, Evidence],
        language: Language,
    ) -> str:
        evidence_blocks = []
        for evidence_id in sorted(fact.evidence_ids):
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                evidence_blocks.append(
                    f'<li><code>{_e(evidence_id)}</code><span>{_e(message("report.not_available", language))}</span></li>'
                )
                continue
            evidence_blocks.append(
                f'<li><details><summary><code>{_e(evidence.id)}</code> <span>{_e(evidence.kind)}</span></summary><div class="evidence-detail"><p><span class="label">{_e(message("report.source", language))}</span> {_e(evidence.source)}</p>{_json_block(evidence.value)}</div></details></li>'
            )
        return f"""
        <details class="fact-row">
          <summary><span class="status-dot status-{_e(fact.status)}"></span><span class="status-pill">{_e(status_label(fact.status, language))}</span><code>{_e(fact.id)}</code><span>{_e(fact.name)}</span><em>{_e(artifact)}</em></summary>
          <div class="fact-detail"><div class="detail-grid"><div><span class="label">{_e(message("report.fact_id", language))}</span><code>{_e(fact.id)}</code></div><div><span class="label">{_e(message("report.status", language))}</span><span class="status-pill">{_e(status_label(fact.status, language))}</span></div><div><span class="label">{_e(message("report.structured_value", language))}</span>{_json_block(fact.value)}</div><div><span class="label">{_e(message("report.evidence_ids", language))}</span><ul class="plain-list">{"".join(evidence_blocks) or f'<li>{_e(message("report.not_available", language))}</li>'}</ul></div></div></div>
        </details>
        """

    def _render_provenance(self, data: _ReportData) -> str:
        language = data.language
        artifacts = (data.static, data.runtime, data.reconciliation)
        rows = []
        for artifact in artifacts:
            if artifact.sha256:
                times = " · ".join(
                    f"{_e(_time_label(label, language))}: {_e(value)}"
                    for label, value in artifact.time_labels
                ) or _e(message("report.not_available", language))
                rows.append(
                    f'<tr><td><code>{_e(artifact.relative_path)}</code></td><td>{_e(artifact.artifact)}</td><td><code>{_e(artifact.schema_version)}</code></td><td><code>{_e(artifact.sha256)}</code></td><td>{times}</td></tr>'
                )
            else:
                rows.append(
                    f'<tr><td><code>{_e(artifact.relative_path)}</code></td><td>{_e(artifact.artifact)}</td><td colspan="3"><span class="unavailable">{_e(message("report.not_available", language))}</span></td></tr>'
                )
        return f"""
        <section class="section" id="provenance">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.provenance.eyebrow", language))}</p><h2>{_e(message("report.provenance.title", language))}</h2></div><span class="section-index">09</span></div>
          <p class="section-note">{_e(message("report.provenance.note", language))}</p>
          <div class="table-wrap"><table><thead><tr><th>{_e(message("report.path", language))}</th><th>{_e(message("report.artifact", language))}</th><th>{_e(message("report.schema", language))}</th><th>{_e(message("report.sha256", language))}</th><th>{_e(message("report.snapshot_time", language))}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
        </section>
        """

    @staticmethod
    def _unavailable_section(
        section_id: str,
        index: str,
        eyebrow: str,
        title: str,
        note: str,
        *,
        language: Language,
    ) -> str:
        return f"""
        <section class="section unavailable-section" id="{section_id}">
          <div class="section-heading"><div><p class="eyebrow">{_e(eyebrow)}</p><h2>{_e(title)}</h2></div><span class="section-index">{_e(index)}</span></div>
          <div class="empty-state"><strong>{_e(title)}</strong><span>{_e(note)}</span></div>
        </section>
        """


def _artifact_times(parsed: object) -> tuple[tuple[str, str], ...]:
    metadata = getattr(parsed, "metadata", None)
    if metadata is None:
        return ()
    values: list[tuple[str, str]] = []
    for label, field in (("Started", "started_at"), ("Finished", "finished_at"), ("Observed", "observed_at")):
        value = getattr(metadata, field, None)
        if value is not None:
            values.append((label, value.isoformat() if isinstance(value, datetime) else str(value)))
    return tuple(values)


def _time_label(label: str, language: Language) -> str:
    if label == "Observed":
        return message("report.observed_label", language)
    return message(f"report.{label.lower()}", language)


def _artifact_note(artifact: _Artifact, language: Language) -> str:
    if artifact.error_key is not None:
        return message(artifact.error_key, language)
    return artifact.error or message("report.not_available", language)


def _e(value: object) -> str:
    sanitized = _sanitize(value)
    if sanitized is None:
        text = ""
    elif isinstance(sanitized, (Mapping, list, tuple)):
        text = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, default=str)
    else:
        text = str(sanitized)
    return escape(text, quote=True)


def _display(value: object, language: Language = "en") -> str:
    return _e(
        message("report.not_available", language)
        if value is None or value == ""
        else value
    )


def _sanitize(value: object) -> object:
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            sanitized[key_text] = "[redacted]" if _SENSITIVE_KEY.search(key_text) else _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _SENSITIVE_ASSIGNMENT.sub(r"\g<key>\1[redacted]", value)
    return value


def _json_text(value: object) -> str:
    return json.dumps(_sanitize(value), ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _json_block(value: object) -> str:
    return f'<pre class="code-block">{_e(_json_text(value))}</pre>'


def _json_inline(value: object) -> str:
    return _e(json.dumps(_sanitize(value), ensure_ascii=False, sort_keys=True, default=str))


def _fact_value(facts: list[Fact], name: str) -> object | None:
    fact = next((item for item in facts if item.name == name), None)
    if fact is None:
        return None
    if isinstance(fact.value, dict) and len(fact.value) == 1:
        return next(iter(fact.value.values()))
    return fact.value


def _status_counts(facts: list[Fact]) -> dict[str, int]:
    return {status: sum(fact.status == status for fact in facts) for status in ("declared", "inferred", "verified", "conflicted")}


def _is_source_migration(fact: Fact) -> bool:
    return fact.name == "Flyway migration declaration" and isinstance(fact.value, dict) and fact.value.get("type") == "versioned"


def _is_repeatable_migration(fact: Fact) -> bool:
    return fact.name == "Flyway migration declaration" and isinstance(fact.value, dict) and fact.value.get("type") == "repeatable"


def _is_direct_maven_dependency(fact: Fact) -> bool:
    return (
        fact.id.startswith("fact.maven.dependency.")
        and isinstance(fact.value, dict)
        and fact.value.get("location") == "dependencies"
    )


def _version_sort_key(value: object) -> tuple[int, ...]:
    if value is None:
        return (2**31,)
    parts = re.split(r"[._]", str(value))
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return (2**31,)


def _source_versions(facts: list[Fact]) -> list[str]:
    versions = [str(fact.value.get("version")) for fact in facts if _is_source_migration(fact)]
    return sorted(versions, key=lambda value: (_version_sort_key(value), value))


def _runtime_versions(facts: list[Fact]) -> list[str]:
    versions = [
        str(fact.value.get("version"))
        for fact in facts
        if fact.name == "Flyway runtime migration history"
        and isinstance(fact.value, dict)
        and fact.value.get("success")
        and not _is_runtime_baseline(fact.value)
    ]
    return sorted(versions, key=lambda value: (_version_sort_key(value), value))


def _is_runtime_baseline(value: object) -> bool:
    if not isinstance(value, dict) or str(value.get("version")) != "0":
        return False
    return str(value.get("type", "")).upper() == "BASELINE" or value.get("script") == "<< Flyway Baseline >>" or value.get("description") == "<< Flyway Baseline >>"


def _version_range(versions: list[str]) -> str:
    if not versions:
        return ""
    if len(versions) == 1:
        return f"V{versions[0]}"
    return f"V{versions[0]}–V{versions[-1]}"


def _runtime_version_line(baseline: str | None, versions: list[str]) -> str:
    pieces = []
    if baseline is not None:
        pieces.append(f"Baseline {baseline}")
    if versions:
        pieces.append(_version_range(versions))
    return " + ".join(pieces)


def _finding_sort_key(finding: Any) -> tuple[tuple[int, ...], str]:
    return tuple(finding.version_key), finding.id


_CSS = r"""
:root{--ink:#0b1f33;--ink-2:#173b52;--paper:#f6f3ec;--surface:#fffdf8;--rule:#d8dedc;--muted:#607078;--teal:#087f73;--teal-soft:#d9f0ea;--amber:#a65413;--amber-soft:#fff0dd;--red:#a52b32;--blue:#236b91;--shadow:0 12px 34px rgba(11,31,51,.08)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:16px;line-height:1.55}code,pre,input,.eyebrow,.section-index,.status-pill,.method{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}code{overflow-wrap:anywhere}h1,h2,h3,p{margin-top:0}h1{max-width:720px;margin-bottom:20px;font-size:clamp(2.6rem,6vw,5.4rem);line-height:.98;letter-spacing:-.065em;font-weight:720}h2{font-size:clamp(1.55rem,2.6vw,2.45rem);line-height:1.08;letter-spacing:-.04em;margin-bottom:0}h3{font-size:1.03rem;margin-bottom:0}.hero{background:var(--ink);color:#f3f7f4;padding:clamp(34px,6vw,84px) max(24px,calc((100vw - 1180px)/2));position:relative;overflow:hidden}.hero:after{content:"";position:absolute;width:520px;height:520px;border:1px solid rgba(95,212,188,.22);border-radius:50%;right:-140px;top:-270px;box-shadow:0 0 0 34px rgba(95,212,188,.03),0 0 0 68px rgba(95,212,188,.02)}.hero-grid{max-width:1180px;margin:auto;display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:48px;align-items:end;position:relative;z-index:1}.eyebrow{font-size:.72rem;letter-spacing:.15em;font-weight:700;color:var(--teal);margin-bottom:12px}.hero .eyebrow{color:#73d4bf}.hero-copy{max-width:660px;color:#c4d1d3;font-size:1.08rem}.hero-stamp{border-left:1px solid #385262;padding-left:20px;display:grid;gap:5px;color:#a9c0c3}.hero-stamp strong{color:#fff;font:600 .78rem/1.4 ui-monospace,SFMono-Regular,monospace;overflow-wrap:anywhere}.hero-stamp small{font-size:.78rem}.skip-link{position:absolute;left:-999px;top:8px;background:#fff;color:var(--ink);padding:10px 14px;z-index:10}.skip-link:focus{left:8px}.shell{max-width:1180px;margin:auto;padding:0 24px}.section{padding:72px 0;border-bottom:1px solid var(--rule)}.section-heading{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;margin-bottom:24px}.section-index{color:#93a3a4;font-size:.8rem;letter-spacing:.1em}.section-note{color:var(--muted);max-width:760px}.identity-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:1px;background:var(--rule);border:1px solid var(--rule);box-shadow:var(--shadow);margin:28px 0}.identity-grid>div{background:var(--surface);padding:18px;min-width:0}.label{display:block;text-transform:uppercase;letter-spacing:.09em;font:700 .67rem/1.3 ui-monospace,SFMono-Regular,monospace;color:var(--muted);margin-bottom:7px}.identity-grid code,.identity-grid strong{display:block;overflow-wrap:anywhere}.stat-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px}.stat-card{background:var(--surface);border:1px solid var(--rule);padding:18px 15px;min-height:118px;display:flex;flex-direction:column;justify-content:space-between}.stat-card span,.mini-stat span{font:700 .68rem/1.3 ui-monospace,SFMono-Regular,monospace;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}.stat-card strong{font-size:1.85rem;line-height:1;color:var(--ink);font-variant-numeric:tabular-nums}.stat-card.unavailable strong,.unavailable{color:#8d9797;font-size:1rem}.table-wrap{overflow-x:auto;border:1px solid var(--rule);background:var(--surface);margin:18px 0;box-shadow:0 5px 20px rgba(11,31,51,.04)}table{border-collapse:collapse;width:100%;min-width:620px}th,td{text-align:left;vertical-align:top;padding:13px 15px;border-bottom:1px solid #e6e9e5}th{font:700 .68rem/1.3 ui-monospace,SFMono-Regular,monospace;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);background:#f2f2eb}tr:last-child td{border-bottom:0}.mini-stat-grid{display:grid;grid-template-columns:repeat(9,minmax(0,1fr));gap:8px;margin:22px 0}.mini-stat{background:rgba(255,253,248,.72);border:1px solid var(--rule);padding:13px;min-height:72px}.mini-stat strong{display:block;margin-top:8px;font-size:1.2rem;line-height:1.05;font-variant-numeric:tabular-nums}.drift-banner,.match-banner,.runtime-banner{display:flex;align-items:center;gap:12px;padding:15px 18px;margin:22px 0;border:1px solid}.drift-banner{background:var(--amber-soft);border-color:#e1b98f;color:#6f330f}.match-banner{background:var(--teal-soft);border-color:#a6d8cc;color:#065b52}.runtime-banner{background:#e6f0f5;border-color:#b9d2df;color:#165375}.drift-banner span:last-child,.match-banner span:last-child,.runtime-banner span{color:var(--muted)}.drift-dot,.match-dot{width:10px;height:10px;border-radius:50%;display:inline-block;flex:0 0 auto}.drift-dot{background:var(--amber)}.match-dot{background:var(--teal)}.flyway-compare{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:22px 0}.flyway-compare>div{background:var(--ink);color:#f4f8f2;padding:20px}.flyway-compare .label{color:#8fb4b4}.finding-list{margin-top:30px}.subheading{display:flex;justify-content:space-between;align-items:baseline;gap:16px;margin:30px 0 12px}.subheading span{font:700 .7rem ui-monospace,monospace;color:var(--muted)}.finding{background:var(--surface);border:1px solid var(--rule);padding:18px 20px;margin:10px 0}.finding-runtime_only,.finding-version_mismatch,.finding-runtime_failed,.finding-ambiguous{border-left:4px solid var(--amber)}.finding-source_only{border-left:4px solid var(--blue)}.finding-matched{border-left:4px solid var(--teal)}.finding-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.finding-top>strong{font-size:1.2rem}.finding-top>code{margin-left:auto;color:var(--muted);font-size:.72rem}.status-pill{display:inline-flex;align-items:center;border:1px solid #bdcbc6;padding:3px 7px;font-size:.67rem;line-height:1.2;letter-spacing:.02em;color:#315650;background:#eef5f1}.status-conflicted,.finding-runtime_failed .status-pill,.finding-ambiguous .status-pill{color:var(--red);background:#fff0f0;border-color:#e4b4b7}.status-verified{color:var(--teal)}.status-declared{color:#76551c}.status-inferred{color:#236b91}.compact-dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 14px;margin:12px 0}.compact-dl dt{color:var(--muted);text-transform:capitalize}.compact-dl dd{margin:0}.reference-block{border-top:1px solid var(--rule);padding-top:12px;margin-top:14px}.reference-block ul{list-style:none;padding:0;margin:8px 0 0;display:grid;gap:6px}.reference-block li{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.reference-block li span{font-size:.78rem;color:var(--muted)}.section-toolbar{display:flex;justify-content:space-between;gap:20px;align-items:end;color:var(--muted);margin-bottom:15px}.section-toolbar p{margin:0;max-width:650px}.section-toolbar label{font:700 .7rem ui-monospace,monospace;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);display:grid;gap:7px;min-width:250px}.section-toolbar input{font:400 .9rem system-ui,sans-serif;padding:10px 12px;border:1px solid #aebdba;background:var(--surface);color:var(--ink);min-height:44px}.section-toolbar input:focus{outline:3px solid rgba(8,127,115,.3);outline-offset:2px}.endpoint-list{display:grid;gap:8px}.endpoint-row,.fact-row{background:var(--surface);border:1px solid var(--rule);box-shadow:0 4px 14px rgba(11,31,51,.03)}.endpoint-row[open],.fact-row[open]{border-color:#8bbeb4}.endpoint-row summary,.fact-row summary{cursor:pointer;list-style:none;min-height:50px;padding:12px 15px;display:grid;grid-template-columns:80px minmax(150px,2fr) 1fr 1fr 100px;gap:12px;align-items:center}.endpoint-row summary::-webkit-details-marker,.fact-row summary::-webkit-details-marker{display:none}.endpoint-row summary:before,.fact-row summary:before{content:"+";color:var(--teal);font:700 1.1rem ui-monospace,monospace}.endpoint-row[open] summary:before,.fact-row[open] summary:before{content:"−"}.endpoint-row summary code{overflow-wrap:anywhere}.method{font-size:.72rem;font-weight:700;color:#fff;padding:4px 7px;background:var(--ink-2);width:max-content}.method-get{background:var(--teal)}.method-post{background:#236b91}.method-put{background:#7759a7}.method-delete{background:var(--red)}.method-patch{background:#a65413}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;border-top:1px solid var(--rule);padding:20px}.detail-grid>div{min-width:0}.plain-list{padding:0;margin:0;list-style:none;display:grid;gap:7px}.plain-list li{display:flex;gap:10px;flex-wrap:wrap;align-items:baseline}.evidence-detail{padding:12px 14px;border-top:1px solid var(--rule)}.code-block{white-space:pre-wrap;word-break:break-word;background:#edf0eb;padding:14px;border:1px solid #dce3dc;margin:8px 0;max-height:340px;overflow:auto;font:400 .76rem/1.55 ui-monospace,monospace;color:#1b3544}.maven-group{margin-top:26px}.empty-note,.empty-state{color:var(--muted)}.empty-state{border:1px dashed #bbc7c3;background:rgba(255,253,248,.5);padding:24px;display:grid;gap:5px}.tag-list{display:flex;flex-wrap:wrap;gap:8px;margin:15px 0}.tag{border:1px solid #b9cbc5;background:var(--teal-soft);padding:7px 10px}.ledger{display:grid;gap:8px}.fact-row summary{grid-template-columns:12px 95px minmax(200px,2fr) minmax(180px,2fr) 150px}.fact-row summary em{font:400 .72rem ui-monospace,monospace;color:var(--muted);font-style:normal;text-align:right}.status-dot{width:8px;height:8px;border-radius:50%;display:block}.status-declared{background:#b17818}.status-inferred{background:#236b91}.status-verified{background:var(--teal)}.status-conflicted{background:var(--red)}.fact-detail{border-top:1px solid var(--rule);padding:20px}.footer{max-width:1180px;margin:auto;padding:28px 24px 64px;color:var(--muted);font-size:.82rem}.endpoint-row:focus-within,.fact-row:focus-within,summary:focus-visible{outline:3px solid rgba(8,127,115,.28);outline-offset:2px}@media(max-width:1050px){.stat-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.mini-stat-grid{grid-template-columns:repeat(5,minmax(0,1fr))}.identity-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:720px){body{font-size:16px}.hero-grid{grid-template-columns:1fr;gap:28px}.hero-stamp{border-left:0;border-top:1px solid #385262;padding:15px 0 0}.section{padding:48px 0}.stat-grid,.mini-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.identity-grid,.flyway-compare,.detail-grid{grid-template-columns:1fr}.section-toolbar{display:grid;align-items:stretch}.section-toolbar label{min-width:0}.endpoint-row summary,.fact-row summary{grid-template-columns:32px 1fr 1fr;gap:8px}.endpoint-row summary .method{grid-column:2}.endpoint-row summary code{grid-column:2 / -1}.endpoint-row summary span:nth-of-type(2),.endpoint-row summary span:nth-of-type(3){grid-column:2}.endpoint-row summary .status-pill{grid-column:3;grid-row:3}.fact-row summary{grid-template-columns:12px 90px 1fr}.fact-row summary code{grid-column:3}.fact-row summary span:last-of-type{grid-column:3}.fact-row summary em{grid-column:3;text-align:left}.shell{padding:0 16px}.footer{padding-left:16px;padding-right:16px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.endpoint-row,.fact-row{transition:none}}
"""

_JS = r"""
(() => {
  const input = document.querySelector('[data-endpoint-filter]');
  if (!input) return;
  const rows = Array.from(document.querySelectorAll('[data-endpoint-row]'));
  input.addEventListener('input', () => {
    const query = input.value.trim().toLowerCase();
    rows.forEach((row) => {
      row.hidden = query !== '' && !row.textContent.toLowerCase().includes(query);
    });
  });
})();
"""
