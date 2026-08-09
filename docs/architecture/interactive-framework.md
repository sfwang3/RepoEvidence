# Interactive framework decision

## Decision

RepoEvidence uses Textual for the persistent human workspace and keeps Rich for one-shot and plain rendering. Textual is imported only by `repoevidence.interactive` and is never initialized for an existing subcommand, a pipe, a redirect, CI, `TERM=dumb`, `--plain`, or `interaction=plain`.

The tested runtime range is:

- `textual>=8.2,<9` (Phase 0 tested with 8.2.8)
- `platformdirs>=4,<5` (Phase 0 tested with 4.11.1)

The range is intentionally bounded to the tested major versions. It is not a promise that every future release is compatible.

## Phase 0 evidence

The feasibility spike ran in the repository’s Python 3.12.3 virtual environment and used fake state/fake operations only. It verified:

- CJK labels and paths remain renderable;
- 40, 60, 80, 100, and 120 column headless layouts survive;
- headless resize, focus, modal dismissal, and Select interaction;
- controlled background worker success and failure while the app remains usable;
- `NO_COLOR` route and visible non-color semantics;
- Textual headless test harness;
- importing `repoevidence.cli` does not import Textual;
- a real Unix PTY launch, `q` quit, and terminal restoration.

Result: **pass for current WSL/Linux implementation work**.

## Scope of the result

This is not a cross-platform manual acceptance claim. macOS, native Windows/ConPTY, Windows Terminal, SSH/tmux variants, and screen-reader behavior remain designed-for and pending manual validation. The production implementation must keep the Rich/plain fallback so those environments have a recoverable path if Textual initialization or rendering is unsuitable.

## Visual direction

The terminal signature is a stable evidence ledger: restrained teal accent, semantic success/attention/failure/info roles, neutral surfaces, visible focus marker, ASCII status tokens, and explicit copy. It intentionally avoids a giant logo, emoji/Nerd Font dependency, card wall, decorative progress, and color-only state encoding.
