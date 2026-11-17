"""Small Markdown helpers shared by extraction and the vault."""

import re

import yaml

_HEADING = re.compile(r"^#{1,6}\s")
_FENCES = ("```", "~~~")


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Separate a leading YAML block from the body. Returns ({}, text) when there is none."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    data = yaml.safe_load(text[4:end]) or {}
    body = text[end + 4 :].lstrip("\n")
    return (data if isinstance(data, dict) else {}), body


def join_frontmatter(data: dict, body: str) -> str:
    header = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return f"---\n{header}---\n\n{body.strip()}\n"


def split_blocks(text: str) -> list[str]:
    """Split Markdown on blank lines, keeping fenced code whole and headings on their own."""
    blocks: list[str] = []
    current: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if current:
            blocks.append("\n".join(current))
            current.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if fence is not None:
            current.append(line)
            if stripped.startswith(fence):
                fence = None
        elif stripped.startswith(_FENCES):
            fence = stripped[:3]
            current.append(line)
        elif not stripped:
            flush()
        elif _HEADING.match(stripped):
            flush()
            blocks.append(stripped)
        else:
            current.append(line.rstrip())
    flush()
    return blocks


def is_heading(block: str) -> bool:
    return bool(_HEADING.match(block))
