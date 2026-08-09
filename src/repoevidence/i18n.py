"""Small, dependency-free localization helpers for human-facing output."""

# ruff: noqa: E501

from __future__ import annotations

import locale
import os
from collections.abc import Mapping, Sequence
from typing import Literal

Language = Literal["en", "zh-CN"]
SUPPORTED_LANGUAGES: tuple[Language, ...] = ("en", "zh-CN")

_AUTO = "auto"
_MESSAGE_KEY_PREFIX = "__repoevidence_message_key__:"
_LOCALE_ENV_KEYS = ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")


class InvalidLanguageError(ValueError):
    """Raised when a CLI or environment language is not supported."""

    def __init__(self, value: object) -> None:
        self.value = str(value)
        super().__init__(
            f"Unsupported language {self.value!r}. Choose auto, en, or zh-CN."
        )


_CATALOGS: dict[Language, dict[str, str]] = {
    "en": {
        "cli.root.help": "Deterministic, LLM-free software evidence collection.",
        "cli.verify.help": "Run explicitly requested runtime verification.",
        "cli.lang.help": "Language for human-readable messages: auto, en, or zh-CN.",
        "cli.scan.help": "Collect deterministic repository evidence from REPO_PATH.",
        "cli.reconcile.help": "Reconcile existing static and MySQL Flyway artifacts offline.",
        "cli.report.help": "Generate a self-contained offline HTML report from existing artifacts.",
        "cli.mysql.help": "Run fixed, read-only MySQL metadata verification for REPO_PATH.",
        "cli.help.option": "Show this message and exit.",
        "cli.install_completion": "Install completion for the current shell.",
        "cli.show_completion": "Show completion for the current shell, to copy it or customize the installation.",
        "cli.scan.complete": "Scan complete. Evidence written to {path}",
        "cli.reconcile.complete": "Reconciliation complete. Result written to {path}",
        "cli.report.complete": "Report written to {path}",
        "cli.mysql.complete": "MySQL verification complete. Result written to {path}",
        "cli.warnings": "Warnings: {count}",
        "cli.error": "Error [{code}]: {message}",
        "cli.report_error": "Report error [{code}]: {message}",
        "cli.invalid_language": "Unsupported language {value!r}. Choose auto, en, or zh-CN.",
        "error.mysql_config_missing": "Required MySQL verification environment variables are missing or invalid.",
        "error.mysql_connection_failed": "Unable to connect to MySQL.",
        "error.mysql_query_failed": "A fixed read-only MySQL metadata query failed.",
        "error.mysql_verification_failed": "MySQL runtime verification failed.",
        "error.missing_static_scan": "Required static_scan artifact is missing.",
        "error.missing_mysql_verification": "Required mysql_verification artifact is missing.",
        "error.missing_reconciliation": "Required reconciliation artifact is missing.",
        "error.invalid_static_scan": "Required static scan artifact is invalid.",
        "error.invalid_mysql_verification": "Required MySQL verification artifact is invalid.",
        "error.repository_root_mismatch": "Static and MySQL artifacts have different repository roots.",
        "error.unsupported_static_schema": "Static scan artifact schema is unsupported.",
        "error.unsupported_runtime_schema": "MySQL verification artifact schema is unsupported.",
        "report.title": "RepoEvidence report — {name}",
        "report.skip_link": "Skip to report content",
        "report.hero.eyebrow": "REPOEVIDENCE / LOCAL SNAPSHOT",
        "report.hero.title": "Evidence, arranged for inspection.",
        "report.hero.copy": "A static, source-grounded view of what the repository declares, what runtime verification observed, and where the snapshots disagree.",
        "report.generated": "Generated",
        "report.generated_aria": "Report generated time",
        "report.tool_version": "Tool version {version}",
        "report.footer": "Generated locally by RepoEvidence. No network, server, or runtime execution required.",
        "report.overview.eyebrow": "OVERVIEW",
        "report.overview.title": "Repository snapshot",
        "report.repository_path": "Repository path",
        "report.display_name": "Display name",
        "report.git_commit": "Git commit",
        "report.branch": "Branch",
        "report.static_facts": "Static Facts",
        "report.runtime_verified_facts": "Runtime Verified Facts",
        "report.spring_endpoints": "Spring Endpoints",
        "report.maven_dependencies": "Maven Dependencies",
        "report.repository_flyway_migrations": "Repository Flyway Migrations",
        "report.mysql_tables": "MySQL Tables",
        "report.drift_findings": "Drift Findings",
        "report.evidence_status.eyebrow": "EVIDENCE STATUS",
        "report.evidence_status.title": "Facts keep their epistemic boundary",
        "report.evidence_status.note": "Declared and inferred statements remain visibly different from verified runtime observations. No health score is inferred.",
        "report.status": "Status",
        "report.static_scan": "Static scan",
        "report.mysql_verification": "MySQL verification",
        "report.reconciliation.eyebrow": "RECONCILIATION / DRIFT",
        "report.reconciliation.title": "Where snapshots disagree",
        "report.drift.detected": "DRIFT DETECTED",
        "report.drift.detected.note": "Repository and runtime Flyway snapshots are not identical.",
        "report.drift.none": "No drift detected",
        "report.drift.none.note": "All reported reconciliation findings are aligned.",
        "report.matched": "Matched",
        "report.runtime_only": "Runtime-only",
        "report.source_only": "Source-only",
        "report.version_mismatch": "Version mismatch",
        "report.runtime_failed": "Runtime failed",
        "report.ambiguous": "Ambiguous",
        "report.repository_max_version": "Repository max version",
        "report.runtime_max_successful": "Runtime max successful",
        "report.runtime_baseline": "Runtime baseline",
        "report.repository_flyway": "Repository Flyway",
        "report.runtime_flyway": "Runtime Flyway",
        "report.findings": "Findings",
        "report.total": "{count} total",
        "report.no_reconciliation_findings": "No reconciliation findings.",
        "report.references": "References",
        "report.spring.eyebrow": "SPRING API",
        "report.spring.title": "Spring API / Static endpoint map",
        "report.spring.toolbar": "{count} endpoints inferred from static annotations. HTTP response status is not present in static evidence; fact status is shown below.",
        "report.filter_endpoints": "Filter endpoints",
        "report.filter_placeholder": "method, path, controller",
        "report.filter_aria": "Filter Spring endpoints",
        "report.no_endpoint_facts": "No endpoint facts.",
        "report.fact_id": "Fact ID",
        "report.source_location": "Source location",
        "report.line": "line {value}",
        "report.evidence_ids": "Evidence IDs",
        "report.annotation_information": "Annotation information",
        "report.maven.eyebrow": "MAVEN DECLARATIONS",
        "report.maven.title": "Maven declarations / Build intent",
        "report.maven.note": "Declared only; no Effective POM resolution, dependency download, or final Maven resolved state is claimed.",
        "report.project_coordinates": "Project coordinates",
        "report.java_declarations": "Java-related declarations",
        "report.spring_boot_parent": "Spring Boot parent declaration",
        "report.dependencies": "Dependencies",
        "report.dependency_management": "dependencyManagement",
        "report.plugins": "Plugins",
        "report.modules": "Modules",
        "report.declaration": "Declaration",
        "report.value": "Value",
        "report.rank": "Rank",
        "report.description": "Description",
        "report.success": "success",
        "report.failed": "failed",
        "report.no_declarations": "No declarations.",
        "report.flyway.eyebrow": "FLYWAY SOURCE",
        "report.flyway.title": "Flyway source / What the repository declares",
        "report.flyway.note": "Declared source migrations are not presented as executed runtime migrations.",
        "report.version": "Version",
        "report.type": "Type",
        "report.source_filename": "Source filename",
        "report.file_sha256": "File SHA-256",
        "report.no_migrations": "No migrations.",
        "report.migration_sets": "Migration sets",
        "report.migration_set": "Migration set",
        "report.versioned": "Versioned",
        "report.repeatable": "Repeatable",
        "report.ordered_versions": "Ordered versions",
        "report.no_migration_set_summaries": "No migration set summaries.",
        "report.mysql.eyebrow": "MYSQL RUNTIME",
        "report.mysql.title": "MySQL runtime / Verified observation",
        "report.verified_runtime": "Verified runtime observation",
        "report.observed": "Observed {value}",
        "report.server_version": "Server version",
        "report.selected_database": "Selected database",
        "report.tables": "Tables",
        "report.columns": "Columns",
        "report.primary_key": "PK",
        "report.unique": "UNIQUE",
        "report.foreign_key": "FK",
        "report.indexes": "Indexes",
        "report.base_tables": "Base tables",
        "report.table_columns": "{tables} tables · {columns} columns",
        "report.no_tables": "No tables.",
        "report.flyway_runtime_history": "Flyway runtime history",
        "report.rows": "{count} rows",
        "report.script": "Script",
        "report.result": "Result",
        "report.no_flyway_history": "No Flyway history.",
        "report.ledger.eyebrow": "EVIDENCE DRILL-DOWN",
        "report.ledger.title": "Fact and evidence ledger",
        "report.ledger.note": "Open a fact to inspect its status, structured value, evidence IDs, and the raw observations behind it.",
        "report.structured_value": "Structured value",
        "report.source": "Source",
        "report.no_facts": "No facts available.",
        "report.provenance.eyebrow": "PROVENANCE",
        "report.provenance.title": "Artifact provenance / Report inputs",
        "report.provenance.note": "The report is a view of these snapshots. Their paths and SHA-256 digests identify exactly what was read.",
        "report.path": "Path",
        "report.artifact": "Artifact",
        "report.schema": "Schema",
        "report.sha256": "SHA-256",
        "report.snapshot_time": "Snapshot time",
        "report.started": "Started",
        "report.finished": "Finished",
        "report.not_available": "Not available",
        "report.observed_label": "Observed",
        "report.source_file": "source file",
        "report.runtime_script": "runtime script",
        "report.artifact_missing": "Not available",
        "report.artifact_invalid_json": "Artifact is not valid JSON",
        "report.artifact_invalid_object": "Artifact must contain a JSON object",
        "report.artifact_schema_unsupported": "Artifact schema is unsupported",
        "report.artifact_schema_invalid": "Artifact failed schema validation",
        "finding.matched": "Flyway migration {version} matches source and runtime.",
        "finding.runtime_only": "Flyway runtime migration {version} has no source declaration.",
        "finding.source_only": "Flyway source migration {version} has no runtime history row.",
        "finding.version_mismatch": "Flyway version {version} has different source and runtime scripts.",
        "finding.runtime_failed": "Flyway runtime migration {version} failed.",
        "finding.ambiguous": "Flyway version {version} has duplicate declarations.",
        "status.declared": "declared",
        "status.inferred": "inferred",
        "status.verified": "verified",
        "status.conflicted": "conflicted",
        "finding_label.matched": "matched",
        "finding_label.runtime_only": "runtime_only",
        "finding_label.source_only": "source_only",
        "finding_label.version_mismatch": "version_mismatch",
        "finding_label.runtime_failed": "runtime_failed",
        "finding_label.ambiguous": "ambiguous",
    },
    "zh-CN": {
        "cli.root.help": "确定性的、无 LLM 的软件证据收集。",
        "cli.verify.help": "运行显式请求的运行时验证。",
        "cli.lang.help": "人类可读消息的语言：auto、en 或 zh-CN。",
        "cli.scan.help": "从 REPO_PATH 收集确定性的仓库证据。",
        "cli.reconcile.help": "离线对账现有的静态和 MySQL Flyway artifacts。",
        "cli.report.help": "根据现有 artifacts 生成自包含的离线 HTML 报告。",
        "cli.mysql.help": "对 REPO_PATH 执行固定的只读 MySQL metadata 验证。",
        "cli.help.option": "显示此帮助信息并退出。",
        "cli.install_completion": "为当前 shell 安装补全。",
        "cli.show_completion": "显示当前 shell 的补全内容，便于复制或自定义安装。",
        "cli.scan.complete": "扫描完成。证据已写入：{path}",
        "cli.reconcile.complete": "对账完成。结果已写入：{path}",
        "cli.report.complete": "报告已生成：{path}",
        "cli.mysql.complete": "MySQL 验证完成。结果已写入：{path}",
        "cli.warnings": "发现 {count} 条警告。",
        "cli.error": "错误 [{code}]：{message}",
        "cli.report_error": "报告错误 [{code}]：{message}",
        "cli.invalid_language": "不支持的语言 {value!r}。请选择 auto、en 或 zh-CN。",
        "error.mysql_config_missing": "缺少 MySQL 连接配置。",
        "error.mysql_connection_failed": "无法连接 MySQL。",
        "error.mysql_query_failed": "固定的只读 MySQL metadata 查询失败。",
        "error.mysql_verification_failed": "MySQL 运行时验证失败。",
        "error.missing_static_scan": "缺少静态扫描 artifact。",
        "error.missing_mysql_verification": "缺少 MySQL 验证 artifact。",
        "error.missing_reconciliation": "缺少对账 artifact。",
        "error.invalid_static_scan": "静态扫描 artifact 无效。",
        "error.invalid_mysql_verification": "MySQL 验证 artifact 无效。",
        "error.repository_root_mismatch": "静态 artifact 与 MySQL artifact 的仓库根目录不同。",
        "error.unsupported_static_schema": "不支持静态扫描 artifact 的 schema。",
        "error.unsupported_runtime_schema": "不支持 MySQL 验证 artifact 的 schema。",
        "report.title": "RepoEvidence 报告 — {name}",
        "report.skip_link": "跳转到报告内容",
        "report.hero.eyebrow": "REPOEVIDENCE / 本地快照",
        "report.hero.title": "为检查而整理的证据。",
        "report.hero.copy": "以静态、基于源码的方式展示仓库声明的内容、运行时验证观察到的内容，以及快照之间存在差异的位置。",
        "report.generated": "生成时间",
        "report.generated_aria": "报告生成时间",
        "report.tool_version": "工具版本 {version}",
        "report.footer": "由 RepoEvidence 在本地生成。不需要网络、服务器或运行时执行。",
        "report.overview.eyebrow": "概览",
        "report.overview.title": "仓库快照",
        "report.repository_path": "仓库路径",
        "report.display_name": "显示名称",
        "report.git_commit": "Git commit",
        "report.branch": "分支",
        "report.static_facts": "静态 Facts",
        "report.runtime_verified_facts": "运行时已验证 Facts",
        "report.spring_endpoints": "Spring endpoints",
        "report.maven_dependencies": "Maven dependencies",
        "report.repository_flyway_migrations": "仓库 Flyway migrations",
        "report.mysql_tables": "MySQL tables",
        "report.drift_findings": "漂移 findings",
        "report.evidence_status.eyebrow": "Evidence 状态",
        "report.evidence_status.title": "Facts 保持认识边界",
        "report.evidence_status.note": "已声明和推断的陈述会与已验证的运行时观测保持清晰区分。不推导健康评分。",
        "report.status": "状态",
        "report.static_scan": "静态扫描",
        "report.mysql_verification": "MySQL 验证",
        "report.reconciliation.eyebrow": "RECONCILIATION / 漂移",
        "report.reconciliation.title": "快照存在差异的位置",
        "report.drift.detected": "检测到仓库与运行环境差异（DRIFT DETECTED）",
        "report.drift.detected.note": "仓库与运行环境的 Flyway 快照并不一致。",
        "report.drift.none": "未检测到漂移",
        "report.drift.none.note": "所有报告的 reconciliation findings 都已对齐。",
        "report.matched": "匹配",
        "report.runtime_only": "仅存在于运行环境",
        "report.source_only": "仅存在于源码仓库",
        "report.version_mismatch": "版本不匹配",
        "report.runtime_failed": "运行时失败",
        "report.ambiguous": "存在歧义",
        "report.repository_max_version": "仓库最大版本",
        "report.runtime_max_successful": "运行环境最大成功版本",
        "report.runtime_baseline": "运行环境 baseline",
        "report.repository_flyway": "仓库 Flyway",
        "report.runtime_flyway": "运行环境 Flyway",
        "report.findings": "漂移 findings",
        "report.total": "共 {count} 条",
        "report.no_reconciliation_findings": "暂无 reconciliation findings。",
        "report.references": "引用",
        "report.spring.eyebrow": "SPRING API",
        "report.spring.title": "Spring API / 静态 endpoint 映射",
        "report.spring.toolbar": "根据静态注解推断出 {count} 个 endpoints。静态 Evidence 中没有 HTTP response status；下面显示 Fact status。",
        "report.filter_endpoints": "筛选 endpoints",
        "report.filter_placeholder": "method、path、controller",
        "report.filter_aria": "筛选 Spring endpoints",
        "report.no_endpoint_facts": "暂无 endpoint Facts。",
        "report.fact_id": "Fact ID",
        "report.source_location": "源码位置",
        "report.line": "第 {value} 行",
        "report.evidence_ids": "Evidence IDs",
        "report.annotation_information": "注解信息",
        "report.maven.eyebrow": "MAVEN DECLARATIONS",
        "report.maven.title": "Maven declarations / 构建意图",
        "report.maven.note": "仅展示声明；不声称提供 Effective POM resolution、依赖下载或最终 Maven resolved state。",
        "report.project_coordinates": "项目坐标",
        "report.java_declarations": "Java 相关声明",
        "report.spring_boot_parent": "Spring Boot parent 声明",
        "report.dependencies": "依赖（Dependencies）",
        "report.dependency_management": "dependencyManagement",
        "report.plugins": "插件（Plugins）",
        "report.modules": "模块（Modules）",
        "report.declaration": "声明",
        "report.value": "值",
        "report.rank": "序号",
        "report.description": "描述",
        "report.success": "成功",
        "report.failed": "失败",
        "report.no_declarations": "暂无声明。",
        "report.flyway.eyebrow": "FLYWAY SOURCE",
        "report.flyway.title": "Flyway source / 仓库声明的内容",
        "report.flyway.note": "声明的源码 migration 不表示它们已经作为运行时 migration 执行。",
        "report.version": "版本",
        "report.type": "类型",
        "report.source_filename": "源码文件名",
        "report.file_sha256": "文件 SHA-256",
        "report.no_migrations": "暂无 migrations。",
        "report.migration_sets": "Migration sets（迁移集合）",
        "report.migration_set": "Migration set（迁移集合）",
        "report.versioned": "Versioned",
        "report.repeatable": "Repeatable",
        "report.ordered_versions": "排序后的版本",
        "report.no_migration_set_summaries": "暂无 migration set summary。",
        "report.mysql.eyebrow": "MYSQL RUNTIME",
        "report.mysql.title": "MySQL runtime / 已验证的观测",
        "report.verified_runtime": "已验证的运行时观测",
        "report.observed": "观测时间 {value}",
        "report.server_version": "服务器版本",
        "report.selected_database": "选中的数据库",
        "report.tables": "Tables",
        "report.columns": "Columns",
        "report.primary_key": "PK",
        "report.unique": "UNIQUE",
        "report.foreign_key": "FK",
        "report.indexes": "Indexes",
        "report.base_tables": "基础表",
        "report.table_columns": "{tables} 个 tables · {columns} 个 columns",
        "report.no_tables": "暂无 tables。",
        "report.flyway_runtime_history": "Flyway runtime history（运行时历史）",
        "report.rows": "{count} 行",
        "report.script": "脚本",
        "report.result": "结果",
        "report.no_flyway_history": "暂无 Flyway history。",
        "report.ledger.eyebrow": "EVIDENCE DRILL-DOWN",
        "report.ledger.title": "Fact 与 Evidence ledger",
        "report.ledger.note": "展开 Fact，查看其状态、结构化值、Evidence IDs 以及背后的原始观测。",
        "report.structured_value": "结构化值",
        "report.source": "来源",
        "report.no_facts": "暂无 Facts。",
        "report.provenance.eyebrow": "PROVENANCE",
        "report.provenance.title": "Artifact provenance / 报告输入",
        "report.provenance.note": "报告是这些快照的视图。路径和 SHA-256 digest 用于精确标识实际读取的内容。",
        "report.path": "路径",
        "report.artifact": "Artifact",
        "report.schema": "Schema",
        "report.sha256": "SHA-256",
        "report.snapshot_time": "快照时间",
        "report.started": "开始",
        "report.finished": "结束",
        "report.not_available": "暂无数据",
        "report.observed_label": "观测时间",
        "report.source_file": "源码文件",
        "report.runtime_script": "运行时脚本",
        "report.artifact_missing": "暂无数据",
        "report.artifact_invalid_json": "Artifact 不是有效 JSON",
        "report.artifact_invalid_object": "Artifact 必须包含 JSON object",
        "report.artifact_schema_unsupported": "Artifact schema 不受支持",
        "report.artifact_schema_invalid": "Artifact 未通过 schema 校验",
        "finding.matched": "Flyway migration {version} 与源码和运行环境匹配。",
        "finding.runtime_only": "运行环境中的 Flyway migration {version} 在源码中没有声明。",
        "finding.source_only": "源码中的 Flyway migration {version} 没有运行时 history row。",
        "finding.version_mismatch": "Flyway version {version} 的源码脚本和运行时脚本不同。",
        "finding.runtime_failed": "运行环境中的 Flyway migration {version} 执行失败。",
        "finding.ambiguous": "Flyway version {version} 存在重复声明。",
        "status.declared": "已声明（declared）",
        "status.inferred": "推断（inferred）",
        "status.verified": "已验证（verified）",
        "status.conflicted": "冲突（conflicted）",
        "finding_label.matched": "匹配（matched）",
        "finding_label.runtime_only": "仅存在于运行环境（runtime_only）",
        "finding_label.source_only": "仅存在于源码仓库（source_only）",
        "finding_label.version_mismatch": "版本不匹配（version_mismatch）",
        "finding_label.runtime_failed": "运行时失败（runtime_failed）",
        "finding_label.ambiguous": "存在歧义（ambiguous）",
    },
}


