# RepoEvidence Interactive Terminal Implementation Report

日期：2026-08-09  
实现基线：当前 working tree 中上一轮 CLI / Report UX 改造及本轮新增 Interactive Terminal implementation。  
状态：实现完成，等待产品负责人进行人工视觉验收；没有 commit、push、tag 或发布。

## 1. 实际实现的 architecture

本轮把 RepoEvidence 实现为 hybrid developer tool：

- 人类用户：Textual Persistent Interactive Terminal Workspace。
- 自动化与脚本：原有 one-shot CLI，继续输出人类可读 plain/Rich presentation。
- 机器：原有 Evidence、Fact、VerificationResult、ReconciliationResult 等 JSON artifact。
- 深度阅读：现有 HTML Report，新增 application-level report manifest 作为 freshness 投影输入。

代码分层如下：

```text
CLI / TTY routing
  ├─ plain / Rich terminal presenter
  └─ lazy interactive.run_workspace
       └─ Textual RepoEvidenceApp
            └─ WorkspaceProjection
                 ├─ project_context (read-only discovery)
                 ├─ assessment (read-only artifact parsing)
                 ├─ workspace status projection
                 └─ application operation services
                      └─ existing scanner / verifier / reconciler / report generator
```

Widget 不直接调用 collector、verifier 或数据库连接器。Interactive action 通过 `WorkspaceOperationService` 调用既有 application service；Textual Worker 类型停留在 presentation layer。

## 2. Textual Phase 0 结果

Phase 0 在当前 WSL/Linux、Python 3.12.3、真实项目 virtualenv 中通过。临时 spike 位于 `/tmp/repoevidence-interactive-phase0/`，验证后已移除。

实际验证项目：

- CJK 文案与路径显示。
- 40、60、80、100、120 columns 的 headless layout。
- resize、focus、modal、Select。
- 100ms / 1s / 5s 受控 worker，以及 worker failure。
- `NO_COLOR`、headless test harness、lazy import。
- Unix PTY 启动、`q` 退出和 TTY restore。

结论：Textual 是当前环境的正式 runtime framework，未发现 architecture-level blocker。此次通过只代表 WSL/Linux 当前实现环境；原生 Windows/ConPTY、Windows Terminal、macOS、SSH/tmux、screen reader 仍需人工验收。

## 3. 新增 dependency

`pyproject.toml` 显式声明：

- `textual>=8.2,<9`；Phase 0 实测 `8.2.8`。
- `platformdirs>=4,<5`；Phase 0 实测 `4.11.1`。
- `rich>=13.7` 保持显式声明，用于 one-shot、plain/non-TTY 和 fallback rendering。

Textual 仅由 `repoevidence.interactive` lazy import。已有 one-shot CLI、pipe、redirect、CI、`TERM=dumb`、`--plain` 和 `interaction=plain` 不初始化 Textual。

## 4. Workspace information architecture

首页不是 dashboard/card wall，而是五个稳定区域：

1. Project Header：RepoEvidence、repository name、Git branch/short commit/dirty state、Project root、Opened from。
2. Status Ledger：Source、MySQL Runtime、Comparison、Report 四行长期存在的对象。
3. Context Detail：当前选中对象的含义、原因、provenance、时间、artifact path、限制和上下文动作。
4. Recent Activity：当前 session 最多保留 5 条事件，不写入 target repository。
5. Footer / Status Line：Help、Settings、Quit 和少量 keyboard accelerator。

核心操作从可见 Button/List/Select 进入；键盘和 mouse 都是可用路径，快捷键只是加速器。

## 5. Status projection

`WorkspaceProjection` 是 presentation-neutral projection，不属于 machine artifact schema。它包含 `WorkspaceCheck`、primary/secondary action、selected item 和 active operation/phase。

每个 `WorkspaceCheck` 记录：

- artifact lifecycle；
- freshness / provenance；
- operation state；
- domain outcome；
- observed timestamp；
- reason codes / provenance summary；
- artifact path；
- available actions；
- safety level。

启动时只从 `ProjectContext`、`assess_repository`、report manifest 和 user settings 构建 projection，不执行 scan、inspect、verify、reconcile、report generation 或 browser open。

## 6. lifecycle / freshness / operation / outcome

四个维度在 `src/repoevidence/status.py` 中独立表达：

