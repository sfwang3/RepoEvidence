from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Sequence

import typer
from typer import _click
from typer.core import TyperCommand, TyperGroup

from repoevidence.application import (
    RepositoryPathError,
    generate_report,
    inspect_repository,
    reconcile_repository,
    resolve_repository_path,
    scan_repository,
    verify_mysql_repository,
)
from repoevidence.assessment import CheckState, assess_repository
from repoevidence.i18n import (
    InvalidLanguageError,
    Language,
    error_message,
    message,
    resolve_language,
)
from repoevidence.presentation.terminal import ErrorView, TerminalPresenter
from repoevidence.project_context import ProjectPathError, discover_project_context
from repoevidence.reporting import ReportGenerationError
from repoevidence.user_config import UserSettings, load_user_settings


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
        "[default:": "[默认：",
        "[required]": "[必填]",
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


_UNKNOWN_COMMAND = re.compile(
    r"^No such command '(?P<value>[^']+)'\."
    r"(?: Did you mean '(?P<suggestion>[^']+)'\?)?$"
)


def _usage_error_view(
    error: _click.exceptions.ClickException,
    language: Language,
) -> ErrorView:
    context = getattr(error, "ctx", None)
    command_path = getattr(context, "command_path", "repoevidence")
    help_command = f"{command_path} --help"

    if isinstance(error, _click.exceptions.NoSuchOption):
        return ErrorView(
            title_key="error.unknown_option.title",
            reason_key="error.unknown_option.reason",
            recovery_key="error.unknown_option.recovery",
            technical_code="unknown_option",
            command=help_command,
            details={"value": error.option_name},
        )

    if isinstance(error, _click.exceptions.MissingParameter):
        parameter_name = getattr(getattr(error, "param", None), "name", None)
        if parameter_name == "repo_path":
            return ErrorView(
                title_key="error.repository_argument_missing.title",
                reason_key="error.repository_argument_missing.reason",
                recovery_key="error.repository_argument_missing.recovery",
                technical_code="repository_argument_missing",
                command=f"{command_path} REPO_PATH",
            )

    match = _UNKNOWN_COMMAND.match(error.message)
    if match is not None:
        suggestion = match.group("suggestion")
        rendered_suggestion = (
            message(
                "error.unknown_command.suggestion",
                language,
                value=suggestion,
            )
            if suggestion
            else ""
        )
        return ErrorView(
            title_key="error.unknown_command.title",
            reason_key="error.unknown_command.reason",
            recovery_key="error.unknown_command.recovery",
            technical_code="unknown_command",
            command="repoevidence --help",
            details={
                "value": match.group("value"),
                "suggestion": rendered_suggestion,
            },
        )

    return ErrorView(
        title_key="error.invalid_usage.title",
        reason_key="error.invalid_usage.reason",
        recovery_key="error.invalid_usage.recovery",
        technical_code="invalid_usage",
        command=help_command,
        details={"detail": error.message},
    )


def _localized_group_class(language: Language) -> type[TyperGroup]:
    """Return a small public Typer group layer for framework help headings."""

    class LocalizedTyperGroup(TyperGroup):
        def list_commands(self, ctx: Any) -> list[str]:
            commands = super().list_commands(ctx)
            order = {
                "inspect": 0,
                "scan": 1,
                "verify": 2,
                "reconcile": 3,
                "report": 4,
            }
            return sorted(commands, key=lambda name: (order.get(name, 99), name))

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

        def main(
            self,
            args: Sequence[str] | None = None,
            prog_name: str | None = None,
            complete_var: str | None = None,
            standalone_mode: bool = True,
            windows_expand_args: bool = True,
            **extra: Any,
        ) -> Any:
            if not standalone_mode:
                return super().main(
                    args=args,
                    prog_name=prog_name,
                    complete_var=complete_var,
                    standalone_mode=False,
                    windows_expand_args=windows_expand_args,
                    **extra,
                )
            try:
                result = super().main(
                    args=args,
                    prog_name=prog_name,
                    complete_var=complete_var,
                    standalone_mode=False,
                    windows_expand_args=windows_expand_args,
                    **extra,
                )
            except _click.exceptions.ClickException as error:
                TerminalPresenter(language).error(_usage_error_view(error, language))
                raise SystemExit(error.exit_code) from None
            raise SystemExit(result if isinstance(result, int) else 0)

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


