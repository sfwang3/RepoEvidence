from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

import typer
from typer.core import TyperCommand, TyperGroup

from repoevidence.i18n import (
    InvalidLanguageError,
    Language,
    error_message,
    message,
    resolve_language,
)
from repoevidence.reconciliation import Reconciler
from repoevidence.reporting import ReportGenerationError, ReportGenerator
from repoevidence.scanner import Scanner
from repoevidence.verification.mysql import MySQLVerifier


def _translate_framework_help(rendered: str, language: Language) -> str:
    if language == "en":
        return rendered
    replacements = {
        "Usage:": "用法：",
        "Options:": "选项：",
        "Commands:": "命令：",
        "Arguments:": "参数：",
        "Show this message and exit.": message("cli.help.option", language),
        "Install completion for the current shell.": message(
            "cli.install_completion", language
        ),
        "Show completion for the current shell, to copy it or customize the installation.": message(
            "cli.show_completion", language
        ),
        "Show completion for the current shell, to copy it or": (
            "显示当前 shell 的补全内容，便于复制或"
        ),
        "customize the installation.": "自定义安装。",
    }
    for source, target in replacements.items():
        rendered = rendered.replace(source, target)
    return rendered


def _write_localized_help(
    language: Language,
    formatter: Any,
    render_help: Any,
) -> None:
    """Use Click's public formatter object and translate only its fixed labels."""

    formatter_type = type(formatter)
    capture = formatter_type(
        width=getattr(formatter, "width", None),
        max_width=getattr(formatter, "max_width", None),
    )
    render_help(capture)
    formatter.write(_translate_framework_help(capture.getvalue(), language))


def _localized_group_class(language: Language) -> type[TyperGroup]:
    """Return a small public Typer group layer for framework help headings."""

    class LocalizedTyperGroup(TyperGroup):
        def format_help(self, ctx: Any, formatter: Any) -> None:
            # ``rich_markup_mode=None`` makes this use Click's standard public
            # formatter path. Command names and user-provided values are untouched.
            _write_localized_help(
                language,
                formatter,
                lambda capture: super(LocalizedTyperGroup, self).format_help(
                    ctx, capture
                ),
            )

    return LocalizedTyperGroup


def _localized_command_class(language: Language) -> type[TyperCommand]:
    """Return the command counterpart for localized subcommand help."""

    class LocalizedTyperCommand(TyperCommand):
        def format_help(self, ctx: Any, formatter: Any) -> None:
            _write_localized_help(
                language,
                formatter,
                lambda capture: super(LocalizedTyperCommand, self).format_help(
                    ctx, capture
                ),
            )

    return LocalizedTyperCommand


