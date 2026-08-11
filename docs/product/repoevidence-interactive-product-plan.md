# RepoEvidence Interactive Product + UX + Terminal Architecture Plan

> 状态：产品决策讨论稿（Draft for Product Review）
>
> 日期：2026-08-09
>
> 适用范围：RepoEvidence 下一阶段的人机交互、终端产品形态与适配层架构
> 明确不代表：最终批准方案、实现承诺、API 冻结或发布计划

本文基于当前仓库、当前未提交 working tree、现有测试及已有 CLI / Report UX 设计文档编写。本文只规划，不授权实现；任何阶段开始前都需要产品负责人逐阶段验收和批准。

## 1. Executive Summary

### 1.1 一句话建议

RepoEvidence 应成为一个 **Hybrid developer tool**：保留稳定、可脚本化的 one-shot CLI 作为自动化入口，同时为人类用户提供一个以“项目证据状态 + 上下文动作”为核心的长期存在终端工作区。

这里的重点不是“给 CLI 加一个漂亮外壳”，也不是复制 AI coding agent 的聊天框。RepoEvidence 的核心任务是：

1. 理解源码声明了什么；
2. 在用户明确授权时验证运行时事实；
3. 比较两类证据；
4. 让用户能够追溯结论。

因此，最适合它的交互核心是 **稳定的状态账本（evidence status ledger）+ 明确的下一步动作 + 可下钻的证据详情**。

### 1.2 推荐结论

| 决策维度 | 推荐方向 |
|---|---|
| 产品形态 | Hybrid CLI + persistent interactive workspace |
| 人类主交互 | 状态驱动、上下文动作式 workspace，而非 REPL、聊天或菜单树 |
| 专家加速 | 可选 command palette；它是加速器，不是主导航，也不要求 slash command |
| 自动化接口 | 现有 one-shot CLI + machine JSON，保持稳定与非交互 |
| 深度阅读 | HTML Report，继续承担完整 Evidence traceability，不在本阶段推翻重做 |
| 技术候选 | Textual 为首选，但必须先通过 Phase 0 跨终端原型门禁；Rich 保留为 one-shot/plain presenter |
| 状态架构 | 将 artifact 生命周期、freshness、operation state、domain outcome 分离 |
| 首次启动 | 只做安全、只读的项目与 artifact 发现；不自动 scan、不运行目标代码、不连接数据库 |
| 迁移方式 | 先增加显式 `workspace` 入口，再经人工验收决定是否让 TTY 下的裸 `repoevidence` 默认进入 workspace |

### 1.3 本阶段最重要的产品原则

- **状态可信比视觉华丽重要。** 如果无法证明数据仍然新鲜，应显示“无法确认”，不能显示“当前”。
- **显式授权连接运行时。** 只有用户选择 MySQL 验证动作后才允许连接数据库。
- **失败不退出工作区。** 错误是可恢复的 session state，不是整个程序的终点。
- **颜色只是冗余编码。** 每种状态必须同时通过文字与 ASCII symbol 表达。
- **自动化永远不进入 TUI。** pipe、redirect、CI 和 Agent 获得稳定的非交互行为。
- **UI 不产生新的 machine truth。** TUI 只调用 application service、订阅 operation event、呈现 state projection。
- **渐进披露。** 首页回答“现在是什么状态、下一步是什么”；完整证据留给 detail 和 HTML。

### 1.4 当前最关键的架构风险

当前 `assessment.CheckState.current` 更接近“artifact 存在、可解析且该次操作成功”，并不总能证明它与实时仓库一致。现场审查发现，工作目录中的 `evidence.json` 来源提交与当前 HEAD 不同，但 `assess_repository()` 仍将 Source 判为 `current`；dirty worktree 又进一步增加了不确定性。

如果直接把这五态投射成 workspace 的“当前/最新”，终端应用会向用户制造错误信心。因此，interactive work 开始前必须先建立：

- artifact lifecycle；
- freshness / provenance；
- operation state；
- domain outcome（例如 drift detected）；

四者分离的 projection。这个问题优先级高于终端框架选型。

### 1.5 非目标

本规划不加入，也不为以下内容安排实施阶段：

- LLM 或 chat assistant；
- PostgreSQL、Gradle 或新 Collector；
- cloud backend、Web SPA、账号系统；
- artifact 历史归档平台；
- HTML Report 的整体重做；
- 自动修复源码或数据库；
- 在 TUI 中采集或保存数据库密码；
- 用健康分、质量分或单一百分比分数概括证据质量。

## 2. Current Product Assessment

### 2.1 审查范围与基线

本次审查覆盖：

- `README.md`、`README.zh-CN.md`、`README.pypi.md`；
- `pyproject.toml`；
- `src/repoevidence/cli.py`；
- `application.py`、`assessment.py`；
- `presentation/*`；
- `i18n.py`；
- `reporting.py`、`report_view.py`、`report_html.py`；
- scanner、collector、model、verification、reconciliation 等相关实现；
- CLI、application、assessment、machine contract、terminal presentation、localized CLI、report state 等相关测试；
- `docs/superpowers/specs/` 与 `docs/superpowers/plans/` 中现有设计和实施文档；
- 当前 Git branch、HEAD、tracked diff、untracked files 与现有 `.repoevidence/` artifact。

审查时测试基线为 `213 passed`。这只说明当前测试基线通过，不代表 interactive 产品已被实现或验收。

### 2.2 当前已实现能力

当前公开工作流为：

```text
repoevidence scan .
repoevidence inspect .
repoevidence verify mysql .
repoevidence reconcile .
repoevidence report .
```

现有产品已经具备：

- 静态扫描与多 collector 聚合；
- Evidence / Fact / Conflict machine model；
- MySQL metadata / Flyway history 的只读 runtime verification；
- source 与 runtime 的离线 reconciliation；
- JSON machine artifact；
- HTML Report；
- application service layer；
- presentation-neutral assessment 与 report view；
- 英文和简体中文；
- Typer one-shot CLI；
- 基于 Rich 的终端文本呈现；
- TTY 与 plain output 的基本适配；
- 一轮围绕“结论 → 覆盖范围 → 注意项 → 下一步 → 技术证据”的 CLI / Report 信息架构调整。

### 2.3 分层判断

#### Machine contract

以下内容应被视为稳定 machine contract，interactive UI 不得暗改其语义或重新实现：

| Contract | 当前职责 | UI 重构要求 |
|---|---|---|
| `Evidence` / `Fact` / `Conflict` | 描述来源、事实、冲突及引用 | 只读消费，保持 ID、字段与引用关系 |
| `ScanResult` | 静态扫描 machine result | 保持 schema、collector 结果与序列化稳定 |
| `VerificationResult` | MySQL verification result | 保持 env-only、只读查询和错误语义 |
| `ReconciliationResult` | source/runtime 比较结果 | 保持 exact input hash 与 deterministic output |
| `.repoevidence/evidence.json` | 最新静态证据 artifact | 不改变路径和 JSON 契约 |
| `.repoevidence/verification/mysql.json` | 最新 MySQL 快照 | 不改变路径和 JSON 契约 |
| `.repoevidence/reconciliation.json` | 最新比较结果 | 不改变路径和 JSON 契约 |
| schema version / status / IDs | Agent、CI 和外部消费者的稳定接口 | UI label 不得反向污染 machine enum |

Machine layer 的关键安全属性也必须保持：

- `scan` / `inspect` / `report` 不连接数据库；
- `reconcile` 只读取 artifact，不连接数据库；
- 只有显式 `verify mysql` 才允许数据库连接；
- 不运行 target code；
- MySQL 查询保持只读且不读取业务行；
- report 保持离线、自包含、转义和敏感字段处理；
- deterministic ordering、reference validation 和输入 hash 不因 UI 改变。

#### Application layer

`application.py` 已经提供适合复用的 orchestration seam：

- `scan_repository()`；
- `inspect_repository()`；
- `verify_mysql_repository()`；
- `reconcile_repository()`；
- `generate_report()`。

这些 service 负责路径校验、调用 machine capability、写入标准 artifact 和返回 application result。未来 CLI 与 interactive adapter 应共同调用这些 service，而不是各自调用 collector 或 verifier。

`assessment.py` 是只读的状态解释层，当前提供 `not_run / failed / current / stale / unknown` 五态及 conclusion。它适合成为 workspace projection 的输入，但其 freshness 语义必须先被加强，不能直接当作实时项目状态。

#### Presentation layer

以下属于 presentation，可在不改变 machine truth 的前提下演进：

- Typer command、参数解析、exit code 路由；
- `presentation/terminal.py` 中的 Rich 输出；
- i18n message catalog 与 human label；
- `report_view.py` 中的展示 view model；
- `report_html.py` 的 HTML 结构与视觉；
- 将来新增的 interactive controller、view、key binding 与 workspace layout。

### 2.4 当前 UX 改造到了哪里

上一轮改造已经解决了部分“原始 JSON dump / 平铺输出”的问题：

- no-arg 首屏变成简短的产品定位、推荐动作与 help 提示；
- `inspect` 成为安全的 guided path；
- CLI 与 HTML 采用一致的叙事顺序；
- 英中双语覆盖扩展；
- terminal presenter 有了克制的颜色与层次；
- Report 在结论、覆盖、注意项和 traceability 上明显改善；
- machine-contract tests 与 journey tests 对安全边界和输出行为形成保护。

但它仍然是“一条命令 → 一段彩色文本 → 退出”。Rich 改善了排版，没有改变产品交互模型。因此人工反馈所说的“不像成熟 developer tool”是成立的：问题不只是颜色、标题或 panel 数量，而是缺少持续上下文和可恢复工作流。

### 2.5 当前 working tree 的意义

审查时仓库位于 `main`，相对 `origin/main` 存在大量未提交修改和未跟踪文件。它们主要属于上一轮 CLI / Report adaptive inspection 工作，包括：

- README、packaging、CLI、i18n、reporting 及相关测试的 tracked 修改；
- 新增但未提交的 application、assessment、presentation、report view / HTML 文件；
- 新增但未提交的 application、assessment、machine contract、journey、report state、terminal presentation 测试；
- `docs/superpowers/` 下的新设计与实施计划；
- `dist/` 产物。

这些都被视为用户现有工作，本规划不修改、回滚、整理或提交它们。它也意味着：下一阶段不能假设这些新接口已经形成发布契约；在开始 interactive 实现前，应先由负责人决定上一轮改造的验收与落库边界。

### 2.6 未来可以重构与绝不能破坏的边界

可以规划重构：

- assessment projection 与 freshness 推断；
- presentation-neutral workspace model；
- application operation event / observer；
- artifact 的原子写入；
- CLI adapter 与 interactive adapter 的装配；
- i18n catalog 的模块化和动态刷新；
- terminal-only visual system 与 responsive layout。

绝不能因 UI 重构破坏：

- Pydantic machine schema 和 JSON 语义；
- artifact 路径、确定性和引用关系；
- CLI command、参数、exit code、stdout/stderr 和非交互语义；
- MySQL 仅在显式验证时连接的安全承诺；
- offline reconciliation；
- HTML 的完整证据可追溯能力；
- `--lang` / environment locale 的既有兼容；
- target repository 与 user preference 的存储隔离。

## 3. Product Positioning

### 3.1 RepoEvidence 最终应该是什么

RepoEvidence 应被定位为：

> 一个本地优先、证据可追溯的 repository understanding and runtime verification tool；它帮助开发者看清“源码声明”“运行时事实”和“两者差异”，但不替用户执行目标项目，也不自动修改系统。

它不是：

- 通用项目管理 dashboard；
- 数据库运维客户端；
- AI 聊天机器人；
- IDE 替代品；
- 持续驻留的监控 daemon；
- 对代码质量给出单一分数的 scanner。

### 3.2 核心用户任务

RepoEvidence 对应的是一个有明确先后关系但允许跳转的 investigation loop：

```text
发现项目
   ↓
理解源码声明 ───────→ 阅读 Evidence
   ↓
按需验证运行时
   ↓
比较源码与运行时 ──→ 处理 drift / uncertainty
   ↓
生成可分享、可审计的 Report
   ↺ 代码、数据库或 artifact 变化后刷新
```

这是“检查 / 验证 / 比较 / 阅读证据”的任务模型，不是“输入任意自然语言并等待回答”的消息模型。

### 3.3 为什么不是只做更漂亮的 one-shot CLI

one-shot CLI 对以下场景仍然最优：

- 用户已经知道准确动作；
- shell automation；
- CI；
- Agent / script；
- 失败必须用 exit code 表达；
- 输出需要 pipe、redirect 或机器解析。

但它不擅长：

- 保持当前 project / artifact / operation context；
- 在一次 session 内展示先后状态变化；
- 失败后让用户就地修复和重试；
- 帮助新手理解 prerequisite 与下一步；
- 在 source、runtime、comparison、report 之间快速浏览。

因此，成熟方向不是替换 CLI，而是为人类任务增加互补界面。

### 3.4 产品界面组合

| 界面 | 主要受众 | 核心职责 | 不应承担 |
|---|---|---|---|
| Interactive Terminal | 新手、日常用户、高级调查者 | 当前状态、操作、恢复、下一步、摘要下钻 | 完整 Evidence 长文档、机器契约 |
| One-shot CLI | 熟练用户、CI、script、Agent | 可预测执行、exit code、组合与自动化 | 持久导航、session 状态 |
| Machine JSON | Agent、CI、集成程序、审计工具 | 稳定、可验证的 machine truth | 人类友好叙事 |
| HTML Report | 深度阅读、分享、审计 | 完整结论、证据来源、表格、hash、traceability | 实时操作控制、运行进度 |

## 4. User Personas

### 4.1 Persona 总览

| 用户类型 | 为什么打开 | 第一优先问题 | 第一动作 | 主要界面 |
|---|---|---|---|---|
| 第一次使用的普通开发者 | 想快速理解陌生仓库或验证工具价值 | “这是什么项目？工具会不会运行/修改它？” | 只读查看项目与可执行的安全动作 | Interactive Terminal |
| 日常用户 | 检查源码或环境变化后的状态 | “上次结果还有效吗？下一步该刷新什么？” | 刷新 stale / unknown 的最小必要步骤 | Interactive + CLI |
| Evidence 高级用户 | 追查具体声明、冲突和来源位置 | “这个结论由哪些 Evidence 支撑？” | 打开 detail 或 HTML 的对应位置 | HTML + Interactive + JSON |
| CI / script / Agent | 自动产生、校验或消费 artifacts | “命令是否确定成功，schema 是否稳定？” | 运行明确 subcommand | CLI + JSON |
| 审计 / 可追溯结果用户 | 复核某一时点的结论与 provenance | “输入、时间、hash、错误和限制是什么？” | 阅读 Report 并保留 artifacts | HTML + JSON |

### 4.2 第一次使用 RepoEvidence 的普通开发者

**打开原因**：刚接触一个仓库、看到文档推荐、或想知道数据库迁移声明与运行环境是否一致。

**最想知道**：

- RepoEvidence 是做什么的；
- 当前目录是否可分析；
- 它是否会运行 target code 或连接数据库；
- 现在是否已有结果；
- 最安全的第一步是什么。

**第一步**：确认项目身份后选择“Inspect source”。这是显式动作，不在启动时自动执行。

**最容易困惑**：把“没有验证 MySQL”理解成失败；把“有 artifact”理解成“仍然最新”；不知道 inspect、verify、reconcile、report 的关系。

**完成后需要**：一个清楚的 source 摘要、覆盖范围、限制和下一步；如果要继续，应能原地选择验证或查看报告。

**主要界面**：Interactive Terminal；HTML 是需要深读时的第二界面。

### 4.3 已知基本能力的日常用户

**打开原因**：代码、分支或环境刚变化，希望确认上次证据是否仍有效。

**最想知道**：什么发生了变化、哪一步需要重跑、是否出现 drift。

**第一步**：查看四项 status ledger，并执行被标记为 stale / uncertain 的最小动作。

**最容易困惑**：时间戳很新但输入已经变化；runtime 快照成功却被误认为实时连接状态；重跑 scan 后旧 comparison 仍存在但已 stale。

**完成后需要**：可信的最新状态、清楚的 domain conclusion、可复制的 report path。

**主要界面**：Interactive Terminal 用于状态和恢复；熟练后也会直接使用 one-shot CLI。

### 4.4 需要深入 Evidence 的高级用户

**打开原因**：解释某个 API、Maven、Flyway、runtime schema 或 reconciliation finding。

**最想知道**：结论对应的 Evidence ID、Fact、source location、collector、runtime row 和 input hash。

**第一步**：从状态或 finding 摘要下钻，随后打开 HTML 的精确章节或直接检查 JSON。

**最容易困惑**：过度简化的 TUI 隐藏限制；presentation label 与 machine enum 不一致；旧 report 与新 artifact 混用。

**完成后需要**：可追溯证据链、明确的不确定性、可复现的 machine artifact。

**主要界面**：HTML 是完整阅读主界面；Interactive 用于导航和操作；JSON 是最终技术依据。

### 4.5 CI / script / Agent

**打开原因**：在流水线中生成 artifact、比较结果，或让 Agent 消费稳定结构。

**最想知道**：命令是否非交互、exit code 是否可靠、stdout/stderr 是否稳定、schema 是否兼容。

**第一步**：调用带完整参数的现有 subcommand，而不是启动 workspace。

**最容易困惑**：TTY 检测意外进入 alternate screen；颜色污染日志；human copy 混入 machine output；默认行为发生不兼容变化。

**完成后需要**：确定的 exit code、artifact path 和 machine JSON，不需要动画或 keyboard UI。

**主要界面**：One-shot CLI + JSON。HTML 只在产物归档需要时生成。

### 4.6 审计或需要可追溯结果的用户

**打开原因**：复核某次交付、迁移或环境差异，可能不参与日常开发。

