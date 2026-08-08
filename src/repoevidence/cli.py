from pathlib import Path

import typer

from repoevidence.reconciliation import Reconciler
from repoevidence.scanner import Scanner
from repoevidence.verification.mysql import MySQLVerifier

app = typer.Typer(
    name="repoevidence",
    help="Deterministic, LLM-free software evidence collection.",
    no_args_is_help=True,
)
verify_app = typer.Typer(name="verify", help="Run explicitly requested runtime verification.")
app.add_typer(verify_app, name="verify")


@app.callback()
def main() -> None:
    """Deterministic, LLM-free software evidence collection."""


@app.command("scan")
def scan(
    repo_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        metavar="REPO_PATH",
    ),
) -> None:
    """Collect deterministic repository evidence from REPO_PATH."""
    root = repo_path.expanduser().resolve()
    result = Scanner.default().scan(root)
    output_path = root / ".repoevidence" / "evidence.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Evidence written to {output_path}")
    if result.warnings:
        typer.echo(f"Warnings: {len(result.warnings)}")
    if result.errors:
        typer.echo(f"Errors: {len(result.errors)}")


@app.command("reconcile")
def reconcile(
    repo_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        metavar="REPO_PATH",
    ),
) -> None:
    """Reconcile existing static and MySQL Flyway artifacts offline."""
    root = repo_path.expanduser().resolve()
    result = Reconciler().reconcile(root)
    output_path = root / ".repoevidence" / "reconciliation.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Reconciliation written to {output_path}")
    if result.warnings:
        typer.echo(f"Warnings: {len(result.warnings)}")
    if result.errors:
        typer.echo(f"Errors: {len(result.errors)}")


@verify_app.command("mysql")
def verify_mysql(
    repo_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        metavar="REPO_PATH",
    ),
) -> None:
    """Run fixed, read-only MySQL metadata verification for REPO_PATH."""
    root = repo_path.expanduser().resolve()
    result = MySQLVerifier().verify(root)
    output_path = root / ".repoevidence" / "verification" / "mysql.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    typer.echo(f"MySQL verification written to {output_path}")
    if result.warnings:
        typer.echo(f"Warnings: {len(result.warnings)}")
    if result.errors:
        typer.echo(f"Errors: {len(result.errors)}")


if __name__ == "__main__":
    app()
