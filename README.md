# RepoEvidence

RepoEvidence is a deterministic, LLM-free engine for understanding software repositories with evidence you can inspect and verify.

It separates what a repository declares from what runtime verification observes:

```text
repository → collectors → Evidence / Fact → JSON
                                      ↘ Verification / Reconciliation
```

Evidence preserves the original observation. A Fact is a structured interpretation with an explicit status: `declared`, `inferred`, `verified`, or `conflicted`. Runtime verification is opt-in, and reconciliation reports cross-artifact drift without pretending that static source evidence and runtime observations are the same thing.

## Quick start

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

### Offline HTML report

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

## ChargeSafe example

ChargeSafe was used as a real acceptance case, but it is not required to use RepoEvidence and is not bundled with the package. The evidence showed a repository/runtime Flyway drift:

```text
Repository: V1–V6
Runtime:    Baseline 0 + V1–V9
Result:     runtime-only V7 / V8 / V9
```

The generated reconciliation kept the runtime references for V7, V8, and V9 and did not invent source references. No database credentials or connection configuration are part of this example.

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

## License

RepoEvidence is licensed under the Apache License 2.0.
