# wikinotes

**Note-taking, evolved.** Give wikinotes your study material and a language model builds
and maintains a personal wiki from it: interlinked Markdown pages you can read, query and
keep growing. Every claim links back to the paragraph it came from.

[Leer en español](README.es.md)

> Status: early development. The commands below are being built in the open; see the
> [roadmap](#roadmap) for what works today.

## Quick start

wikinotes is not on PyPI yet. Install it from a clone with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/jdramirezzu/wikinotes.git && cd wikinotes
uv sync
```

1. Point wikinotes at a model. Any OpenAI-compatible endpoint works:

   ```bash
   export WIKINOTES_MODEL="<model-name>"
   export WIKINOTES_BASE_URL="<provider-url>"   # for a local Ollama: http://localhost:11434/v1
   export WIKINOTES_API_KEY="<your-key>"        # not needed for a local model
   ```

2. Create a vault and add your notes:

   ```bash
   uv run wikinotes init my-wiki
   cd my-wiki
   uv run wikinotes add ~/notes/biology.md
   uv run wikinotes status
   ```

3. Ask a question. The answer cites the paragraphs it comes from, and says so when your
   notes do not cover it:

   ```bash
   uv run wikinotes ask "What do mitochondria do?"
   ```

4. Open `my-wiki/` in Obsidian or any editor and read your pages.

| Optional variable | Meaning |
|---|---|
| `WIKINOTES_PRICE_INPUT`, `WIKINOTES_PRICE_OUTPUT` | Your provider's price in USD per million tokens, so costs are reported |
| `WIKINOTES_MAX_USD` | Spending cap for one command |
| `WIKINOTES_VAULT` | Vault folder, when you are not inside it |

Today wikinotes reads Markdown and text (`.md`, `.markdown`, `.txt`), PDF, Word (`.docx`),
PowerPoint (`.pptx`) and Excel (`.xlsx`). A PDF needs a text layer; scans are not read yet. A source must fit in the model's context
window; splitting long documents is planned.

## Why a wiki and not just search

Most "chat with your documents" tools search your files again for every question. wikinotes
instead writes knowledge down once, as pages that connect ideas across your sources, and
keeps those pages up to date as you add material.

This design comes from a master's research project that compared both approaches on the
same model and the same documents:

| Finding | What wikinotes does about it |
|---|---|
| The wiki answered more questions correctly (0.78 vs 0.54), and far more when the answer needed several sources (1.00 vs 0.42) | The wiki is the core of the product |
| For a single fact from one source both were about even, and search cost about a tenth | Search over the original text is the fallback for precise lookups |
| The wiki sometimes answered when it should have said "not in your notes", and kept outdated values | Explicit abstention, citations verified by code, and a `lint` command |

Those numbers come from one experiment on 50 scientific papers. They motivated the design;
they are not a guarantee for your notes.

## How it works

```
my-wiki/
  sources/      your original files, never modified
  extracted/    each source as Markdown with numbered paragraphs
  wiki/         the pages the model writes, linked with [[wikilinks]]
  index.md      catalog of pages
  log.md        history of what was added
  SCHEMA.md     your conventions: page types, language, style
```

The folder is plain Markdown. Open it in [Obsidian](https://obsidian.md) or any editor: the
links and the graph work, and a citation takes you to the exact source paragraph.

## Principles

- **Your knowledge stays yours.** Plain files on your disk, under Git, with no lock-in.
- **Any model.** Works with any OpenAI-compatible endpoint, including local models.
- **Traceable.** A citation that does not resolve to a real paragraph is removed.
- **Honest.** When your notes do not answer a question, wikinotes says so.
- **Costs are visible.** Every model call records tokens, time and price, with a spending cap.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Repository, packaging, CI | Done |
| M1 | Vault, Markdown ingestion, questions with verified citations | Done |
| M2 | PDF, office files, photos of handwritten notes | Planned |
| M3 | Source-text search fallback, `lint`, saving answers as pages | Planned |
| Later | Graphical interface, flashcards, shared wikis | Ideas welcome |

## Contributing

Contributions of any size are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
