# RepoEvidence

[English](README.md) | 简体中文

## RepoEvidence 是什么

RepoEvidence 是一个 local-first、evidence-backed 的仓库理解与运行时验证
工具。它帮助你检查源码声明了什么，在明确授权后按需读取 MySQL runtime
metadata，比较源码 migration 与数据库 history，把结论追溯到 Evidence，并
生成离线 HTML Report。

分析过程是确定性的，不会执行目标仓库代码。源码声明与运行时观察会被分开
保存，因此每个结论都可以连同证据、状态、快照和边界一起阅读。

```text
repository → source inspection → Evidence / Fact → report
                              ↘ runtime verification / reconciliation
```

## 快速开始

RepoEvidence 需要 Python 3.12 或更高版本。普通用户建议从交互式工作区开始：

```bash
pipx install repoevidence

cd 你的项目
repoevidence
```

在合适的交互式 TTY 中，RepoEvidence 会进入本地 Interactive Workspace。你
可以先检查源码，再按需显式验证 MySQL、比较源码和 runtime evidence，并打开
完整报告。

需要明确指定当前目录时，也可以使用：

```bash
repoevidence workspace .
```

启动 Workspace 不会扫描源码、不运行目标项目、不连接 MySQL，也不会修改数据库。
启动阶段只读取项目身份、Git 元数据、已有 RepoEvidence artifact、用户设置和
终端能力。

## Interactive Workspace

Workspace 面向日常使用 RepoEvidence 的人类用户。它展示当前项目状态和下一步
安全操作，不要求你先记住一组命令。

| 区域 | 展示内容 |
| --- | --- |
| Project identity | 仓库名称、位置、Git branch/commit 和已知项目上下文。 |
| Source | 源码是否已经检查、对应哪个 snapshot，以及检查发现的内容。 |
| MySQL Runtime | runtime metadata 是否已经显式验证，以及当前、过期、不确定或失败状态。 |
| Comparison | 是否可以比较源码/runtime evidence，以及当前支持的差异。 |
| Report | 离线报告是否存在、是否新鲜，或是否需要刷新/切换语言重新生成。 |

选择 ledger 中的一项，可以看到面向人的解释、technical details 和当前上下文
操作。操作会随状态变化：检查源码、在 effect preview 后验证 MySQL、离线比较已有
artifact、刷新报告或打开报告。如果 artifact 缺失或过期，Workspace 不会静默
替你运行上游操作。

Settings 可以即时切换 English / 简体中文，也可以设置主题、interaction 和
reduced motion。语言偏好可以保存，供之后的 session 使用。Recent activity 会
记录操作结果和失败信息，方便恢复。Workspace 提供 Help 和快捷键，但主要入口
是可见的 ledger 与 contextual actions，而不是记忆快捷键。

## RepoEvidence 检查什么

源码检查会读取仓库元数据、常见项目文件、Spring MVC 声明、Maven 项目声明和
Flyway migration 文件。它不会运行 Maven、Flyway、SQL、tests 或目标仓库代码。

在用户明确请求后，MySQL verification 会读取 runtime schema metadata、schema
summary、indexes、constraints 和 Flyway history，不读取业务表行。当前
Reconciliation 比较的是源码 Flyway evidence 与 runtime Flyway history，不能把
它理解为对整个项目健康状况的判断。

## Runtime verification 的安全边界

MySQL verification 是 explicit opt-in 操作，只有用户采取操作后才会发生，并通
过环境变量和固定的只读 metadata queries 配置。Workspace 会在建立连接前展示
effect preview。RepoEvidence 不修改数据库，也不会把数据库凭据保存到 user
settings。

请使用最小权限账号，通过以下环境变量配置；不要在命令示例或源码中写入真实密码：

```text
REPOEVIDENCE_MYSQL_HOST
REPOEVIDENCE_MYSQL_PORT
REPOEVIDENCE_MYSQL_USER
REPOEVIDENCE_MYSQL_PASSWORD
REPOEVIDENCE_MYSQL_DATABASE
```

只有 `repoevidence verify mysql .` 及其对应的 Workspace 操作会连接 MySQL。
源码检查、报告生成和 Reconciliation 都是 offline 操作。

## One-shot CLI 与自动化

One-shot commands 不会进入 TUI，适合 automation、CI、scripts、Agent 和高级
用户：

| 命令 | 含义 |
| --- | --- |
| `repoevidence inspect .` | 安全检查源码，并生成报告。 |
| `repoevidence scan .` | 只生成源码 machine artifact。 |
| `repoevidence verify mysql .` | 显式验证 runtime metadata。 |
| `repoevidence reconcile .` | 离线比较源码/runtime evidence。 |
| `repoevidence report .` | 从已有 artifact 生成或刷新离线 HTML Report。 |

`inspect` 适合一次得到源码 snapshot 和报告；`scan`、`verify`、`reconcile` 和
`report` 保持独立，让自动化流程可以精确选择被允许的操作。

## HTML Report

