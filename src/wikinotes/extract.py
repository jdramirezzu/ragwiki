"""Turn a user's file into a Source: Markdown split into citable paragraphs."""

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from wikinotes.domain import Block, Source
from wikinotes.markdown import is_heading, split_blocks, split_frontmatter


class UnsupportedFormat(Exception):
    """Raised when no extractor handles the file's extension."""


def _read_text(path: Path) -> str:
    _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return body


# Extension -> function returning the document as Markdown text.
EXTRACTORS: dict[str, Callable[[Path], str]] = {
    ".md": _read_text,
    ".markdown": _read_text,
    ".txt": _read_text,
}


def number_blocks(markdown: str) -> tuple[Block, ...]:
    """Give every non-heading block a sequential anchor: p1, p2, ..."""
    blocks: list[Block] = []
    count = 0
    for text in split_blocks(markdown):
        if is_heading(text):
            blocks.append(Block(text))
        else:
            count += 1
            blocks.append(Block(text, f"p{count}"))
    return tuple(blocks)


def _title(blocks: tuple[Block, ...], path: Path) -> str:
    for block in blocks:
        match = re.match(r"^#\s+(.+)$", block.text)
        if match:
            return match.group(1).strip()
    return re.sub(r"[-_]+", " ", path.stem).strip()


def extract(path: Path) -> Source:
    path = Path(path)
    extractor = EXTRACTORS.get(path.suffix.lower())
    if extractor is None:
        supported = ", ".join(sorted(EXTRACTORS))
        raise UnsupportedFormat(
            f"Cannot read '{path.suffix}' files yet ({path.name}). Supported: {supported}"
        )
    blocks = number_blocks(extractor(path))
    return Source(
        title=_title(blocks, path),
        original=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        blocks=blocks,
    )