**最想知道**：这个结论在什么输入、提交、时间和工具版本下产生；哪些内容未覆盖；错误是否被保留。

**第一步**：阅读生成的 HTML Report，再根据 Evidence ID 查看 JSON。

**最容易困惑**：把当前 workspace 状态与某个历史报告混在一起；把 unavailable 当成 verified clean；看不到失败的技术细节。

**完成后需要**：可以保存和分享的 self-contained Report、对应 artifacts 与明确 provenance。

**主要界面**：HTML + JSON；Interactive 只帮助定位与刷新。

## 5. Current UX Failure Analysis

### 5.1 第一屏缺少“项目上下文”

当前裸 `repoevidence` 能说明产品和推荐 `inspect`，但它不知道用户此刻在哪里，也不回答：

- 当前目录是什么项目；
- 已有哪些 artifacts；
- 哪些结果已失败或过时；
- Report 是否存在；
- 最小下一步是什么。

因此首屏仍像 command help 的前言，而不是一个知道当前项目状态的 developer tool。

### 5.2 命令之间没有连续性

用户需要记忆并重复输入：

```text
repoevidence inspect .
repoevidence verify mysql .
repoevidence reconcile .
repoevidence report .
```

每个进程结束后，刚才的成功、失败、warning 和 next action 都消失。用户自己承担了 workflow controller 的角色。

### 5.3 彩色文本不是 terminal application

Rich 改善了层次，但当前 terminal presenter 没有：

- 持续存在的选择与 focus；
- 可响应的 status area；
- operation lifecycle；
- detail / back navigation；
- error recovery action；
- session activity；
- 可发现但不过载的 keyboard model。

因此“更漂亮”没有转化成“更可操作”。

### 5.4 状态语义存在过度承诺

`current`、`stale` 等 machine-facing state 如果未经 projection 直接翻译，普通用户很容易理解为“与当前项目事实完全一致”。而现在并没有对 dirty worktree、legacy provenance、runtime snapshot age、report input manifest 提供统一证明。

这是产品可信度问题，不是 copy 问题。

### 5.5 默认语言虽然可配置，但不够产品化

现有 `--lang`、`REPOEVIDENCE_LANG` 和 system locale 已具备基础，但用户无法在持续 session 中：

- 看到当前 language 来源；
- 立即切换并刷新整个 UI；
- 将偏好与项目 artifact 隔离地持久保存；
- 理解 CLI explicit flag、env 和偏好的优先级。

### 5.6 深度与首页之间仍缺少桥梁

HTML Report 已经明显改善，但 CLI 与 Report 之间仍是“生成一个路径”。用户缺少：

- report 是否存在、是否 stale、使用何种语言生成的状态；
- 明确的 generate / refresh / open action；
- 从 terminal finding 到 HTML 对应位置的导航语义。

本阶段应补桥梁，而不是重做 Report。

## 6. Product Interface Strategy

### 6.1 比较的产品形态

| 产品形态 | 新手 | 熟练用户 | CI / automation | 状态持续 | 错误恢复 | 长期复杂度 | 适配度 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A. 传统 one-shot CLI | 中 | 高 | 最高 | 低 | 低 | 低 | 必须保留，但不足以独立承担人类体验 |
| B. 持久 full-screen terminal app | 高 | 高 | 不适用 | 最高 | 高 | 高 | 适合作为人类主界面，但不能替换 CLI |
| C. command palette-first app | 中 | 最高 | 不适用 | 高 | 中 | 中高 | 适合作为专家加速，不适合作为唯一入口 |
| D. menu-driven app | 高 | 低中 | 不适用 | 高 | 高 | 中 | 上手容易，但规模增长后笨重且像安装向导 |
| E. Hybrid CLI + interactive workspace | 高 | 最高 | 最高 | 高 | 高 | 中高 | 最符合 RepoEvidence 的混合用户结构 |
| F. REPL / command prompt | 中 | 高 | 低（已有 shell 更好） | 高 | 中 | 中 | 与调查任务不匹配，容易复制 shell 和 slash command |

### 6.2 评价维度

#### 新手学习成本

新手需要看到状态、prerequisite 和明确的主要动作，而不是先学命令语法。persistent workspace 和 menu 都能帮助，但 menu 容易掩盖整体状态；状态 workspace 更能建立心智模型。

#### 熟练用户效率

熟练用户需要两条快路径：

- shell 中直接执行既有 one-shot command；
- workspace 中通过少量稳定快捷键或 palette 跳到动作。

不应强迫熟练用户用方向键穿过多层菜单。

#### CI、可脚本化与 accessibility

CI 和 Agent 必须完全绕过 interactive runtime。对 screen reader、终端兼容或不喜欢 alternate screen 的人，也必须提供 plain one-shot path。accessibility 不能只等同于 TUI 的 keyboard support。

#### 状态持久性

这里有两个不同概念：

- **session persistence**：工作区内操作后页面继续存在；
- **project persistence**：`.repoevidence/` artifacts 在进程间保留。

MVP 需要前者与现有后者，但不需要引入 daemon、数据库或新的历史记录系统。

#### 多语言

persistent app 要求所有可见文本从 message key 投射，并可在 session 内重新渲染。命令名称和 machine enum 不翻译；人类 label、帮助与恢复建议翻译。

#### terminal compatibility

成熟体验必须包含 graceful degradation，而不是假设所有终端都支持 alternate screen、24-bit color、mouse、Unicode icon 或 120 列宽。

### 6.3 组合策略

推荐组合不是让一个界面统治全部用户，而是按任务分工：

```text
                       shared application services
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
 one-shot CLI adapter    interactive workspace     report presenter
        │                         │                         │
 stdout/stderr/exit       state/actions/recovery      self-contained HTML
        │                         │                         │
        └────────────── machine artifacts / contracts ─────┘
```

## 7. Candidate Interaction Models

### 7.1 方案 A：Command prompt / slash-style workspace

#### Interaction flow

启动后显示 summary 和输入框；用户键入 `inspect`、`verify mysql`、`language` 或 slash alias。历史输出形成滚动流。

#### Discoverability

可通过 completion 与 help 提升，但用户仍需知道“应该输入什么”。slash 只是语法前缀，不会自动建立检查流程的心智模型。

#### Keyboard behavior

- Up / Down：command history；
- Tab：completion；
- Enter：提交；
- Ctrl+R：历史搜索；
- Ctrl+C：取消输入或 operation。

#### 优点

- 对 shell 用户熟悉；
- expert 输入速度快；
- prompt_toolkit 对这一模型非常成熟；
- activity 与命令自然形成时间线。

#### 局限

- 重复了系统 shell 与现有 CLI；
- 仍以“记命令”为中心；
- status 容易被滚动历史冲走；
- slash command 容易给人聊天机器人错觉；
- 多语言时 command 应否翻译会产生额外困惑；
- 复杂 detail、selection 和 recovery 最终仍要加入别的 navigation model。

#### 判断

不推荐作为 RepoEvidence 主模型。可以保留 command palette 搜索动作的优点，但不引入持续可见的聊天式输入框，也不以 `/inspect`、`/verify`、`/language` 为核心。

### 7.2 方案 B：Menu / guided runbook

#### Interaction flow

用户按顺序看到：选择项目 → inspect → verify → reconcile → report。当前步骤完成后突出下一步，失败时显示 retry / configure。

#### Discoverability

最高。新手无需记忆任何命令，prerequisite 可以直接解释。

#### Keyboard behavior

- Up / Down：选择菜单项；
- Enter：执行；
- Esc：返回；
- `?`：帮助；
- 少量数字键可选。

#### 优点

- 首次使用容易；
- 可以逐步解释安全边界；
- recovery action 很直观；
- 实现复杂度低于完整多区域 workspace。

#### 局限

- RepoEvidence 的真实工作流不是永远线性；
- 高级用户需要在 source、comparison、report 间来回检查；
- MySQL verification 是可选的，runbook 容易把它表现为“必须完成”；
- 日常用户会反复穿过已经理解的步骤；
- 菜单项增长后会变成复杂导航树。

#### 判断

适合作为 fresh repository 的引导 view，不应成为整个应用的永久信息架构。

### 7.3 方案 C：Command palette + action-oriented canvas

#### Interaction flow

首页极简显示 project summary；用户打开 Actions palette，模糊搜索 Inspect、Verify MySQL、Compare、Generate Report、Change Language 等动作。

#### Discoverability

palette 打开后很高，但“如何打开 palette”本身有隐藏成本。没有稳定 status ledger 时，用户不知道为什么要选某个动作。

#### Keyboard behavior

- 一个全局快捷键打开 palette；
- 输入模糊搜索；
- Up / Down 选择；
- Enter 执行；
- Esc 关闭。

#### 优点

- expert 非常快；
- 动作数量增加时仍可搜索；
- 多语言 label 可以切换而 action ID 保持稳定；
- 不需要 command grammar。

#### 局限

- 对新手而言主要能力仍隐藏；
- palette 适合找动作，不适合解释持续状态；
- keyboard shortcut 的 discoverability 与 screen reader 兼容需要额外设计；
- 如果所有操作都依赖 palette，应用会像一个空白启动器。

#### 判断

推荐作为二级 expert accelerator，不推荐作为唯一 interaction model。

### 7.4 方案 D：Persistent workspace + contextual actions

#### Interaction flow

启动后稳定显示 project identity、Source / MySQL / Comparison / Report 四项状态和唯一主要下一步。用户在状态行间移动，Enter 查看 detail；detail 根据当前状态提供 Inspect、Retry、Compare、Refresh Report、Open Report 等上下文动作。palette 可选。

#### Discoverability

高。用户无需先打开 help 就能看到当前状态和下一步；advanced actions 通过 detail / palette 渐进披露。

#### Keyboard behavior

- Tab / Shift+Tab：在主要 focus region 间移动；
- Up / Down：在当前列表内移动；
- Enter：打开所选 detail / 执行已明确标注的动作；
- Esc：返回或关闭 modal；
- `?`：context help；
- `q`：在无 operation 时退出；
- Ctrl+C：先请求取消 operation，再次按下或无 operation 时退出；
- palette shortcut：作为可选加速，最终键位经原型测试决定。

#### 优点

- 直接匹配证据状态与 investigation loop；
- 首屏稳定，不随日志滚走；
- failure 可留在原位并给 recovery；
- novice 与 expert 可以共享同一心智模型；
- 不需要 chat、slash grammar 或大型 menu tree。

#### 局限

- 需要可靠的 workspace state projection；
- responsive layout、focus、async worker 和 testing 复杂度更高；
- 如果首页塞入过多 detail，会退化为 card wall；
- full-screen alternate buffer 对部分用户不友好，必须有 plain fallback。

#### 判断

这是最符合 RepoEvidence 产品任务的主模型。

## 8. Recommended Interaction Model

### 8.1 推荐：Hybrid envelope + contextual workspace core

最终产品由两个并列入口组成：

```text
明确 subcommand                     裸命令（TTY）
repoevidence inspect .              repoevidence
          │                              │
          ▼                              ▼
one-shot CLI                     persistent workspace
          │                              │
          └────── shared services ───────┘
```

推荐的 workspace core 是：

1. **状态先于动作**：先让用户看到 Source / MySQL / Comparison / Report 的可信状态；
2. **一个主要下一步**：根据 prerequisite、staleness 和 failure 选出推荐动作，但不自动执行；
3. **上下文动作**：用户选择状态后才显示相关操作；
4. **detail 下钻**：摘要 → status reason → finding → HTML / JSON；
5. **session 保留**：operation 完成或失败后仍停留在 workspace；
6. **palette 加速**：熟练用户可以直接搜索动作，但首页不依赖它；
7. **one-shot 旁路**：任何时候都可退出并使用稳定 CLI；TUI 不垄断功能。

### 8.2 不采用聊天式输入的原因

RepoEvidence 的 action set 是有限、可验证且有安全级别的。自由文本输入会：

- 让用户误以为存在自然语言理解或 LLM；
- 降低动作授权的明确性；
- 增加歧义与本地化负担；
- 隐藏实际可用能力；
- 使安全边界更难解释。

因此，输入应围绕 selection、action、filter 和 setting，而不是对话。

### 8.3 Action taxonomy

所有 interactive action 都应拥有稳定、未翻译的内部 ID：

| Action family | 示例 action ID | 说明 |
|---|---|---|
| Navigation | `view.source`, `view.comparison` | 只改变当前 view |
| Safe local read | `project.refresh_status` | 重新读取 filesystem / Git metadata |
| Artifact producing | `source.inspect`, `report.generate` | 写入 `.repoevidence/`，需明确动作 |
| External read | `runtime.verify_mysql` | 连接外部数据库，必须额外明确授权 |
| Derived computation | `comparison.reconcile` | 离线读取现有 artifacts |
| OS integration | `report.open` | 显式打开浏览器或展示路径 |
| Preference | `settings.language`, `settings.theme` | 只写 user-level config |

UI label 可翻译，action ID、audit log key 与 service mapping 不翻译。

### 8.4 Safety levels

| Safety level | 行为 | 交互要求 |
|---|---|---|
| `read_only_local` | 读取项目、Git metadata、artifact | 可直接执行，但不在启动时造成大量 I/O |
| `write_project_artifact` | 更新 `.repoevidence/` | 明确动作，显示目标路径与将被替换的最新 artifact |
| `external_read` | 连接 MySQL 并执行只读 metadata query | 明确确认目标来源，不显示 secret；绝不自动执行 |
| `open_external_app` | 调用 OS 打开浏览器 | 只在用户选择后执行；headless 时降级为路径 |

当前没有 destructive action。未来若出现，必须建立独立确认策略，不能沿用以上级别。

## 9. Information Architecture

### 9.1 首页必须回答的五个问题

workspace 首页按优先级只回答：

1. 我正在看哪个 repository / snapshot？
2. Source、Runtime、Comparison、Report 各是什么状态？
3. 这些状态是否仍可信、为何可信或为何不确定？
4. 当前最重要的下一步是什么？
5. 我如何查看详情、执行动作或退出？

任何不能帮助回答以上问题的元素，不应默认占据首页。

### 9.2 顶部区域

顶部建议只占 1–2 行：

- 产品名 `RepoEvidence`；
- repository identity：目录名 + 可截断路径；
- Git branch + short commit（存在 Git 时）；
- dirty marker 或“无法确认工作树状态”；
- 当前 active operation 的简短状态（仅运行时）。

为什么存在：状态必须有明确 subject 和 snapshot。为什么不放 logo：24 行终端中的每一行都应服务任务。

### 9.3 中间主要区域

默认主区域是四行 status ledger：

```text
Source
MySQL runtime
Comparison
Report
```

每行包含：ASCII state token、人类 label、时间或 freshness qualifier、最多一个简短原因。选中后 detail region 显示解释、coverage、prerequisite 和 actions。

宽终端可左右分栏；窄终端只显示 ledger，Enter 进入独立 detail screen。这样避免 card wall。

### 9.4 下一步动作

首页最多突出一个 primary next action，例如：

- Inspect source；
- Verify MySQL（明确为可选且会连接数据库）；
- Compare source and runtime；
- Refresh comparison；
- Refresh report；
- Resolve configuration / Retry。

同时允许显示一个 secondary action（例如 View existing report），其余动作进入 detail 或 palette。

“下一步”是推荐，不是 blocking wizard。用户可自由选择任何满足 prerequisite 的动作。

### 9.5 Session activity

activity 只保留本次进程中的近期事件：开始、完成、warning、failure、cancel。默认最多 3–5 行；宽屏显示，窄屏折叠为 “Activity (2)” 或独立 view。

它不应成为长期审计日志，也不应写入 target repository。持久证据仍由 machine artifacts 与 Report 承担。

### 9.6 底部区域

底部一行显示当前可用的最少键位：

```text
Tab move   Enter details/action   ? help   q quit   Actions…
```

提示应随 context 变化；不可用动作不显示。状态栏可显示 language/theme 的短标识，但不把它们设计成鼠标专属 selector。

### 9.7 Notifications

- 短暂通知只用于非关键 confirmation，例如“Report path copied”；
- failure、warning 和影响状态的结果必须同时进入 detail / activity，不能只闪现；
- notification 有纯文本前缀和 screen-reader 可理解 copy；
- 同类消息合并，避免 toast storm。

## 10. First-run Experience

### 10.1 裸 `repoevidence` 的推荐启动决策树

```text
start
  │
  ├─ explicit subcommand? ─ yes ─→ existing one-shot behavior
  │
  ├─ stdout/stdin not suitable TTY or CI/plain override? ─ yes ─→ plain welcome + exit 0
  │
  └─ suitable TTY
        │
        ├─ resolve user language/theme
        ├─ discover project context (read-only)
        ├─ discover/validate existing artifacts (read-only)
        └─ enter workspace, no operation auto-run
```

为了降低迁移风险，首次发布 interactive capability 时应先提供显式 `repoevidence workspace [PATH]`；裸命令切换到 workspace 应在后续 gate 完成并经过人工验收后启用。

### 10.2 启动时可以自动读取的内容

以下行为是本地只读、可预测且不触发 target code，允许自动执行：

- 当前 working directory 与显式 path；
- 可识别的 Git top-level、repository name、branch、HEAD、dirty state；
- 轻量 project markers，用于提示“看起来像可分析项目”，而非新增 collector；
- `.repoevidence/` 是否存在；
- 已知 artifact 路径、mtime、size；
- artifact schema、解析状态、stored metadata、exact input hash；
- Report 文件和未来 report manifest 是否存在；
- user-level language/theme/interaction preference；
- TTY、terminal size、`NO_COLOR`、`TERM` 等 presentation capability。

