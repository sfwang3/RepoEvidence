# RepoEvidence Interactive Visual Review Guide

这份文档用于产品负责人在当前 WSL/Linux 环境进行人工验收。它不把 headless test 当作视觉验收替代品。

## 如何启动

在仓库根目录、已安装当前 virtualenv 的情况下：

```bash
.venv/bin/repoevidence
```

显式入口：

```bash
.venv/bin/repoevidence workspace .
```

退出使用首页可见的 `Quit`，或使用 `q` / `Ctrl+C`。执行期间 `q` / `Ctrl+C` 会保护正在写 artifact 的 operation，不会伪装成已经取消。

本轮真实验证的是 WSL/Linux PTY。原生 Windows、Windows Terminal、macOS、SSH/tmux、screen reader 需要在对应环境重新验收。

## Fresh state 怎么构造

使用一个不会污染项目的临时目录：

```bash
REVIEW_ROOT="$(mktemp -d)"
mkdir -p "$REVIEW_ROOT/fresh"
cd "$REVIEW_ROOT/fresh"
/home/wangsf/projects/personal/RepoEvidence/.venv/bin/repoevidence workspace .
```

预期首屏：

- Source：尚未检查；
- MySQL：尚未验证 · 可选；
- Comparison：尚不可比较；
- Report：尚无报告；
- primary action：检查源码；
- 明确说明不会运行项目、不会连接数据库。

启动前不应出现 `.repoevidence`，启动本身不创建 artifact。

## Inspect 怎么测

在 fresh workspace 选择 `检查源码 / Inspect source`：

1. 观察 Source row 进入 `[>>]` 或 running 状态。
2. operation 超过约 350ms 时观察 Recent activity 出现真实 elapsed；不应出现伪造百分比或 collector count。
3. 完成后 Source 显示本次 session 已检查，Report 显示生成状态和 manifest 信息。
4. 观察 activity 中的 completed 事件。
5. 选择 Source row，检查 detail 中的原因、时间、artifact path 和可用动作。
6. 确认没有启动目标项目、Maven、测试或数据库连接。

同一 session 内修改一个源码文件，再重新观察状态：如果没有新的 inspect，状态不能继续无条件声称 fresh/current；dirty provenance 不足时应是 uncertain。

## MySQL failure 怎么测

不需要真实密码。确认当前进程没有设置 MySQL 环境变量：

```bash
unset REPOEVIDENCE_MYSQL_HOST REPOEVIDENCE_MYSQL_PORT \
  REPOEVIDENCE_MYSQL_USER REPOEVIDENCE_MYSQL_PASSWORD \
  REPOEVIDENCE_MYSQL_DATABASE
```

在 workspace 选择 `MySQL Runtime`，再选择可见的 `Verify MySQL`：

- modal 默认 focus 应在 Cancel，而不是确认按钮；
- HOST、PORT、USER、PASSWORD、DATABASE 只显示 configured/missing；
- 不显示任何环境变量 value；
- effect preview 应说明只读 schema metadata/Flyway history，不读业务记录、不修改数据库、不保存密码。

先点 Cancel：不应有 connector call，也不应写 verification artifact。重新打开 modal 后明确点 `Confirm Verify MySQL`：失败应留在 app 内，显示恢复方向和 technical type，不退出整个 workspace。

也可以用一个不可达的测试 host 验证 connection failure，但不要把真实密码写入命令行、capture 或截图。

## Language 怎么切

首页点击可见 `Settings`：

1. 打开真实 `Interface language / 界面语言` Select。
2. 选择 `简体中文`。
3. 检查当前 workspace、ledger、detail、activity、Settings labels 立即变为中文。
4. 返回首页，不应重新执行 inspect/verify。
5. 重新启动 workspace，检查 user config 保留语言偏好。
6. 选择 English，确认再次立即重绘。

语言优先级验收：显式 `--lang` 应覆盖 `REPOEVIDENCE_LANG` 和 user config；没有显式语言时中文 system locale 应首选中文。切换 workspace 语言不能偷偷覆盖已有 HTML Report；如果 manifest language 不同，应显示已有报告语言和“按当前语言刷新”的 action。

## Drift fixture 怎么看

推荐使用已生成的 screenshot：

```text
/tmp/repoevidence-interactive-review/07-drift.svg
```

或者使用已有 CLI fixture 先产生 source artifact，再写入一个输入 hash 匹配的 `ReconciliationResult`，其中 `summary.drift_detected=true`。选择 Comparison row，预期：

- row token 是成功/当前输入语义，不是 `[!!]` operation failure；
- detail 的 domain outcome 是 Drift detected / 发现差异；
- available actions 包含查看 finding、查看 comparison、重新比较；
- activity 可以写“comparison found drift”，但不写“operation failed”。

## Stale fixture 怎么看

先构造 source + runtime + reconciliation，并记录两个输入 artifact 的 hash。随后只修改 runtime artifact 的 bytes，不重写 reconciliation。重新启动 workspace 或刷新状态，选择 Comparison：

- 应显示 stale / 输入已变化；
- reason 应包含 `input_hash_mismatch` 或 upstream stale；
- 不应把旧比较结果当作对应当前输入；
- 不应删除任何 artifact。

可直接查看：

```text
/tmp/repoevidence-interactive-review/08-stale.svg
```

## Narrow mode 怎么看

调整 terminal 到 40、60、80、100、120 columns，至少检查：

