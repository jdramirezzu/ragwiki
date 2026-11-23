"""The vault: a folder of plain Markdown that holds sources, extracted text and wiki pages."""

import json
import re
import shutil
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

from wikinotes.domain import Block, Page, Source, slugify
from wikinotes.markdown import join_frontmatter, split_blocks, split_frontmatter

STATE_DIR = ".wikinotes"

DEFAULT_SCHEMA = """# Wiki conventions

Edit this file to tell the model how you want your wiki written. It is sent with every
request.

- Language: write pages in the language of the source material.
- Page types: `concept` (an idea, method or term), `source` (a summary of one document),
  `synthesis` (an answer or comparison that connects several pages).
- Style: short paragraphs, plain words, one idea per page. Aim for under 600 words.
- When a new source changes or contradicts an older claim, keep both, say which one is
  newer, and cite each.
"""

_GITIGNORE = (
    ".wikinotes/calls.jsonl\n.wikinotes/uploads/\n.wikinotes/embeddings/\n.obsidian/workspace*\n"
)
_ANCHOR_ONLY = re.compile(r"^\^(p\d+)$")
_ANCHOR_TRAILING = re.compile(r"^(.*\S) \^(p\d+)$", re.DOTALL)
# Obsidian needs the block id on its own line after lists, quotes, tables and code.
_STRUCTURED = re.compile(r"^(```|~~~|\||>|[-*+] |\d+[.)] )")


