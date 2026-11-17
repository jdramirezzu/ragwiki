"""Turn a user's file into a Source: Markdown split into citable paragraphs."""

import hashlib
import re
import textwrap
import zipfile
from collections.abc import Callable
from pathlib import Path

from wikinotes.domain import Block, Source
from wikinotes.markdown import is_heading, split_blocks, split_frontmatter
from wikinotes.models import estimate_tokens

# A citable block larger than this is cut into smaller ones. Converters can return a whole
# spreadsheet or a page without blank lines as one block, which no model could take in and
# which would make a citation point at far too much text.
MAX_BLOCK_TOKENS = 500
_TABLE_RULE = re.compile(r"^\|[\s:|-]+\|$")
_FENCES = ("```", "~~~")


class UnsupportedFormat(Exception):
    """Raised when no extractor handles the file's extension."""


class UnreadableSource(Exception):
    """Raised when a supported file is damaged or holds no text."""


# The converter marks slide boundaries with HTML comments, which are noise in a note.
_CONVERTER_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _read_text(path: Path) -> str:
    _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return body


def _is_pdf(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def _read_document(path: Path, looks_right: Callable[[Path], bool]) -> str:
    """Convert a PDF or office file with markitdown.

    The file signature is checked first because the converter silently falls back to
    reading a damaged file as plain text, which would put garbage in the wiki.
    """
    if not looks_right(path):
        raise UnreadableSource(f"{path.name} is damaged or is not a real {path.suffix} file.")
    from markitdown import MarkItDown, MarkItDownException

    try:
        markdown = MarkItDown(enable_plugins=False).convert(str(path)).markdown
    except MarkItDownException as error:
        raise UnreadableSource(f"{path.name} could not be read: {error}") from error
    return _CONVERTER_COMMENT.sub("\n", markdown)


def _read_pdf(path: Path) -> str:
    return _read_document(path, _is_pdf)


def _read_office(path: Path) -> str:
    return _read_document(path, zipfile.is_zipfile)


# Extension -> function returning the document as Markdown text.
EXTRACTORS: dict[str, Callable[[Path], str]] = {
    ".md": _read_text,
    ".markdown": _read_text,
    ".txt": _read_text,
    ".pdf": _read_pdf,
    ".docx": _read_office,
    ".pptx": _read_office,
    ".xlsx": _read_office,
}


# Photos of notes. They carry no text, so a model has to transcribe them.
IMAGE_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def is_photo(path: Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_TYPES


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _limit(text: str) -> list[str]:
    """Cut a block that exceeds MAX_BLOCK_TOKENS between lines; code is left whole.

    Every piece of a table repeats the header, so each one still reads as a table.
    """
    if estimate_tokens(text) <= MAX_BLOCK_TOKENS or text.startswith(_FENCES):
        return [text]
    lines = text.split("\n")
    is_table = len(lines) > 2 and lines[0].startswith("|") and _TABLE_RULE.match(lines[1])
    header = lines[:2] if is_table else []
    budget = MAX_BLOCK_TOKENS - estimate_tokens("\n".join(header))
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines[len(header) :]:
        # A line that is too long on its own is cut between words. Table rows are kept.
        segments = (
            [line]
            if is_table
            else textwrap.wrap(
                line, width=budget * 3, break_long_words=False, break_on_hyphens=False
            )
        )
        for segment in segments or [line]:
            cost = estimate_tokens(segment) + 1
            if current and size + cost > budget:
                pieces.append("\n".join(header + current))
                current, size = [], 0
            current.append(segment)
            size += cost
    if current:
        pieces.append("\n".join(header + current))
    return pieces


def number_blocks(markdown: str) -> tuple[Block, ...]:
    """Give every non-heading block a sequential anchor: p1, p2, ..."""
    blocks: list[Block] = []
    count = 0
    for text in split_blocks(markdown):
        if is_heading(text):
            blocks.append(Block(text))
            continue
        for piece in _limit(text):
            count += 1
            blocks.append(Block(piece, f"p{count}"))
    return tuple(blocks)


def _title(blocks: tuple[Block, ...], path: Path) -> str:
    for block in blocks:
        match = re.match(r"^#\s+(.+)$", block.text)
        if match:
            return match.group(1).strip()
    return re.sub(r"[-_]+", " ", path.stem).strip()


def source_from_markdown(path: Path, markdown: str) -> Source:
    """Build the Source for `path` from its content already converted to Markdown."""
    blocks = number_blocks(markdown)
    if not any(block.anchor for block in blocks):
        raise UnreadableSource(
            f"No text found in {path.name}. If it is a scan, add its pages as photos instead."
        )
    return Source(
        title=_title(blocks, path),
        original=path.name,
        sha256=file_hash(path),
        blocks=blocks,
    )


def extract(path: Path, read_image: Callable[[Path], str] | None = None) -> Source:
    """Read a file into a Source. `read_image` transcribes a photo into Markdown."""
    path = Path(path)
    if is_photo(path):
        if read_image is None:
            raise UnreadableSource(
                f"{path.name} is a photo: it needs a model to be transcribed. Add it with "
                "`wikinotes add`."
            )
        return source_from_markdown(path, read_image(path))
    extractor = EXTRACTORS.get(path.suffix.lower())
    if extractor is None:
        supported = ", ".join(sorted({*EXTRACTORS, *IMAGE_TYPES}))
        raise UnsupportedFormat(
            f"Cannot read '{path.suffix}' files yet ({path.name}). Supported: {supported}"
        )
    return source_from_markdown(path, extractor(path))
