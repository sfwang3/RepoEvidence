# RepoEvidence

English | [简体中文文档](https://github.com/sfwang3/RepoEvidence/blob/main/README.zh-CN.md)

## Why RepoEvidence

RepoEvidence is a deterministic, LLM-free engine for understanding software repositories with evidence you can inspect and verify.

## Core Evidence / Fact model

It separates what a repository declares from what runtime verification observes:

```text
repository → collectors → Evidence / Fact → JSON
                                      ↘ Verification / Reconciliation
```

Evidence preserves the original observation. A Fact is a structured interpretation with an explicit status: `declared`, `inferred`, `verified`, or `conflicted`. Runtime verification is opt-in, and reconciliation reports cross-artifact drift without pretending that static source evidence and runtime observations are the same thing.

## Quick Start

Requires Python 3.12 or newer.

```bash
python -m pip install repoevidence

repoevidence scan /path/to/repository
repoevidence report /path/to/repository
```

The scan writes `.repoevidence/evidence.json`. The report writes a self-contained HTML file to `.repoevidence/report/index.html`; open it directly in a browser. Report generation does not start a server, install frontend dependencies, access the network, or execute the target repository.

## CLI

### Static scan

```bash
repoevidence scan /path/to/repository
```

The default static collectors inspect repository metadata, Spring MVC annotations, Maven declarations, and Flyway migration files. The scan does not run Maven, Flyway, SQL, tests, or target-repository code.

### Offline HTML Report

```bash
repoevidence report /path/to/repository
```

The report reads the existing static scan and, when present, MySQL verification and reconciliation artifacts. Missing optional artifacts are shown as `Not available`; the command never runs those upstream operations automatically.

### Explicit MySQL verification

```bash
repoevidence verify mysql /path/to/repository
```

This is the only command that connects to MySQL. Connection settings are read from environment variables, never from CLI arguments:

```text
REPOEVIDENCE_MYSQL_HOST
REPOEVIDENCE_MYSQL_PORT
REPOEVIDENCE_MYSQL_USER
REPOEVIDENCE_MYSQL_PASSWORD
REPOEVIDENCE_MYSQL_DATABASE
```

The verifier runs fixed read-only metadata queries and writes `.repoevidence/verification/mysql.json`. Use a dedicated database account with only the `SELECT` permissions required by those metadata queries. No business table rows are collected.

### Offline Flyway reconciliation

```bash
repoevidence reconcile /path/to/repository
```

Reconciliation reads `.repoevidence/evidence.json` and `.repoevidence/verification/mysql.json` only. It does not connect to MySQL or execute repository code. The result is `.repoevidence/reconciliation.json` and currently covers Flyway `matched`, `runtime_only`, `source_only`, `version_mismatch`, `runtime_failed`, `ambiguous`, and baseline handling.

## ChargeSafe drift example

ChargeSafe was used as a real acceptance case, but it is not required to use RepoEvidence and is not bundled with the package. The evidence showed a repository/runtime Flyway drift:

```text
Repository Flyway: V1-V6
Runtime:           Baseline 0 + V1-V9
matched:           6
runtime-only:      V7/V8/V9
drift_detected:    true
```

The generated reconciliation kept the runtime references for V7, V8, and V9, did not invent source references, and renders the outcome as `DRIFT DETECTED` in the HTML report. No database credentials or connection configuration are part of this example.

## Current coverage

- Repository metadata: Git commit/branch and common project files.
- Spring API: statically inferred `@RestController` endpoints from Java source.
- Maven: declared projects, modules, parent, properties, dependencies, dependency management, and plugins. No Effective POM or dependency resolution is claimed.
- Flyway: declared versioned/repeatable migration files, ordering, and source file SHA-256. SQL is not executed.
- MySQL: explicitly requested runtime metadata, schema summaries, indexes, constraints, and Flyway history.
- Evidence-backed reconciliation: Flyway drift across static and runtime artifacts.
- Offline HTML report: overview, status counts, domain sections, drift findings, fact/evidence drill-down, and artifact provenance.

## Security model

RepoEvidence treats repositories, databases, and artifact contents as untrusted input.

- Static scan, report, and reconciliation do not execute target code.
- Report and reconciliation are offline operations.
- MySQL verification is explicit opt-in and uses fixed read-only queries.
- Passwords are not accepted as CLI arguments and secrets are not intended to enter artifacts or reports.
- Report HTML escapes artifact-derived text and redacts secret-like structured fields.
- Evidence and Fact references are stable and inspectable; uncertainty is not fabricated into a Fact.

## Limitations

RepoEvidence does not currently provide runtime Spring endpoint verification, DTO/entity analysis, Swagger/OpenAPI generation, SQL schema interpretation, Maven execution, dependency resolution, business-row inspection, automatic repair, risk scoring, LLM features, PDF/DOCX export, or a web service.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
python -m build
python -m twine check dist/*
```

The package declares Python `>=3.12`. CI runs the test suite, linter, distribution build, and distribution metadata checks without requiring a live database.

## Apache-2.0 License

RepoEvidence is licensed under the Apache License 2.0.

---

# RepoEvidence（简体中文）

[English README](https://github.com/sfwang3/RepoEvidence/blob/main/README.md) | 简体中文

## 为什么选择 RepoEvidence（Why RepoEvidence）

RepoEvidence 是一个确定性的、无 LLM 的软件仓库理解引擎，提供可检查、可验证的证据。

## 核心 Evidence / Fact 模型（Core Evidence / Fact model）

RepoEvidence 将仓库声明的内容与运行时 Verification（验证）观察到的内容分开：

```text
repository → collectors → Evidence / Fact → JSON
                                      ↘ Verification / Reconciliation
```

Evidence 保留原始观测结果。Fact 是带有明确状态的结构化解释，状态包括 `declared`、`inferred`、`verified` 或 `conflicted`。运行时 Verification 是显式选择的；Reconciliation（对账）报告跨 artifact 的 drift，而不会假装静态源代码证据与运行时观测是同一种东西。

## 快速开始（Quick Start）

需要 Python 3.12 或更高版本。

```bash
python -m pip install repoevidence

repoevidence scan /path/to/repository
repoevidence report /path/to/repository
```

`scan` 会写入 `.repoevidence/evidence.json`。`report` 会将 self-contained（自包含）的 HTML 文件写入 `.repoevidence/report/index.html`；可以直接在浏览器中打开。HTML Report 不会启动服务器、安装前端依赖、访问网络或执行目标仓库。

## CLI

### 静态 scan（Static scan）

```bash
repoevidence scan /path/to/repository
```

默认的静态 collectors 会检查仓库元数据、Spring MVC 注解、Maven 声明和 Flyway migration 文件。`scan` 不会运行 Maven、Flyway、SQL、tests 或目标仓库代码。

### 离线 HTML Report（Offline HTML Report）

```bash
repoevidence report /path/to/repository
```

`report` 读取已有的静态 scan，以及（如果存在）MySQL Verification 和 Reconciliation artifacts。缺少的可选 artifacts 会显示为 `Not available`；该命令不会自动运行这些上游操作。

### 显式 MySQL Verification（Explicit MySQL verification）

```bash
repoevidence verify mysql /path/to/repository
```

这是唯一会连接 MySQL 的命令。连接设置从环境变量读取，不从 CLI 参数读取：

```text
REPOEVIDENCE_MYSQL_HOST
REPOEVIDENCE_MYSQL_PORT
REPOEVIDENCE_MYSQL_USER
REPOEVIDENCE_MYSQL_PASSWORD
REPOEVIDENCE_MYSQL_DATABASE
```

verifier 会执行固定的只读 metadata queries，并写入 `.repoevidence/verification/mysql.json`。请使用只拥有这些 metadata queries 所需 `SELECT` 权限的专用数据库账号。不会采集业务表行。

### 离线 Flyway Reconciliation（Offline Flyway reconciliation）

```bash
repoevidence reconcile /path/to/repository
```

Reconciliation 只读取 `.repoevidence/evidence.json` 和 `.repoevidence/verification/mysql.json`。它不会连接 MySQL 或执行仓库代码。结果写入 `.repoevidence/reconciliation.json`；当前覆盖 Flyway 的 `matched`、`runtime_only`、`source_only`、`version_mismatch`、`runtime_failed`、`ambiguous` 和 baseline 处理。

## ChargeSafe drift 示例（ChargeSafe drift example）

ChargeSafe 曾被用作真实的 acceptance case（验收案例），但使用 RepoEvidence 不要求 ChargeSafe，且该项目不随 package 打包。证据显示了 repository/runtime Flyway drift：

```text
Repository Flyway: V1-V6
Runtime:           Baseline 0 + V1-V9
matched:           6
runtime-only:      V7/V8/V9
drift_detected:    true
```

生成的 Reconciliation 保留了 V7、V8 和 V9 的 runtime references，没有凭空生成 source references，并在 HTML Report 中将结果显示为 `DRIFT DETECTED`。此示例不包含数据库凭据或连接配置。

## 当前支持范围（Current coverage）

- Repository metadata：Git commit/branch 和常见项目文件。
- Spring API：从 Java 源代码中静态推断 `@RestController` endpoints。
- Maven：声明的 projects、modules、parent、properties、dependencies、dependency management 和 plugins。不声称提供 Effective POM 或 dependency resolution。
- Flyway：声明的 versioned/repeatable migration 文件、排序和源文件 SHA-256。不执行 SQL。
- MySQL：显式请求的 runtime metadata、schema summaries、indexes、constraints 和 Flyway history。
- Evidence-backed Reconciliation：跨静态和 runtime artifacts 的 Flyway drift。
- Offline HTML Report：overview、status counts、domain sections、drift findings、fact/evidence drill-down 和 artifact provenance。

## 安全模型（Security model）

RepoEvidence 将 repositories、databases 和 artifact contents 视为不受信任的输入。

- Static scan、report 和 Reconciliation 不执行目标代码。
- Report 和 Reconciliation 是 offline operations。
- MySQL Verification 是显式 opt-in，并使用固定的只读 queries。
- 密码不接受为 CLI 参数；不应将 secrets 写入 artifacts 或 reports。
- Report HTML 会转义来自 artifacts 的文本，并对类似 secret 的结构化字段进行 redaction。
- Evidence 和 Fact references 稳定且可检查；不会把不确定性虚构成 Fact。

## 限制（Limitations）

RepoEvidence 当前不提供 runtime Spring endpoint verification、DTO/entity analysis、Swagger/OpenAPI generation、SQL schema interpretation、Maven execution、dependency resolution、business-row inspection、automatic repair、risk scoring、LLM features、PDF/DOCX export 或 web service。

## 开发（Development）

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
python -m build
python -m twine check dist/*
```

package 声明 Python `>=3.12`。CI 会运行测试套件、linter、distribution build 和 distribution metadata checks，且不要求连接 live database。

## Apache-2.0 License

RepoEvidence 采用 Apache License 2.0 授权。