class VaultError(Exception):
    """Raised when a vault is missing, already exists or holds unexpected content."""


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # --- locating and creating -------------------------------------------------------

    @classmethod
    def create(cls, root: Path) -> "Vault":
        root = Path(root)
        if (root / STATE_DIR).exists():
            raise VaultError(f"{root} is already a wikinotes vault")
        for name in ("sources", "extracted", "wiki", STATE_DIR):
            (root / name).mkdir(parents=True, exist_ok=True)
        vault = cls(root)
        vault._write_state({"version": 1, "sources": {}})
        defaults = {"SCHEMA.md": DEFAULT_SCHEMA, "log.md": "# Log\n", ".gitignore": _GITIGNORE}
        for name, text in defaults.items():
            if not (root / name).exists():
                (root / name).write_text(text, encoding="utf-8")
        vault.rebuild_index()
        if shutil.which("git") and not (root / ".git").exists():
            vault._git("init", "-q")
        vault.commit("init: new wikinotes vault")
        return vault

    @classmethod
    def find(cls, start: Path) -> "Vault":
        start = Path(start).resolve()
        for folder in (start, *start.parents):
            if (folder / STATE_DIR / "state.json").is_file():
                return cls(folder)
        raise VaultError("No wikinotes vault found here. Run `wikinotes init` first.")

    # --- sources ---------------------------------------------------------------------

    def sources(self) -> dict[str, dict]:
        return self._read_state()["sources"]

    def has_hash(self, sha256: str) -> bool:
        return any(entry["sha256"] == sha256 for entry in self.sources().values())

    def new_id(self, title: str) -> str:
        """A source id. The `src-` prefix keeps sources and pages from sharing a link name."""
        taken = set(self.sources())
        base = f"src-{slugify(title)}"
        candidate, number = base, 1
        while candidate in taken:
            number += 1
            candidate = f"{base}-{number}"
        return candidate

    def add_source(self, source: Source, original: Path) -> Source:
        stored = source if source.id else replace(source, id=self.new_id(source.title))
        original = Path(original)
        shutil.copyfile(original, self.root / "sources" / f"{stored.id}{original.suffix.lower()}")
        header = {
            "id": stored.id,
            "title": stored.title,
            "original": stored.original,
            "sha256": stored.sha256,
        }
        self._extracted_path(stored.id).write_text(
            join_frontmatter(header, _render_blocks(stored.blocks)), encoding="utf-8"
        )
        state = self._read_state()
        state["sources"][stored.id] = {
            "title": stored.title,
            "original": stored.original,
            "sha256": stored.sha256,
            "added": date.today().isoformat(),
        }
        self._write_state(state)
        return stored

    def load_source(self, source_id: str) -> Source:
        path = self._extracted_path(source_id)
        if not path.is_file():
            raise VaultError(f"Unknown source: {source_id}")
        header, body = split_frontmatter(path.read_text(encoding="utf-8"))
        return Source(
            id=source_id,
            title=str(header.get("title", source_id)),
            original=str(header.get("original", "")),
            sha256=str(header.get("sha256", "")),
            blocks=_parse_blocks(body),
        )

    # --- pages -----------------------------------------------------------------------

    def page_slugs(self) -> list[str]:
        return sorted(path.stem for path in (self.root / "wiki").glob("*.md"))

    def read_page(self, slug: str) -> Page:
        path = self._page_path(slug)
        if not path.is_file():
            raise VaultError(f"Unknown page: {slug}")
        header, body = split_frontmatter(path.read_text(encoding="utf-8"))
        return Page(
            slug=slug,
            title=str(header.get("title", slug)),
            type=str(header.get("type", "concept")),
            summary=str(header.get("summary", "")),
            sources=[str(item) for item in header.get("sources") or []],
            updated=str(header.get("updated", "")),
            body=body.strip(),
        )

    def write_page(self, page: Page) -> None:
        header = {
            "title": page.title,
            "type": page.type,
            "summary": page.summary,
            "sources": page.sources,
            "updated": page.updated or date.today().isoformat(),
        }
        self._page_path(page.slug).write_text(join_frontmatter(header, page.body), encoding="utf-8")

    # --- index, log, history ---------------------------------------------------------

    def index_text(self, pending: dict[str, Page] | None = None) -> str:
        """The catalog of pages and sources. `pending` holds pages not written to disk yet."""
        pending = pending or {}
        lines = ["# Index", "", "## Pages", ""]
        for slug in sorted(set(self.page_slugs()) | set(pending)):
            page = pending.get(slug) or self.read_page(slug)
            lines.append(f"- [[{slug}]] ({page.type}): {page.summary}")
        lines += ["", "## Sources", ""]
        for source_id, entry in sorted(self.sources().items()):
            lines.append(f"- [[{source_id}]]: {entry['title']}")
        return "\n".join(lines) + "\n"

    def rebuild_index(self) -> None:
        (self.root / "index.md").write_text(self.index_text(), encoding="utf-8")

    def index(self) -> str:
        return (self.root / "index.md").read_text(encoding="utf-8")

    def schema(self) -> str:
        path = self.root / "SCHEMA.md"
        return path.read_text(encoding="utf-8") if path.is_file() else DEFAULT_SCHEMA

    def append_log(self, message: str) -> None:
        with (self.root / "log.md").open("a", encoding="utf-8") as handle:
            handle.write(f"- {date.today().isoformat()} {message}\n")

    def commit(self, message: str) -> None:
        """Snapshot the vault so any ingestion can be undone. A no-op without Git."""
        if shutil.which("git") is None or not (self.root / ".git").exists():
            return
        self._git("add", "-A")
        if not self._git("status", "--porcelain").stdout.strip():
            return
        identity: list[str] = []
        if not self._git("config", "user.name").stdout.strip():
            identity = ["-c", "user.name=wikinotes", "-c", "user.email=wikinotes@localhost"]
        self._git(*identity, "commit", "-q", "-m", message, check=True)

    # --- internals -------------------------------------------------------------------

    def _git(self, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=check
        )

    def _extracted_path(self, source_id: str) -> Path:
        return self.root / "extracted" / f"{source_id}.md"

    def _page_path(self, slug: str) -> Path:
        return self.root / "wiki" / f"{slug}.md"

    def _state_path(self) -> Path:
        return self.root / STATE_DIR / "state.json"

    def _read_state(self) -> dict:
        return json.loads(self._state_path().read_text(encoding="utf-8"))

    def _write_state(self, state: dict) -> None:
        self._state_path().write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def _render_blocks(blocks: tuple[Block, ...]) -> str:
    """Write anchors as Obsidian block ids, so `[[source#^p3]]` opens that paragraph."""
    parts: list[str] = []
    for block in blocks:
        if block.anchor is None:
            parts.append(block.text)
        elif _STRUCTURED.match(block.text):
            parts += [block.text, f"^{block.anchor}"]
        else:
            parts.append(f"{block.text} ^{block.anchor}")
    return "\n\n".join(parts)


def _parse_blocks(body: str) -> tuple[Block, ...]:
    blocks: list[Block] = []
    for raw in split_blocks(body):
        alone = _ANCHOR_ONLY.match(raw)
        trailing = _ANCHOR_TRAILING.match(raw)
        if alone and blocks:
            blocks[-1] = Block(blocks[-1].text, alone.group(1))
        elif trailing:
            blocks.append(Block(trailing.group(1), trailing.group(2)))
        else:
            blocks.append(Block(raw))
    return tuple(blocks)