- `ArtifactLifecycle`：missing、valid、failed、corrupt、unsupported。
- `Freshness`：not_applicable、fresh、stale、uncertain、unknown。
- `OperationState`：idle、running、cancel_requested、succeeded、failed、partial。
- `DomainOutcome`：not_available、source_only、matched、drift_detected、runtime_failed、ambiguous。

关键信任规则：

- stored HEAD 与当前 HEAD 不同一定是 stale。
- dirty worktree 没有足够 provenance 时是 uncertain；不会用绿色状态掩盖它。
- 同一 session 刚成功 inspect 会记录 project root、HEAD 和 status fingerprint；clean worktree 可表达本次会话刚检查并对应当前提交，dirty worktree 即使 status fingerprint 未变化也只显示 uncertain，同时保留“本次会话已检查”限定。
- VerificationResult 含 errors 只能显示 failed/runtime_failed，不能显示 verified。
- Comparison 只有 recorded static/runtime artifact hashes 都精确匹配时才是 current input；drift 是成功操作的 domain outcome，不是 operation failure。
- legacy report 没有 manifest 时 freshness 是 unknown；不使用 mtime 猜测。

Report manifest 位于 `.repoevidence/report/manifest.json`，schema version 为 1，记录 generator version、generated_at、language、consumed artifact paths/hashes、output path、output SHA-256 和 renderer format version。读取已有 manifest 时只接受固定 artifact paths 和固定 report output path；output hash 变化会使 report stale。

## 7. First-run experience

空项目首屏显示：

- Source：尚未检查。
- MySQL：尚未验证 · 可选。
- Comparison：尚不可比较。
- Report：尚无报告。

Primary action 是“Inspect source / 检查源码”。首屏说明只检查源码和项目配置，不运行项目，不连接数据库；没有使用 Evidence/Fact 理论作为第一句，也没有承诺自动修复或自动执行目标项目。

## 8. Operations

稳定 action IDs 保持英文：

`source.inspect`、`source.scan_only`、`runtime.verify_mysql`、`comparison.reconcile`、`report.generate`、`report.refresh`、`report.open`、`view.*`、`settings.*`、`help.open`、`app.quit`。

已接入的真实操作：

- Inspect Source：调用既有 `inspect_repository`，完成 source scan 和现有 report generation；完成后重新读取 projection。
- Generate / Refresh Report：调用既有 `generate_report`，写 report 和 manifest。
- Open Report：只在用户显式选择时调用 `webbrowser.open`；失败时保留完整 HTML path 并在 activity 显示 fallback。
- Verify MySQL：只在 effect preview 的 Confirm 后调用既有 verifier。
- Compare：调用既有离线 reconciler，不建立数据库连接。

`OperationEvent` 是 application/presentation seam，不进入 machine JSON。safe metadata 经过白名单/敏感键过滤，不包含 password、env value、完整 DSN、未 redacted exception。`OperationRunner` 提供 single-flight；同一 workspace 不允许两个 artifact-producing operation 同时运行。

操作反馈使用真实状态：短操作不强行显示 running 行；超过约 350ms 才显示真实 elapsed，完成/失败使用 runner measured elapsed。没有 fake percentage、fake collector count、production sleep 或 fake cancellation。运行期间退出会被保护，避免 worker 尚未完成时破坏 artifact integrity。

## 9. MySQL safety

MVP 继续 env-only：不提供 password input、saved DB profile、`.env` writer 或 credential storage。Confirmation modal 只显示每个变量 `configured` / `missing`，不显示任何 value。

Effect preview 明确说明：

- 会使用当前进程环境变量连接 MySQL。
- 只读取 schema metadata 与 Flyway history。
- 不读取业务记录。
- 不修改数据库。
- 不保存密码。

默认 focus 在 Cancel；只有用户明确按 Confirm Verify MySQL 后才启动 connection operation。失败留在 app 内，保留本地化的发生原因、恢复动作、technical details 和 Retry/Help 入口，不退出整个 app；domain failure 不会被活动记录误报为 completed。

## 10. Language and settings

语言优先级为：explicit `--lang` > `REPOEVIDENCE_LANG` > user config > system locale > English。中文系统 locale 首次 workspace 直接中文，不显示 mandatory startup language wizard。

Settings 是首页可见 action，使用真实 Select/Checkbox：

- Interface language / 界面语言：简体中文、English。
- Theme：Auto、Dark、Light。
- Interaction：Auto、Workspace、Plain。
- Reduced motion / 减少动效。

