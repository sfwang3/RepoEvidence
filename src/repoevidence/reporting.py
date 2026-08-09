# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from repoevidence.artifact_io import atomic_write_text
from repoevidence.assessment import CheckAssessment, CheckState, assess_repository
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
from repoevidence.report_html import ReportHtmlRenderer
from repoevidence.report_manifest import (
    build_report_manifest,
    write_report_manifest,
)
from repoevidence.report_view import (
    AttentionItem,
    ReportViewModel,
    ReportViewModelBuilder,
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
    view: ReportViewModel


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
        atomic_write_text(output_path, self._render(data))
        manifest = build_report_manifest(
            root,
            generated_at=data.generated_at,
            language=data.language,
            output_path=output_path,
        )
        write_report_manifest(root, manifest)
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
        assessment = assess_repository(root)
        view = ReportViewModelBuilder().build(
            assessment,
            generated_at=timestamp,
            language=language,
        )
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
            view=view,
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
        sections = [
            self._render_summary(data),
            self._render_coverage(data),
            self._render_attention(data),
            self._render_overview(data),
            self._render_reconciliation(data),
            self._render_spring(data),
            self._render_maven(data),
            self._render_flyway(data),
            self._render_mysql(data),
            self._render_status(data),
            self._render_ledger(data),
            self._render_provenance(data),
        ]
        body = "\n".join(sections)
        return ReportHtmlRenderer().render(data.view, body)

    def _render_summary(self, data: _ReportData) -> str:
        view = data.view
        language = data.language
        conclusion = view.conclusion
        title = message(
            f"report.conclusion.{conclusion.kind.value}.title",
            language,
            count=conclusion.drift_count,
        )
        body = message(
            f"report.conclusion.{conclusion.kind.value}.body",
            language,
            count=conclusion.drift_count,
        )
        return f"""
        <section class="section summary-section" id="summary">
          <div class="conclusion-layout">
            <div class="conclusion-card">
              <div><p class="eyebrow">{_e(message("report.summary.eyebrow", language))}</p><h2>{_e(title)}</h2></div>
              <p>{_e(body)}</p>
            </div>
            <aside class="boundary-card"><div><span class="label">{_e(message("report.status", language))}</span><p>{_e(message("report.summary.boundary", language))}</p></div></aside>
          </div>
        </section>
        """

    def _render_coverage(self, data: _ReportData) -> str:
        view = data.view
        language = data.language
        coverage = (
            (
                "source",
                view.assessment.source,
                message(
                    "report.coverage.source.detail",
                    language,
                    facts=view.source.fact_count,
                    time=_check_time(view.assessment.source, language),
                ),
            ),
            (
                "mysql",
                view.assessment.mysql,
                message(
                    "report.coverage.mysql.detail",
                    language,
                    facts=view.runtime.verified_fact_count,
                    time=_check_time(view.assessment.mysql, language),
                ),
            ),
            (
                "reconciliation",
                view.assessment.reconciliation,
                message(
                    "report.coverage.reconciliation.detail",
                    language,
                    time=_check_time(view.assessment.reconciliation, language),
                ),
            ),
        )
        items = []
        for domain, check, detail in coverage:
            key = f"terminal.check.{domain}.{check.state.value}"
            if domain == "source" and check.state is not CheckState.CURRENT:
                key = "terminal.check.source.failed"
            items.append(
                f'<li class="coverage-item state-{_e(check.state.value)}">'
                f'<span class="state-label">{_e(message(f"report.state.{check.state.value}", language))}</span>'
                f'<strong>{_e(message(key, language))}</strong><p>{_e(detail)}</p></li>'
            )
        return f"""
        <section class="section" id="coverage">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.coverage.eyebrow", language))}</p><h2>{_e(message("report.coverage.title", language))}</h2></div><span class="section-index">02</span></div>
          <ol class="coverage-list">{"".join(items)}</ol>
        </section>
        """

    def _render_attention(self, data: _ReportData) -> str:
        view = data.view
        language = data.language
        rendered_items = "".join(
            self._render_attention_item(item, language)
            for item in view.attention_items
        )
        if not rendered_items:
            rendered_items = (
                f'<li class="empty-state">{_e(message("report.attention.empty", language))}</li>'
            )
        action = view.next_action
        command = (
            f'<code class="command">{_e(shlex.join(action.command))}</code>'
            if action.command is not None
            else ""
        )
        return f"""
        <section class="section" id="attention">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.attention.eyebrow", language))}</p><h2>{_e(message("report.attention.title", language))}</h2></div><span class="section-index">03</span></div>
          <div class="attention-layout"><ul class="attention-list">{rendered_items}</ul><aside class="boundary-card"><div><strong>{_e(message("report.next.title", language))}</strong><p>{_e(message(f"report.next.{action.kind.value}", language))}</p>{command}</div></aside></div>
        </section>
        """

    @staticmethod
    def _render_attention_item(item: AttentionItem, language: Language) -> str:
        detail_codes = tuple(
            dict.fromkeys(
                (
                    *item.error_codes,
                    *(item.reason_codes if item.state is CheckState.UNKNOWN else ()),
                )
            )
        )
        details = (
            f'<details><summary>{_e(message("report.technical_details", language))}</summary><code>{_e(" · ".join(detail_codes))}</code></details>'
            if detail_codes
            else ""
        )
        return (
            f'<li class="attention-item kind-{_e(item.kind.value)}">'
            f'{_e(message(f"report.attention.{item.kind.value}", language, count=item.count or 0))}'
            f"{details}</li>"
        )

    def _render_overview(self, data: _ReportData) -> str:
        language = data.language
        view = data.view
        facts = data.static_result.facts
        static_collectors = set(data.static_result.collectors)
        git_commit = _fact_value(facts, "HEAD commit")
        branch = _fact_value(facts, "Current branch")
        stats = [
            ("report.static_facts", str(len(facts)), True),
            (
                "report.spring_endpoints",
                str(view.source.spring_endpoint_count)
                if "spring_api" in static_collectors
                else message("report.not_available", language),
                "spring_api" in static_collectors,
            ),
            (
                "report.maven_dependencies",
                str(view.source.maven_dependency_count)
                if "maven_project" in static_collectors
                else message("report.not_available", language),
                "maven_project" in static_collectors,
            ),
            (
                "report.repository_flyway_migrations",
                str(view.source.flyway_migration_count)
                if "flyway_migration" in static_collectors
                else message("report.not_available", language),
                "flyway_migration" in static_collectors,
            ),
        ]
        stat_cards = "".join(
            f'<article class="stat-card {"available" if available else "unavailable"}">'
            f'<span>{_e(message(label_key, language))}</span><strong>{_e(value)}</strong></article>'
            for label_key, value, available in stats
        )
        content = f"""
        <section class="overview section" id="project">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.project.eyebrow", language))}</p><h2>{_e(message("report.project.title", language))}</h2></div><span class="section-index">04</span></div>
          <div class="identity-grid">
            <div><span class="label">{_e(message("report.repository_path", language))}</span><code>{_e(view.repository.path)}</code></div>
            <div><span class="label">{_e(message("report.display_name", language))}</span><strong>{_e(view.repository.name)}</strong></div>
            <div><span class="label">{_e(message("report.git_commit", language))}</span><code>{_display(git_commit, language)}</code></div>
            <div><span class="label">{_e(message("report.branch", language))}</span><code>{_display(branch, language)}</code></div>
          </div>
          <div class="stat-grid">{stat_cards}</div>
          <div class="identity-grid">
            <div><span class="label">{_e(message("report.runtime_verified_facts", language))}</span><strong>{_display(view.runtime.verified_fact_count if view.runtime.successful else None, language)}</strong></div>
            <div><span class="label">{_e(message("report.mysql_tables", language))}</span><strong>{_display(view.runtime.mysql_table_count if view.runtime.successful else None, language)}</strong></div>
            <div><span class="label">{_e(message("report.drift_findings", language))}</span><strong>{_display(view.conclusion.drift_count if view.conclusion.drift_detected is not None else None, language)}</strong></div>
          </div>
        </section>
        """
        return content

    def _render_status(self, data: _ReportData) -> str:
        language = data.language
        static_counts = _status_counts(data.static_result.facts)
        runtime_counts = (
            _status_counts(data.runtime_result.facts)
            if data.runtime_result is not None and data.view.runtime.successful
            else None
        )
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
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.evidence_status.eyebrow", language))}</p><h2>{_e(message("report.evidence_status.title", language))}</h2></div><span class="section-index">10</span></div>
          <p class="section-note">{_e(message("report.evidence_status.note", language))}</p>
          <div class="table-wrap"><table><thead><tr><th>{_e(message("report.status", language))}</th><th>{_e(message("report.static_scan", language))}</th><th>{_e(message("report.mysql_verification", language))}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
        </section>
        """

    def _render_reconciliation(self, data: _ReportData) -> str:
        language = data.language
        recon = data.reconciliation_result
        reconciliation_state = data.view.assessment.reconciliation.state
        if reconciliation_state is CheckState.STALE and recon is not None:
            fact_ids, evidence_ids = _available_reference_ids(data)
            findings = "".join(
                self._render_finding(
                    finding,
                    language,
                    fact_ids=fact_ids,
                    evidence_ids=evidence_ids,
                )
                for finding in sorted(recon.findings, key=_finding_sort_key)
            )
            summary = recon.summary
            return f"""
            <section class="section section-drift" id="reconciliation">
              <div class="section-heading"><div><p class="eyebrow">{_e(message("report.reconciliation.eyebrow", language))}</p><h2>{_e(message("report.reconciliation.stale.title", language))}</h2></div><span class="section-index">05</span></div>
              <div class="stale-banner"><strong>{_e(message("terminal.check.reconciliation.stale", language))}</strong><span>{_e(message("report.reconciliation.stale.note", language))}</span></div>
              <details class="recorded-comparison"><summary>{_e(message("report.reconciliation.recorded_disclosure", language))}</summary><div><p>{_e(message("report.reconciliation.stale.note", language))}</p><p>{_e(message("terminal.reconciliation.counts", language, matched=summary.matched, runtime_only=summary.runtime_only, source_only=summary.source_only))}</p><div class="finding-list">{findings or f'<p class="empty-note">{_e(message("report.no_reconciliation_findings", language))}</p>'}</div></div></details>
            </section>
            """
        if reconciliation_state is not CheckState.CURRENT or recon is None:
            return self._unavailable_section(
                "reconciliation",
                "05",
                message("report.reconciliation.eyebrow", language),
                message("report.not_available", language),
                message("report.reconciliation.failed.note", language),
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
        fact_ids, evidence_ids = _available_reference_ids(data)
        findings = "".join(
            self._render_finding(
                finding,
                language,
                fact_ids=fact_ids,
                evidence_ids=evidence_ids,
            )
            for finding in sorted(recon.findings, key=_finding_sort_key)
        )
        findings = findings or f'<p class="empty-note">{_e(message("report.no_reconciliation_findings", language))}</p>'
        return f"""
        <section class="section section-drift" id="reconciliation">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.reconciliation.eyebrow", language))}</p><h2>{_e(message("report.reconciliation.title", language))}</h2></div><span class="section-index">05</span></div>
          {drift}
          <div class="mini-stat-grid">{summary_cards}</div>
          {narrative}
          <div class="finding-list"><div class="subheading"><h3>{_e(message("report.findings", language))}</h3><span>{_e(message("report.total", language, count=len(recon.findings)))}</span></div>{findings}</div>
        </section>
        """

    def _render_finding(
        self,
        finding: Any,
        language: Language,
        *,
        fact_ids: set[str],
        evidence_ids: set[str],
    ) -> str:
        detail_items = []
        for key in ("source_file", "runtime_script"):
            if key in finding.details:
                detail_items.append(
                    f"<dt>{_e(message(f'report.{key}', language))}</dt>"
                    f"<dd><code>{_display(finding.details[key], language)}</code></dd>"
                )
        refs = "".join(
            self._render_finding_reference(
                reference,
                fact_ids=fact_ids,
                evidence_ids=evidence_ids,
            )
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

    @staticmethod
    def _render_finding_reference(
        reference: Any,
        *,
        fact_ids: set[str],
        evidence_ids: set[str],
    ) -> str:
        available = (
            reference.id in fact_ids
            if reference.reference_type == "fact"
            else reference.id in evidence_ids
        )
        rendered_id = f"<code>{_e(reference.id)}</code>"
        if available:
            rendered_id = (
                f'<a href="#{_e(_reference_anchor(reference.reference_type, reference.id))}">'
                f"{rendered_id}</a>"
            )
        return (
            f'<li><span>{_e(reference.artifact)} / '
            f'{_e(reference.reference_type)}</span>{rendered_id}</li>'
        )

    def _render_spring(self, data: _ReportData) -> str:
        language = data.language
        if "spring_api" not in data.static_result.collectors:
            return self._unavailable_section(
                "spring",
                "06",
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
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.spring.eyebrow", language))}</p><h2>{_e(message("report.spring.title", language))}</h2></div><span class="section-index">06</span></div>
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
            <div><span class="label">{_e(message("report.fact_id", language))}</span><a href="#{_e(_fact_anchor(fact.id))}"><code>{_e(fact.id)}</code></a></div>
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
                "07",
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
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.maven.eyebrow", language))}</p><h2>{_e(message("report.maven.title", language))}</h2></div><span class="section-index">07</span></div>
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
                f'<tr><td><strong>{_e(subject)}</strong><br><a href="#{_e(_fact_anchor(fact.id))}"><code>{_e(fact.id)}</code></a></td><td>{_display(detail, language)}</td><td><span class="status-pill">{_e(status_label(fact.status, language))}</span></td></tr>'
            )
        return f'<div class="table-wrap"><table><thead><tr><th>{_e(message("report.declaration", language))}</th><th>{_e(message("report.value", language))}</th><th>{_e(message("report.status", language))}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'

    def _render_flyway(self, data: _ReportData) -> str:
        language = data.language
        if "flyway_migration" not in data.static_result.collectors:
            return self._unavailable_section(
                "flyway",
                "08",
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
                f'<tr><td><code>{_display(value.get("version"), language)}</code></td><td>{_e(value.get("type"))}</td><td><a href="#{_e(_fact_anchor(fact.id))}">{_e(value.get("source_file"))}</a></td><td><code>{_e(value.get("file_sha256"))}</code></td><td><span class="status-pill">{_e(status_label(fact.status, language))}</span></td></tr>'
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
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.flyway.eyebrow", language))}</p><h2>{_e(message("report.flyway.title", language))}</h2></div><span class="section-index">08</span></div>
          <p class="section-note">{_e(message("report.flyway.note", language))}</p>
          <div class="table-wrap"><table><thead><tr><th>{_e(message("report.version", language))}</th><th>{_e(message("report.type", language))}</th><th>{_e(message("report.source_filename", language))}</th><th>{_e(message("report.file_sha256", language))}</th><th>{_e(message("report.status", language))}</th></tr></thead><tbody>{"".join(rows) or f'<tr><td colspan="5">{_e(message("report.no_migrations", language))}</td></tr>'}</tbody></table></div>
          <div class="subheading"><h3>{_e(message("report.migration_sets", language))}</h3><span>{len(set_facts)}</span></div>
          <div class="table-wrap"><table><thead><tr><th>{_e(message("report.migration_set", language))}</th><th>{_e(message("report.versioned", language))}</th><th>{_e(message("report.repeatable", language))}</th><th>{_e(message("report.ordered_versions", language))}</th></tr></thead><tbody>{set_rows or f'<tr><td colspan="4">{_e(message("report.no_migration_set_summaries", language))}</td></tr>'}</tbody></table></div>
        </section>
        """

    def _render_mysql(self, data: _ReportData) -> str:
        language = data.language
        runtime = data.runtime_result
        if (
            runtime is None
            or data.view.assessment.mysql.state is not CheckState.CURRENT
        ):
            state = data.view.assessment.mysql.state
            note_key = {
                CheckState.NOT_RUN: "report.attention.database_not_verified",
                CheckState.FAILED: "report.attention.database_verification_failed",
                CheckState.STALE: "report.attention.state_unknown",
                CheckState.UNKNOWN: "report.attention.state_unknown",
            }.get(state, "report.not_available")
            return self._unavailable_section(
                "mysql",
                "09",
                message("report.mysql.eyebrow", language),
                message("report.not_available", language),
                message(note_key, language),
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
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.mysql.eyebrow", language))}</p><h2>{_e(message("report.mysql.title", language))}</h2></div><span class="section-index">09</span></div>
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
        evidence_blocks = "".join(
            self._render_evidence_ledger(evidence, language)
            for evidence in sorted(evidence_by_id.values(), key=lambda item: item.id)
        )
        return f"""
        <section class="section" id="ledger">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.ledger.eyebrow", language))}</p><h2>{_e(message("report.ledger.title", language))}</h2></div><span class="section-index">11</span></div>
          <p class="section-note">{_e(message("report.ledger.note", language))}</p>
          <div class="ledger">{blocks or f'<p class="empty-note">{_e(message("report.no_facts", language))}</p>'}</div>
          <div class="subheading"><h3>{_e(message("report.evidence_records", language))}</h3><span>{len(evidence_by_id)}</span></div>
          <div class="ledger">{evidence_blocks}</div>
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
                f'<li><a href="#{_e(_evidence_anchor(evidence.id))}"><code>{_e(evidence.id)}</code></a><span>{_e(evidence.kind)} · {_e(evidence.source)}</span></li>'
            )
        return f"""
        <details class="fact-row" id="{_e(_fact_anchor(fact.id))}">
          <summary><span class="status-dot status-{_e(fact.status)}"></span><span class="status-pill">{_e(status_label(fact.status, language))}</span><code>{_e(fact.id)}</code><span>{_e(fact.name)}</span><em>{_e(artifact)}</em></summary>
          <div class="fact-detail"><div class="detail-grid"><div><span class="label">{_e(message("report.fact_id", language))}</span><code>{_e(fact.id)}</code></div><div><span class="label">{_e(message("report.status", language))}</span><span class="status-pill">{_e(status_label(fact.status, language))}</span></div><div><span class="label">{_e(message("report.structured_value", language))}</span>{_json_block(fact.value)}</div><div><span class="label">{_e(message("report.evidence_ids", language))}</span><ul class="plain-list">{"".join(evidence_blocks) or f'<li>{_e(message("report.not_available", language))}</li>'}</ul></div></div></div>
        </details>
        """

    @staticmethod
    def _render_evidence_ledger(evidence: Evidence, language: Language) -> str:
        return f"""
        <details class="fact-row evidence-row" id="{_e(_evidence_anchor(evidence.id))}">
          <summary><span class="status-dot"></span><span class="status-pill">Evidence</span><code>{_e(evidence.id)}</code><span>{_e(evidence.kind)}</span><em>{_e(evidence.source)}</em></summary>
          <div class="fact-detail"><div class="detail-grid"><div><span class="label">{_e(message("report.source", language))}</span><code>{_e(evidence.source)}</code></div><div><span class="label">{_e(message("report.structured_value", language))}</span>{_json_block(evidence.value)}</div></div></div>
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
                    f'<tr><td><a href="{_e(_artifact_href(artifact.artifact))}"><code>{_e(artifact.relative_path)}</code></a></td><td>{_e(artifact.artifact)}</td><td><code>{_e(artifact.schema_version)}</code></td><td><code>{_e(artifact.sha256)}</code></td><td>{times}</td></tr>'
                )
            else:
                rows.append(
                    f'<tr><td><code>{_e(artifact.relative_path)}</code></td><td>{_e(artifact.artifact)}</td><td colspan="3"><span class="unavailable">{_e(message("report.not_available", language))}</span></td></tr>'
                )
        return f"""
        <section class="section" id="provenance">
          <div class="section-heading"><div><p class="eyebrow">{_e(message("report.provenance.eyebrow", language))}</p><h2>{_e(message("report.provenance.title", language))}</h2></div><span class="section-index">12</span></div>
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


def _check_time(check: CheckAssessment, language: Language) -> str:
    if check.timestamp is None:
        return message("report.coverage.no_time", language)
    return check.timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def _fact_anchor(fact_id: str) -> str:
    return f"fact-{fact_id}"


def _evidence_anchor(evidence_id: str) -> str:
    return f"evidence-{evidence_id}"


def _reference_anchor(reference_type: str, reference_id: str) -> str:
    return (
        _fact_anchor(reference_id)
        if reference_type == "fact"
        else _evidence_anchor(reference_id)
    )


def _available_reference_ids(data: _ReportData) -> tuple[set[str], set[str]]:
    facts = set(fact.id for fact in data.static_result.facts)
    evidence = set(item.id for item in data.static_result.evidence)
    if data.runtime_result is not None:
        facts.update(fact.id for fact in data.runtime_result.facts)
        evidence.update(item.id for item in data.runtime_result.evidence)
    return facts, evidence


def _artifact_href(artifact: str) -> str:
    return {
        "static_scan": "../evidence.json",
        "mysql_verification": "../verification/mysql.json",
        "reconciliation": "../reconciliation.json",
    }[artifact]


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
