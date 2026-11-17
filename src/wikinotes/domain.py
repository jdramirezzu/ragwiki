"""Core types. No file or network access happens here."""

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Block:
    """A piece of a source. Only blocks with an anchor (`p1`, `p2`, ...) can be cited."""

    text: str
    anchor: str | None = None


@dataclass(frozen=True)
class Source:
    """A user's document after extraction to Markdown."""

    title: str
    original: str
    sha256: str
    blocks: tuple[Block, ...]
    id: str = ""

    @property
    def paragraphs(self) -> dict[str, str]:
        return {block.anchor: block.text for block in self.blocks if block.anchor}


@dataclass
class Page:
    """A wiki page written by the model and validated by code."""

    slug: str
    title: str
    type: str
    summary: str
    body: str
    sources: list[str] = field(default_factory=list)
    updated: str = ""


def slugify(text: str) -> str:
    """Lowercase ASCII words joined by hyphens, safe as a file name and as a link target."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:60].strip("-") or "untitled"