- 40–60：single-column，不出现横向滚动；
- 80×24：Project identity、Source、MySQL、Comparison、Report、primary action、footer/help 同时可理解；
- 100×30 / 120×40：detail 有额外空间，但没有变成 card wall；
- CJK 文案不因布局 crash；
- 极窄时 secondary metadata 可以隐藏，但 status、结论、下一动作仍存在。

预览：

```text
/tmp/repoevidence-interactive-review/09-narrow.svg
```

## NO_COLOR 怎么看

```bash
NO_COLOR=1 /home/wangsf/projects/personal/RepoEvidence/.venv/bin/repoevidence workspace .
```

检查：

- 不依赖颜色才能区分状态；
- `[OK]`、`[--]`、`[~~]`、`[!!]`、`[??]` 和文字结论仍然可读；
- focus、primary action、failure detail 仍能被识别；
- 不输出彩色 ANSI 作为必要语义。

当前实现会保留终端默认色的 reset 序列，但真实 PTY 捕获中不再出现非默认前景/背景颜色序列；`[OK]` 等 token 和文字是独立语义。

预览：

```text
/tmp/repoevidence-interactive-review/10-no-color.svg
```

## HTML 怎么打开

Interactive 不会在生成 report 后自动打开浏览器。完成 Inspect 或 Generate/Refresh Report 后，在 Report row 选择明确的 `Open report` action。

浏览器 integration 成功时 activity 应说明已打开；integration 失败时 workspace 仍保持成功，activity/detail 应显示完整 path，例如：

```text
.repoevidence/report/index.html
```

one-shot fallback：

```bash
.venv/bin/repoevidence report .
```

Report 深度阅读仍负责 tables、Evidence、Fact、provenance 和 audit traceability；Terminal workspace 只显示当前状态、恢复路径和下一动作。

## PTY capture / SVG review files

本轮真实生成：

```text
/tmp/repoevidence-interactive-review/01-fresh.svg
/tmp/repoevidence-interactive-review/02-inspect-running.svg
/tmp/repoevidence-interactive-review/03-inspect-complete.svg
/tmp/repoevidence-interactive-review/04-language-selector.svg
/tmp/repoevidence-interactive-review/05-chinese-workspace.svg
/tmp/repoevidence-interactive-review/06-mysql-failure.svg
/tmp/repoevidence-interactive-review/07-drift.svg
/tmp/repoevidence-interactive-review/08-stale.svg
/tmp/repoevidence-interactive-review/09-narrow.svg
/tmp/repoevidence-interactive-review/10-no-color.svg
/tmp/repoevidence-interactive-review/pty-workspace.txt
/tmp/repoevidence-interactive-review/pty-bare.txt
/tmp/repoevidence-interactive-review/pty-fresh-wheel.txt
/tmp/repoevidence-interactive-review/pty-no-color.txt
```

SVG 是 Textual screenshot export；PTY capture 用于检查 alternate screen、真实输入和终端恢复。

## 人工验收 checklist

### A–R journey

- [ ] A. fresh repository：首屏说明用途，四项 ledger 全部存在。
- [ ] B. inspect running：真实 running state / phase / elapsed 可见。
- [ ] C. inspect completed：Source 与 Report 状态更新，activity 保留结果。
- [ ] D. language selector：从 visible Settings 进入真实 Select。
- [ ] E. 中文 workspace：CJK labels、detail、footer、activity 正常。
- [ ] F. MySQL missing config：只显示 configured/missing，默认不误触确认。
- [ ] G. MySQL failure：失败留在 app，有原因、恢复动作和 technical details。
- [ ] H. comparison matched：显示 matched，而不是泛化为 healthy。
- [ ] I. comparison drift：drift 是 domain outcome，不是 operation failure。
- [ ] J. stale comparison：输入 hash 变化后显示 stale。
- [ ] K. report refresh：显式 refresh，不能语言切换后偷偷生成。
- [ ] L. report open fallback：浏览器失败仍显示完整 path。
- [ ] M. 40–60 columns：single-column、无 crash、保留核心动作。
- [ ] N. 80×24：核心体验无需滚动成立。
- [ ] O. NO_COLOR：ASCII token 与文字仍完整。
- [ ] P. non-TTY：plain welcome、exit 0、不等待、不初始化 Textual。
- [ ] Q. Ctrl+C：idle 时退出；operation 时保护 artifact integrity。
- [ ] R. normal quit：可见 Quit 与 `q` 都能正常退出、终端恢复。

### Trust and safety

- [ ] Startup 没有 scan、inspect、verify、reconcile、report generation、browser open、target code execution 或 artifact mutation。
- [ ] MySQL 连接只发生在显式 Verify + Confirm 之后。
- [ ] password、DSN、环境变量 value 不进入 UI、activity、error、snapshot、log 或 OperationEvent。
- [ ] dirty / stale / legacy unknown 不被渲染为 fresh/current。
- [ ] 旧有效 artifact 在失败 operation 后仍保留，未出现 partial overwrite。
- [ ] 现有 one-shot CLI、machine JSON 和 HTML Report contract 没有回归。

### Platform note

- [ ] 当前 WSL/Linux PTY：已实际验证。
- [ ] Native Windows/Windows Terminal、macOS、SSH/tmux、screen reader：在对应环境单独复核，并记录为 tested 或 pending，不混写。