HTML Report 是 offline、self-contained 的。它先给出 human conclusion，再展示
检查范围、新鲜度、限制、下一步、technical findings，以及 source、Maven、Spring、
Flyway、MySQL 和 reconciliation 的 audit traceability。Fact 与 Evidence 的链接
保留从结构化解释回到原始观察值的路径，provenance 则记录报告使用了哪些 artifact。

Workspace 负责当前状态、操作和 recovery；HTML Report 负责完整阅读、technical
evidence 和 audit traceability。生成报告不会启动服务器、访问网络，也不会自动
运行上游操作。

## Machine-readable artifacts

相关操作运行后，RepoEvidence 会在项目目录写入这些 artifact：

```text
.repoevidence/evidence.json
.repoevidence/verification/mysql.json
.repoevidence/reconciliation.json
.repoevidence/report/index.html
.repoevidence/report/manifest.json
```

`evidence.json` 是源码检查 artifact；`mysql.json` 是显式 runtime verification
结果；`reconciliation.json` 是离线比较结果；`index.html` 是面向人的报告。
`report/manifest.json` 只记录报告的 provenance 和 freshness 输入，不能替代
Evidence machine schema。

## 状态可信度与 snapshot

RepoEvidence 会区分：

- 尚未检查；
- 已针对一个已知 snapshot 检查；
- 自该 snapshot 后源码或输入发生变化，结果 changed / stale；
- 暂时无法确认 freshness；
- 操作失败。

目录中存在旧 artifact，并不代表它一定对应当前源码。Runtime verification 是
一次 metadata snapshot，不是实时数据库监控。Comparison 只说明 RepoEvidence
当前支持的 source/runtime evidence 差异，不能包装成“整体项目健康”。

## `--plain`、non-TTY 与 CI

在 interactive TTY 中，直接运行 `repoevidence` 会进入 Workspace。当 stdin 或
stdout 被 redirect、pipe、CI 使用，设置为 `TERM=dumb`，或进程处于其他
non-interactive 情况时，bare `repoevidence` 不会启动 full-screen TUI，而是走不
阻塞的 plain welcome 路径并退出，不会等待输入。

需要明确选择 plain behavior 时使用：

```bash
repoevidence --plain
repoevidence --plain workspace .
```

所有 one-shot commands 都是 plain CLI 操作，与终端是否交互无关，因此 CI 不会突
然启动全屏 UI。

## 语言

在 Workspace 的 Settings 中可以即时切换 English / 简体中文，选择的偏好可以持久
化，供之后的 session 使用。

Automation 和 one-shot commands 可以使用：

```bash
repoevidence --lang en inspect .
repoevidence --lang zh-CN inspect .
```

语言优先级为：

```text
--lang
>
REPOEVIDENCE_LANG
>
user config
>
system locale
>
English fallback
```

用户配置保存在 `platformdirs` 选择的平台标准位置，不把路径写死为当前 WSL 环境。
命令名、option 名、环境变量名、JSON keys、schema versions、IDs、status values、
reconciliation kinds 和 error codes 等 machine-facing contract 始终保持稳定英文。

## 安装与支持环境

`pipx` 适合安装隔离的命令行工具：

```bash
pipx install repoevidence
```

也可以在普通 virtual environment 中安装：

```bash
python -m pip install repoevidence
```

package 会直接声明运行时需要的 dependencies，包括 Textual、platformdirs、Rich
以及现有的 evidence/runtime dependencies。fresh wheel 会包含 Interactive
Workspace、本地化资源、report code 和运行时源码，不依赖开发环境中的 transitive
dependency。

RepoEvidence 的设计目标覆盖 Linux、macOS、Windows 和 WSL。当前 interactive
release validation 主要在 Linux/WSL 完成；本 release 不应被理解为已
完成 Windows/macOS 的全面人工测试。

## 本次 release validation 的边界

- v0.2.0 interactive release validation 主要在 Linux/WSL 完成；native
  Windows/macOS interactive manual validation 仍未完成。
- 本 release 前未完成真实 MySQL successful interactive end-to-end 验收；当前路径
  已有 fixture、headless、failure-recovery 和 machine contract 测试覆盖。

## Security and trust model

RepoEvidence 将 repositories、databases 和保存的 artifacts 视为不受信任的输入。
Static inspection、report generation 和 reconciliation 不执行目标代码。Report
HTML 会转义来自 artifact 的文本，并对类似 secret 的结构化字段做 redaction。
密码不接受为 CLI 参数，也不应进入 artifacts 或 reports。

RepoEvidence 不是 AI assistant、health scanner、automatic fixer 或 database
monitoring service。它记录观察到什么、推断了什么、什么被显式验证，以及什么暂时
无法确认。

## 开发

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check .
python -m build
python -m twine check dist/*
```

package 要求 Python `>=3.12`。CI 会运行 tests、Ruff、distribution build 和
distribution metadata checks，不要求连接 live database。

## License

RepoEvidence 采用 Apache License 2.0 授权。