def _validated_repository(repo_path: Path, language: Language) -> Path:
    try:
        return resolve_repository_path(repo_path)
    except RepositoryPathError as error:
        TerminalPresenter(language).error(
            ErrorView(
                title_key=f"error.{error.code}.title",
                reason_key=f"error.{error.code}.reason",
                recovery_key=f"error.{error.code}.recovery",
                technical_code=error.code,
                path=error.path,
                command="repoevidence inspect /path/to/repository",
            )
        )
        raise typer.Exit(code=2) from None


def _report_error_view(
    error: ReportGenerationError,
    root: Path,
    language: Language,
) -> ErrorView:
    return ErrorView(
        title_key="error.report_generation.title",
        reason_key="error.report_generation.reason",
        recovery_key="error.report_generation.recovery",
        technical_code=error.code,
        path=root,
        command=shlex.join(("repoevidence", "inspect", str(root))),
        details={"detail": error_message(error.code, language, error.message)},
    )


def _repository_io_error_view(root: Path) -> ErrorView:
    return ErrorView(
        title_key="error.repository_io.title",
        reason_key="error.repository_io.reason",
        recovery_key="error.repository_io.recovery",
        technical_code="repository_io_error",
        path=root,
    )


def _interactive_available(settings: UserSettings, *, plain: bool = False) -> bool:
    """Return whether a full-screen workspace is safe for this process."""

    return (
        not plain
        and settings.interaction != "plain"
        and bool(sys.stdin.isatty())
        and bool(sys.stdout.isatty())
        and "CI" not in os.environ
        and os.environ.get("TERM", "").lower() != "dumb"
    )


def _workspace_path_error_view(error: ProjectPathError) -> ErrorView:
    return ErrorView(
        title_key=f"error.{error.code}.title",
        reason_key=f"error.{error.code}.reason",
        recovery_key=f"error.{error.code}.recovery",
        technical_code=error.code,
        path=error.path,
        command="repoevidence workspace [PATH]",
    )


