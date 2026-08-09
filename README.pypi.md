# RepoEvidence

[English documentation](https://github.com/sfwang3/RepoEvidence/blob/main/README.md) |
[简体中文文档](https://github.com/sfwang3/RepoEvidence/blob/main/README.zh-CN.md)

## What RepoEvidence is

RepoEvidence is a local-first, evidence-backed repository understanding and
runtime verification tool. It lets you inspect source declarations, explicitly
verify MySQL runtime metadata, compare source migrations with runtime history,
trace conclusions to Evidence, and generate an offline HTML Report.

The analysis is deterministic and does not execute the target repository.
Source declarations and runtime observations remain separate, with explicit
status, snapshot, provenance, and limits.

## Quick Start

RepoEvidence requires Python 3.12 or newer:

```bash
pipx install repoevidence

cd your-project
repoevidence
```

In a suitable interactive TTY, RepoEvidence opens a local Interactive
Workspace. You can inspect source, explicitly verify MySQL when needed,
compare source and runtime evidence, and open the complete report. Use
`repoevidence workspace .` when you want an explicit workspace path.

Workspace startup only reads project identity, Git metadata, existing
RepoEvidence artifacts, user settings, and terminal capabilities. It does not
scan source, run the target project, connect to MySQL, or modify a database.

## Interactive Workspace

The Workspace is the human-first daily interface. Its ledger covers:

- project identity and Git context;
- Source inspection status and snapshot;
- MySQL Runtime verification status;
- source/runtime Comparison status; and
- Report presence, freshness, and language state.

Selecting an item shows a human explanation, technical details, and contextual
actions such as inspect source, verify MySQL after an effect preview, reconcile
existing artifacts, refresh the report, or open the report. Missing or stale
artifacts do not trigger hidden upstream operations.

Settings supports immediate English / 简体中文 switching, theme and
interaction preferences, and reduced motion. Language preference can be
persisted. Recent activity records operation results and failures. Help and
shortcuts are available, but the visible ledger and actions are the primary
interface.

## What RepoEvidence checks

Source inspection reads repository metadata, common project files, Spring MVC
declarations, Maven project declarations, and Flyway migration files. It does
not run Maven, Flyway, SQL, tests, or target-repository code.

Explicit MySQL verification reads runtime schema metadata, schema summaries,
indexes, constraints, and Flyway history. It does not read business rows.
Reconciliation currently compares source Flyway evidence with runtime Flyway
history; it is not an overall project-health assessment.

## Runtime verification safety

MySQL verification is explicit opt-in. It runs only after user action, uses
environment configuration and fixed read-only metadata queries, shows an
effect preview in the Workspace, does not modify the database, and does not
store credentials in user settings.

Use a least-privilege account with these environment variables. No real
password belongs in a command example:

```text
REPOEVIDENCE_MYSQL_HOST
REPOEVIDENCE_MYSQL_PORT
REPOEVIDENCE_MYSQL_USER
REPOEVIDENCE_MYSQL_PASSWORD
REPOEVIDENCE_MYSQL_DATABASE
```

Only `repoevidence verify mysql .` and its Workspace action connect to MySQL.
Source inspection, report generation, and reconciliation are offline.

## One-shot CLI and automation

These commands do not enter the TUI. They are intended for automation, CI,
scripts, agents, and advanced users:

| Command | Meaning |
| --- | --- |
| `repoevidence inspect .` | Safe source inspection plus report generation. |
| `repoevidence scan .` | Source-only machine artifact. |
| `repoevidence verify mysql .` | Explicit runtime metadata verification. |
| `repoevidence reconcile .` | Offline source/runtime comparison. |
| `repoevidence report .` | Generate or refresh the offline HTML report. |

`inspect` is the convenient source-plus-report workflow. The other commands
remain separate so automation can grant only the operation it needs.

## HTML Report

The report is offline and self-contained. It puts the human conclusion first,
then shows coverage, freshness, limits, next action, and technical findings
across source, Maven, Spring, Flyway, MySQL, and reconciliation. Fact/Evidence
traceability connects interpretations to observed values, while provenance
records consumed artifacts.

The Workspace is for current state, actions, and recovery. The report is for
complete reading, technical evidence, and audit traceability. Report
generation does not start a server, access the network, or run upstream
operations automatically.

## Machine-readable artifacts

```text
.repoevidence/evidence.json
.repoevidence/verification/mysql.json
.repoevidence/reconciliation.json
.repoevidence/report/index.html
.repoevidence/report/manifest.json
```

`evidence.json` is the source artifact; `mysql.json` is the explicit runtime
verification result; `reconciliation.json` is the offline comparison; and
`index.html` is the human report. `report/manifest.json` is only for report
provenance and freshness. It does not replace the Evidence machine schema.

## Status confidence and snapshots

RepoEvidence distinguishes not yet checked, checked for a known snapshot,
changed or stale, unable to confirm freshness, and operation failure. An old
artifact is not proof that it describes the current source. Runtime
verification is a metadata snapshot, not live database monitoring. Comparison
describes only the source/runtime differences currently supported by
RepoEvidence, not overall project health.

## `--plain`, non-TTY, and CI

Bare `repoevidence` enters the Workspace only in a suitable interactive TTY.
With redirected or piped input/output, CI, `TERM=dumb`, or other
non-interactive streams, it uses a non-blocking plain welcome path and exits
without starting the full-screen TUI or waiting for input.

Use `--plain` to choose that behavior explicitly:

```bash
repoevidence --plain
repoevidence --plain workspace .
```

One-shot commands are always non-TUI operations.

## Language

Workspace Settings can switch English / 简体中文 immediately and persist the
user preference. One-shot commands support:

```bash
repoevidence --lang en inspect .
repoevidence --lang zh-CN inspect .
```

The resolution order is:

```text
--lang > REPOEVIDENCE_LANG > user config > system locale > English fallback
```

The user config uses the platform-standard location selected by `platformdirs`
and is not tied to WSL. Machine-facing names and values remain stable English
contracts.

## Installation and supported environments

```bash
pipx install repoevidence
# or, inside a virtual environment:
python -m pip install repoevidence
```

Runtime dependencies are declared directly, including Textual, platformdirs,
Rich, and the existing evidence/runtime dependencies. A fresh wheel includes
the Interactive Workspace, i18n resources, report code, and runtime source.

RepoEvidence is designed for Linux, macOS, Windows, and WSL. Current
interactive release validation has been performed primarily on Linux/WSL;
native Windows/macOS have not been represented as fully manually tested by
this release.

## Release validation limits

- v0.2.0 interactive release validation was performed primarily on Linux/WSL;
  native Windows/macOS interactive manual validation remains pending.
- A real MySQL successful interactive end-to-end journey was not completed
  before this release. Fixture, headless, failure-recovery, and machine
  contract tests cover the current path.

## Security and trust model

Repositories, databases, and artifacts are untrusted input. Static inspection,
report generation, and reconciliation do not execute target code. Report HTML
escapes artifact-derived text and redacts secret-like structured fields.
Passwords are not accepted as CLI arguments and are not intended for artifacts
or reports.

RepoEvidence is not an AI assistant, health scanner, automatic fixer, or
database monitoring service. It records observations, interpretations,
explicit verifications, and uncertainty.

## Development

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check .
python -m build
python -m twine check dist/*
```

The package requires Python `>=3.12`. CI runs tests, Ruff, distribution builds,
and metadata checks without a live database.

## License

RepoEvidence is licensed under Apache-2.0.

---

# RepoEvidence（简体中文）

## RepoEvidence 是什么

RepoEvidence 是一个 local-first、evidence-backed 的仓库理解与运行时验证工具。
它帮助你检查源码声明，在明确授权后验证 MySQL runtime metadata，比较源码
migration 与 runtime history，把结论追溯到 Evidence，并生成离线 HTML Report。

分析是确定性的，不会执行目标仓库代码；源码声明与运行时观察保持分离，并带有
明确的状态、snapshot、provenance 和边界。

## 快速开始

需要 Python 3.12 或更高版本：

```bash
pipx install repoevidence

cd 你的项目
repoevidence
```

在合适的 interactive TTY 中，RepoEvidence 会进入本地 Interactive Workspace。你
可以先检查源码，按需显式验证 MySQL，比较源码和 runtime evidence，并打开完整报
告。需要明确指定当前目录时使用 `repoevidence workspace .`。

Workspace 启动只读取项目身份、Git 元数据、已有 RepoEvidence artifacts、用户设置
和终端能力，不会扫描源码、运行目标项目、连接 MySQL 或修改数据库。

## Interactive Workspace

Workspace 是面向人类日常使用的界面，ledger 包含：

- 项目身份与 Git 上下文；
- Source 检查状态与 snapshot；
- MySQL Runtime verification 状态；
- source/runtime Comparison 状态；
- Report 是否存在、新鲜度和语言状态。

选择一项可以看到人类可读的解释、technical details 和 contextual actions，例如
检查源码、在 effect preview 后验证 MySQL、离线比较已有 artifacts、刷新或打开报
告。缺失或过期的 artifact 不会触发隐藏的上游操作。

Settings 支持即时切换 English / 简体中文、主题、interaction 和 reduced motion，
语言偏好可以持久化。Recent activity 会记录操作结果和失败信息。Help 和快捷键可
用，但主要入口是可见的 ledger 与 actions。

## RepoEvidence 检查什么

源码检查读取仓库元数据、常见项目文件、Spring MVC 声明、Maven 项目声明和
Flyway migration 文件；不会运行 Maven、Flyway、SQL、tests 或目标仓库代码。

显式 MySQL verification 读取 schema metadata、summary、indexes、constraints 和
Flyway history，不读取业务表行。Reconciliation 当前比较源码 Flyway evidence 与
runtime Flyway history，不能作为整体项目健康评估。

## Runtime verification 的安全边界

MySQL verification 是 explicit opt-in，只有用户操作后才运行，使用环境变量和固定
只读 metadata queries；Workspace 会在连接前显示 effect preview。它不修改数据库，
也不把凭据写入 user settings。

```text
REPOEVIDENCE_MYSQL_HOST
REPOEVIDENCE_MYSQL_PORT
REPOEVIDENCE_MYSQL_USER
REPOEVIDENCE_MYSQL_PASSWORD
REPOEVIDENCE_MYSQL_DATABASE
```

只有 `repoevidence verify mysql .` 及对应的 Workspace action 会连接 MySQL；源码
检查、报告生成和 Reconciliation 都是 offline 操作。

## One-shot CLI 与自动化

这些命令不会进入 TUI，适合 automation、CI、scripts、Agent 和高级用户：

| 命令 | 含义 |
| --- | --- |
| `repoevidence inspect .` | 安全检查源码并生成报告。 |
| `repoevidence scan .` | 只生成源码 machine artifact。 |
| `repoevidence verify mysql .` | 显式验证 runtime metadata。 |
| `repoevidence reconcile .` | 离线比较源码/runtime evidence。 |
| `repoevidence report .` | 生成或刷新离线 HTML Report。 |

## HTML Report

报告是 offline、self-contained 的，先展示 human conclusion，再展示 source、Maven、
Spring、Flyway、MySQL 和 reconciliation 的范围、新鲜度、限制、下一步、technical
findings 与 audit traceability。Fact/Evidence 可追溯观察值，provenance 记录报告
使用的 artifacts。

Workspace 负责当前状态、操作和 recovery；报告负责完整阅读、technical evidence
和审计追溯。生成报告不会启动服务器、访问网络或自动运行上游操作。

## Machine-readable artifacts

```text
.repoevidence/evidence.json
.repoevidence/verification/mysql.json
.repoevidence/reconciliation.json
.repoevidence/report/index.html
.repoevidence/report/manifest.json
```

`report/manifest.json` 只用于报告 provenance/freshness，不是 Evidence machine
schema 的替代品。

## 状态可信度与 snapshot

RepoEvidence 区分尚未检查、已针对已知 snapshot 检查、changed/stale、无法确认
freshness 和操作失败。旧 artifact 不保证对应当前源码。Runtime verification 是
metadata snapshot，不是实时数据库监控；Comparison 只说明当前支持的
source/runtime evidence 差异，不代表整体项目健康。

## `--plain`、non-TTY 与 CI

bare `repoevidence` 只在合适的 interactive TTY 中进入 Workspace。redirect、pipe、
CI、`TERM=dumb` 或其他 non-interactive 场景会使用不阻塞的 plain welcome 路径并退
出，不启动全屏 TUI，也不等待输入。

```bash
repoevidence --plain
repoevidence --plain workspace .
```

One-shot commands 始终是 non-TUI 操作。

## 语言

Workspace Settings 可即时切换 English / 简体中文并持久化偏好；one-shot commands
支持 `--lang en` 和 `--lang zh-CN`。优先级为：

```text
--lang > REPOEVIDENCE_LANG > user config > system locale > English fallback
```

user config 使用 `platformdirs` 选择的平台标准路径，不绑定 WSL。machine-facing
名称和值保持稳定英文。

## 安装与支持环境

```bash
pipx install repoevidence
# 或在 virtual environment 中：
python -m pip install repoevidence
```

package 直接声明 Textual、platformdirs、Rich 以及现有运行时依赖；fresh wheel 包含
Interactive Workspace、i18n、report code 和运行时源码。

设计目标覆盖 Linux、macOS、Windows 和 WSL。当前 interactive release validation
主要在 Linux/WSL 完成，不应把 Windows/macOS 视为已全面人工测试。

## 本次 release validation 的边界

- v0.2.0 interactive release validation 主要在 Linux/WSL 完成；native
  Windows/macOS interactive manual validation 仍未完成。
- 本 release 前未完成真实 MySQL successful interactive end-to-end 验收；当前路径
  已有 fixture、headless、failure-recovery 和 machine contract 测试覆盖。

## Security and trust model

repositories、databases 和 artifacts 都被视为不受信任输入。Static inspection、
report generation 和 reconciliation 不执行目标代码；Report HTML 会转义 artifact
文本并 redaction 类似 secret 的结构化字段。密码不接受为 CLI 参数，也不应写入
artifacts 或 reports。

RepoEvidence 不是 AI assistant、health scanner、automatic fixer 或 database
monitoring service，而是记录观察、解释、显式验证和不确定性。

## 开发

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check .
python -m build
python -m twine check dist/*
```

package 要求 Python `>=3.12`；CI 会在无需 live database 的情况下运行 tests、Ruff、
distribution build 和 metadata checks。

## License

RepoEvidence 采用 Apache-2.0 授权。
