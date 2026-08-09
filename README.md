# RepoEvidence

English | [简体中文](README.zh-CN.md)

## What RepoEvidence is

RepoEvidence is a local-first, evidence-backed repository understanding and
runtime verification tool. It helps you inspect what source code declares,
verify MySQL runtime metadata only after you explicitly ask, compare source
migrations with runtime history, trace conclusions back to Evidence, and
generate an offline HTML Report.

The analysis is deterministic and does not execute the target repository. It
keeps source declarations and runtime observations separate, so a conclusion
can be read together with its evidence, status, snapshot, and limits.

```text
repository → source inspection → Evidence / Fact → report
                              ↘ runtime verification / reconciliation
```

## Quick Start

RepoEvidence requires Python 3.12 or newer. For a normal human-first
workflow:

```bash
pipx install repoevidence

cd your-project
repoevidence
```

In a suitable interactive TTY, RepoEvidence opens a local Interactive
Workspace. You can inspect source, explicitly verify MySQL when needed,
compare source and runtime evidence, and open the complete report.

The equivalent explicit entry point is:

```bash
repoevidence workspace .
```

Starting the Workspace does not scan source, run the target project, connect
to MySQL, or modify a database. Startup only reads project identity, Git
metadata, existing RepoEvidence artifacts, user settings, and terminal
capabilities.

## Interactive Workspace

The Workspace is for people using RepoEvidence day to day. It presents the
current project state and the next safe action instead of requiring you to
remember a command sequence.

| Area | What it shows |
| --- | --- |
| Project identity | Repository name, location, Git branch/commit, and known project context. |
| Source | Whether source inspection has been performed, what snapshot it covers, and what it found. |
| MySQL Runtime | Whether explicit runtime metadata verification is available, current, stale, uncertain, or failed. |
| Comparison | Whether source/runtime evidence can be reconciled and what differences are known. |
| Report | Whether the offline report is present, fresh, stale, or needs a language/report refresh. |

Select a ledger item to read its human explanation, technical details, and
contextual actions. Actions change with the state: inspect source, verify
MySQL after an effect preview, reconcile existing artifacts offline, refresh
the report, or open the report. The Workspace does not silently perform an
upstream operation just because an artifact is missing or old.

Settings provides immediate English / 简体中文 switching, theme and
interaction preferences, and reduced-motion behavior. A language preference
can be persisted for later sessions. Recent activity shows the result of
operations and failures so that recovery remains visible. Help and keyboard
shortcuts are available in the Workspace, but the visible ledger and actions
are the primary interface.

## What RepoEvidence checks

Source inspection reads repository metadata, common project files, Spring MVC
declarations, Maven project declarations, and Flyway migration files. It does
not run Maven, Flyway, SQL, tests, or code from the target repository.

When explicitly requested, MySQL verification reads runtime schema metadata,
schema summaries, indexes, constraints, and Flyway history. It does not read
business rows. Reconciliation currently compares the source Flyway evidence
with the runtime Flyway history; it is not a claim about the overall health of
the project.

## Runtime verification safety

MySQL verification is an explicit opt-in operation. It happens only after a
user action, using environment configuration and fixed read-only metadata
queries. The Workspace shows an effect preview before the connection is made.
RepoEvidence does not modify the database and does not store database
credentials in its user settings.

Configure a least-privilege account through these environment variables; do
not put a real password in a command example or source file:

```text
REPOEVIDENCE_MYSQL_HOST
REPOEVIDENCE_MYSQL_PORT
REPOEVIDENCE_MYSQL_USER
REPOEVIDENCE_MYSQL_PASSWORD
REPOEVIDENCE_MYSQL_DATABASE
```

Only `repoevidence verify mysql .` and its corresponding Workspace action
connect to MySQL. Source inspection, report generation, and reconciliation
remain offline.

## One-shot CLI and automation

One-shot commands do not enter the TUI. They are the stable entry points for
automation, CI, scripts, agents, and advanced users:

| Command | Meaning |
| --- | --- |
| `repoevidence inspect .` | Safe source inspection plus report generation. |
| `repoevidence scan .` | Source-only machine artifact generation. |
| `repoevidence verify mysql .` | Explicit runtime metadata verification. |
| `repoevidence reconcile .` | Offline source/runtime comparison. |
| `repoevidence report .` | Generate or refresh the offline HTML report from existing artifacts. |

`inspect` is the convenient one-shot path when you want a source snapshot and
the report together. `scan`, `verify`, `reconcile`, and `report` remain
separate so an automation pipeline can choose exactly which operation is
allowed.