def create_app(language: Language) -> typer.Typer:
    """Build a CLI whose human-facing help and output use ``language``."""

    resolved_language = resolve_language(language)
    group_class = _localized_group_class(resolved_language)
    command_class = _localized_command_class(resolved_language)
    root_app = typer.Typer(
        name="repoevidence",
        help=message("cli.root.help", resolved_language),
        epilog=message("cli.root.epilog", resolved_language),
        no_args_is_help=False,
        invoke_without_command=True,
        cls=group_class,
        rich_markup_mode=None,
    )
    verify_app = typer.Typer(
        name="verify",
        help=message("cli.verify.help", resolved_language),
        cls=group_class,
        rich_markup_mode=None,
    )
    @root_app.callback()
    def root_callback(
        ctx: typer.Context,
        lang: str = typer.Option(
            "auto",
            "--lang",
            help=message("cli.lang.help", resolved_language),
            is_eager=True,
            metavar="auto|en|zh-CN",
        ),
        plain: bool = typer.Option(
            False,
            "--plain",
            help=message("cli.plain.help", resolved_language),
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
        ctx.ensure_object(dict)
        ctx.obj["plain"] = plain
        if ctx.invoked_subcommand is None:
            settings = load_user_settings().settings
            if not _interactive_available(settings, plain=plain):
                TerminalPresenter(resolved_language).welcome()
                return
            try:
                from repoevidence.interactive import run_workspace

                run_workspace(None, language=resolved_language, settings=settings)
            except ProjectPathError as error:
                TerminalPresenter(resolved_language).error(_workspace_path_error_view(error))
                raise typer.Exit(code=2) from None
            except OSError:
                TerminalPresenter(resolved_language).error(
                    _repository_io_error_view(Path.cwd())
                )
                raise typer.Exit(code=1) from None

    @root_app.command(
        "workspace",
        cls=command_class,
        help=message("cli.workspace.help", resolved_language),
    )
    def workspace(
        ctx: typer.Context,
        path: Path | None = typer.Argument(None, metavar="PATH"),
        plain: bool = typer.Option(
            False,
            "--plain",
            help=message("cli.plain.help", resolved_language),
        ),
    ) -> None:
        settings = load_user_settings().settings
        parent_options = ctx.parent.obj if ctx.parent and ctx.parent.obj else {}
        use_plain = plain or bool(parent_options.get("plain", False))
        if path is not None:
            try:
                discover_project_context(path)
            except ProjectPathError as error:
                TerminalPresenter(resolved_language).error(_workspace_path_error_view(error))
                raise typer.Exit(code=2) from None
        if not _interactive_available(settings, plain=use_plain):
            TerminalPresenter(resolved_language).welcome()
            return
        try:
            from repoevidence.interactive import run_workspace

            run_workspace(path, language=resolved_language, settings=settings)
        except ProjectPathError as error:
            TerminalPresenter(resolved_language).error(_workspace_path_error_view(error))
            raise typer.Exit(code=2) from None
        except OSError:
            root = path.expanduser().resolve() if path is not None else Path.cwd()
            TerminalPresenter(resolved_language).error(_repository_io_error_view(root))
            raise typer.Exit(code=1) from None

    @root_app.command(
        "scan",
        cls=command_class,
        help=message("cli.scan.help", resolved_language),
    )
    def scan(
        repo_path: Path = typer.Argument(
            ...,
            metavar="REPO_PATH",
        ),
    ) -> None:
        root = _validated_repository(repo_path, resolved_language)
        presenter = TerminalPresenter(resolved_language)
        presenter.scan_started(root)
        try:
            application_result = scan_repository(root)
        except OSError:
            presenter.error(_repository_io_error_view(root))
            raise typer.Exit(code=1) from None
        result = application_result.scan_result
        presenter.scan_finished(application_result)
        if result.errors:
            raise typer.Exit(code=1)

    @root_app.command(
        "reconcile",
        cls=command_class,
        help=message("cli.reconcile.help", resolved_language),
    )
    def reconcile(
        repo_path: Path = typer.Argument(
            ...,
            metavar="REPO_PATH",
        ),
    ) -> None:
        root = _validated_repository(repo_path, resolved_language)
        presenter = TerminalPresenter(resolved_language)
        presenter.reconcile_started(root)
        try:
            application_result = reconcile_repository(root)
        except OSError:
            presenter.error(_repository_io_error_view(root))
            raise typer.Exit(code=1) from None
        assessment = assess_repository(root, require_static=False)
        presenter.reconcile_finished(application_result, assessment)
        if (
            application_result.reconciliation_result.errors
            or assessment.reconciliation.state is not CheckState.CURRENT
        ):
            raise typer.Exit(code=1)

    @root_app.command(
        "report",
        cls=command_class,
        help=message("cli.report.help", resolved_language),
    )
    def report(
        repo_path: Path = typer.Argument(
            ...,
            metavar="REPO_PATH",
        ),
    ) -> None:
        root = _validated_repository(repo_path, resolved_language)
        presenter = TerminalPresenter(resolved_language)
        presenter.report_started(root)
        try:
            result = generate_report(root, language=resolved_language)
        except ReportGenerationError as exc:
            presenter.error(_report_error_view(exc, root, resolved_language))
            raise typer.Exit(code=1) from None
        except OSError:
            presenter.error(_repository_io_error_view(root))
            raise typer.Exit(code=1) from None
        presenter.report_finished(result)

    @root_app.command(
        "inspect",
        cls=command_class,
        help=message("cli.inspect.help", resolved_language),
    )
    def inspect(
        repo_path: Path = typer.Argument(
            ...,
            metavar="REPO_PATH",
        ),
    ) -> None:
        root = _validated_repository(repo_path, resolved_language)
        presenter = TerminalPresenter(resolved_language)
        presenter.inspect_started(root)
        try:
            result = inspect_repository(root, language=resolved_language)
        except ReportGenerationError as exc:
            presenter.error(_report_error_view(exc, root, resolved_language))
            raise typer.Exit(code=1) from None
        except OSError:
            presenter.error(_repository_io_error_view(root))
            raise typer.Exit(code=1) from None
        presenter.inspect_finished(result)
        if result.summary.errors:
            raise typer.Exit(code=1)

    @verify_app.command(
        "mysql",
        cls=command_class,
        help=message("cli.mysql.help", resolved_language),
    )
    def verify_mysql(
        repo_path: Path = typer.Argument(
            ...,
            metavar="REPO_PATH",
        ),
    ) -> None:
        root = _validated_repository(repo_path, resolved_language)
        presenter = TerminalPresenter(resolved_language)
        presenter.verify_started(root)
        try:
            application_result = verify_mysql_repository(root)
        except OSError:
            presenter.error(_repository_io_error_view(root))
            raise typer.Exit(code=1) from None
        assessment = assess_repository(root, require_static=False)
        presenter.verify_finished(application_result, assessment)
        if application_result.verification_result.errors:
            raise typer.Exit(code=1)

    root_app.add_typer(verify_app, name="verify")
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
        settings = load_user_settings().settings
        language = resolve_language(requested, user_language=settings.language)
    except InvalidLanguageError as exc:
        typer.echo(message("cli.invalid_language", "en", value=exc.value), err=True)
        raise SystemExit(2) from None
    create_app(language)(args=args, prog_name="repoevidence")


app = create_app("en")


if __name__ == "__main__":
    main()