def message_key(key: str) -> str:
    """Return a stable marker that can be resolved by a presentation layer."""

    return f"{_MESSAGE_KEY_PREFIX}{key}"


def message(key: str, language: Language, **values: object) -> str:
    """Render one catalog message for a supported language."""

    if key.startswith(_MESSAGE_KEY_PREFIX):
        key = key.removeprefix(_MESSAGE_KEY_PREFIX)
    try:
        template = _CATALOGS[language][key]
    except KeyError as exc:
        raise KeyError(f"Unknown localization key {key!r} for {language!r}") from exc
    return template.format(**values)


def resolve_language(
    requested: str | None = _AUTO,
    *,
    environ: Mapping[str, str] | None = None,
    locale_values: Sequence[str | None] | None = None,
) -> Language:
    """Resolve a human-facing language without allowing locale errors to escape."""

    requested_value = _clean_value(_AUTO if requested is None else requested)
    if requested_value not in {_AUTO, *SUPPORTED_LANGUAGES}:
        raise InvalidLanguageError(requested_value)
    if requested_value in SUPPORTED_LANGUAGES:
        return requested_value  # type: ignore[return-value]

    environment = os.environ if environ is None else environ
    configured = _clean_value(environment.get("REPOEVIDENCE_LANG"))
    if configured and configured != _AUTO:
        if configured not in SUPPORTED_LANGUAGES:
            raise InvalidLanguageError(configured)
        return configured  # type: ignore[return-value]

    values = list(locale_values) if locale_values is not None else _system_locale_values(environment)
    if any(_is_chinese_locale(value) for value in values):
        return "zh-CN"
    return "en"


