"""Command-line interface."""

from typing import Annotated

import typer

from wikinotes import __version__

app = typer.Typer(
    help="Turn your study material into an interlinked, LLM-maintained Markdown wiki.",
    no_args_is_help=True,
)


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
