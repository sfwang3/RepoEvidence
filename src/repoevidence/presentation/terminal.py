"""Adaptive terminal presentation with equivalent TTY and plain semantics."""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, TextIO

from rich.console import Console
from rich.text import Text

from repoevidence.application import (
    InspectResult,
    ReconciliationApplicationResult,
    ReportApplicationResult,
    ScanApplicationResult,
    VerificationApplicationResult,
)
from repoevidence.assessment import (
    CheckAssessment,
    CheckState,
    ConclusionKind,
    RepositoryAssessment,
)
from repoevidence.i18n import Language, error_message, message, resolve_language
from repoevidence.report_view import (
    NextActionKind,
    SourceNoticeKind,
    classify_source_notices,
)


@dataclass(frozen=True)
class ErrorView:
    """Structured, localizable human error without changing machine error codes."""

    title_key: str
    reason_key: str
    recovery_key: str
    technical_code: str
    path: Path | None = None
    command: str | None = None
    details: Mapping[str, object] | None = None


class TerminalPresenter:
    """Render application results without exposing machine-model jargon first."""

    def __init__(
        self,
        language: str,
        *,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        force_terminal: bool | None = None,
        width: int | None = None,
        no_color: bool | None = None,
    ) -> None:
        self.language: Language = resolve_language(language)
        color_disabled = (
            "NO_COLOR" in os.environ if no_color is None else no_color
        )
        effective_terminal = False if color_disabled else force_terminal
        console_options = {
            "force_terminal": effective_terminal,
            "width": width,
            "no_color": color_disabled,
            "highlight": False,
            "markup": False,
        }
        self.stdout = Console(file=stdout or sys.stdout, **console_options)
        self.stderr = Console(file=stderr or sys.stderr, **console_options)

    def welcome(self) -> None:
        self._brand(self.stdout)
        self.stdout.print(
            message("terminal.welcome.purpose", self.language),
            soft_wrap=True,
        )
        self.stdout.print()
        self._section(self.stdout, message("terminal.welcome.start", self.language))
        self._command(self.stdout, "repoevidence inspect .")
        self.stdout.print(message("terminal.welcome.help", self.language))

    def inspect_started(self, root: Path) -> None:
        self.stdout.print(
            message("terminal.source.started", self.language, path=root),
            style="dim",
            soft_wrap=True,
        )

    def inspect_finished(self, result: InspectResult) -> None:
        summary = result.summary
        assessment = summary.assessment
        if summary.errors:
            self._result_heading(
                self.stderr,
                message("terminal.source.failed", self.language),
                failed=True,
            )
            for error in summary.errors:
                self.stderr.print(error)
            self._section(
                self.stderr,
                message("terminal.section.artifact", self.language),
            )
            self.stderr.print(
                message(
                    "terminal.artifact.path",
                    self.language,
                    path=summary.evidence_path,
                ),
                soft_wrap=True,
            )
            return
        self._result_heading(
            self.stdout,
            message("terminal.source.complete", self.language),
        )
        self.stdout.print(
            message(
                "terminal.source.project",
                self.language,
                name=summary.repository_name,
            )
        )
        if summary.warnings:
            self.stdout.print(
                message(
                    "terminal.source.warnings",
                    self.language,
                    count=len(summary.warnings),
                )
            )
            self._render_source_notices(self.stdout, summary.warnings)
        self.stdout.print(
            " · ".join(
                (
                    self._count("spring", summary.spring_endpoint_count),
                    self._count("maven", summary.maven_dependency_count),
                    self._count("flyway", summary.flyway_migration_count),
                )
            )
        )
        self.stdout.print()
        self._render_coverage(self.stdout, assessment)
        self.stdout.print()
        self._render_conclusion(self.stdout, assessment.conclusion)
        self.stdout.print()
        self._render_next_action(
            self.stdout,
            assessment,
            summary.repository_path,
            prefer_mysql=summary.flyway_migration_count > 0,
        )
        self.stdout.print()
        self._section(self.stdout, message("terminal.section.report", self.language))
        self.stdout.print(
            message(
                "terminal.report.path",
                self.language,
                path=summary.report_path,
            ),
            soft_wrap=True,
        )

    def scan_started(self, root: Path) -> None:
        self.inspect_started(root)

    def scan_finished(self, result: ScanApplicationResult) -> None:
        scan = result.scan_result
        if scan.errors:
            self._result_heading(
                self.stderr,
                message("terminal.source.failed", self.language),
                failed=True,
            )
            for error in scan.errors:
                self.stderr.print(error)
            self._section(
                self.stderr,
                message("terminal.section.artifact", self.language),
            )
            self.stderr.print(
                message(
                    "terminal.artifact.path",
                    self.language,
                    path=result.evidence_path,
                ),
                soft_wrap=True,
            )
            return
        facts = scan.facts
        spring = sum(fact.id.startswith("fact.spring.endpoint.") for fact in facts)
        maven = sum(
            fact.id.startswith("fact.maven.dependency.")
            and isinstance(fact.value, dict)
            and fact.value.get("location") == "dependencies"
            for fact in facts
        )
        flyway = sum(
            fact.name == "Flyway migration declaration"
            and isinstance(fact.value, dict)
            and fact.value.get("type") == "versioned"
            for fact in facts
        )
        self._result_heading(
            self.stdout,
            message("terminal.source.complete", self.language),
        )
        self.stdout.print(
            " · ".join(
                (
                    self._count("spring", spring),
                    self._count("maven", maven),
                    self._count("flyway", flyway),
                )
            )
        )
        if scan.warnings:
            self.stdout.print(
                message(
                    "terminal.source.warnings",
                    self.language,
                    count=len(scan.warnings),
                )
            )
            self._render_source_notices(self.stdout, scan.warnings)
        self.stdout.print()
        self._render_coverage(self.stdout, result.assessment)
        self.stdout.print()
        self._render_conclusion(self.stdout, result.assessment.conclusion)
        self.stdout.print()
        self._section(self.stdout, message("terminal.section.next", self.language))
        self.stdout.print(message("terminal.next.generate_report", self.language))
        self._command(
            self.stdout,
            shlex.join(
                ("repoevidence", "report", str(Path(scan.repository_root)))
            ),
        )
        self._section(self.stdout, message("terminal.section.artifact", self.language))
        self.stdout.print(
            message(
                "terminal.artifact.path",
                self.language,
                path=result.evidence_path,
            ),
            soft_wrap=True,
        )

    def verify_started(self, root: Path) -> None:
        self._brand(self.stdout)
        self.stdout.print(
            message(
                "terminal.verification.started",
                self.language,
                name=root.name or root,
            ),
            style="bold",
        )
        self.stdout.print(
            message("terminal.verification.scope", self.language),
            soft_wrap=True,
        )

    def verify_finished(
        self,
        result: VerificationApplicationResult,
        assessment: RepositoryAssessment,
    ) -> None:
        verification = result.verification_result
        if verification.errors or assessment.mysql.state is not CheckState.CURRENT:
            self._result_heading(
                self.stderr,
                message("terminal.verification.failed", self.language),
                failed=True,
            )
            for error in verification.errors:
                self.stderr.print(
                    error_message(error.code, self.language, error.message)
                )
                self.stderr.print(
                    message(
                        "terminal.error.code",
                        self.language,
                        code=error.code,
                    ),
                    style="dim",
                )
            self.stderr.print(message("terminal.verification.no_changes", self.language))
            self.stderr.print()
            self._section(
                self.stderr,
                message("terminal.section.next", self.language),
            )
            error_codes = {error.code for error in verification.errors}
            if "mysql_config_missing" in error_codes:
                self.stderr.print(
                    message("terminal.verification.configure", self.language)
                )
                for name in (
                    "REPOEVIDENCE_MYSQL_HOST",
                    "REPOEVIDENCE_MYSQL_PORT",
                    "REPOEVIDENCE_MYSQL_USER",
                    "REPOEVIDENCE_MYSQL_PASSWORD",
                    "REPOEVIDENCE_MYSQL_DATABASE",
                ):
                    self.stderr.print(Text(name, style="bold"))
            else:
                self.stderr.print(
                    message("terminal.verification.retry", self.language)
                )
            self._command(
                self.stderr,
                shlex.join(
                    (
                        "repoevidence",
                        "verify",
                        "mysql",
                        str(assessment.repository_root),
                    )
                ),
            )
            self.stderr.print()
            self._section(
                self.stderr,
                message("terminal.section.artifact", self.language),
            )
            self.stderr.print(
                message(
                    "terminal.artifact.path",
                    self.language,
                    path=result.verification_path,
                ),
                soft_wrap=True,
            )
            return

        self._result_heading(
            self.stdout,
            message("terminal.verification.complete", self.language),
        )
        self.stdout.print(message("terminal.verification.no_changes", self.language))
        self.stdout.print()
        self._render_next_action(
            self.stdout,
            assessment,
            assessment.repository_root,
        )
        self._section(self.stdout, message("terminal.section.artifact", self.language))
        self.stdout.print(
            message(
                "terminal.artifact.path",
                self.language,
                path=result.verification_path,
            ),
            soft_wrap=True,
        )

    def reconcile_started(self, root: Path) -> None:
        self._brand(self.stdout)
        self.stdout.print(
            message(
                "terminal.reconciliation.started",
                self.language,
                name=root.name or root,
            ),
            style="bold",
        )

    def reconcile_finished(
        self,
        result: ReconciliationApplicationResult,
        assessment: RepositoryAssessment,
    ) -> None:
        reconciliation = result.reconciliation_result
        if (
            reconciliation.errors
            or assessment.reconciliation.state is not CheckState.CURRENT
        ):
            self._result_heading(
                self.stderr,
                message("terminal.reconciliation.failed", self.language),
                failed=True,
            )
            for error in reconciliation.errors:
                self.stderr.print(
                    error_message(error.code, self.language, error.message)
                )
                self.stderr.print(
                    message(
                        "terminal.error.code",
                        self.language,
                        code=error.code,
                    ),
                    style="dim",
                )
            if not reconciliation.errors:
                self.stderr.print(
                    message(
                        f"terminal.conclusion.{assessment.conclusion.value}",
                        self.language,
                    )
                )
                for code in (
                    *assessment.mysql.error_codes,
                    *assessment.reconciliation.error_codes,
                ):
                    self.stderr.print(
                        message("terminal.error.code", self.language, code=code),
                        style="dim",
                    )
            self.stderr.print()
            self._render_next_action(
                self.stderr,
                assessment,
                assessment.repository_root,
            )
            self._section(
                self.stderr,
                message("terminal.section.artifact", self.language),
            )
            self.stderr.print(
                message(
                    "terminal.artifact.path",
                    self.language,
                    path=result.reconciliation_path,
                ),
                soft_wrap=True,
            )
            return

        key = (
            "terminal.reconciliation.drift"
            if assessment.conclusion is ConclusionKind.DRIFT
            else "terminal.reconciliation.no_drift"
        )
        self._result_heading(self.stdout, message(key, self.language))
        summary = reconciliation.summary
        self.stdout.print(
            message(
                "terminal.reconciliation.counts",
                self.language,
                matched=summary.matched,
                runtime_only=summary.runtime_only,
                source_only=summary.source_only,
            )
        )
        self.stdout.print(
            message("terminal.reconciliation.scope", self.language),
            soft_wrap=True,
        )
        self.stdout.print()
        self._section(self.stdout, message("terminal.section.next", self.language))
        self.stdout.print(message("terminal.next.report", self.language))
        self._command(
            self.stdout,
            shlex.join(
                ("repoevidence", "report", str(assessment.repository_root))
            ),
        )
        self.stdout.print()
        self._section(self.stdout, message("terminal.section.artifact", self.language))
        self.stdout.print(
            message(
                "terminal.artifact.path",
                self.language,
                path=result.reconciliation_path,
            ),
            soft_wrap=True,
        )

    def report_started(self, root: Path) -> None:
        self.stdout.print(
            message(
                "terminal.report.started",
                self.language,
                name=root.name or root,
            ),
            style="dim",
        )

    def report_finished(self, result: ReportApplicationResult) -> None:
        self._result_heading(
            self.stdout,
            message("terminal.report.complete", self.language),
        )
        self.stdout.print()
        self._render_coverage(self.stdout, result.assessment)
        self.stdout.print()
        self._render_conclusion(self.stdout, result.assessment.conclusion)
        self.stdout.print()
        self._section(self.stdout, message("terminal.section.next", self.language))
        action = result.view_model.next_action
        if action.kind is NextActionKind.REVIEW_FINDINGS:
            self.stdout.print(message("terminal.next.review_findings", self.language))
        elif action.kind is NextActionKind.REVIEW_EVIDENCE:
            self.stdout.print(message("terminal.next.review_evidence", self.language))
        else:
            key = {
                NextActionKind.INSPECT: "terminal.next.inspect",
                NextActionKind.VERIFY_MYSQL: "terminal.next.verify_mysql",
                NextActionKind.RECONCILE: "terminal.next.reconcile",
            }[action.kind]
            self.stdout.print(message(key, self.language))
            if action.command is not None:
                self._command(self.stdout, shlex.join(action.command))
        self.stdout.print()
        self._section(self.stdout, message("terminal.section.report", self.language))
        self.stdout.print(
            message(
                "terminal.report.path",
                self.language,
                path=result.report_path,
            ),
            soft_wrap=True,
        )

    def error(self, error: ErrorView) -> None:
        values = {
            "path": error.path or "",
            "command": error.command or "",
            **(error.details or {}),
        }
        self._result_heading(
            self.stderr,
            message(error.title_key, self.language, **values),
            failed=True,
        )
        self.stderr.print(
            message(error.reason_key, self.language, **values),
            soft_wrap=True,
        )
        self.stderr.print()
        self.stderr.print(
            message(error.recovery_key, self.language, **values),
            soft_wrap=True,
        )
        if error.command:
            self._command(self.stderr, error.command)
        self.stderr.print(
            message(
                "terminal.error.code",
                self.language,
                code=error.technical_code,
            ),
            style="dim",
        )

    def _render_coverage(
        self,
        console: Console,
        assessment: RepositoryAssessment,
    ) -> None:
        self._section(console, message("terminal.section.coverage", self.language))
        for domain, check in (
            ("source", assessment.source),
            ("mysql", assessment.mysql),
            ("reconciliation", assessment.reconciliation),
        ):
            key = f"terminal.check.{domain}.{check.state.value}"
            if domain == "source" and check.state is CheckState.UNKNOWN:
                key = "terminal.check.source.failed"
            console.print(message(key, self.language), style=self._state_style(check))

    def _render_conclusion(
        self,
        console: Console,
        conclusion: ConclusionKind,
    ) -> None:
        self._section(console, message("terminal.section.conclusion", self.language))
        console.print(
            message(f"terminal.conclusion.{conclusion.value}", self.language),
            soft_wrap=True,
        )

    def _render_next_action(
        self,
        console: Console,
        assessment: RepositoryAssessment,
        root: Path,
        *,
        prefer_mysql: bool = True,
    ) -> None:
        self._section(console, message("terminal.section.next", self.language))
        if assessment.source.state is not CheckState.CURRENT:
            console.print(message("terminal.next.inspect", self.language))
            self._command(
                console,
                shlex.join(("repoevidence", "inspect", str(root))),
            )
            return
        if assessment.mysql.state in {CheckState.FAILED, CheckState.UNKNOWN}:
            console.print(message("terminal.next.verify_mysql", self.language))
            self._command(
                console,
                shlex.join(("repoevidence", "verify", "mysql", str(root))),
            )
            return
        if assessment.mysql.state is CheckState.NOT_RUN and prefer_mysql:
            console.print(message("terminal.next.verify_mysql", self.language))
            self._command(
                console,
                shlex.join(("repoevidence", "verify", "mysql", str(root))),
            )
            return
        if (
            not prefer_mysql
            and assessment.mysql.state is not CheckState.CURRENT
        ):
            console.print(message("terminal.next.review_report", self.language))
            return
        if assessment.reconciliation.state in {
            CheckState.NOT_RUN,
            CheckState.FAILED,
            CheckState.STALE,
            CheckState.UNKNOWN,
        }:
            console.print(message("terminal.next.reconcile", self.language))
            self._command(
                console,
                shlex.join(("repoevidence", "reconcile", str(root))),
            )
            return
        console.print(message("terminal.next.report", self.language))
        self._command(
            console,
            shlex.join(("repoevidence", "report", str(root))),
        )

    def _count(self, domain: str, count: int) -> str:
        plurality = "one" if count == 1 else "many"
        return message(
            f"terminal.source.{domain}.{plurality}",
            self.language,
            count=count,
        )

    def _render_source_notices(
        self,
        console: Console,
        warnings: list[str] | tuple[str, ...],
    ) -> None:
        for kind in classify_source_notices(warnings):
            if kind is SourceNoticeKind.GIT_METADATA_UNAVAILABLE:
                console.print(
                    message("terminal.notice.git_metadata_unavailable", self.language),
                    soft_wrap=True,
                )

    @staticmethod
    def _brand(console: Console) -> None:
        console.print(Text("RepoEvidence", style="bold cyan"))

    @staticmethod
    def _section(console: Console, title: str) -> None:
        console.print(Text(title, style="bold"))

    @staticmethod
    def _command(console: Console, command: str) -> None:
        console.print(Text(command, style="bold cyan"), soft_wrap=True)

    @staticmethod
    def _result_heading(console: Console, title: str, *, failed: bool = False) -> None:
        console.print(Text(title, style="bold red" if failed else "bold green"))

    @staticmethod
    def _state_style(check: CheckAssessment) -> str:
        return {
            CheckState.CURRENT: "green",
            CheckState.NOT_RUN: "yellow",
            CheckState.FAILED: "red",
            CheckState.STALE: "yellow",
            CheckState.UNKNOWN: "magenta",
        }[check.state]