def status_label(status: str, language: Language) -> str:
    """Return a human-facing status while retaining the canonical value in Chinese."""

    return message(f"status.{status}", language) if status in {
        "declared",
        "inferred",
        "verified",
        "conflicted",
    } else status


def finding_label(kind: str, language: Language) -> str:
    """Return a human-facing reconciliation kind while retaining its canonical value."""

    known = {
        "matched",
        "runtime_only",
        "source_only",
        "version_mismatch",
        "runtime_failed",
        "ambiguous",
    }
    return message(f"finding_label.{kind}", language) if kind in known else kind


def error_message(code: str, language: Language, fallback: str | None = None) -> str:
    """Translate known system error codes and preserve unknown raw messages."""

    key = f"error.{code}"
    if key in _CATALOGS[language]:
        return message(key, language)
    return fallback if fallback is not None else code


def finding_message(
    kind: str,
    language: Language,
    *,
    version: object,
    fallback: str,
) -> str:
    """Translate generated finding prose without translating raw artifact values."""

    key = f"finding.{kind}"
    if key not in _CATALOGS[language]:
        return fallback
    return message(key, language, version=version if version is not None else "<unknown>")


def _clean_value(value: object) -> str:
    return "" if value is None else str(value).strip()


def _system_locale_values(environ: Mapping[str, str]) -> tuple[str | None, ...]:
    values: list[str | None] = [environ.get(key) for key in _LOCALE_ENV_KEYS]
    try:
        current = locale.getlocale()
    except Exception:
        return tuple(values)
    values.append(current[0] if isinstance(current, tuple) else str(current))
    return tuple(values)


def _is_chinese_locale(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.replace("_", "-").lower()
    return normalized.startswith("zh-") or normalized == "zh" or "chinese" in normalized