语言切换立即重绘 workspace、ledger、detail、activity、settings、help labels；不会重新执行 operation，不会偷偷重新生成 HTML Report。Report manifest 的 language mismatch 显示已有报告语言不同，并提供中文刷新方向。

user-level `settings.json` 使用 `platformdirs`：Linux 走 XDG config directory，Windows 使用 APPDATA，macOS 使用 Application Support。只保存 schema_version、language、theme、interaction、reduced_motion。corrupt/unsupported config 回退默认且不删除原文件。

## 11. Visual system

视觉语言是 restrained evidence ledger：

- teal/cyan-green：primary accent / running。
- green：success。
- amber：attention / stale。
- red：failure。
- cool blue：information。
- slate/gray：muted metadata。

颜色不是唯一状态依据。状态始终带 ASCII token：`[OK]`、`[--]`、`[~~]`、`[!!]`、`[??]`、运行中 `[>>]`，并有清晰文字结论。没有 giant logo、emoji、Nerd Font、彩虹色或 KPI card wall。Dark/Light、256-color、`NO_COLOR` 和 selected focus marker 有独立路径。真实 PTY 下 `NO_COLOR=1` 不再输出非默认颜色序列。

## 12. Responsive behavior

- 120×40：ledger 与 detail split，底部保留少量 activity。
- 100×30：split 可用；CJK/空间紧张时可退为 compact single-column。
- 80×24：核心 identity、四个 ledger rows、primary action、footer/help 均成立。
- 40–60 columns：single-column，隐藏次要 detail/activity metadata，保留状态、结论和下一动作。

当前 CSS 以 narrow/very-narrow class 控制布局，没有横向滚动 workspace；headless 40/60/80/100/120 测试通过，极窄窗口不 crash。

## 13. Non-TTY and automation

以下情况永远不进入 full-screen TUI：stdout redirect、stdin non-TTY、pipe、CI、`TERM=dumb`、`--plain`、`interaction=plain`。裸命令在这些情况下显示 approved plain welcome 并 exit 0，不等待输入；不发送 alternate screen、live cursor、spinner carriage return 或 input prompt。

现有 `inspect`、`scan`、`verify mysql`、`reconcile`、`report` 子命令仍是 one-shot。machine users 继续读取原有 JSON artifacts；人类文本不是 machine API。

## 14. Accessibility

核心任务可以 keyboard-only 完成：Tab/Shift+Tab、Arrow、Enter、Esc、Ctrl+C、q。首页显示 Help、Settings、Quit，不要求用户先知道快捷键。Textual Button/List/Select/Modal 保留 mouse enhancement。

Reduced motion 使用静态 running text 与真实 elapsed，取消 CSS transition；没有 fake animation。`NO_COLOR` 下仍保留文字和 ASCII status token。

## 15. Machine compatibility

没有修改 Evidence、Fact、Conflict、ScanResult、VerificationResult、ReconciliationResult 的 schema version、IDs、references、status enums、finding kinds、error codes、artifact paths、序列化合同或 one-shot exit semantics。

新增层是独立的：Report Manifest、User Config、Workspace Projection、Operation Event。artifact writer 采用 same-directory temporary file、flush/fsync、atomic replace，避免失败操作用 partial bytes 覆盖旧的有效 JSON；Report manifest 还校验 output hash，避免 HTML 与旧 manifest 的短暂不一致被误报为 fresh。

## 16. Tests

本轮已添加/扩展测试覆盖：

- project root / Git / explicit path / non-Git。
- lifecycle、freshness、dirty uncertain、HEAD stale、verification errors、comparison hash stale、drift outcome。
- report manifest hash/language/legacy/corrupt。
- user config path、allowlist、corrupt fallback、atomic save。
- operation event safety、elapsed、single-flight、service dispatch。
- Textual headless startup/read-only/default focus、row selection/detail、modal/select、language/theme/reduced motion、worker success/failure/recovery、MySQL confirmation、report open fallback、responsive sizes、NO_COLOR。
- non-TTY lazy import 与 CLI routing。

最终 verification 已完成：`.venv/bin/pytest -q` 为 `260 passed in 10.51s`；`.venv/bin/ruff check .` 通过；`git diff --check` 通过；clean `python -m build` 成功生成 `repoevidence-0.1.0.tar.gz` 与 `repoevidence-0.1.0-py3-none-any.whl`；`python -m twine check dist/*` 两个文件均 PASSED。

