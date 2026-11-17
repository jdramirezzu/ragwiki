"""Command-line interface."""

import os
from pathlib import Path
from typing import Annotated

import typer

from wikinotes import __version__
from wikinotes.vault import Vault, VaultError

app = typer.Typer(
    help="Turn your study material into an interlinked, LLM-maintained Markdown wiki.",
    no_args_is_help=True,
)

VaultOption = Annotated[
    Path | None,
    typer.Option("--vault", help="Vault folder. Defaults to $WIKINOTES_VAULT or the current one."),
]


def _fail(message: str) -> typer.Exit:
    typer.echo(f"Error: {message}", err=True)
    return typer.Exit(code=1)


def _open_vault(vault: Path | None) -> Vault:
    start = vault or os.environ.get("WIKINOTES_VAULT") or Path.cwd()
    try:
        return Vault.find(Path(start))
    except VaultError as error:
        raise _fail(str(error)) from error


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"wikinotes {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_print_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """Turn your study material into an interlinked, LLM-maintained Markdown wiki."""


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Folder for the new vault.")] = Path("."),
) -> None:
    """Create a new vault: the folder that holds your sources and your wiki."""
    try:
        vault = Vault.create(path)
    except VaultError as error:
        raise _fail(str(error)) from error
    typer.echo(f"Created a vault at {vault.root}")
    typer.echo("Next: wikinotes add <file>")


@app.command()
def status(vault: VaultOption = None) -> None:
    """Show what the vault holds."""
    opened = _open_vault(vault)
    typer.echo(f"Vault: {opened.root}")
    typer.echo(f"Sources: {len(opened.sources())}")
    typer.echo(f"Pages: {len(opened.page_slugs())}")