def create_app(language: Language) -> typer.Typer:
    """Build a CLI whose human-facing help and output use ``language``."""

    resolved_language = resolve_language(language)
    group_class = _localized_group_class(resolved_language)
    command_class = _localized_command_class(resolved_language)
    root_app = typer.Typer(
        name="repoevidence",
        help=message("cli.root.help", resolved_language),
        no_args_is_help=True,
        cls=group_class,
        rich_markup_mode=None,
    )
    verify_app = typer.Typer(
        name="verify",
        help=message("cli.verify.help", resolved_language),
        cls=group_class,
        rich_markup_mode=None,
    )
    root_app.add_typer(verify_app, name="verify")

    @root_app.callback()
    def root_callback(
        lang: str = typer.Option(
            "auto",
            "--lang",
            help=message("cli.lang.help", resolved_language),
            is_eager=True,
            metavar="auto|en|zh-CN",
        ),
    ) -> None:
        """Select the language for human-readable presentation."""

        if lang not in {"auto", "en", "zh-CN"}:
            raise typer.BadParameter(
                message("cli.invalid_language", resolved_language, value=lang),
                param_hint="--lang",
            )
        if lang != "auto" and lang != resolved_language:
            raise typer.BadParameter(
                message("cli.invalid_language", resolved_language, value=lang),
                param_hint="--lang",
            )

    @root_app.command(
        "scan",
        cls=command_class,
        help=message("cli.scan.help", resolved_language),
    )
    def scan(
        repo_path: Path = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            metavar="REPO_PATH",
        ),
    ) -> None:
        root = repo_path.expanduser().resolve()
        result = Scanner.default().scan(root)
        output_path = root / ".repoevidence" / "evidence.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        typer.echo(message("cli.scan.complete", resolved_language, path=output_path))
        if result.warnings:
            typer.echo(message("cli.warnings", resolved_language, count=len(result.warnings)))
        if result.errors:
            for error in result.errors:
                typer.echo(
                    message(
                        "cli.error",
                        resolved_language,
                        code=error.code,
                        message=error_message(
                            error.code,
                            resolved_language,
                            error.message,
                        ),
                    ),
                    err=True,
                )
            raise typer.Exit(code=1)

    @root_app.command(
        "reconcile",
        cls=command_class,
        help=message("cli.reconcile.help", resolved_language),
    )
    def reconcile(
        repo_path: Path = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            metavar="REPO_PATH",
        ),
    ) -> None:
        root = repo_path.expanduser().resolve()
        result = Reconciler().reconcile(root)
        output_path = root / ".repoevidence" / "reconciliation.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        typer.echo(message("cli.reconcile.complete", resolved_language, path=output_path))
        if result.warnings:
            typer.echo(message("cli.warnings", resolved_language, count=len(result.warnings)))
        if result.errors:
            for error in result.errors:
                typer.echo(
                    message(
                        "cli.error",
                        resolved_language,
                        code=error.code,
                        message=error_message(
                            error.code,
                            resolved_language,
                            error.message,
                        ),
                    ),
                    err=True,
                )
            raise typer.Exit(code=1)

    @root_app.command(
        "report",
        cls=command_class,
        help=message("cli.report.help", resolved_language),
    )
    def report(
        repo_path: Path = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            metavar="REPO_PATH",
        ),
    ) -> None:
        root = repo_path.expanduser().resolve()
        try:
            output_path = ReportGenerator().generate(root, language=resolved_language)
        except ReportGenerationError as exc:
            typer.echo(
                message(
                    "cli.report_error",
                    resolved_language,
                    code=exc.code,
                    message=error_message(exc.code, resolved_language, exc.message),
                ),
                err=True,
            )
            raise typer.Exit(code=1) from None
        typer.echo(message("cli.report.complete", resolved_language, path=output_path))

    @verify_app.command(
        "mysql",
        cls=command_class,
        help=message("cli.mysql.help", resolved_language),
    )
    def verify_mysql(
        repo_path: Path = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            metavar="REPO_PATH",
        ),
    ) -> None:
        root = repo_path.expanduser().resolve()
        result = MySQLVerifier().verify(root)
        output_path = root / ".repoevidence" / "verification" / "mysql.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        typer.echo(message("cli.mysql.complete", resolved_language, path=output_path))
        if result.warnings:
            typer.echo(message("cli.warnings", resolved_language, count=len(result.warnings)))
        if result.errors:
            for error in result.errors:
                typer.echo(
                    message(
                        "cli.error",
                        resolved_language,
                        code=error.code,
                        message=error_message(
                            error.code,
                            resolved_language,
                            error.message,
                        ),
                    ),
                    err=True,
                )
            raise typer.Exit(code=1)

    return root_app


def _requested_language(args: Sequence[str]) -> str | None:
    """Read only the explicit global option before constructing the Typer app."""

    for index, value in enumerate(args):
        if value.startswith("--lang="):
            return value.partition("=")[2]
        if value == "--lang" and index + 1 < len(args):
            return args[index + 1]
    return None


def main(argv: Sequence[str] | None = None) -> None:
    """Resolve language first, then hand the unchanged arguments to Typer."""

    args = list(sys.argv[1:] if argv is None else argv)
    requested = _requested_language(args)
    try:
        language = resolve_language(requested)
    except InvalidLanguageError as exc:
        typer.echo(message("cli.invalid_language", "en", value=exc.value), err=True)
        raise SystemExit(2) from None
    create_app(language)(args=args, prog_name="repoevidence")


app = create_app("en")


if __name__ == "__main__":
    main()