最终 wheel 隔离环境位于 `/tmp/repoevidence-wheel-final2-RmktS6`：one-shot inspect、non-TTY workspace、bare non-TTY lazy import 均 PASS；真实 wheel PTY workspace exit 0 且 alternate-screen restore FOUND。

## 17. PTY / manual journeys

当前 WSL/Linux 已真实执行：

- `repoevidence workspace .`：进入 workspace、显示 header/ledger/detail/footer，发送 `q` 后退出 0。
- 裸 `repoevidence`：进入同一 workspace，发送 `q` 后退出 0。
- non-TTY subprocess：plain welcome，未加载 `repoevidence.interactive`。
- Textual Phase 0：focus/modal/select/resize/worker/NO_COLOR/TTY restore。

完整人工 journey A–R 的可重复步骤写在 `docs/product/repoevidence-interactive-visual-review.md`。MySQL real connection 未在本环境宣称成功；失败配置和失败 artifact 使用 fixture/headless 测试验证。

## 18. Screenshots / captures

真实 Textual SVG preview 位于：

`/tmp/repoevidence-interactive-review/`

包括：

```text
01-fresh.svg
02-inspect-running.svg
03-inspect-complete.svg
04-language-selector.svg
05-chinese-workspace.svg
06-mysql-failure.svg
07-drift.svg
08-stale.svg
09-narrow.svg
10-no-color.svg
pty-workspace.txt
pty-bare.txt
pty-fresh-wheel.txt
pty-no-color.txt
```

SVG 是 Textual `export_screenshot` 生成的真实 render evidence，不是静态 mockup；PTY capture 含终端控制序列，供检查 alternate-screen、退出和 restore 行为。

## 19. Platform actually tested

实际运行并可声称 tested：

- WSL2/Linux environment。
- Python 3.12.3 virtualenv。
- Textual 8.2.8、platformdirs 4.11.1。
- 当前 shell 的 Unix PTY，以及 Textual headless harness。

## 20. Designed for / pending manual validation

产品设计和跨平台代码目标包括 Linux、WSL、Windows Terminal/Windows、macOS。尚未声称人工验收：

- native Windows / ConPTY / Windows Terminal；
- macOS terminal；
- SSH、tmux、screen；
- screen reader 与完整 accessibility tree；
- 不同字体 fallback、中文宽度差异和 256-color terminal 组合。

这些平台仍有 Rich/plain fallback，不应被报告为当前环境已测试。

## 21. Remaining blockers

没有发现 Textual architecture blocker、machine contract conflict 或安全 blocker。审查发现的 dirty freshness、domain activity、中文 detail、manifest path/output trust、CI routing 和 `NO_COLOR` 问题已修正并加入回归覆盖。

正式发布前仍需：跨平台人工 visual review、真实 terminal 字宽/CJK review、真实 MySQL failure journey 的环境验证。本轮不 bump version、不发布。

## 22. Known UX issues

- 当前 workspace 的 operation phase 多数服务只提供 `execute`，因此不会伪造更细的 phase；后续服务若提供安全 phase 可直接接入 OperationEvent。
- Activity 只保留本 session 最近 5 条，不是永久审计 log；深度 audit trace 仍在 HTML Report 和 JSON artifact。
- Textual 的 border glyph 会随终端字体显示不同；状态语义不依赖这些 glyph。
- Command Palette 保留为可选 accelerator，当前 visible action 已覆盖核心流程，不要求使用 palette。

## 23. Git diff summary

上一轮 baseline 的 tracked changes 保留在 working tree；本轮新增主要包括：

- project context、status projection、report manifest、atomic writer、user config；
- lazy Textual interactive package、workspace app、operation seam；
- CLI workspace / bare-TTY routing / plain fallback；
- 状态、operation、manifest、config、interactive、CLI regression tests；
- 本报告、visual review guide、framework architecture note；
- README 三份文档的 workspace 入口说明。

交付时 tracked diff stat 为 `12 files changed, 1553 insertions(+), 274 deletions(-)`；本轮新增 untracked 主要是 interactive/application/status/config/manifest source、对应 tests、architecture/product/report docs 和 `dist/` build artifacts。上一轮 baseline 的 README、CLI、i18n、reporting 与既有 tests 修改保持原样；不执行 commit、push、tag、publish。
