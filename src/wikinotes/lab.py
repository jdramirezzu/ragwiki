"""Helpers for the comparison lab, kept apart from Streamlit so they can be tested.

The lab itself is `lab_app.py`, a Streamlit script started by `wikinotes lab`.
"""

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from wikinotes.compare import Comparison
from wikinotes.vault import STATE_DIR, Vault

# PDFs, binary text documents (Word, PowerPoint) and plain text.
LAB_TYPES = ("pdf", "docx", "pptx", "md", "markdown", "txt")
UPLOADS = "uploads"

_CITATION = re.compile(r" ?\[\[([^\[\]|#]+)#\^(p\d+)\]\]")
_LINK = re.compile(r"\[\[([^\[\]|#]+)(?:\|([^\[\]]*))?\]\]")


def save_upload(vault: Vault, name: str, data: bytes) -> Path:
    """Keep an uploaded file inside the vault so it can be ingested and found again."""
    safe = Path(name).name or "upload"
    if Path(safe).suffix.lower().lstrip(".") not in LAB_TYPES:
        raise ValueError(f"{safe}: only {', '.join(LAB_TYPES)} files can be compared")
    folder = vault.root / STATE_DIR / UPLOADS
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe
    path.write_bytes(data)
    return path


def readable(text: str) -> str:
    """Turn wiki syntax into plain Markdown: citations become `[source ¶p2]`."""
    text = _CITATION.sub(lambda m: f" `{m.group(1)} ¶{m.group(2)}`", text)
    return _LINK.sub(lambda m: f"*{m.group(2) or m.group(1)}*", text)


def money(usd: float | None) -> str:
    return "unknown" if usd is None else f"${usd:.4f}"


_COLUMNS = (
    "id",
    "time",
    "question",
    "verdict",
    "note",
    "expected",
    "wiki_correct",
    "rag_correct",
    "wiki_found",
    "wiki_calls",
    "wiki_input_tokens",
    "wiki_output_tokens",
    "wiki_seconds",
    "wiki_usd",
    "wiki_citations",
    "rag_found",
    "rag_calls",
    "rag_input_tokens",
    "rag_output_tokens",
    "rag_seconds",
    "rag_usd",
    "rag_citations",
)


def rows(comparisons: Iterable[Comparison]) -> list[dict]:
    """One flat row per comparison, for a table or a spreadsheet."""
    table = []
    for item in comparisons:
        row = {"id": item.id, "time": item.time, "question": item.question}
        row |= {"verdict": item.verdict or "", "note": item.note, "expected": item.expected}
        for name in ("wiki", "rag"):
            correct = item.correct(name)
            row[f"{name}_correct"] = "" if correct is None else correct
        for arm in (item.wiki, item.rag):
            data = asdict(arm)
            for key in ("found", "calls", "input_tokens", "output_tokens", "seconds", "usd"):
                row[f"{arm.arm}_{key}"] = data[key]
            row[f"{arm.arm}_citations"] = " ".join(arm.citations)
        table.append(row)
    return table


def to_csv(comparisons: Iterable[Comparison]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_COLUMNS)
    writer.writeheader()
    writer.writerows(rows(comparisons))
    return buffer.getvalue()
