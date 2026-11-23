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

No notes at hand? Follow the [walkthrough](docs/demo.md) with the example notes in
[`examples/`](examples/README.md).

| Optional variable | Meaning |
|---|---|
| `WIKINOTES_PRICE_INPUT`, `WIKINOTES_PRICE_OUTPUT` | Your provider's price in USD per million tokens, so costs are reported |
| `WIKINOTES_MAX_USD` | Spending cap for one command |
| `WIKINOTES_VAULT` | Vault folder, when you are not inside it |
| `WIKINOTES_VISION_MODEL` | Model used for photos, when the main one cannot see images |
| `WIKINOTES_VISION_BASE_URL`, `WIKINOTES_VISION_API_KEY` | Only when the vision model is at another provider |
| `WIKINOTES_CONTEXT_TOKENS` | Your model's context window in tokens (default 32000). Lower it for small local models |

Today wikinotes reads Markdown and text (`.md`, `.markdown`, `.txt`), PDF, Word (`.docx`),
PowerPoint (`.pptx`) and photos of notes (`.png`, `.jpg`, `.jpeg`, `.webp`). Spreadsheets are
left out on purpose: they hold data rather than notes.

A photo is transcribed by a model that can see images. The transcription is saved in
`extracted/` next to your original photo, so you can check it. If your text model cannot
see images, set `WIKINOTES_VISION_MODEL` to one that can. A PDF needs a text layer: for a
scan, add its pages as photos.

Before any model call, `add` prints an estimate of the calls, tokens and price. When the
price is above zero it asks you to confirm; `--yes` skips the question and `--estimate`
only shows the estimate. The estimate is rough: token counts are approximated from text
length, and the real cost of each call is recorded in `.wikinotes/calls.jsonl`.

A source larger than the model's context window is split into parts, and nothing is written
unless every part succeeds. Paragraphs are never cut, so citations stay exact.

## Compare a wiki and RAG on your files

Not sure a wiki is worth it for your documents? The lab repeats the study's experiment on
your own material: the same model answers your questions twice, once from the wiki and once
from paragraphs retrieved from your files (RAG), and shows both answers side by side.

```bash
uv sync --extra lab
uv run wikinotes lab ~/my-lab
```

1. **Sources.** Choose PDFs, Word or PowerPoint files, or plain text (`.txt`, `.md`). You see
   the estimated cost of building the wiki before anything is spent.
2. **Compare.** Type the questions you care about, one per line. Optionally add `|` and the
   expected answer as key terms (`What produces ATP? | ATP, mitochondria`), or `none` when
   your files do not answer it. Each answer shows its citations, tokens, time and cost.
3. **Results.** Judge each pair of answers, download everything as CSV or JSONL, and read
   the recommendation: the wiki is suggested only when it answers clearly better (a gap of
   at least 0.10 over five or more evaluated questions); otherwise RAG, which is cheaper.

RAG retrieval is lexical (BM25) by default: offline and free. Set
`WIKINOTES_EMBEDDING_MODEL` to use embeddings from your provider instead. The study used
embeddings with 5 retrieved paragraphs; try several values of `k` before deciding.

## Why a wiki and not just search

Most "chat with your documents" tools search your files again for every question. wikinotes
instead writes knowledge down once, as pages that connect ideas across your sources, and
keeps those pages up to date as you add material.

This design comes from a [master's research project](https://github.com/1KVueltasAlCampo/llm-knowledge-management-wiki-agent) that compared both
approaches with the same model, the same 100 scientific papers and the same 100 questions:

| Finding | What wikinotes does about it |
|---|---|
| The wiki answered more questions correctly (0.70 vs 0.48 with 5 retrieved paragraphs), and its lead was largest when the answer joined several papers | The wiki is the core of the product |
| Each wiki question cost 7.2× and took 4.1× as long, plus a one-time cost to build the wiki. Giving RAG 20 paragraphs shrank the lead to +0.06, no longer significant | The [lab](#compare-a-wiki-and-rag-on-your-files) lets you check which one pays off for your files |
| The wiki kept what it learned but captured 63–80 % of what it could, and did not retire outdated values | Explicit abstention, citations verified by code, and a planned `lint` command |

Those numbers come from one experiment on arXiv papers. They motivated the design; they are
not a guarantee for your notes.

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
| M2 | PDF, office files, photos of handwritten notes, long sources, cost estimate | Done |
| Lab | Compare a wiki and RAG on your own files, with a recommendation | Done |
| M3 | Source-text search fallback, `lint`, saving answers as pages | Planned |
| Later | Graphical interface, flashcards, shared wikis | Ideas welcome |

## Contributing

Contributions of any size are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md).

The lab is the first graphical interface. If you design or build interfaces, read
[Designing an interface for wikinotes](docs/interface.md).

## License

[MIT](LICENSE)