## HTML Report

The HTML Report is offline and self-contained. It puts the human conclusion
first, then provides coverage, freshness, limits, next actions, technical
findings, and audit traceability across source, Maven, Spring, Flyway, MySQL,
and reconciliation evidence. Fact and Evidence links preserve the path from
an interpretation back to the observed value, and provenance records which
artifacts the report consumed.

The Workspace is for current state, actions, and recovery. The HTML Report is
for complete reading, technical evidence, and an audit trail. Report
generation never starts a server, accesses the network, or runs upstream
operations automatically.

## Machine-readable artifacts

RepoEvidence writes these local artifacts when their operations are run:

```text
.repoevidence/evidence.json
.repoevidence/verification/mysql.json
.repoevidence/reconciliation.json
.repoevidence/report/index.html
.repoevidence/report/manifest.json
```

`evidence.json` is the source inspection artifact. `mysql.json` contains the
explicit runtime verification result, and `reconciliation.json` contains the
offline comparison result. `index.html` is the human report. The report
`manifest.json` records report provenance and freshness inputs; it is not a
replacement for the Evidence machine schema.

## Status confidence and snapshots

RepoEvidence distinguishes between:

- not yet checked;
- checked for a known snapshot;
- changed or stale since that snapshot;
- unable to confirm freshness; and
- an operation failure.

An existing artifact does not necessarily describe the current source tree.
Runtime verification is a snapshot of metadata, not live database monitoring.
Comparison reports only the source/runtime evidence differences that
RepoEvidence currently supports; it should not be read as an overall project
health score.

## `--plain`, non-TTY, and CI

In an interactive TTY, bare `repoevidence` enters the Workspace. When stdin or
stdout is redirected, piped, used by CI, paired with `TERM=dumb`, or otherwise
non-interactive, bare `repoevidence` does not start the full-screen TUI. It
uses the non-blocking plain welcome path and exits instead of waiting for
input.

Use `--plain` when you want to select plain behavior explicitly:

```bash
repoevidence --plain
repoevidence --plain workspace .
```

All one-shot commands are plain command-line operations regardless of whether
the terminal is interactive, so a CI job will not unexpectedly switch to a
full-screen UI.

## Language

In the Workspace, open Settings to switch between English and Simplified
Chinese immediately. The selected preference can be persisted for future
sessions.

For one-shot commands and automation, use:

```bash
repoevidence --lang en inspect .
repoevidence --lang zh-CN inspect .
```

Language resolution follows this order:

```text
--lang
> REPOEVIDENCE_LANG
> user config
> system locale
> English fallback
```

The user configuration is stored in the platform-standard location selected
by `platformdirs`; its path is not tied to WSL. Command names, option names,
environment variable names, JSON keys, schema versions, IDs, status values,
reconciliation kinds, and error codes remain stable English machine-facing
contracts.

## Installation and supported environments

`pipx` is convenient for an isolated command-line installation:

```bash
pipx install repoevidence
```

The package also supports a normal virtual environment:

```bash
python -m pip install repoevidence
```

Runtime dependencies are declared directly by the package, including Textual,
platformdirs, Rich, and the existing evidence/runtime dependencies. A fresh
wheel therefore includes the Interactive Workspace, localization resources,
report code, and runtime source without relying on development-only
transitive dependencies.

RepoEvidence is designed for Linux, macOS, Windows, and WSL. Current
interactive release validation has been performed primarily on Linux/WSL;
native Windows and macOS should not be interpreted as fully manually tested
by this release.

## Release validation limits

- v0.2.0 interactive release validation was performed primarily on Linux/WSL;
  native Windows/macOS interactive manual validation remains pending.
- A real MySQL successful interactive end-to-end journey was not completed
  before this release. Fixture, headless, failure-recovery, and machine
  contract tests cover the current path.

## Security and trust model

Repositories, databases, and stored artifacts are treated as untrusted input.
Static inspection, report generation, and reconciliation do not execute target
code. Report HTML escapes artifact-derived text and redacts secret-like
structured fields. Passwords are not accepted as CLI arguments, and secrets
are not intended to enter artifacts or reports.

RepoEvidence is not an AI assistant, health scanner, automatic fixer, or
database monitoring service. It records what was observed, what was inferred,
what was explicitly verified, and what could not be confirmed.

## Development

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check .
python -m build
python -m twine check dist/*
```

The package requires Python `>=3.12`. CI runs tests, Ruff, distribution
builds, and distribution metadata checks without requiring a live database.

## License

RepoEvidence is licensed under the Apache License 2.0.
