"""Command-line interface."""

import os
from pathlib import Path
from typing import Annotated

import typer

from wikinotes import __version__
from wikinotes.ask import ask as answer_question
from wikinotes.ask import cited_paragraph
from wikinotes.estimate import Estimate, estimate_ingest
from wikinotes.extract import UnreadableSource, UnsupportedFormat
from wikinotes.ingest import IngestError, Progress, ingest
from wikinotes.models import (
    BudgetExceeded,
    ConfigError,
    MeteredModel,
    Model,
    ModelError,
    context_tokens_from_env,
    metered_from_env,
    prices_from_env,
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


def _print_progress(progress: Progress) -> None:
    if progress.stage == "transcribing":
        typer.echo(f"{progress.file}: transcribing the photo")
    elif progress.parts > 1:
        typer.echo(f"{progress.file}: part {progress.part} of {progress.parts}, {progress.stage}")


def _print_estimate(estimate: Estimate) -> None:
    cost = (
        "price unknown (set WIKINOTES_PRICE_INPUT and WIKINOTES_PRICE_OUTPUT to see it)"
        if estimate.usd is None
        else f"about ${estimate.usd:.4f}"
    )
    typer.echo(
        f"Estimate: {estimate.files} file(s), about {estimate.calls} model call(s), "
        f"{estimate.input_tokens:,} input and {estimate.output_tokens:,} output tokens, {cost}"
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
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Do not ask before spending money.")
    ] = False,
    estimate_only: Annotated[
        bool, typer.Option("--estimate", help="Show the estimated cost and stop.")
    ] = False,
) -> None:
    """Add files to the vault and let the model update the wiki with them.

    The estimated cost is shown first. When it is above zero you are asked to confirm.
    """
    opened = _open_vault(vault)
    try:
        context_tokens = context_tokens_from_env()
        price_input, price_output = prices_from_env()
        estimate = estimate_ingest(
            opened,
            files,
            context_tokens=context_tokens,
            price_input=price_input,
            price_output=price_output,
        )
    except (ConfigError, UnsupportedFormat, UnreadableSource) as error:
        raise _fail(str(error)) from error
    _print_estimate(estimate)
    if estimate_only:
        return
    model = _open_model(opened)
    if estimate.usd and not yes:
        typer.confirm("Continue?", abort=True)
    try:
        for path in files:
            try:
                result = ingest(
                    opened,
                    model,
                    path,
                    context_tokens=context_tokens,
                    on_progress=_print_progress,
                )
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
    cited = cited_paragraph(vault, citation)
    excerpt = " ".join(cited.text.split())
    if len(excerpt) > 120:
        excerpt = excerpt[:117] + "..."
    return f"- {citation} ({cited.source_title}): {excerpt}"


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
