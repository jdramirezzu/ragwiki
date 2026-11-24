"""Forecasting what an ingestion will cost, before any model call is made.

The numbers are rough on purpose: tokens are estimated from text length and the size of
the model's replies is a guess. The real cost of every call is recorded afterwards.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ragwiki.extract import extract, file_hash, is_photo
from ragwiki.ingest import MAX_UPDATES, PART_SHARE, SYSTEM, render_source, split_source
from ragwiki.models import DEFAULT_CONTEXT_TOKENS, estimate_tokens
from ragwiki.photos import SYSTEM as PHOTO_SYSTEM
from ragwiki.vault import Vault

# Instructions and JSON template around the source in each prompt.
PROMPT_OVERHEAD = 200
# Reply sizes fitted on real DeepSeek ingestions (tests/test_estimate.py keeps the data):
# ten short Spanish notes and five English papers. Even a short note gets several pages
# and updates to existing ones, so the written reply has a large fixed part.
PLAN_REPLY_BASE = 800
PLAN_REPLY_RATIO = 0.1
WRITE_REPLY_BASE = 8_000
WRITE_REPLY_RATIO = 1.2
WRITE_REPLY_MAX = 32_000
# The wiki grows while a batch is ingested: each part adds pages, so later plan calls read
# a longer index and later write calls receive existing pages to update.
PAGES_PER_PART = 4
INDEX_TOKENS_PER_PAGE = 45
PAGE_TOKENS = 850
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


def reply_tokens(part: int) -> tuple[int, int]:
    """The forecast reply tokens of the plan and write calls for a part of `part` tokens."""
    plan = PLAN_REPLY_BASE + int(part * PLAN_REPLY_RATIO)
    write = min(WRITE_REPLY_MAX, WRITE_REPLY_BASE + int(part * WRITE_REPLY_RATIO))
    return plan, write


def _page_size(vault: Vault) -> int:
    """Average tokens of one page: measured in this vault, or a typical page."""
    slugs = vault.page_slugs()
    if not slugs:
        return PAGE_TOKENS
    return sum(estimate_tokens(vault.read_page(slug).body) for slug in slugs) // len(slugs)


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
    # A source added for retrieval only still costs its wiki pages.
    known = {e["sha256"] for key, e in vault.sources().items() if vault.in_wiki(key)}
    fixed = estimate_tokens(SYSTEM + vault.schema()) + PROMPT_OVERHEAD
    index = estimate_tokens(vault.index())
    page_count = len(vault.page_slugs())
    page_size = _page_size(vault)
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
            updates = page_size * min(MAX_UPDATES // 2, page_count)
            input_tokens += (fixed + part + index) + (fixed + part + updates)
            output_tokens += sum(reply_tokens(part))
            page_count += PAGES_PER_PART
            index += PAGES_PER_PART * INDEX_TOKENS_PER_PAGE

    priced = price_input > 0 or price_output > 0
    usd = (input_tokens * price_input + output_tokens * price_output) / 1_000_000
    return Estimate(files, calls, input_tokens, output_tokens, usd if priced else None)