启动发现必须有预算：不要递归扫描整个仓库，不调用 collectors，不计算与状态判断无关的大规模 hash。若某项 freshness 只能通过昂贵扫描证明，应显示“尚未确认”，等待显式 inspect。

### 10.3 启动时绝对不能自动执行的内容

- 运行 target code、构建、测试、Maven 或任何 project command；
- 连接 MySQL 或其他外部服务；
- runtime verification；
- source scan / inspect；
- reconciliation；
- report regeneration 或自动打开浏览器；
- 修改、删除、修复或迁移 artifact；
- 写 target repository；
- destructive operation；
- 探测或输出 secret 值。

即使 inspect 当前是安全的，首次启动也不应自动执行：显式动作可以保持成本、artifact 写入和用户预期可控。

### 10.4 fresh repository：没有状态时

首屏应明确：

- 识别到的项目身份；
- “尚未检查源码”是正常初始状态，不是 error；
- RepoEvidence 不会运行项目；
- primary action：`Inspect source`；
- secondary action：`What will be inspected?`；
- MySQL verification 是后续可选动作，且只有明确选择时才连接。

不显示四个红色失败项，不用完成度 0%，不弹 mandatory onboarding carousel。

### 10.5 已有 RepoEvidence 状态时

启动后直接展示 status ledger，并区分：

- artifact 可读且与可证明输入匹配；
- artifact 可读但输入已经变化；
- artifact 可读但缺少足够 provenance，无法确认；
- artifact 记录了失败；
- artifact 缺失；
- artifact 损坏或 schema 不支持。

primary action 由最接近有效结论的缺口决定，而不是永远推荐 inspect。

### 10.6 当前目录不是有效项目时

RepoEvidence scanner 并不要求 Git 仓库，因此“不是 Git repo”不能直接等同 invalid。应区分：

- path 不存在或不可读：真正的 invalid path；
- 可读目录但没有常见项目 marker：unsupported / low-confidence candidate；
- Git repo 但当前在子目录；
- 已显式指定任意目录。

workspace 应保留并提供：选择/输入其他 path、使用当前目录继续、查看支持范围、退出。不能 crash，也不能未经用户同意自动跳到某个父目录。

### 10.7 repository root 的建议与待决点

建议：当用户未给 path 且当前目录位于唯一、可识别的 Git repo 内时，以 Git top-level 作为推荐 project root，同时明显展示“opened from”与实际 root，并允许切回精确 cwd。

原因：多数 repository evidence 与 `.repoevidence/` 应绑定 repo root。但这会改变当前 `.` 的直觉，尤其对 monorepo / nested project。因此这是实现前必须由产品负责人批准的行为，不能由框架默认决定。

## 11. Persistent Workspace Design

### 11.1 核心心智模型：Evidence ledger，不是 dashboard

推荐把 workspace 理解为一张“当前证据账本”：四个对象各自有来源、时间、可信度和可执行动作。它不是把大量指标铺成卡片，也不是实时监控仪表盘。

```text
Project snapshot
  ├─ Source evidence
  ├─ MySQL runtime evidence
  ├─ Comparison derived from exact source + runtime inputs
  └─ Report derived from selected artifacts and language
```

这个层级让用户知道：Comparison 和 Report 是派生结果；上游变化会使下游 stale，但不会删除旧结果。

### 11.2 稳定区域与临时区域

| 区域 | 生命周期 | 内容 |
|---|---|---|
| Project header | 整个 session | repository、path、branch、commit、dirty / unknown |
| Status ledger | 整个 session | Source、MySQL、Comparison、Report |
| Context detail | 随 selection 变化 | 状态原因、coverage、findings 摘要、actions |
| Operation view | operation 期间暂时替换 detail | 当前真实阶段、elapsed、warning、cancel 能力 |
| Activity | 本 session | 最近完成、失败与 warning |
| Footer help | 随 context 变化 | 当前有效键位与安全提示 |

status ledger 不能在 operation 期间消失；用户始终知道操作影响哪个对象。operation 完成后，projection 重新读取 artifacts，不能只凭“worker 返回成功”手工把 UI row 改绿。

### 11.3 导航层级

MVP 最多三层：

1. Workspace overview；
2. Status detail / findings list；
3. Single finding / technical detail 或 modal。

HTML Report 属于外部深读界面，不在 TUI 内重建第四、第五层复杂 table navigation。`Esc` 总是向上返回一层；`q` 只从 overview 退出，或先关闭 modal/detail，具体行为必须一致并在 footer 可见。

### 11.4 默认 focus

- fresh repository：focus 在 primary `Inspect source`；
- 已有 actionable failure：focus 在失败状态行，但不自动触发 Retry；
- proven stale：focus 在最上游 stale item；
- drift detected 且 artifacts 当前：focus 在 Comparison；
- 全部可用：focus 在最相关 conclusion / Report，而不是任意第一行；
- operation 完成：focus 返回被操作对象，screen reader announcement 描述结果。

默认 focus 的规则应纯函数化并可测试，不能由 rendering 顺序偶然决定。

### 11.5 Action availability

动作分为：

- **available**：可直接选择；
- **available with confirmation**：例如 MySQL verification；
- **blocked by prerequisite**：显示缺少什么和可跳转动作；
- **unavailable in environment**：例如无 browser opener；
- **running / temporarily disabled**：另一个 artifact-producing operation 正在运行。

disabled action 不能只有灰色；必须有可读取原因。首页不展示大量 disabled button，只有在 detail / palette 中查询时才呈现原因。

### 11.6 Activity 不是 command transcript

activity event 使用结构化 key：

```text
operation.started
operation.completed
operation.failed
artifact.became_stale
report.open_unavailable
```

presentation 根据语言渲染。不要把 Rich markup、完整 traceback 或 command string 作为持久 state；technical detail 可按需查看和复制。session 结束后默认不保存 activity，以避免把 UI preference、项目事件和审计 artifact 混在一起。

## 12. Status Model

### 12.1 必须分离的四个维度

当前五态可以继续作为 application assessment 的 lifecycle vocabulary，但 interactive projection 不能只保留一个 enum。

| 维度 | 回答的问题 | 示例 |
|---|---|---|
| Artifact lifecycle | 结果是否存在、可读、成功生成 | missing、valid、failed、corrupt、unsupported |
| Freshness / provenance | 它是否可证明对应当前输入 | fresh、stale、uncertain、not_applicable |
| Operation state | 当前是否正在做什么 | idle、running、cancel_requested、succeeded、partial、failed |
| Domain outcome | 结果本身说明了什么 | source_only、matched、drift_detected、runtime_failed |

“运行失败”和“发现 drift”绝不是同一件事。前者是 operation failure；后者可能是一项完全成功、且最有价值的 domain result。

### 12.2 建议的 presentation-neutral projection

概念上，每个 workspace item 至少需要：

```text
WorkspaceCheck
  id
  lifecycle
  freshness
  observed_at
  provenance_summary
  reason_codes[]
  artifact_path
  available_actions[]
  safety_level
```

这里存储 reason code，不存最终中英文句子。TUI、CLI summary 和未来其他 presenter 可以共享 projection，但 machine JSON 不应因此增加 human UI 字段。

### 12.3 Freshness 规则

#### Source

- 同一 session 中 inspect 成功，且 project fingerprint 未观察到变化：可显示“本次会话刚检查”；
- artifact stored HEAD 与当前 clean HEAD 不同：proven stale；
- artifact stored HEAD 与当前 HEAD 相同且 working tree clean：可显示“匹配当前提交”；
- working tree dirty，但 artifact 没有足够的 file-level provenance：uncertain，不能显示 fresh；
- legacy artifact 缺少 HEAD / fingerprint：uncertain；
- artifact 无法解析：lifecycle corrupt / freshness not applicable。

仅检查 `mtime` 不足以证明 source freshness；完整重新 hash 全仓库又可能等同一次 scan。MVP 宁可诚实显示 uncertain，也不要隐式做昂贵工作或误报 current。

#### MySQL runtime

MySQL artifact 是某个时间点的快照，不是持续在线状态。成功 verification 后应显示：

```text
Verified 14:32 · snapshot
```

不应仅显示“当前”。除非未来有产品批准的环境标识与 freshness policy，否则不设置任意 5 分钟、1 小时之类的伪科学 TTL。用户可看到时间并主动刷新。

#### Comparison

只有当 `reconciliation.json` 记录的 source input hash 与当前选定 `evidence.json` 精确一致，且 runtime input hash 与当前选定 MySQL artifact 精确一致时，comparison 才可显示“对应现有输入”。任何一个输入变化都使它 proven stale。

如果 runtime verification 记录的是 failure，comparison 可以有 `runtime_failed` domain outcome；它不是“matched”，也不应被首页绿色掩盖。

#### Report

当前仅凭 `index.html` 存在无法可靠判断 Report 是否与最新 inputs 一致。推荐在不改变现有 machine JSON 的前提下，单独设计一个最小、versioned report manifest，记录：

- generator version；
- generated_at；
- language；
- consumed artifact paths 与 content hashes；
- output path；
- renderer format version。

manifest 可位于 `.repoevidence/report/manifest.json`，但这个路径和 schema 必须单独设计、评审和测试，不能由 TUI 临时发明。旧 report 没有 manifest 时显示“存在；新鲜度无法确认”，而不是 stale 或 current。

### 12.4 从 internal state 到人类状态

普通用户不应看到 `not_run`、`unknown` 等 enum。建议的英文 / 中文概念如下：

| Internal meaning | English human label | 中文人类标签 | Symbol | Color role | Enter behavior |
|---|---|---|---|---|---|
| Missing / never run | Not inspected / Not verified / Not compared / No report | 尚未检查 / 尚未验证 / 尚未比较 / 尚无报告 | `[--]` | muted | 解释作用与启动动作 |
| Valid and proven fresh | Inspected for this snapshot / Inputs match | 已对应此项目快照 / 输入一致 | `[OK]` | success | 展示 coverage、time、provenance |
| Valid but stale | Source changed / Inputs changed / Report needs refresh | 源码已变化 / 输入已变化 / 报告需要刷新 | `[~~]` | attention | 展示变化原因与 Refresh |
| Failed operation artifact | Verification failed / Report generation failed | 验证失败 / 报告生成失败 | `[!!]` | failure | 展示 what/why/retry/detail |
| Cannot prove / corrupt / unsupported | Freshness not confirmed / Cannot read result | 无法确认新鲜度 / 无法读取结果 | `[??]` | informational-attention | 展示原因、preserve、regenerate |

不同对象使用不同动词，避免把四行都翻译成抽象“当前”。ASCII token 不依赖 Nerd Font、emoji 或颜色。

### 12.5 Status precedence

当多个条件同时存在时，presentation precedence 建议为：

1. active operation；
2. corrupt / unsupported；
3. recorded operation failure；
4. missing / never run；
5. proven stale；
6. uncertain provenance；
7. proven fresh；

domain conclusion 作为独立摘要出现。例如：

```text
[OK] Comparison   Inputs match · completed 14:35
     Result       Drift detected · 2 runtime-only migrations
```

这里第一行表示比较本身可信完成，第二行用 attention 表示发现，不应把整个 operation 染成 failure。

### 12.6 Dependency invalidation

```text
Source changed ──────────────┐
                             ├─→ Comparison stale ─→ Report stale
MySQL snapshot replaced ─────┘

Source-only Report input changed ──────────────────→ Report stale
Report language preference changed ────────────────→ existing Report remains valid,
                                                      but language differs; refresh is explicit
```

上游更新不会删除下游 artifact。UI 保留旧结果并明确标记 staleness，让用户仍可查看“上次比较”，同时不会混淆为当前结论。

## 13. Operation UX

### 13.1 总体原则

- 用户动作后立即给出 acknowledgment，但不伪造进度；
- operation status 基于真实事件或通用 busy 状态；
- 不人为 `sleep`，不为了展示动画延迟完成；
- 不显示 fake percentage；
- 不把 spinner 当作成熟感装饰；
- 失败后留在 workspace，保留上下文和 recovery；
- operation 完成后重新 assessment artifacts；
- elapsed time 只显示真实 wall-clock time。

### 13.2 按耗时选择反馈

| 实际耗时 | 推荐反馈 | 原因 |
|---|---|---|
| `< 300–400ms` | 不显示 animation；直接从 running acknowledgment 过渡到结果 | 避免 spinner 闪烁 |
| `约 0.4–2s` | 延迟出现 spinner + 单一真实动词；约 1s 后显示 elapsed | 用户知道应用未卡住 |
| `> 2s` | live status + 当前真实阶段 + elapsed | 提供可恢复的等待感 |
| 阶段数未知 | 通用 “Inspecting source…” | 不编造 collector 数或百分比 |
| operation 可提供事件 | 显示已发生的 step transition | 只呈现真实进展 |

阈值是初始 UX 假设，需通过真实仓库与低性能环境测试调整，不应散落为多个 widget magic number。

### 13.3 `inspect`

`inspect` 当前语义是 scan 后生成 report。interactive 中应保持这个 contract，不把它悄悄变成只 scan。

可展示的真实阶段：

1. Validating project path；
2. Inspecting source；
3. Writing evidence artifact；
4. Building report；
5. Writing report。

只有 application service 实际发出阶段事件时才逐项展示。collector 名称可以出现在展开的 detail/activity 中，但首页不持续滚动大量文件名。

完成后：

- 重新评估 Source 与 Report；
- 若旧 Comparison 因 source hash 改变而 stale，明确提示；
- 显示 coverage / conflicts / errors 摘要；
- primary next action 根据结果决定，而不是固定 verify。

### 13.4 `verify mysql`

这是唯一涉及外部连接的现有动作，必须拥有更强的前置说明：

- “Connects to MySQL using environment configuration”；
- 列出需要的 variable 名称与是否存在，绝不显示 value；
- 明确“reads metadata and migration history; does not read business rows”；
- 让用户确认 Verify，而不是把 focus 默认放在确认按钮并允许误触 Enter。

可展示的阶段必须来自真实实现，例如 connecting、reading metadata、reading Flyway history、writing artifact。不要展示 server hostname、username 或 DSN，除非未来经过 redaction 设计批准。

当前 connection timeout 为 5 秒，但 query-level timeout 与 cooperative cancellation 仍需专项验证。UI 不能在 worker 尚未停止时宣布“已取消”。

完成后：

- verification success 与 runtime findings 分开；
- 显示 snapshot timestamp；
- 如果 comparison 输入变化，标记 comparison stale；
- 建议 Compare，但保持其为显式动作。

### 13.5 `reconcile`

通常是快速的离线 computation：

- prerequisite 缺失时不启动 worker，直接解释需要 Source / MySQL artifacts；
- 很快完成时不闪 spinner；
- 读取 exact inputs、计算、写 artifact；
- domain outcome 明确区分 matched、drift、ambiguous、runtime failed；
- drift 不是 application failure，exit / operation 状态仍可成功。

完成后的第一摘要应是结论与 finding 数量；完整 mapping、hash 和 references 留给 detail / HTML / JSON。

### 13.6 `report`

Report 操作分成三个不同 action：

- `Generate report`：不存在时生成；
- `Refresh report`：已有但 stale / language differs 时重新生成；
- `Open report`：只打开现有输出，不自动重建。

操作阶段可以是 loading artifacts、building view、rendering、writing。成功后显示路径、语言、生成时间和是否与当前 artifacts 匹配。

打开浏览器必须显式；SSH、容器、WSL 或无 opener 环境降级为显示可复制绝对路径，不把无法打开当作 report generation failure。

### 13.7 Failure、partial result 与 warning

| 类型 | operation state | artifact 行为 | UI 行为 |
|---|---|---|---|
| Failure before useful result | failed | 不用不完整文件覆盖上次有效 artifact | 保留 app，显示 Retry / Configure / Detail |
| Machine contract 表达的 verification failure | operation 可成功写 artifact，domain 为 runtime_failed | 保留可审计 failure artifact | Runtime 行显示验证失败与时间 |
| Partial collector result | partial / succeeded-with-warning，取决于 application contract | 写入合法 machine result | 摘要 coverage + warning，不能伪装全覆盖 |
| Non-blocking warning | succeeded | 正常写 artifact | attention 文本，不把整个 row 标红 |
| UI-only failure（如 browser open） | report 本身不变 | 不改 artifact | 只影响 action notification，提供路径 |

必须在架构评审中统一“process execution failure”和“machine artifact records failure”的语义，避免 TUI、CLI exit code 和 Report 互相矛盾。

### 13.8 Concurrency 与 cancellation

MVP 建议：同一 workspace 同时只允许运行一个 artifact-producing operation。

原因：Source、Comparison、Report 有明确依赖；并发写最新 artifact 会造成竞态、stale projection 和难以解释的取消语义。read-only navigation、help 和查看旧结果仍保持响应。

取消规则：

- 只有 service 明确支持 cooperative cancellation 时显示 Cancel；
- `cancel_requested` 与 `cancelled` 分开；
- 不强杀线程并假装安全；
- Ctrl+C 第一次请求取消，第二次是否强退必须经过技术验证并给出 artifact safety 保证；
- 退出时若 operation 仍在写文件，必须阻止无提示退出或保证原子写入。

### 13.9 Operation event contract

建议在 application layer 增加可选、presentation-neutral observer/event seam：

```text
OperationEvent
  operation_id
  operation_kind
  phase_id
  event_kind
  monotonic_timestamp
  safe_metadata
```

它不是新 machine truth，也不写入现有 JSON。CLI 可以忽略；TUI 用于 live status；测试可以验证真实 phase 顺序。`safe_metadata` 必须是白名单，禁止携带 env values、password、完整 DSN 或未 redacted exception。

### 13.10 Artifact 写入完整性

persistent app 增加了取消、终端关闭和并发风险。建议在 application layer 统一采用：同目录临时文件 → flush/close → atomic replace 的写入策略，并保持最终 JSON bytes（包括排序、indent、尾换行）与现有 contract 一致。

