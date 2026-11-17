"""Command-line interface."""

import os
from pathlib import Path
from typing import Annotated

import typer

from wikinotes import __version__
from wikinotes.ask import ask as answer_question
from wikinotes.extract import UnreadableSource, UnsupportedFormat
from wikinotes.ingest import IngestError, ingest
from wikinotes.models import (
    BudgetExceeded,
    ConfigError,
    MeteredModel,
    Model,
    ModelError,
    metered_from_env,
)
from wikinotes.vault import STATE_DIR, Vault, VaultError

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


def build_model(vault: Vault) -> Model:
    """The model for this run, configured from the environment and metered into the vault."""
    return metered_from_env(vault.root / STATE_DIR / "calls.jsonl")


def _open_model(vault: Vault) -> Model:
    try:
        return build_model(vault)
    except ConfigError as error:
        raise _fail(str(error)) from error


def _print_cost(model: Model) -> None:
    if isinstance(model, MeteredModel):
        typer.echo(f"Model calls: {model.calls}, cost: ${model.spent_usd:.4f}")


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
def add(
    files: Annotated[list[Path], typer.Argument(help="Files to add.", exists=True, dir_okay=False)],
    vault: VaultOption = None,
) -> None:
    """Add files to the vault and let the model update the wiki with them."""
    opened = _open_vault(vault)
    model = _open_model(opened)
    try:
        for path in files:
            try:
                result = ingest(opened, model, path)
            except (
                UnsupportedFormat,
                UnreadableSource,
                IngestError,
                BudgetExceeded,
                ModelError,
            ) as error:
                raise _fail(f"{path.name}: {error}") from error
            if result.skipped:
                typer.echo(f"{path.name}: already in the vault as {result.source_id}")
                continue
            typer.echo(f"{path.name}: added as {result.source_id}")
            if result.created:
                typer.echo(f"  created: {', '.join(result.created)}")
            if result.updated:
                typer.echo(f"  updated: {', '.join(result.updated)}")
            if result.dropped_citations:
                typer.echo(f"  removed {result.dropped_citations} citation(s) that did not resolve")
    finally:
        _print_cost(model)


def _describe_citation(vault: Vault, citation: str) -> str:
    source_id, anchor = citation.split("#^")
    source = vault.load_source(source_id)
    excerpt = " ".join(source.paragraphs[anchor].split())
    if len(excerpt) > 120:
        excerpt = excerpt[:117] + "..."
    return f"- {citation} ({source.title}): {excerpt}"


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="What you want to know.")],
    vault: VaultOption = None,
) -> None:
    """Answer a question from the wiki, citing the source paragraphs."""
    opened = _open_vault(vault)
    model = _open_model(opened)
    try:
        answer = answer_question(opened, model, question)
    except (BudgetExceeded, ModelError) as error:
        raise _fail(str(error)) from error
    finally:
        _print_cost(model)
    if not answer.found:
        typer.echo(f"Not in your notes: {answer.text}")
        return
    typer.echo(answer.text)
    typer.echo("\nSources:")
    for citation in answer.citations:
        typer.echo(_describe_citation(opened, citation))


@app.command()
def status(vault: VaultOption = None) -> None:
    """Show what the vault holds."""
    opened = _open_vault(vault)
    typer.echo(f"Vault: {opened.root}")
    typer.echo(f"Sources: {len(opened.sources())}")
    typer.echo(f"Pages: {len(opened.page_slugs())}")
