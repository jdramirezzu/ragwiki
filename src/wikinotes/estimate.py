"""Forecasting what an ingestion will cost, before any model call is made.

The numbers are rough on purpose: tokens are estimated from text length and the size of
the model's replies is a guess. The real cost of every call is recorded afterwards.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from wikinotes.extract import extract, file_hash, is_photo
from wikinotes.ingest import MAX_UPDATES, PART_SHARE, SYSTEM, render_source, split_source
from wikinotes.models import DEFAULT_CONTEXT_TOKENS, estimate_tokens
from wikinotes.photos import SYSTEM as PHOTO_SYSTEM
from wikinotes.vault import Vault

# Instructions and JSON template around the source in each prompt.
PROMPT_OVERHEAD = 200
# A plan is a short list of slugs, titles and one-line summaries.
PLAN_REPLY = 400
# Written pages restate the part with citations; long parts are summarized.
WRITE_REPLY_BASE = 300
WRITE_REPLY_RATIO = 1.5
WRITE_REPLY_MAX = 4_000
# A photo cannot be measured without paying for its transcription, so a page of notes is
# assumed: what the image costs to read and how much text comes out of it.
PHOTO_INPUT = 1_500
PHOTO_TEXT = 800


@dataclass(frozen=True)
class Estimate:
    files: int
    calls: int
    input_tokens: int
    output_tokens: int
    usd: float | None
    """None when no price is configured, so the cost is unknown rather than free."""


def _pages_context(vault: Vault) -> int:
    """Tokens of the existing pages a write call is likely to receive for updating."""
    slugs = vault.page_slugs()
    if not slugs:
        return 0
    total = sum(estimate_tokens(vault.read_page(slug).body) for slug in slugs)
    return total // len(slugs) * min(MAX_UPDATES // 2, len(slugs))


def estimate_ingest(
    vault: Vault,
    paths: Iterable[Path],
    *,
    context_tokens: int = DEFAULT_CONTEXT_TOKENS,
    price_input: float = 0.0,
    price_output: float = 0.0,
) -> Estimate:
    """Forecast the model calls, tokens and price of adding `paths`. Changes nothing.

    Prices are in USD per million tokens. Files already in the vault cost nothing. Raises
    the same errors as ingestion for a file that cannot be read.
    """
    known = {entry["sha256"] for entry in vault.sources().values()}
    fixed = estimate_tokens(SYSTEM + vault.schema()) + PROMPT_OVERHEAD
    index = estimate_tokens(vault.index())
    pages = _pages_context(vault)
    files = calls = input_tokens = output_tokens = 0

    for path in paths:
        path = Path(path)
        if file_hash(path) in known:
            continue
        files += 1
        if is_photo(path):
            calls += 1
            input_tokens += estimate_tokens(PHOTO_SYSTEM) + PHOTO_INPUT
            output_tokens += PHOTO_TEXT
            sizes = [PHOTO_TEXT]
        else:
            source = extract(path)
            parts = split_source(source, max(1, context_tokens // PART_SHARE))
            sizes = [
                estimate_tokens(render_source(source, blocks, number, len(parts)))
                for number, blocks in enumerate(parts, start=1)
            ]
        for part in sizes:
            calls += 2
            input_tokens += (fixed + part + index) + (fixed + part + pages)
            reply = WRITE_REPLY_BASE + int(part * WRITE_REPLY_RATIO)
            output_tokens += PLAN_REPLY + min(WRITE_REPLY_MAX, reply)

    priced = price_input > 0 or price_output > 0
    usd = (input_tokens * price_input + output_tokens * price_output) / 1_000_000
    return Estimate(files, calls, input_tokens, output_tokens, usd if priced else None)