这是架构准备项，不是 TUI 自己的职责；是否在 Phase 1 实施需单独测试 Windows replace semantics。旧有效 artifact 在失败时应尽可能保留。

## 14. Language UX

### 14.1 解析优先级

推荐明确并文档化：

```text
CLI explicit --lang
  > REPOEVIDENCE_LANG
  > user-level RepoEvidence config
  > system locale
  > English fallback
```

`--lang auto` 表示跳过 explicit language，继续按 env → config → system locale → English 解析；如果现有语义不同，需要在迁移前验证兼容性。

### 14.2 首次启动语言

- system locale 明确为 `zh-CN` / compatible Chinese 时，首屏直接中文；
- English locale 直接英文；
- 无法识别时回退 English；
- 不弹 mandatory language selector，因为它会阻碍熟悉用户并增加首次启动步骤；
- 首屏 footer/help 中应让语言设置可发现，例如 `Settings · 中文` 或 `Language: English`。

只有当 locale 解析失败且产品研究证明确有必要时，才考虑一次性 non-blocking language choice；当前不推荐。

### 14.3 session 内切换

语言设置应存在于可见 Settings view，并可从 optional command palette 搜索。选择后：

- workspace 所有静态 label 立即刷新；
- status reason、action label、help、modal、activity 使用 event key 重新渲染；
- running operation 的 phase label 立即刷新，但 operation 本身不重启；
- machine ID、命令名、path、Evidence ID、schema enum 不翻译；
- 对当前 session 生效后，按用户选择写入 user config。

不需要 `/language` 命令，也不要求记忆专用快捷键。若未来提供 shortcut，它只能是 accelerator，并在 help 中可发现。

### 14.4 Report 语言

切换 workspace 语言不能静默重写 HTML Report。Report 行应显示：

```text
Report exists · English · generated 14:35
Workspace language: 中文
```

用户可以选择“Refresh report in 中文”。已有英文 Report 在 artifacts 未变时仍是有效报告，只是语言与当前 preference 不同；这与 stale 分开表达。

### 14.5 Copy 原则

- 状态 label 使用自然动词：“尚未检查”，而不是直译 `not_run`；
- 中文避免生硬名词堆叠，明确主体：“源码已变化，需要重新比较”；
- 英文避免抽象 system copy：“Source changed” 优于 “State is stale”；
- 安全提示明确行为：“Connects to MySQL” 而不是 “Continue?”；
- action 使用动词开头；
- 一行无法容纳时优先保留结论与动作，technical qualifier 进入 detail。

## 15. Terminal Framework Comparison

### 15.1 调研方法与判断前提

框架不是从功能清单抽象比较，而是围绕 RepoEvidence 的实际需求：四项稳定状态、keyboard focus、detail / modal、后台同步 operation、responsive terminal、headless tests、跨平台、plain fallback 和可发布 wheel。

调研以 2026-08-09 的官方文档和项目页面为依据。版本更新很快，进入实施前必须重新核对兼容范围；本文不把当日最新版本直接写成 dependency pin。

### 15.2 对比矩阵

| 维度 | Textual | prompt_toolkit | Rich Live / Layout | curses / stdlib | Urwid |
|---|---|---|---|---|---|
| Persistent layout | 强：reactive widget、layout、screen | 强，但需自行组合控件与状态 | 渲染强，应用结构需自建 | 基础 window，全部自建 | 强：widget/layout/main loop |
| Keyboard / focus | 内建 binding、focus、widget semantics | 极强，尤其 prompt/completion/history | 无完整 focus/input model | 原始 key handling | 成熟 widget navigation |
| Async / background work | Worker API，async/thread 两类 | 原生 asyncio，适合 prompt app | Live refresh；任务管理自建 | 自建 loop/thread | 多 event loop adapter |
| Selector / palette | 内建 command palette，也可自定义 | completion/dialog 可搭建 | 需自建 | 需自建 | 可用 widget 搭建 |
| Modal / screen | 内建 Screen / ModalScreen | Float/dialog 可实现 | 需自建 | 需自建 | Overlay 可实现 |
| Command history | 非核心；需另做 | 最强，内建 history/search | 无 | 自建 | 非核心 |
| Responsive terminal | CSS-like layout、size event | layout/dimensions 可做 | Layout ratio/size 可做，交互自建 | 完全手工 | 成熟 flow/box/fixed sizing |
| Automated UI test | `run_test()` + Pilot + size；snapshot plugin | pipe input / dummy I/O，需更多 harness | 输出 capture 容易，交互无框架 | PTY 为主，脆弱 | 可测但生态与工具较少 |
| Windows | 官方支持，建议 Windows Terminal | Windows/Unix 支持良好 | Rich 支持良好 | stdlib Python Windows 无 curses；需 `windows-curses` | 官方描述为部分支持/有限制 |
| WSL/Linux/macOS | 官方支持 | 支持 | 支持 | Unix 系较好 | Unix 系成熟 |
| `NO_COLOR` | 有 NoColor filter；仍需产品测试 | style 可禁用，需 adapter policy | 原生识别 `NO_COLOR` | 全部自管 | monochrome palette 可做 |
| Non-TTY fallback | 需要在启动前路由，不应启动 app | 可使用 dumb I/O，但仍建议旁路 | Console 对 non-TTY 最成熟 | 不适合 | 不适合 |
| Packaged wheel | 纯 Python、PyPI 活跃 | 纯 Python universal wheel | 已是现有依赖 | stdlib，但 Windows 加包 | PyPI wheel；许可证需复核 |
| Dependency footprint | 最大，建立在 Rich 等能力上 | 中等 | 最小增量（项目已有） | Unix 最小，跨平台成本最大 | 中等 |
| Learning curve | 中高：reactivity、CSS、worker、message | 中高：buffer/layout/event loop | 低渲染、高应用架构 | 最高 | 中高 |
| Long-term extensibility | 最高，适合 workspace/selector/modal | 高，适合 REPL/editor/prompt | 低中，越做越像自研框架 | 低，维护成本高 | 高，但 Windows和生态风险更大 |

### 15.3 Textual

适配优势：

- 官方提供 persistent widgets、responsive layout、screen / modal 和 command palette；palette 可以禁用或降级，不必成为产品模型；
- Worker API 能把现有同步 application service 放在线程 worker 中，并保持 UI loop 响应；线程回调 UI 有明确边界；
- 官方 headless `run_test()` 与 Pilot 支持按键、点击和 terminal size 测试，适合状态 workspace；
- 官方声明支持 Linux、macOS、Windows；
- 与项目已经使用的 Rich 视觉能力一致，plain presenter 仍可独立保留。

相关官方资料：[Getting Started / platform support](https://textual.textualize.io/getting_started/)、[Workers](https://textual.textualize.io/guide/workers/)、[Testing](https://textual.textualize.io/guide/testing/)、[Screens](https://textual.textualize.io/guide/screens/)、[Command Palette](https://textual.textualize.io/guide/command_palette/)、[`NO_COLOR` filter](https://textual.textualize.io/api/filter/)。

主要风险：

- dependency 和框架概念显著增加；
- async UI 与同步 scanner/verifier 的 thread boundary 需要严格设计；
- release velocity 高，必须 pin 经测试的兼容范围并设升级策略；
- CSS-like styling 容易诱导团队做过度 panel 化界面；
- Windows、SSH、tmux、窄屏和 CJK 实际表现仍需人工 prototype，官方支持不能替代验收。

### 15.4 prompt_toolkit

prompt_toolkit 对 command line editing、completion、history、自定义 key binding 和 fullscreen application 很强，且原生支持 asyncio。官方资料包括：[full-screen applications](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/full_screen_apps.html)、[asyncio](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/advanced_topics/asyncio.html)、[history and key bindings](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/asking_for_input.html) 与 [I/O abstractions](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/reference.html)。

如果最终产品被决定为 REPL / command prompt，它会是首选。但推荐模型不是以文本输入、history 和 completion 为中心；使用 prompt_toolkit 将要求团队自行建立 status widget system、screen/modal conventions、test harness 和 responsive composition。它能做，但框架优势与本产品主任务不完全重合。

### 15.5 Rich Live / Layout

Rich 已经是当前 presentation dependency，在 Console 的 TTY detection、`NO_COLOR`、`TERM=dumb`、Windows 和 plain rendering 上表现成熟；`Live` 与 `Layout` 能做持续刷新和区域布局。参考：[Console](https://rich.readthedocs.io/en/latest/console.html)、[Live Display](https://rich.readthedocs.io/en/latest/reference/live.html)、[Layout](https://rich.readthedocs.io/en/latest/layout.html)。

但 Rich 是 renderer，不是完整 application framework。若直接用 Live / Layout 构建 workspace，团队还需自行实现：input event loop、focus、modal、palette、screen stack、resize policy、worker lifecycle、accessibility conventions 和 interactive testing。这会让“减少 dependency”换成长期维护一个内部 TUI framework，不推荐。

Rich 应继续承担：

- one-shot TTY presenter；
- plain / non-TTY rendering；
- 必要时的 shared text style vocabulary；
- Textual 不启动时的 fallback。

### 15.6 curses / stdlib

Python curses 能提供 window、keyboard 与 terminal control，但官方 HOWTO 明确指出它只提供基础能力，button、dialog 等都需应用自己构建；标准 Python Windows 不包含 curses，需要第三方 `windows-curses`。参考：[Python curses HOWTO](https://docs.python.org/3/howto/curses.html)、[curses library](https://docs.python.org/3/library/curses.html)、[windows-curses](https://pypi.org/project/windows-curses/)。

RepoEvidence 的价值不在发明 widget toolkit。直接 curses 会把大量时间投入 Unicode width、focus、resize、Windows、testing 和 event loop，长期维护成本与当前团队/产品规模不匹配，不推荐。

### 15.7 Urwid

Urwid 是值得考虑的成熟替代：有 widget、responsive sizing、overlay 和可选 asyncio main loop，也支持 monochrome palette。参考：[overview](https://urwid.org/manual/overview.html)、[main loop](https://urwid.org/manual/mainloop.html)、[display modules](https://urwid.org/manual/displaymodules.html)、[widgets](https://urwid.org/manual/widgets.html)。

但官方项目资料对 Windows 的支持仍有局限，生态、测试 ergonomics 与当前 Textual 相比不占优势；许可证和 downstream packaging 也需要额外审查。除非 Phase 0 证明 Textual 在目标终端有不可接受的问题，否则 Urwid 不作为首选。

### 15.8 推荐结论与门禁

**技术首选：Textual；保留 Rich 作为 one-shot / plain adapter。**

推荐成立的原因不是“Textual 最流行”，而是 RepoEvidence 确实需要它最强的部分：稳定 layout、focus、screen/modal、background worker、responsive behavior 和 headless keyboard testing；同时不需要自行发明这些基础设施。

但这是一项有条件建议。只有 Phase 0 原型同时通过以下条件，才允许加入正式 dependency：

- 40、60、80、100、120 列布局可用；
- English / zh-CN CJK width 正确；
- Linux、macOS、Windows Terminal、WSL 的核心键盘流通过人工验收；
- tmux / SSH 的可接受行为有记录；
- `NO_COLOR`、light/dark、256-color、`TERM=dumb` 和 non-TTY 路由明确；
- synchronous inspect / verify worker 不冻结 UI；
- wheel 安装、cold start 和 import cost 可接受；
-测试可以稳定模拟 keyboard、resize、failure 和 cancellation；
- 团队接受 pinned major range、升级 cadence 和学习成本。

若原型失败，第二选择不是立即用 Rich 自研，而是重新评估产品模型：如果缩减为 prompt / activity stream，选 prompt_toolkit；如果仍需 widget workspace，再比较 Urwid。

## 16. Recommended Technical Architecture

### 16.1 目标分层

```text
┌──────────────────────────────────────────────────────────────┐
│ Entry adapters                                               │
│ Typer one-shot CLI        TTY router        Textual app       │
└──────────────┬──────────────────┬──────────────────┬──────────┘
               │                  │                  │
┌──────────────▼──────────────────▼──────────────────▼──────────┐
│ Presentation-neutral application layer                       │
│ services · project assessment · workspace projection         │
│ operation events · user-safe error mapping                    │
└──────────────┬──────────────────────────────────────┬─────────┘
               │                                      │
┌──────────────▼────────────────────┐  ┌──────────────▼─────────┐
│ Machine capabilities             │  │ Presenters              │
│ scanner · verifier · reconciler  │  │ terminal · HTML         │
└──────────────┬────────────────────┘  └──────────────┬─────────┘
               │                                      │
┌──────────────▼──────────────────────────────────────▼─────────┐
│ Stable machine artifacts and schemas                         │
└──────────────────────────────────────────────────────────────┘
```

### 16.2 建议组件

文件名只表示规划边界，不是最终批准的 module layout：

| Component | 可能位置 | 职责 |
|---|---|---|
| Project context discovery | `project_context.py` | path、Git metadata、lightweight capability、无副作用发现 |
| Artifact assessment | `assessment.py` / `project_status.py` | lifecycle、freshness、dependency invalidation |
| Workspace projection | `workspace.py` | status row、reason codes、next action、action availability |
| Operation runner | `operations.py` | service 调用、event、single-flight、cancel policy |
| User config | `user_config.py` | platform path、schema、atomic load/save、precedence |
| CLI TTY router | `cli.py` 附近 | no-arg TTY / non-TTY / override 路由，lazy import interactive |
| Interactive app | `interactive/app.py` | Textual lifecycle 与 dependency injection |
| Interactive screens/widgets | `interactive/views/*` | layout、focus、render、modal；不读 machine files |
| Terminal styles | `interactive/theme.*` | semantic roles，不保存 domain logic |
| Existing presenters | `presentation/terminal.py`, `report_html.py` | one-shot/plain 与 HTML，保持独立 |

### 16.3 Data flow

正确的数据流：

```text
user action
  → interactive controller validates availability/safety
  → operation runner invokes application service
  → application service invokes machine capability and writes artifact
  → assessment re-reads artifacts/project context
  → workspace projection derives human-independent status/reason/action IDs
  → selected presenter localizes and renders
```

禁止的数据流：

```text
Textual widget → Scanner.default() → write its own JSON
CLI command    → custom MySQL query → bespoke output
HTML renderer  → infer a different reconciliation conclusion
```

### 16.4 Synchronous service 与 UI event loop

当前 scanner、verifier、reconciler 和 report service 以同步 API 为主。MVP 不应为了 Textual 盲目把 machine layer 全部 async 化。

建议：

- Textual UI loop 保持 async/reactive；
- service 在框架提供的 thread worker 中运行；
- event observer 必须 thread-safe；
- UI 更新回到主 event loop；
- service result 和 exception 经过 application-safe mapping；
- tests 使用 fake service / deterministic event source，不依赖真实 sleep。

只有当 MySQL connector 或 collector 需要真正 cooperative cancellation 时，再在 application boundary 引入可选 cancellation token；不要把 Textual-specific Worker 类型穿透到 service。

### 16.5 Error mapping

需要 presentation-neutral `UserFacingProblem` 概念：

- stable problem code；
- operation / artifact subject；
- human summary message key；
- reason message key；
- recovery action IDs；
- sanitized technical detail；
- optional underlying exception type for logs/tests。

它不替换 machine `VerificationError` 等 schema，只负责把 application exception、filesystem error 与 machine result 投射到用户界面。

### 16.6 Dependency 与 import 边界

- Textual 只由 interactive package import；
- one-shot subcommand 与 non-TTY no-arg path 不应为了输出一行帮助就初始化 Textual app；
- CLI router lazy import workspace；
- Rich 继续用于 existing terminal presenter；
- 如果 Textual 成为裸命令的正式默认体验，推荐作为正常 runtime dependency，而不是让默认安装缺失功能的 optional extra；
- dependency version 使用经过 Phase 0 / CI 验证的 compatible range，并有定期升级任务，不追逐每次 release。

是否提供 `repoevidence[minimal]` 不在本阶段范围；过早提供双 distribution profile 会扩大 support matrix。

### 16.7 Machine truth ownership

interactive UI 可以保存：selection、focus、expanded item、active modal、ephemeral operation event。它不能成为以下信息的唯一来源：

- scan facts；
- verification result；
- reconciliation finding；
- artifact freshness proof；
- report provenance。

如果关闭 TUI 后某个结论消失且 machine artifact 无法复现，它就不应被称为 RepoEvidence evidence。

## 17. CLI / TUI / HTML / JSON Boundaries

### 17.1 共享 application service

以下能力由 CLI 与 TUI 共享：

- path validation；
- scan / inspect orchestration；
- MySQL verification；
- reconciliation；
- report generation；
- artifact serialization / atomic write；
- artifact assessment；
- project status / freshness projection；
- application-safe problem mapping。

共享不意味着把 terminal copy 放进 service。service 返回 structured result、problem code 与 event。

### 17.2 CLI adapter 职责

- command / option parsing；
- `--lang` 与 environment precedence；
- one-shot invocation；
- stdout / stderr separation；
- exit code；
- TTY/plain presenter 选择；
- no-arg interactive routing；
- CI / non-TTY bypass。

CLI adapter 不重新 scan、verify 或 reconcile，也不保存 session-only workspace state。

### 17.3 Interactive presenter 职责

- persistent screen lifecycle；
- focus、keyboard、modal、responsive layout；
- operation worker / cancellation UI；
- status projection render；
- next action 与 context action；
- session activity；
- live language/theme refresh；
- explicit report open integration。

Interactive presenter 不解析 Evidence 来发明新的业务结论；需要新 projection 时应在 application / view-model layer实现并由其他 presenter 可复用。

### 17.4 Report presenter 职责

- 完整、可打印的叙事；
- coverage 和 limitations；
- 全部 Evidence / Fact / Verification / Reconciliation traceability；
- source locations、IDs、hash、provenance、technical tables；
- offline self-contained HTML；
- stable anchors 供 terminal deep link（如未来批准）。

### 17.5 JSON 职责

- machine schema truth；
- Agent / script integration；
- deterministic serialization；
- audit input / output；
- UI 与 Report 的可复现来源。

Human label、ANSI、Textual widget state、localized sentence 均不得进入 machine JSON，除非经过独立 schema 版本决策。

### 17.6 Interactive Terminal 与 HTML Report 的明确分工

| 信息 / 行为 | Terminal workspace | HTML Report |
|---|---|---|
| 当前 project / branch / operation | 主要呈现 | 只记录生成时 provenance |
| 四项 artifact 状态与 freshness | 主要呈现 | 在报告元信息中记录所用输入 |
| 推荐下一步与 recovery action | 主要呈现 | 不提供运行控制 |
| operation spinner / elapsed / cancel | 仅 Terminal | 不出现 |
| top findings 摘要 | 3–5 条或计数，可下钻 | 完整 findings 与解释 |
| 全部 Evidence / Fact | 只显示选中项摘要或 ID | 主要呈现 |
| source locations、references、hash | detail 中按需显示 | 完整呈现、可打印 |
| 大型技术表格 | 不塞入首页，必要时跳转 | 主要呈现 |
| generate / refresh / open | 显式操作入口 | 自身不执行操作 |
| 分享、离线阅读、审计留存 | 提供 path | 主要职责 |

Report 行需要表达：是否存在、生成时间、语言、path、freshness 和可用动作。Terminal 可以提供 `Open report` 或未来经批准的 anchor deep link，但不实现一个内嵌 browser，也不复制 Report 的完整 filtering / table layout。

以下信息原则上只放 HTML / JSON，不占据 workspace 首页：全部 collector records、每个 Evidence 的完整原文、所有 Fact references、完整 reconciliation mapping、长 error stack、完整 input hash、schema dump、打印样式和审计附录。

### 17.7 边界验收问题

每次 interactive feature review 都应问：

1. 同一能力是否仍可从 one-shot CLI 使用？
2. TUI 是否调用现有 application service？
3. 关闭 TUI 后 machine artifact 是否完整？
4. Report 是否从同一 result/view model 得到相同结论？
5. 非 TTY 是否完全绕过 interactive import / event loop？
6. UI failure 是否误改 machine artifact 或 CLI exit semantics？

## 18. Terminal Visual Language

### 18.1 设计签名

RepoEvidence 的终端视觉签名应是 **stable evidence ledger**：克制、精确、可追踪；视觉重点来自稳定对齐、状态 token、少量 accent 和清楚的上下级关系，而不是 logo、卡片墙、渐变、巨型标题或不断滚动的动画。

### 18.2 Semantic color roles

以下只定义角色，不在本规划中确定最终 ANSI / CSS 值：

| Role | 用途 | 禁止用途 |
|---|---|---|
| `accent` | 产品名、主要 next action、链接式可交互文本 | 大面积背景填充 |
| `success` | operation 成功、proven fresh、matched | 未验证、仅“无 error” |
| `attention` | stale、drift、warning、需要用户判断 | 所有普通标题 |
| `failure` | operation failure、corrupt、unreachable | drift finding 本身 |
| `muted` | 辅助时间、未运行、不可用但非错误 | 唯一状态编码 |
| `active` | 当前 operation / current detail | 永久装饰 |
| `selected` | keyboard focus / selected row | 与 active 混为一色且无形状差异 |
| `command` | 可复制的 CLI command、key hint | 普通 paragraph |
| `path` | repository / artifact / report path | secret / DSN |
| `inactive` | 非当前 region、secondary metadata | 低到不可读的对比度 |

### 18.3 Light、dark 与 terminal palette

不要假设 terminal background。默认主题应优先使用 terminal 的基础前景/背景与有限 ANSI semantic color，避免硬编码“深蓝背景 + 白字”。

- `theme=auto` 使用能力检测与保守 palette；
- dark/light preference 只选择语义 palette，不重绘整个 terminal；
- 256-color 环境应完整可用；truecolor 只是增强；
- 颜色对比度需在常见 light/dark terminal 人工检查；
- selection 同时使用 focus marker / reverse / underline 中至少一种，不只换颜色。

### 18.4 `NO_COLOR` 与 monochrome

设置 `NO_COLOR` 时：

- 禁止 semantic color，但保留 bold/underline 时也要谨慎；
- `[OK] [--] [~~] [!!] [??]` 和完整 label 保留；
- selection 使用 `>`、bracket 或 reverse（若能力允许）；
- warning / failure 保留文字前缀；
- snapshot tests 与人工验收必须覆盖 monochrome。

`NO_COLOR` 优先于 user theme；CLI explicit color policy 若未来提供，需要单独定义，不在本阶段增加新 flag。

### 18.5 Typography 与符号

终端没有可控 web font。设计不能依赖 JetBrains Mono、Nerd Font 或 icon font。默认使用：

- ASCII status token；
- Unicode box drawing 只作可选、可降级的细分隔；
- 不使用 emoji 作为核心状态；
- 数字、ID、hash、path 保持 monospace 自然优势；
- CJK double-width、combining character、截断和 ellipsis 必须实测。

### 18.6 边框与空间

- 首页最多一个轻量分隔概念，不为每行画 panel；
- 状态依靠对齐、空行和缩进，不靠四层 box；
- 80×24 不使用永久左右 sidebar；
- 空白是层次，不填满所有行；
- 路径优先中间截断并在 detail 中展示完整值；
- narrow terminal 中标题、原因和动作按优先级折叠，而不是水平滚动整个页面。

### 18.7 Motion

- 只在用户需要知道“仍在运行”时动画；
- spinner 使用单一、稳定节奏；
- operation 完成后停止，不播放庆祝动画；
- reduced motion preference 禁用 spinner animation，改用静态 `Running · 3.2s`；
- 不做自动轮播、跳动数字、progress bar 或 typing effect。

## 19. Wireframes / Screen Mockups

以下草图用于比较信息结构，不是最终 CSS、颜色或 exact copy。`>` 表示 keyboard focus；`[OK] [--] [~~] [!!] [??]` 在彩色与 `NO_COLOR` 下都存在。

### 19.1 候选 1：Status Ledger Workspace（推荐）

#### 1A. Fresh repository

```text
RepoEvidence   shop-service · main@a17c9e2 · clean
/work/shop-service

Project evidence
> [--] Source       尚未检查
  [--] MySQL        尚未验证 · 可选，只有明确操作才会连接
  [--] Comparison   尚不可比较 · 需要 Source 和 MySQL
  [--] Report       尚无报告

下一步
  Inspect source
  只读取源码与项目配置；不会运行项目，也不会连接数据库。

Enter 开始检查   Tab 移动   ? 帮助   q 退出
```

为什么有效：项目、安全边界和第一动作在同一屏；初始状态使用 muted，不把“尚未运行”当红色错误。

#### 1B. Immediately after source inspection

```text
RepoEvidence   shop-service · main@a17c9e2 · clean

Project evidence
> [OK] Source       已检查此项目快照 · 14:28
  [--] MySQL        尚未验证 · 可选
  [--] Comparison   尚不可比较 · 需要 MySQL snapshot
  [OK] Report       已生成 · 中文 · 14:28

Source summary
  4 collectors · 38 facts · 2 conflicts · coverage 有限制

下一步
  Review source evidence
  可选：Verify MySQL（将连接外部数据库）

Enter 查看详情   A Actions   ? 帮助   q 退出
```

为什么有效：完成后不强迫验证数据库；`inspect` 同时生成 Report 的当前 contract 被保留。

#### 1C. MySQL not verified — selected detail

```text
RepoEvidence   shop-service · main@a17c9e2 · clean

  [OK] Source       已检查此项目快照 · 14:28
> [--] MySQL        尚未验证 · 可选
  [--] Comparison   尚不可比较
  [OK] Report       已生成 · 中文 · 14:28

MySQL runtime
  RepoEvidence 仅在你选择 Verify 后连接数据库。
  使用环境变量配置；只读取 metadata 与 Flyway history，
  不读取业务数据。当前配置：4/5 项已设置（值不会显示）。

  [ Configure help ]    [ Verify MySQL… ]

Tab 移动   Enter 选择   Esc 概览   ? 安全说明
```

为什么有效：not verified 被解释为可选状态；外部连接动作有明确的 effect preview 和二次确认。

#### 1D. Drift detected

```text
RepoEvidence   shop-service · release/2.3@c4210df · clean

Project evidence
  [OK] Source       匹配当前提交 · 15:02
  [OK] MySQL        已验证快照 · 15:04
> [OK] Comparison   输入一致 · 15:04
  [~~] Report       比较结果更新后需要刷新

Comparison result                                      ATTENTION
  Drift detected · 3 findings
  2 runtime-only migrations · 1 version mismatch

下一步
  Review 3 findings
  Secondary: Refresh report

Enter 查看 findings   R 刷新报告   ? 帮助   q 退出
```

为什么有效：comparison operation 是成功的 `[OK]`，domain outcome “Drift detected” 独立显示 attention；不会把有价值的发现错误表现成程序失败。

#### 优点

- 状态稳定、依赖关系可见；
- novice 不必记 command，expert 可以快速扫四行；
- failure、stale、unknown 有自然落点；
- 最适合 responsive collapse；
- 与 HTML 的“完整详情”分工清楚。

#### 风险

- status projection 不准确时危害最大；
- 容易在迭代中被塞成 dashboard/card wall；
- 需要认真处理 selection、detail 与 primary action 的视觉竞争。

### 19.2 候选 2：Guided Runbook / Vertical Stepper

#### 2A. Fresh repository

```text
RepoEvidence   shop-service

Understand this repository in four steps

> 1  Inspect source       Ready
     Safe local inspection; does not run the project.
  2  Verify MySQL         Optional · waiting
  3  Compare              Waiting for source and runtime
  4  Read report          Not generated

Start step 1: Inspect source

Enter continue   ↓ choose another step   ? why these steps   q quit
```

#### 2B. Immediately after source inspection

```text
RepoEvidence   shop-service

  ✓ 1  Inspect source       Complete · 14:28
> · 2  Verify MySQL         Optional · not run
  · 3  Compare              Waiting for MySQL
  ✓ 4  Read source report   Available · 中文

Source: 38 facts · 2 conflicts

You can read the source report now.
Verifying MySQL is optional and connects only when selected.

Enter open step   ↑↓ move   Esc overview   q quit
```

#### 2C. MySQL not verified — verification step

```text
RepoEvidence   shop-service   Step 2 of 4 (optional)

Verify MySQL runtime

What happens
  • Connect using environment configuration
  • Read metadata and Flyway history
  • Write .repoevidence/verification/mysql.json

Configuration                         4/5 present
  Missing: MYSQL_DATABASE

> Show setup help        Verify (unavailable)

Enter choose   Esc back   ? security details
```

#### 2D. Drift detected

```text
RepoEvidence   shop-service

  ✓ 1  Inspect source       Complete · current commit
  ✓ 2  Verify MySQL         Complete · snapshot 15:04
> ! 3  Compare              Complete · drift detected
  ~ 4  Read report          Needs refresh

3 findings need review
  2 runtime-only migrations
  1 version mismatch

> Review findings        Refresh report

Enter choose   ↑↓ move   ? interpretation   q quit
```

#### 优点

- 首次使用学习成本最低；
- prerequisite 与安全说明自然；
- recovery 可以绑定到具体 step；
- fresh repository 的 onboarding 很清楚。

#### 缺点

- 暗示一个固定、必须完成的线性流程；
- Report 实际可在 source-only 情况下存在，step 4 不是永远依赖 step 3；
- 日常用户与高级用户来回调查时效率下降；
- optional MySQL 很容易被视觉上误读为“未完成任务”；
- 随能力扩展会退化成安装向导或复杂菜单。

#### 可吸收部分

将 fresh repository 的首次引导 copy 和 step explanation 吸收到候选 1 的 detail；不保留永久 stepper。

### 19.3 候选 3：Palette-first Minimal Canvas

#### 3A. Fresh repository

```text
RepoEvidence   shop-service · no evidence yet

No source inspection has been run.

> Open Actions…
  Suggested: Inspect source

Ctrl+K actions   ? help   q quit
```

打开 palette：

```text
Actions                                                     Esc
> Inspect source                         safe local operation
  View supported evidence
  Change language
  Open project path
```

#### 3B. Immediately after source inspection

```text
RepoEvidence   shop-service · source inspected 14:28

38 facts · 2 conflicts · report available
MySQL has not been verified.

Recent
  14:28  Source inspection completed
  14:28  Report generated · 中文

> Review source evidence

Ctrl+K actions   ? help   q quit
```

#### 3C. MySQL not verified — palette search

```text
Actions: verify                                              Esc

> Verify MySQL…
    Connects to an external database using environment config
  Show MySQL configuration help

Source is available. MySQL has not been verified.

↑↓ select   Enter choose
```

#### 3D. Drift detected

```text
RepoEvidence   shop-service · drift detected

3 comparison findings
  2 runtime-only · 1 version mismatch

Recent
  15:04  MySQL snapshot verified
  15:04  Comparison completed · drift detected
  15:04  Report became stale

> Review findings

Ctrl+K actions   ? help   q quit
```

#### 优点

- 视觉极简；
- expert 可以模糊搜索任何 action；
- action 数量增长后不需要菜单树；
- activity stream 对操作时间线自然。

#### 缺点

- Source / Runtime / Comparison / Report 的稳定关系不再一眼可见；
- 依赖 palette 发现能力；
- 新手容易把首页当成“只有一个按钮”；
- recent activity 会逐渐挤走当前状态；
- 无 history 的 fresh session 信息不足，有 history 又引入新的持久数据问题。

#### 可吸收部分

把 searchable Actions palette 作为候选 1 的二级 accelerator；不采用 palette-first canvas。

### 19.4 推荐界面的 responsive 行为

#### 120×40

```text
Header: repository / branch / commit / dirty / operation
────────────────────────────────────────────────────────────────────────────
Status ledger (约 45%)             Selected detail / findings (约 55%)
Source                             explanation
MySQL                              coverage / provenance
Comparison                         contextual actions
Report
────────────────────────────────────────────────────────────────────────────
Recent activity（最多 3–5 行）
Footer help
```

- 使用左右分栏；
- activity 可见；
- detail 可显示较完整 finding 摘要；
- 不因空间大就加入更多永久卡片。

#### 100×30

- 保留左右分栏，但 detail 缩短；或在 CJK copy 过宽时切换单列；
- activity 最多 2–3 行；
- header path 中间截断；
- footer 只显示当前 context 的 4 个 key。

#### 80×24

```text
RepoEvidence  shop-service · main@a17c9e2 · clean

> [OK] Source       已检查此项目快照 · 14:28
  [--] MySQL        尚未验证 · 可选
  [--] Comparison   需要 MySQL snapshot
  [OK] Report       已生成 · 中文

Source summary
  38 facts · 2 conflicts · coverage 有限制

Next: Review source evidence
      Verify MySQL is optional and connects externally.

Enter details   A Actions   ? help   q quit
```

- 单列是默认，不强行 split；
- selected detail 只保留摘要和最多两个动作；
- activity 折叠为计数或独立 view；
- 24 行内不需要 vertical scroll 才能看到 next action 和 footer。

#### 40–60 columns

```text
RepoEvidence  shop-service
main@a17c9e2 · dirty

> [OK] Source
       inspected 14:28
  [--] MySQL
       not verified (optional)
  [--] Comparison
       needs MySQL
  [~~] Report
       refresh needed

Next: Refresh report

Enter  Actions  ?  q
```

- 无边框、无表格竖线；
- 每项最多两行，先 label 后 qualifier；
- 完整 path 只在 detail，可水平复制但主 view 自动换行；
- metadata 按 commit → branch → path 顺序逐级隐藏；
- action palette 全屏覆盖，而不是窄弹窗；
- 若低于产品批准的 minimum width，不 crash：显示清楚的 narrow-mode 提示并保持 one-shot command 可用。

### 19.5 候选结论

采用候选 1 作为信息架构；吸收候选 2 的 first-run explanation；吸收候选 3 的可搜索 Actions。不能把三套导航同时永久显示，否则会变成 status rows + stepper + palette + activity 的过载界面。

## 20. Error Recovery

### 20.1 统一呈现顺序

每个 recoverable problem 使用同一信息顺序：

1. **发生了什么**：一行用户可理解摘要；
2. **为什么**：已知原因，不猜测；
3. **如何恢复**：一个 primary recovery + 最多一个 secondary；
4. **Technical details**：按需展开，包含 code、path、timestamp、sanitized error。

failure 后 application 不退出，其他 artifact 仍可浏览。只有 terminal I/O 无法恢复、internal invariant 被破坏或用户明确退出时才结束 session。

### 20.2 场景矩阵

| 场景 | 发生什么 | 为什么 / 状态 | Primary recovery | Technical detail |
|---|---|---|---|---|
| MySQL config missing | Verify 未启动 | 必需 env variable 缺失；Runtime 保持 not verified | Show configuration help；设置后 Recheck | 只列 variable name 和 present/missing，不列 value |
| Database unreachable | Verification 失败但 workspace 保留 | timeout、DNS、auth 或 server error；不得猜具体原因 | Retry verification | sanitized connector code、发生阶段、elapsed；不含 DSN/password |
| Invalid repo/path | 无法建立 project context | path 不存在、不是目录、无权限 | Choose another path | normalized path、OS error code |
| Low-confidence repository | 目录可读但未识别常见 marker | 不等同 failure | Inspect current directory 或 choose path | 识别到的 markers / limitations |
| Artifact missing | 对应步骤从未完成或文件被移除 | 正常 prerequisite gap | Run producing action | expected path |
| Artifact corrupted | 不能解析，旧文件保持原样 | truncated JSON、invalid schema/content | Regenerate artifact | parser path / line、schema，禁止自动删除 |
| Unsupported schema | 当前版本无法解释 artifact | artifact 来自更高/不支持版本 | Show compatibility help | found/expected schema version |
| Stale comparison | 输入 hash 已变化 | 旧 comparison 仍可查看但不是当前结论 | Compare again | old/new input hash shortened，完整值在 detail |
| Report failure | generation 未完成；以前有效 Report 尽量保留 | renderer、write permission、disk error | Retry report | output path、safe exception、phase |
| Report open failure | Report 本身仍有效 | headless、无 opener 或 OS integration error | Show/copy report path | opener result；不把 Report 标 failed |
| Unsupported condition | 能读取但当前 collector/reconciler 无法解释 | 不是“clean” | Review limitation / export JSON | stable reason code、Evidence IDs |
| Internal application error | 当前 action 失败，workspace 进入 degraded state | bug 或 invariant violation | Copy sanitized diagnostic / exit safely | traceback 只在明确 debug mode 或本地 log，先 redaction |

### 20.3 MySQL 配置恢复细节

MVP 保持 env-only：TUI 不提供 password input，不写 `.env`，不把 connection profile 存入 user config。设置环境变量后，已经启动的进程通常无法从 parent shell 获得新 export；因此 UI 必须诚实说明：

- 在另一个 shell 设置不会自动注入当前进程；
- 推荐退出、在配置好的 shell 中重新启动，或使用现有受支持的启动方式；
- `Recheck environment` 只重新读取当前 process environment；
- 不提供“帮我写 .env”动作。

未来若要支持 masked session entry，必须单独做 security threat model，不在当前 roadmap。

### 20.4 Corrupt artifact 策略

- 不自动删除、rename 或覆盖；
- 首页显示 `[??] Cannot read result`；
- detail 给出路径、检测原因和“Regenerate”作用；
- regenerate 应通过 application service 原子替换；
- 如果需要保留 corrupt sample 供诊断，用户自己复制，TUI 不自动扩散敏感内容；
- 其他不依赖它的功能继续可用。

### 20.5 Crash 与恢复

MVP 不引入 session restore。应用异常退出后，重新启动只根据 machine artifacts 重新构建状态；临时 UI selection、activity 和 modal 不恢复。原子 artifact 写入与 startup corrupt detection 是恢复基础。

## 21. User Configuration

### 21.1 需要 user-level config

推荐增加极小的 user-level configuration，因为语言、主题和默认交互方式是跨项目的人类偏好；每次启动都重新选择会损害成熟度。

它必须与 project analysis state 分离：

```text
Project machine state              User UI preference
.repoevidence/                     OS user config directory
  evidence.json                      settings.json
  verification/mysql.json
  reconciliation.json
  report/
```

### 21.2 推荐位置

使用 OS 标准 user config directory，优先通过明确声明的 `platformdirs` dependency 或等价、经过测试的内部 resolver：

| Platform | 推荐路径 |
|---|---|
| Linux | `$XDG_CONFIG_HOME/repoevidence/settings.json`，未设时 `~/.config/repoevidence/settings.json` |
| macOS | `~/Library/Application Support/RepoEvidence/settings.json` |
| Windows | `%APPDATA%\RepoEvidence\settings.json` |

不要依赖某个 transitive dependency 偶然安装 `platformdirs`；若采用，应在 `pyproject.toml` 直接声明并测试 wheel。

### 21.3 推荐格式

JSON 足以支持初始设置，使用 stdlib 解析、versioned schema 和原子写入：

```json
{
  "schema_version": 1,
  "language": "auto",
  "theme": "auto",
  "interaction": "auto",
  "reduced_motion": false
}
```

允许值建议：

- `language`: `auto`, `en`, `zh-CN`；
- `theme`: `auto`, `dark`, `light`；
- `interaction`: `auto`, `workspace`, `plain`；
- `reduced_motion`: boolean。

字段名和枚举不翻译。未知字段在 forward compatibility 策略明确前应保留或安全忽略，不能无提示重写丢失。

### 21.4 不保存的内容

初始 user config 不保存：

- MySQL host、port、database、username、password、DSN；
- environment variable values；
- Evidence / Fact / Verification result；
- last operation output；
- session activity / command history；
- target repository-specific state；
- last-opened repository（MVP 默认不保存，避免隐私与跨项目误开）；
- report 内容或 path index。

如果未来保存 last repository，必须提供 disable / clear、路径隐私说明和不存在路径恢复，本阶段不需要。

### 21.5 Precedence 与 override

- explicit CLI flag 只覆盖本次 invocation，不写 config；
- env var 覆盖 config，但不改 config；
- Settings 中用户明确保存才写 config；
- `NO_COLOR` 是环境级 accessibility override，优先于 theme；
- config 读取失败时使用 default 并显示 non-blocking warning；
- config 损坏时不自动清空，提供路径与恢复说明。

### 21.6 Config 写入安全

- 创建父目录时使用用户默认权限；
- 同目录临时文件 + atomic replace；
- schema validation；
- 不在 debug output 打印整个 config object，以防未来字段扩展；
- 写入失败只影响 preference persistence，不应结束 workspace；
- project `.repoevidence/` 永不读取 user UI preference。

## 22. Accessibility

### 22.1 Keyboard-only baseline

所有核心任务必须无需 mouse：

- Tab / Shift+Tab 跨 region；
- Up / Down 在 list 内；
- Enter 打开或确认明确 action；
- Esc 关闭 / 返回；
- `?` 打开 contextual help；
- `q` predictable quit；
- Ctrl+C 遵循 operation cancellation policy。

快捷键数量保持少且稳定。字母捷径只给高频、低风险动作；外部连接不能只靠单键立即执行。

### 22.2 Focus 与 selection

- focus 永远可见；
- focus 不只依赖颜色；
- modal 打开时 focus trap，关闭后回到触发元素；
- disabled action 可被发现时要能读取 reason，但不能让用户在大量不可用项间 tab；
- operation 完成不任意跳走；
- resize 后 focus 对象保持，而不是根据行号变化。

### 22.3 Screen reader 与 plain alternative

full-screen TUI 对 screen reader 的表现因 terminal 与平台差异很大，不能仅凭 framework widget semantics 声称 accessible。

必须：

- 保留 one-shot CLI 的线性 plain output；
- 提供 `--plain` / `interaction=plain` 选择；
- 文档明确 automation 与 accessible fallback command；
- 对常见 screen reader + terminal 做人工任务测试；
- 关键结果可复制为 plain text / 通过现有 CLI 重现；
- 不让 ephemeral toast 成为唯一信息来源。

### 22.4 Color blindness 与 monochrome

- red/green 之外始终有 token + label；
- selected 与 attention 使用不同形状/位置；
- drift、failure、stale 使用不同文字；
- `NO_COLOR` 完整可用；
- 人工检查常见 protanopia/deuteranopia simulation 只能辅助，不能替代 monochrome task test。

### 22.5 CJK、Unicode 与输入法

- English 和 zh-CN 都在 40/60/80/100/120 列测试；
- 验证双宽字符、标点、ellipsis、combining sequence；
- path 中的中文、空格和 emoji filename 不破坏 layout；
- palette filter 若支持 IME，需在 macOS、Windows、Linux 实测；
- 核心导航不依赖需要复杂输入法的命令；
- fallback token 使用 ASCII。

### 22.6 Motion 与认知负担

- reduced motion 模式用静态 running label；
- 首页一次只有一个 primary action；
- warning copy 短而具体；
- help 按 context 展示，不一次列出几十个键；
- 安全确认说明 effect，不使用双重否定；
- 没运行是 neutral，不制造“红色待办焦虑”。

## 23. Non-TTY / Automation Compatibility

### 23.1 Interactive eligibility

自动进入 full-screen workspace 至少需要：

- 无 explicit one-shot subcommand；
- stdin 与 stdout 都是适合交互的 TTY；
- `TERM` 不是 `dumb`；
- 没有 `--plain` 或 `interaction=plain`；
- 未检测到明确 CI non-interactive intent；
- terminal 初始化成功。

任何一项不满足，都走 plain path。stderr 是否 TTY 不应单独决定，因为用户可能重定向 diagnostics；具体规则需 PTY tests 固化。

TTY 检测只能作为默认启发式。显式 `repoevidence workspace [PATH]` 表达用户意图，但在真正 non-TTY 中仍应清楚失败，而不是输出 ANSI frame 到 pipe。

### 23.2 裸命令兼容

当前裸 `repoevidence` 打印 welcome / recommended inspect / help 后退出。推荐迁移结果：

| Context | 最终行为 |
|---|---|
| Suitable human TTY | 进入 workspace（在 staged rollout 完成后） |
| stdout pipe / redirect | 保持现有 plain welcome，exit 0 |
| stdin 非 TTY | plain welcome，exit 0 |
| `TERM=dumb` | plain welcome，exit 0 |
| CI | plain welcome，exit 0，除非用户运行明确 subcommand |
| `--plain` / config plain | plain welcome，exit 0 |
| explicit `workspace` + non-TTY | stderr 给出清楚说明并建议 one-shot CLI；推荐 usage exit 2，需产品批准 |

在默认切换前，必须把当前 plain welcome 做 golden contract test，确保 pipe / redirect 没有 spinner、alternate-screen escape、Rich style 或 interactive import error。

### 23.3 Existing subcommands

以下命令无论是否 TTY，都继续 one-shot，不自动进入 workspace：

```text
repoevidence inspect .
repoevidence scan .
repoevidence verify mysql .
repoevidence reconcile .
repoevidence report .
```

它们保持：

- 参数和 command name；
- stdout/stderr intent；
- exit code；
- artifact path；
- `--lang`；
- TTY color 与 plain output policy；
- machine contract。

Interactive app 不能改变命令默认路径或在 command 成功后“顺便进入 workspace”。

### 23.4 Pipe、redirect 与 log

- no progress animation；
- no carriage-return live update；
- no alternate-screen control sequence；
- no keyboard prompt；
- `NO_COLOR` 被遵守；
- error 在 stderr、正常 summary 在 stdout 的当前约定保持；
- technical machine consumer 继续读取 JSON artifact，不解析 localized human output。

### 23.5 Environment capability failure

如果满足 TTY 条件但 Textual 初始化失败：

- restore terminal state；
- 输出简洁、localized plain error；
- 推荐 `repoevidence inspect .` 或 `repoevidence --plain`；
- 不自动执行 inspect；
- 记录可安全复制的 framework/problem code；
- exit code 策略在 Phase 0 固化。

## 24. Testing Strategy

### 24.1 测试金字塔

```text
              Manual terminal / UX acceptance
          PTY + selected cross-platform journeys
       Headless interactive state/keyboard tests
    Projection / transition / application service tests
Machine schema / deterministic artifact contract tests
```

越接近 machine layer 越全面自动化；越接近视觉感知越需要少量高价值自动测试 + 真实人眼验收。

### 24.2 Unit tests

应全面自动化：

- project context discovery；
- Git absent / clean / dirty / detached HEAD / nested path；
- artifact missing / valid / corrupt / unsupported；
- source freshness 规则；
- runtime snapshot label 与 timestamp；
- exact comparison input hash invalidation；
- report manifest assessment；
- status precedence；
- next-action pure function；
- action availability / safety level；
- config precedence、schema、corrupt file、atomic write；
- language message completeness；
- safe error redaction；
- operation event order 与 elapsed 使用 monotonic clock。

必须有一个 regression test 覆盖“artifact stored HEAD 与当前 HEAD 不同，不能显示 current”；另一个覆盖 dirty worktree 无充分 provenance 时显示 uncertain。

### 24.3 State transition tests

用 table-driven tests 覆盖：

```text
fresh repo
  → inspect success
  → verify success
  → reconcile drift
  → report refresh
  → source changes
  → comparison/report stale
  → inspect failure / retry success
```

另测：

- verification failure artifact；
- partial collector result；
- corrupt artifact regenerated；
- report open failure不改变 Report status；
- language change只改变 copy，不改变 domain state；
- operation cancel requested 与 confirmed cancel。

禁止在这些测试中用真实 `sleep`；使用 fake clock、controlled worker 和 deterministic events。

### 24.4 Application service tests

保留并扩展当前 service tests：

- CLI 与 TUI 调用同一个 service；
- exact serialization 和 path 未变；
- event observer 缺失时行为完全兼容；
- observer error 不破坏 machine operation；
- atomic replace 成功/失败；
- previous valid artifact 在 failure 后保留；
- verifier 仍只在 explicit service call 连接；
- inspect 顺序仍为 scan → report；
- reconciliation 仍离线。

### 24.5 Interactive headless tests

Textual 方案下使用官方 `run_test()` / Pilot：

- app startup 不自动调用 service；
- default focus；
- Tab / Shift+Tab / arrows / Enter / Esc / `?` / `q`；
- fresh、current、stale、unknown、failure、drift screens；
- modal focus restore；
- palette search与 action ID mapping；
- external verify confirmation；
- resize 40/60/80/100/120 columns；
- English / zh-CN runtime switch；
- worker completion / failure / cancellation；
- one operation single-flight；
- notification 同时进入 activity；
- `NO_COLOR` semantic tokens remain。

Widget test 应断言 domain-visible semantics 与 focus，不把内部 CSS class 数量当主要 contract。

### 24.6 PTY tests

至少在 Unix CI 使用真实 pseudo-terminal 验证：

- alternate screen enter/restore；
- Ctrl+C、q 与 process exit；
- terminal resize signal；
- stdout redirect 时不进入 TUI；
- stderr redirect 不破坏 route；
- crash 后 cursor / echo 被恢复；
- Unicode / CJK basic rendering；
- no ANSI 在 plain output；
- cold start 到 first meaningful screen 的时间。

Windows 使用 ConPTY 或目标 CI 能力做等价 journey；不能用 Unix PTY 结果推断 Windows 已通过。

### 24.7 Localization tests

- catalog key parity；
- 参数化 en / zh-CN 所有状态组合；
- 不出现 raw enum / missing key；
- 语言切换后已有 activity 重渲染或按批准策略稳定显示；
- Report language differs 的 copy；
- terminal width 下中文不遮挡 action；
- machine JSON bytes 不随 UI language 改变（除已有明确的 report language presentation）。

### 24.8 Accessibility automation

值得自动化：

- focus order；
- action 可 keyboard 触达；
- `NO_COLOR` token；
- selected marker；
- modal focus trap；
- reduced motion 下无 spinner timer；
- plain fallback；
- 不使用仅颜色区别的 snapshot semantic assertion。

不能仅靠自动化证明：screen reader 可理解、copy 自然、对比度舒适、CJK 视觉平衡、动画是否烦扰。这些必须人工验收。

### 24.9 Machine contract tests

现有 machine-contract tests 是 interactive 项目的硬门禁：

- Pydantic schema；
- artifact exact structure；
- deterministic ordering；
- IDs / references；
- hash；
- command exit behavior；
- verify-only external connection；
- report escaping / redaction。

每阶段全量运行，不能因为 UI tests 通过就忽略。

### 24.10 Visual regression

适合 snapshot 的内容：

- 关键 layout 在固定 terminal size 的结构；
- status token、label、focus marker；
- 80×24 / 40×20 是否保留 primary action；
- English / zh-CN / `NO_COLOR`；
- failure modal 不超出 viewport。

不应把每个 pixel-like cell 或 spinner frame 都冻结。snapshot update 必须人工 review diff；它只能发现变化，不能判断界面成熟。

### 24.11 人工验收矩阵

每个 Phase gate 至少选择：

- Linux：常见 terminal + tmux；
- macOS：Terminal 或 iTerm2；
- Windows：Windows Terminal / PowerShell；
- WSL：Windows Terminal 中的 WSL；
- SSH / remote shell；
- dark 与 light terminal；
- 80×24、100×30、120×40、50×20；
- English 与中文；
- `NO_COLOR`；
- keyboard-only；
- 至少一次 screen reader / plain fallback task；
- fast operation 与 artificial controlled slow fake service（不是 production sleep）；
- MySQL config missing、unreachable、drift、corrupt artifact。

### 24.12 验收记录

人工验收不只写“看起来不错”，应记录：terminal/OS/size/language/scenario、观察、blocking issue、screenshot 或 transcript、决策人和日期。未经对应 Phase 人工验收，不进入下一阶段。

## 25. Migration Strategy

### 25.1 兼容目标

对所有带 subcommand 的现有用法保持 100% backward compatibility；对裸 `repoevidence`，只在 suitable human TTY 中有计划地改变，non-TTY 的当前 welcome contract 保持。

### 25.2 分步启用

#### Migration A：显式 preview

- 新增 `repoevidence workspace [PATH]`；
- 裸 `repoevidence` 行为暂不变；
- documentation 标记为 product preview；
- 收集人工验收反馈，不加 telemetry；
- CI 和 scripts 完全不受影响。

#### Migration B：TTY opt-in preference

- 允许 user config `interaction=workspace`；
- 裸命令只有明确偏好时进入 workspace；
- 提供 `--plain`；
- 继续验证 startup、accessibility 和 packaging。

#### Migration C：TTY default

只有当 Acceptance Criteria 全部通过且产品负责人批准：

- suitable TTY 下裸命令进入 workspace；
- non-TTY / CI / redirect 仍输出现有 welcome 并退出；
- `interaction=plain` 与 `--plain` 提供永久 opt-out；
- release note 清楚说明唯一有意改变的入口。

如果产品负责人希望一次发布就切默认，可合并 A/B/C，但风险显著增加，不推荐。

### 25.3 Artifact migration

- 不迁移或重写现有 evidence / verification / reconciliation JSON；
- legacy artifacts 缺 freshness metadata 时显示 uncertain；
- 不为了让 UI 变绿而静默重新 scan；
- 如果加入 report manifest，只在下一次显式生成/刷新 Report 时创建；
- 旧 HTML 继续可打开；
- unsupported future schema 保留并提示兼容，不降级写回。

### 25.4 CLI documentation migration

README 的主路径最终可变为：

- 人类探索：`repoevidence` / `repoevidence workspace .`；
- 自动化与准确动作：列出现有 subcommands；
- 安全承诺：启动 workspace 不自动 scan/verify；
- non-TTY behavior；
- plain/accessibility path；
- language precedence；
- Report 与 JSON 的职责。

但在 Phase A 前不更新 README 宣称默认 TUI，也不把未批准的 keyboard / framework 写成正式承诺。

### 25.5 Rollback strategy

interactive default 若出现严重兼容问题，必须能通过一个小范围 adapter change 恢复裸命令 plain behavior，而不回滚 machine/application layer。为此：

- TTY router 独立；
- interactive lazy import；
- explicit subcommands 不依赖 app startup；
- user config 解析失败不阻止 CLI；
- machine artifacts 不因 TUI 使用新专属格式。

## 26. Phased Implementation Roadmap

### 26.1 阶段原则

- 每一阶段是独立 review unit，不组成一个巨大 PR；
- 每阶段先自动验证，再人工验收，产品负责人批准后才进入下一阶段；
- machine contract 与 external-connection safety 是所有阶段的持续门禁；
- 文件列表是预期影响面，不授权本次修改；
- 若前一轮 uncommitted CLI / Report 工作尚未被验收，应先确定基线归属，避免新阶段叠在不稳定 working tree 上；
- 任一阶段可停止，现有 one-shot CLI 仍保持可用。

### 26.2 Phase 0 — Product decision + framework feasibility spike

**目标**

- 验证 Status Ledger Workspace 心智模型；
- 验证 Textual 是否能在目标终端、尺寸、语言和 worker 场景中满足要求；
- 冻结第一批产品决策，不生产正式功能。

**预期文件 / 产物**

- 本文的 product decision revision；
- 一份 Architecture Decision Record，例如 `docs/architecture/interactive-framework.md`；
- 可丢弃、不打包的 `experiments/interactive-workspace/` 原型，或完全独立的 prototype branch/worktree；
- 人工验收矩阵与结果记录；
- dependency / wheel / cold-start 调研记录。

**Contract**

- 不修改 machine schema、artifact、CLI command 或生产 source；
- 原型使用 fake state / fake service，不连接数据库、不扫描 target code；
- 不把 prototype CSS / widget 视为最终设计。

**验证**

- Textual headless keyboard / resize prototype tests；
- 40/60/80/100/120 列；
- zh-CN / en / `NO_COLOR`；
- fake 100ms、1s、5s、failure、cancel operation；
- Windows Terminal、WSL、Linux、macOS、tmux/SSH 人工任务；
- wheel install 和 startup time measurement。

**独立验收标准**

- 产品负责人能仅凭首屏识别项目、四项状态与下一步；
- 新手无需 palette 即可完成 fake inspect → verify → compare → report；
- expert 可在不穿过 runbook 的情况下快速触发动作；
- terminal restore、resize、CJK 和 monochrome 无 blocking defect；
- Textual 风险、pin 策略与 fallback 被明确接受，或正式选择替代框架。

**主要风险**

- prototype 看起来漂亮但没有真实 state complexity；
- 只在开发者自己的 terminal 验证；
- 提前把 Textual 当既定答案；
- 原型代码未经设计直接进入 production。

**Gate 决策**

Go：批准产品模型和框架；Revise：调整布局/框架后重测；Stop：继续 one-shot CLI，不进入 TUI。

### 26.3 Phase 1 — Trustworthy project status foundation

**目标**

- 在任何 interactive UI 之前建立可信、presentation-neutral 的 project context、freshness 和 dependency invalidation；
- 解决 `current` 误导问题；
- 设计 Report freshness manifest，但只在 contract 批准后实现。

**预期文件**

- `src/repoevidence/assessment.py`；
- 可能新增 `src/repoevidence/project_context.py`；
- 可能新增 `src/repoevidence/project_status.py` 或 `workspace.py`（只含 projection）；
- `src/repoevidence/report_view.py`（仅共享 projection 需要时）；
- 对应 `tests/test_assessment.py`、`tests/test_project_status.py`、`tests/test_report_states.py`；
- machine contract regression tests。

**Contract**

- existing five-state API 若已成为 application contract，保持 backward behavior 或提供显式 migration；
- 新增 freshness 维度，不改变 Evidence / Verification / Reconciliation schema；
- 不自动 scan；
- Git 非必需；
- dirty / legacy / unverifiable 状态诚实降级为 uncertain；
- exact reconciliation input hash 仍为唯一 comparison freshness 依据。

**验证**

- clean same HEAD、different HEAD、dirty worktree、non-Git、detached HEAD；
- missing/corrupt/unsupported artifacts；
- legacy report；
- source/runtime replacement 导致 downstream stale；
- current working repository 的已知 mismatch regression；
- performance budget，不递归做隐式 scan。

**独立验收标准**

- 一个 read-only diagnostic/API 能准确解释四项状态及 reason code；
- 无法证明时不显示 current；
- assessment 不写任何文件、不连接数据库；
- existing CLI/machine tests 全部通过；
- 产品负责人批准人类 label mapping。

**主要风险**

- 为证明 freshness 设计过重 fingerprint 系统；
- Git-centric 假设破坏非 Git 目录；
- 为修 UI 改 machine schema；
- Report 没有 manifest 导致状态永远 uncertain，团队试图用 mtime 猜测。

### 26.4 Phase 2 — Read-only workspace shell and routing

**目标**

- 构建 read-only persistent workspace；
- 展示真实 project context 与 status ledger；
- 完成 navigation、detail、help、responsive shell；
- 先以显式 `repoevidence workspace [PATH]` 暴露。

**预期文件**

- `pyproject.toml`（仅在 Phase 0 批准后增加经过 pin 的 Textual dependency）；
- `src/repoevidence/interactive/__init__.py`；
- `src/repoevidence/interactive/app.py`；
- `src/repoevidence/interactive/controller.py`；
- `src/repoevidence/interactive/views/*` / `widgets/*`；
- `src/repoevidence/cli.py` 的 lazy router；
- `src/repoevidence/i18n.py` 的必要 message keys；
- `tests/test_interactive_app.py`、`tests/test_cli_journeys.py`、PTY tests。

**Contract**

- app startup read-only；
- 不调用 scan/verify/reconcile/report service；
- existing subcommands 与裸命令默认行为先保持；
- non-TTY 不 import/start app；
- view 不直接读取 machine files，只消费 projection；
- `q` / Ctrl+C 恢复 terminal。

**验证**

- fresh/current/stale/unknown/failure/drift fake + real artifact states；
- keyboard focus、help、detail/back；
- resize matrix；
- plain/no-color；
- startup failure fallback；
- packaging import test；
- screen reader/plain alternative manual task。

**独立验收标准**

- 用户能进入/退出、理解当前项目与状态、查看原因，但不能从 TUI 执行 operation；
- 启动期间 filesystem write count 为零；
- 现有 CLI 输出与 exit code 未变化；
- 80×24 首屏无需 scroll 看见 next action 和 footer；
- 人工视觉评审认可“稳定、节制、非卡片墙”。

**主要风险**

- read-only shell 被误认为“功能没做完”而提前塞入 operation；
- framework import 影响 one-shot startup；
- detail view 复制整个 HTML Report；
- 键位和 layout 在 prototype 后失控增长。

### 26.5 Phase 3 — Safe local operations: inspect and report

**目标**

- 通过 shared application service 执行 inspect / report；
- 建立 operation runner、真实 phase event、single-flight、failure recovery；
- 保持 source inspection 的安全承诺；
- 提供 explicit generate / refresh / open report。

**预期文件**

- `src/repoevidence/application.py`；
- 可能新增 `src/repoevidence/operations.py`；
- artifact writer helper；
- interactive controller / operation view；
- `reporting.py` / report manifest 相关文件（只有 schema 已批准时）；
- application、interactive、report state、machine contract tests。

**Contract**

- inspect 仍是 scan → report；
- 不运行 target code、不连接数据库；
- TUI 不直接调用 collector；
- event observer optional，不改变无 observer 的 service behavior；
- atomic write 不改变最终 JSON bytes/schema/path；
- previous valid artifact 在失败时尽量保留；
- report open 是显式 OS action。

**验证**

- sub-400ms / 1s / slow fake service；
- success、partial collector、failure、write failure、cancel policy；
- source update 使 comparison/report 正确 stale；
- inspect service call count / order；
- no fake percentage / no production sleep；
- SSH/headless report open fallback；
- one-shot inspect/report regression。

**独立验收标准**

- 用户可从 fresh workspace 完成 inspect 并继续浏览；
- 失败不退出，Retry 与 technical detail 正确；
- operation 期间 UI 可导航；
- 完成后状态来自重新 assessment；
- HTML Report 外观未被本阶段推翻；
- machine/CLI tests 全部通过。

**主要风险**

- thread worker 与 filesystem write 竞态；
- event 为了动画而反向污染 service；
- Cancel 宣称超出实际能力；
- report manifest 变成另一个未经版本化的 truth。

### 26.6 Phase 4 — External runtime verification and comparison

**目标**

- 将 MySQL verification 与 reconciliation 安全地接入 workspace；
- 完成 external-read confirmation、env preflight、failure recovery 与 drift presentation。

**预期文件**

- interactive MySQL confirmation / detail views；
- application operation mapping；
- `verification/mysql.py` 仅在需要 observer/cancellation seam 且 contract 允许时调整；
- reconciliation operation view；
- fake connector / service tests、PTY journeys、security tests。

**Contract**

- 只有用户明确选择并确认 Verify MySQL 才连接；
- config value 永不显示或写 user config；
- 仍只读 metadata / Flyway history；
- reconcile 仍完全 offline；
- drift 是成功 domain outcome，不是 operation failure；
- source/runtime exact artifacts 决定 comparison input；
- existing `repoevidence verify mysql .` 与 `reconcile .` 不变。

**验证**

- config 0/partial/all present；
- connector 从未在 startup / view navigation 调用；
- timeout、auth、DNS/unreachable 的 sanitized failure；
- verification failure artifact；
- matched、runtime-only、source-only、version mismatch、ambiguous；
- snapshot replacement invalidation；
- cancel requested 的真实 connector behavior；
- secret redaction across screen/activity/log/test snapshot。

**独立验收标准**

- 新手在确认前能准确复述会连接什么、读取什么；
- 缺配置/不可达后 app 可恢复；
- verify 完成后 snapshot time 清楚；
- comparison result 与 Report/JSON 一致；
- 没有任何自动 database connection path；
- 安全与 machine contract tests 通过。

**主要风险**

- thread cancellation 无法中断 connector query；
- error message 泄露 credential/host；
- UI 将 verification success 错当 database health；
- 用户把 runtime snapshot 当实时状态；
- retry 造成意外并发连接。

### 26.7 Phase 5 — Language, settings, accessibility and visual refinement

**目标**

- 实现 session 内 en / zh-CN 切换；
- 增加 user-level settings；
- 完成 theme、`NO_COLOR`、reduced motion 和 plain preference；
- 做克制的 visual polish 与 copy review。

**预期文件**

- `src/repoevidence/user_config.py`；
- `i18n.py` / catalog 拆分（若确有必要）；
- interactive Settings view、theme、help；
- `pyproject.toml` 的直接 config-path dependency（若批准）；
- config/localization/accessibility/snapshot tests；
- bilingual documentation。

**Contract**

- precedence 为 explicit flag > env > config > system locale > English；
- preference 不进入 `.repoevidence/`；
- 不保存 secret 或 last repo；
- UI 语言切换不改 machine artifact；
- Report 语言 refresh 显式；
- `NO_COLOR` 覆盖 theme；
- config failure 不阻断 CLI/workspace。

**验证**

- Linux/macOS/Windows config path；
- corrupt/unsupported/read-only config；
- atomic save；
- live switch during idle/running/failure modal；
- CJK widths；
- light/dark/monochrome；
- reduced motion；
- keyboard-only与 screen reader/plain manual journey。

**独立验收标准**

- 中文用户首次启动自然，无 mandatory selector；
- 切换语言无需重启且所有 visible copy 刷新；
- preference 跨项目生效但不污染项目；
- `NO_COLOR` 仍能区分全部状态与 focus；
- 40–60 列无阻断任务；
- 人工 copy、视觉与 accessibility review 通过。

**主要风险**

- settings scope 膨胀；
- event history 存储已渲染句子而无法切换；
- light theme 依赖未知 terminal background；
- snapshot “通过”掩盖真实视觉问题。

### 26.8 Phase 6 — Default rollout, hardening and documentation

**目标**

- 完成 cross-platform、packaging、performance、crash recovery 和文档；
- 决定并实施 suitable TTY 下裸 `repoevidence` 的默认行为；
- 提供稳定 opt-out 与兼容说明。

**预期文件**

- CLI no-arg router；
- README / README.zh-CN / PyPI docs；
- release/checklist docs；
- full PTY / packaging tests；
- manual acceptance record；
- dependency upgrade policy / ADR finalization。

**Contract**

- existing subcommands 100% compatible；
- non-TTY bare command 保持 plain welcome；
- `--plain` / interaction preference 永久可用；
- terminal init failure安全恢复；
- no telemetry；
- 不扩大 collector/database/scope。

**验证**

- 完整自动 test suite；
- fresh wheel / sdist 安装；
- startup performance；
- platform/terminal matrix；
- pipe/redirect/CI golden output；
- all personas end-to-end journeys；
- HTML/JSON traceability；
- dependency vulnerability/license review。

**独立验收标准**

- 产品负责人明确批准 TTY default 或决定继续 explicit workspace；
- 五类 persona 的主要任务都可完成；
- 所有 Acceptance Criteria 有证据；
- 无 blocking terminal restore、secret、machine contract 或 compatibility 问题；
- 人工视觉验收确认成熟度来自稳定信息和 predictable flow，而非装饰。

**主要风险**

- 为了 release deadline 跳过跨平台人工验收；
- no-arg 改动影响未知脚本；
- 文档把 workspace 描述成自动实时 monitor；
- 默认 dependency 增加安装或启动回归。

### 26.9 不进入 roadmap 的未来 extension point

架构应允许未来增加新的 runtime provider 或 collector action ID，但当前阶段不实现 PostgreSQL、Gradle、新 Collector、cloud、Web 或 LLM。extension point 的唯一要求是：新增 capability 仍经过 machine → application → projection → presenter 的边界，而不是在 TUI 添加临时逻辑。

## 27. Risks

### 27.1 风险登记表

| 风险 | 概率 | 影响 | 早期信号 | 缓解 / Gate |
|---|---:|---:|---|---|
| 状态误报 fresh/current | 高 | 极高 | dirty repo 仍显示绿色当前 | Phase 1 先行；unknown 优先；provenance regression tests |
| TUI 破坏 machine/CLI contract | 中 | 极高 | widget 直接调用 scanner/verifier | shared service boundary；machine contract tests 每阶段门禁 |
| 启动时意外连接 MySQL | 低中 | 极高 | view mount 触发 preflight connector | env presence 只读；connector invocation spy；explicit confirmation |
| secret 泄露 | 中 | 极高 | error/activity/snapshot 出现 DSN/value | whitelist metadata；redaction tests；不保存 credentials |
| Textual 跨平台差异 | 中 | 高 | Windows/CJK/SSH 键位或渲染异常 | Phase 0 platform matrix；plain fallback；明确 support policy |
| Textual release churn | 高 | 中高 | frequent breaking/deprecation warnings | pin tested range；ADR；scheduled upgrades，不自动追新 |
| async/thread 竞态 | 中 | 高 | 完成后 row 错乱、退出损坏文件 | single-flight；atomic write；main-loop update；controlled tests |
| cancellation 语义虚假 | 高 | 高 | UI 显示 cancelled 但 query 继续 | cooperative only；requested/confirmed 分离；不强杀线程 |
| UI 变成 card wall | 中高 | 中高 | 首页 panel/快捷键不断增加 | IA budget；80×24 gate；one-primary-action rule |
| palette 取代 discoverability | 中 | 中 | 新手不知道如何开始 | ledger 永久可见；palette 仅 accelerator |
| Report 被 TUI 重复实现 | 中 | 高 | TUI 出现完整 Evidence 表格/过滤器 | detail depth cap；explicit open/deep link；report ownership |
| no-arg 兼容破坏 | 中 | 高 | pipe 出现 escape 或挂起 | staged rollout；golden non-TTY tests；`--plain` |
| user config 污染项目/泄密 | 低中 | 高 | `.repoevidence/settings.json` 或 connection profile | OS user config only；schema allowlist；security review |
| 多语言布局回归 | 高 | 中 | 中文截断、raw key、action 消失 | catalog parity + width matrix + human copy review |
| Report freshness 无法证明 | 高 | 中高 | UI 根据 mtime 猜 current | versioned manifest decision；legacy unknown |
| scope creep | 高 | 高 | 请求加入 editor/chat/history/cloud | explicit non-goals；每 Phase acceptance boundary |
| 前一轮 uncommitted 基线变化 | 高 | 高 | interactive work 同时改相同 CLI/i18n/report files | 先验收/冻结基线；小阶段；review existing diff ownership |

### 27.2 最大单点风险：可信度

RepoEvidence 的品牌价值来自 evidence。一个视觉成熟但错误显示“最新”的 workspace，比现在的一次性文本更危险，因为持续状态会被用户赋予更高权威。产品应该接受更多 `[??] 无法确认`，直到 provenance 能证明；不要为了让首页“全绿”降低判断门槛。

### 27.3 技术选型反向塑造产品的风险

- Textual 有 command palette，不代表必须采用 palette-first；
- prompt_toolkit 有 prompt/history，不代表产品需要 REPL；
- Rich 有 Panel，不代表每个状态都要卡片化；
- framework spinner 易用，不代表所有任务都该动画；
- CSS 能做复杂 responsive，不代表终端应像 Web GUI。

每个 framework feature 只有在支持已批准的 task flow 时才使用。

### 27.4 维护风险预算

引入 interactive app 后长期需要维护：

- terminal/platform matrix；
- framework upgrade；
- keyboard/focus conventions；
- localization at multiple widths；
- worker/cancellation；
- plain fallback；
- visual/manual acceptance。

如果项目无法承担这项持续预算，应停留在显式、有限 read-only workspace，或选择更轻的 guided CLI，而不是发布一个无人维护的 full-screen app。

## 28. Open Product Questions

以下问题有推荐倾向，但本文不能代替产品负责人决定。

### 28.1 裸命令何时切换

**问题**：`repoevidence` 在 suitable TTY 中是否从第一版 interactive release 就进入 workspace？

**建议**：先显式 `workspace` preview，再 preference opt-in，最后默认切换。

**影响**：决定 backward-compat 风险、文档、用户心智和 rollout 周期。

### 28.2 默认项目 root

**问题**：未给 path 时使用精确 cwd，还是自动建议 Git top-level？

**建议**：唯一明确 Git root 时以其为推荐 root，同时显示 opened-from path 并允许覆盖；monorepo / nested marker 不自动猜。

**影响**：artifact 放置、用户预期、nested project 行为。

### 28.3 Source freshness 证明粒度

**问题**：只用 Git HEAD + dirty/clean 诚实投射，还是增加 versioned source fingerprint/provenance sidecar？

**建议**：MVP 使用 HEAD + dirty/unknown 规则；不要隐式 hash 全仓。后续若 unknown 过多，再独立设计 provenance manifest。

**影响**：准确度、性能、artifact contract 和非 Git 支持。

### 28.4 Report manifest

**问题**：是否接受新增 `.repoevidence/report/manifest.json`，以及其 schema 是否属于 application artifact contract？

**建议**：接受最小、versioned manifest，由 report generation 写入；legacy report 显示 freshness unknown。

**影响**：Report status 可信度、迁移、第三方消费与测试责任。

### 28.5 MySQL configuration UX

**问题**：MVP 是否严格 env-only，还是提供 masked session input/profile？

**建议**：严格 env-only，不在 TUI 输入或持久化 credentials。

**影响**：易用性与显著 security / lifecycle complexity。

### 28.6 External verification confirmation

**问题**：每次 session 第一次 verify 都确认，还是每次动作都确认？

**建议**：每次动作显示 effect preview；同 session 重试可缩短确认，但仍需明确选择，不提供“永久信任”。

**影响**：误操作风险与日常效率。

### 28.7 Report browser integration

**问题**：是否提供 `Open report` 调用 OS browser？

**建议**：提供显式 action；绝不生成后自动打开；失败降级为路径。

**影响**：跨平台、SSH/WSL、安全预期。

### 28.8 Command palette 与快捷键

**问题**：palette 使用何种 key，MVP 是否需要 action-specific shortcuts？

**建议**：Phase 0 测试 Ctrl+K / Ctrl+P 的终端冲突；MVP 只有 palette、help、quit、navigation，最多给 Refresh 一个可发现 shortcut。

**影响**：expert speed、可发现性、shell/terminal key conflict、文档负担。

### 28.9 Minimum terminal size

**问题**：支持到 40 列还是 50/60 列；低于阈值显示 narrow mode 还是要求使用 plain？

**建议**：功能最低 40 列尽力可用，推荐 60+；极窄仍不 crash，并明确提供 plain command。

**影响**：layout complexity、CJK、测试矩阵。

### 28.10 User config dependency

**问题**：直接依赖 `platformdirs`，还是自行实现有限路径 resolver？

**建议**：直接、显式依赖成熟的 platformdirs，并控制 config schema；不要依赖 transitive package。

**影响**：dependency footprint、跨平台正确性、wheel。

### 28.11 Last-used state

**问题**：是否保存 last repository、last selected row 或 activity？

**建议**：MVP 全部不保存；每次从 cwd + artifacts 重建。

**影响**：隐私、误开项目、config scope 与恢复复杂度。

### 28.12 Textual dependency policy

**问题**：Phase 0 通过后，Textual 是正常 dependency 还是 optional extra？

**建议**：如果裸命令最终默认 workspace，则作为正常 dependency、lazy import；optional extra 会让默认产品体验因安装方式不同而分裂。

**影响**：安装大小、startup、support matrix、packaging。

### 28.13 `scan` 是否出现在 workspace

**问题**：workspace 是否暴露 source-only `scan`，还是只提供 guided `inspect`？

**建议**：主界面只提供 `Inspect source`；`Scan source only` 若保留，应作为 advanced palette action并解释不会刷新 Report。现有 CLI `scan` 永久保留。

**影响**：新手心智、Report freshness 与 expert control。

### 28.14 Runtime snapshot 的 freshness copy

**问题**：是否设置产品 TTL 提示“旧”？

**建议**：MVP 不设任意 TTL，只显示 verified timestamp 与 snapshot；用户/环境 policy 未来另议。

**影响**：是否误导用户把时间阈值当数据库真实性。

## 29. Decisions That Must Be Made Before Implementation

### 29.1 Phase 0 开始前的 blocking decisions

产品负责人必须明确批准、否决或修改：

| ID | 必须决定 | 本文推荐 | 若未决定 |
|---|---|---|---|
| D-01 | 产品是 Hybrid CLI + workspace，而不是替换 CLI | 批准 Hybrid | 无法确定入口与边界 |
| D-02 | 主交互采用 Status Ledger + contextual actions | 批准；runbook/palette 仅辅助 | 原型无法收敛 |
| D-03 | 首次启动不自动 inspect / verify / report | 批准全部显式 | 安全与产品预期不明确 |
| D-04 | Textual 是待验证首选，不是既定依赖 | 批准 gated spike | 技术工作可能先于产品决策 |
| D-05 | MVP platform/support matrix | 至少 Linux/macOS/Windows/WSL + 40–120 cols | 无法定义 prototype pass/fail |
| D-06 | 上一轮 uncommitted CLI/Report 改造的基线归属 | 先人工验收并冻结边界 | 新工作会覆盖不稳定改动 |

### 29.2 Phase 1 开始前的 blocking decisions

| ID | 必须决定 | 本文推荐 |
|---|---|---|
| D-07 | `current` 是否允许继续表示“artifact valid” | UI 中不允许；拆 lifecycle/freshness |
| D-08 | dirty worktree 的显示 | 缺 provenance 时 uncertain |
| D-09 | default project root | 明确 Git root 时建议并显示，可覆盖 |
| D-10 | Report manifest 是否进入设计 | 是，最小 versioned application artifact |

### 29.3 Phase 2–4 前的 blocking decisions

| ID | 必须决定 | 本文推荐 |
|---|---|---|
| D-11 | explicit workspace command 名称与 path 语义 | `repoevidence workspace [PATH]` |
| D-12 | Textual dependency/pin | Phase 0 通过后正常依赖 + lazy import |
| D-13 | quit / Ctrl+C / cancellation policy | requested 与 confirmed 分离，不强杀 |
| D-14 | MySQL credentials | env-only MVP |
| D-15 | Verify confirmation | 每次明确 effect preview，不永久信任 |
| D-16 | Report open | 显式 action；无 opener 显示路径 |
| D-17 | 是否在 workspace 暴露 scan | CLI 保留；TUI 主界面不暴露，advanced 可议 |

### 29.4 Default rollout 前的 blocking decisions

| ID | 必须决定 | 本文推荐 |
|---|---|---|
| D-18 | TTY 裸命令默认进入 workspace | staged acceptance 后批准 |
| D-19 | non-TTY exact output / exit contract | 保持当前 plain welcome、exit 0 |
| D-20 | 永久 opt-out | `--plain` + user preference |
| D-21 | minimum terminal size 与 unsupported terminal policy | 40 列尽力、60+ 推荐、plain fallback |
| D-22 | support / framework upgrade cadence | 文档化 tested versions 与定期升级窗口 |

### 29.5 明确无需现在决定

以下问题不应阻塞 MVP，也不应借机扩大 scope：

- 新数据库类型；
- 新 build system / collector；
- cloud sync；
- account / telemetry；
- artifact history archive；
- Web app；
- natural-language commands；
- plugin marketplace；
- 自动修复或 destructive action。

## 30. Acceptance Criteria

以下是整个 interactive product direction 的最终验收清单；每个 Phase 使用其中相关子集。只有有自动测试或人工验收记录支撑时才能勾选。

### 30.1 Product form

- [ ] Existing one-shot CLI remains the primary automation interface.
- [ ] Human TTY users have a persistent workspace that survives operation success/failure until they exit.
- [ ] The workspace is state/action-oriented and contains no chat composer or required slash commands.
- [ ] Command palette is optional and not required to discover the first safe action.
- [ ] No LLM, new collector, new database, cloud, Web SPA or account scope has entered the release.

### 30.2 First-run safety and clarity

- [ ] A first-time user can state what RepoEvidence does from the first screen.
- [ ] The first screen identifies the selected project/root or explains why it cannot.
- [ ] Starting the workspace performs no scan, target-code execution, database connection, reconciliation, report generation or browser open.
- [ ] “Not run” is presented as neutral, not failure.
- [ ] `Inspect source` explains that it does not run target code or connect to MySQL.
- [ ] MySQL verification is clearly optional and external before confirmation.

### 30.3 Status trustworthiness

- [ ] Source, MySQL, Comparison and Report are all represented.
- [ ] Artifact lifecycle, freshness, operation state and domain outcome are separate.
- [ ] A valid artifact from another HEAD is not shown as current.
- [ ] A dirty worktree without sufficient provenance is shown as uncertain.
- [ ] MySQL is labeled as a timestamped snapshot, not a live/current connection.
- [ ] Comparison freshness is based on exact input hashes.
- [ ] Legacy Report freshness is unknown unless a reviewed manifest proves it.
- [ ] Drift detected is not presented as operation failure.
- [ ] Color is never the only status carrier.

### 30.4 Operation UX

- [ ] Fast operations do not flash meaningless animation.
- [ ] Slow operations show only real phases and real elapsed time.
- [ ] There is no fake percentage, artificial sleep or decorative progress.
- [ ] Failure keeps the workspace usable and provides what/why/recovery/detail.
- [ ] Partial result and warning are distinguishable from failure.
- [ ] Only one artifact-producing operation runs at a time in MVP.
- [ ] Cancellation is never claimed before the service confirms it.
- [ ] Completing an operation triggers fresh assessment rather than a UI-only state mutation.
- [ ] Previous valid artifacts are protected from partial overwrite as far as platform semantics allow.

### 30.5 Security

- [ ] No database connection occurs before an explicit Verify MySQL action and confirmation.
- [ ] Environment variable values, password, token and DSN never appear in screen, activity, notification, snapshot or user config.
- [ ] MySQL queries retain existing read-only scope.
- [ ] Reconciliation remains offline.
- [ ] Corrupt artifacts are not automatically deleted.
- [ ] Browser opening is explicit.
- [ ] User preferences never enter target project artifacts.

### 30.6 Interface boundaries

- [ ] CLI and interactive UI call the same application services.
- [ ] No widget calls collectors/verifiers directly.
- [ ] Existing machine JSON schemas, IDs, references, hashes and paths remain compatible.
- [ ] HTML and TUI present the same conclusion from shared results/view models.
- [ ] TUI does not reproduce full Evidence tables that belong in HTML.
- [ ] Closing the TUI does not lose machine results needed for audit.

### 30.7 CLI and non-TTY compatibility

- [ ] All existing subcommands, arguments, exit codes and artifact paths remain compatible.
- [ ] Existing subcommands stay one-shot even in a TTY.
- [ ] Pipe, redirect, CI and `TERM=dumb` never enter alternate screen or wait for input.
- [ ] Bare non-TTY invocation preserves the approved plain welcome and exit code.
- [ ] `--plain` / user plain preference provides a permanent fallback.
- [ ] TUI initialization failure restores terminal state and gives a usable one-shot next step.

### 30.8 Language and configuration

- [ ] Language precedence is explicit flag > env > user config > system locale > English.
- [ ] Chinese and English users receive a natural first screen without mandatory selector.
- [ ] Language changes immediately without restarting operation or mutating machine JSON.
- [ ] Existing Report is not silently regenerated on UI language change.
- [ ] Config uses the OS user directory, a versioned allowlisted schema and atomic write.
- [ ] Config corruption does not block CLI or destroy the file.
- [ ] No credentials, project evidence, last repo or activity are persisted in MVP user config.

### 30.9 Visual and responsive quality

- [ ] 80×24 shows identity, four states, next action and help without required scrolling.
- [ ] 100×30 and 120×40 use extra space for detail, not decorative cards.
- [ ] 40–60 columns retain all core tasks and do not crash.
- [ ] Light, dark, 256-color and `NO_COLOR` are manually reviewed.
- [ ] Focus and selection remain visible without color.
- [ ] No giant ASCII logo, card wall, excessive border, navigation tree or uncontrolled shortcut set exists.
- [ ] CJK paths and labels do not hide the primary action.

### 30.10 Accessibility

- [ ] Every core journey is keyboard-only.
- [ ] Focus order, modal focus restore and context help are predictable.
- [ ] Reduced motion replaces spinner animation with a static running state.
- [ ] Critical events remain available after transient notification disappears.
- [ ] A documented plain workflow exists for screen readers and incompatible terminals.
- [ ] At least one real screen-reader/plain-fallback task is manually tested on the support matrix.

### 30.11 Testing and release readiness

- [ ] Machine contract, application, projection, UI, PTY, localization and accessibility tests pass freshly.
- [ ] Known HEAD mismatch and dirty-worktree freshness regressions are covered.
- [ ] Secret-redaction and no-auto-connect tests are present.
- [ ] Fresh wheel and sdist installs are tested on supported Python/platform combinations.
- [ ] Human visual review covers all four required states in all three candidate-derived flows before final design approval.
- [ ] Snapshot changes receive human review and are not treated as sole UX proof.
- [ ] Each roadmap phase has a dated acceptance record and product-owner gate.
- [ ] The final no-arg TTY default is explicitly approved rather than inferred from implementation.

### 30.12 Definition of product maturity for this phase

本阶段的“成熟”不以 panel 数、动画、快捷键或 framework feature 数衡量，而以以下结果衡量：

- 信息在整个 session 中稳定；
- 操作 effect 可预测；
- 状态能被证据证明；
- 失败可恢复；
- 下一步清楚但不强迫；
- novice 能开始，expert 不被阻碍；
- automation 完全不受 interactive UI 干扰；
- 完整证据仍可在 HTML / JSON 追溯；
- 终端在退出和异常后保持完整可用。

---

## Appendix A — Recommended Decision Snapshot

如果产品负责人希望快速开始评审，本文当前建议可压缩为：

1. 批准 Hybrid CLI + persistent Status Ledger Workspace；
2. 不采用 chat / slash REPL；palette 仅作 expert accelerator；
3. 启动只读，不自动执行任何项目分析或外部连接；
4. Phase 1 先拆分 lifecycle / freshness / operation / outcome；
5. Textual 作为 Phase 0 有条件首选，Rich 保留 plain / one-shot；
6. HTML 继续承担完整阅读，TUI 只做状态、动作、恢复与摘要；
7. 显式 workspace preview 后再决定裸 TTY 默认；
8. user config 独立于 `.repoevidence/`，MVP 不保存 credentials 或 last repo；
9. MySQL env-only，显式确认；
10. 每阶段人工验收后再继续。

## Appendix B — Terminology

| 术语 | 本文含义 |
|---|---|
| Machine truth | 由 versioned schema / artifact 表达、可供程序稳定消费的事实 |
| Artifact lifecycle | artifact 是否缺失、有效、失败、损坏或不支持 |
| Freshness | artifact 与当前选定输入是否有可证明关系 |
| Snapshot | 某个时间点采集的结果，不代表持续实时状态 |
| Domain outcome | 成功完成计算后得到的 matched/drift/source-only 等业务结论 |
| Operation state | 本次用户动作的 running/succeeded/failed/cancelled 状态 |
| Projection | 从 machine/application state 派生、但不包含最终 presentation copy 的视图数据 |
| Workspace | 长期存在的 terminal session，不等于 daemon 或持久后台服务 |
| Plain path | 无 full-screen、无输入等待、可用于 pipe/CI/accessibility 的线性 CLI 行为 |
| Contextual action | 根据所选对象、状态和 prerequisite 提供的明确动作 |

## Appendix C — Review Checklist for Product Owner

评审时建议按以下顺序，而不是先讨论颜色或快捷键：

1. RepoEvidence 的产品定位和四界面分工是否正确；
2. startup safety 与 project-root 行为是否正确；
3. lifecycle / freshness / operation / outcome 的可信状态模型是否被接受；
4. Status Ledger 是否符合用户任务；
5. HTML 与 TUI 边界是否足够克制；
6. MySQL confirmation 与 env-only 是否可接受；
7. Textual Phase 0 gate 和 support matrix 是否可承担；
8. user config scope 是否恰当；
9. staged no-arg migration 是否可接受；
10. roadmap gate、风险和最终 Acceptance Criteria 是否足够。

只有上述问题得到答复后，才值得讨论最终 accent 色、palette shortcut、border style 或 exact animation delay。
