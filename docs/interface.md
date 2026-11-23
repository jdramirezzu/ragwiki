# Designing an interface for ragwiki

ragwiki works from the command line and from the lab (`ragwiki lab`), a local web page
that compares the wiki and RAG on a person's files. This guide is for whoever designs and
builds the next interfaces: it says what the product already does, what the interface
must make visible, and which decisions are still open. It does not prescribe how anything
should look.

## The short version

- The interface is a new front for the same library. Everything it needs comes from
  `import ragwiki`; the command line uses nothing else.
- Five moments need a design: set up, add material, read the wiki, ask, review.
- Four promises must stay visible in any design: traceable, honest, costs shown first,
  nothing half-written.

## The promises the interface must keep visible

| Promise | What it means on screen |
|---|---|
| Traceable | Every claim shows where it comes from. A citation opens the exact source paragraph, ideally next to the claim |
| Honest | "Not in your notes" is a normal, respectable result, not an error. Design it as carefully as an answer |
| Costs shown first | Before any paid model call the person sees an estimate and chooses to continue |
| Nothing half-written | An ingestion either completes or changes nothing. Show it as one step that can be undone |
| Your files | The wiki is a folder of Markdown. Show where it is and never hide it behind the app |

## The five moments

| Moment | What the person does | Library call | States to design |
|---|---|---|---|
| Set up | Chooses a folder and a model | `Vault.create`, `Vault.find`, `metered_from_env` | No model configured, wrong key, local model with no key |
| Add material | Drops files or photos | `estimate_ingest`, then `ingest` with `on_progress` | Estimate, confirm, waiting, long source in parts, photo being transcribed, damaged file, scan without text, already added, failed with nothing changed |
| Read the wiki | Browses pages and follows links | `Vault.page_slugs`, `Vault.read_page`, `Vault.index` | Empty wiki, page with many sources, link to a page that does not exist yet |
| Ask | Types a question | `ask`, then `cited_paragraph` for each citation | Thinking, answer with citations, partial answer, not in your notes, spending cap reached |
| Review | Checks what changed and what it cost | `log.md`, `.ragwiki/calls.jsonl`, the vault's Git history | First use with no history, a transcription that needs correcting |

## Using the library

```python
from pathlib import Path

import ragwiki

vault = ragwiki.Vault.find(Path.home() / "my-wiki")  # or Vault.create(folder)
model = ragwiki.metered_from_env(vault.root / ".ragwiki" / "calls.jsonl")

estimate = ragwiki.estimate_ingest(vault, [path])  # no model call, safe to run anytime
# estimate.calls, estimate.input_tokens, estimate.output_tokens, estimate.usd (None = unknown)

result = ragwiki.ingest(vault, model, path, on_progress=show)
# show receives Progress(file, part, parts, stage); stage is "transcribing", "planning"
# or "writing". result.created, result.updated, result.dropped_citations, result.skipped

answer = ragwiki.ask(vault, model, "What do mitochondria do?")
# answer.found, answer.text (Markdown), answer.citations, answer.pages_read
for citation in answer.citations:
    paragraph = ragwiki.cited_paragraph(vault, citation)
    # paragraph.source_title, paragraph.anchor, paragraph.text
```

Errors to turn into messages: `ConfigError`, `ModelError`, `BudgetExceeded`,
`UnsupportedFormat`, `UnreadableSource`, `IngestError`, `VaultError`. Each carries a
sentence written for the person, not for a developer.

## What is in the vault

| Path | Content | Useful for |
|---|---|---|
| `wiki/<slug>.md` | A page. Front matter: `title`, `type`, `summary`, `sources`, `updated` | Page view, lists, filters by type |
| `extracted/<source-id>.md` | A source as Markdown. Each citable paragraph ends with `^p1`, `^p2`, ... | Showing the cited paragraph in context |
| `sources/` | The original files, untouched | Showing a photo beside its transcription |
| `index.md`, `log.md` | Catalog of pages and history of additions | Home screen, activity |
| `.ragwiki/calls.jsonl` | One line per model call: time, seconds, tokens, price | A running cost total |

A citation is written `[[src-cell-biology#^p2]]` and a link to a page `[[mitochondria]]`.
Both are Obsidian syntax, so the folder already opens there with a working graph.

## Suggestions, not decisions

| Option | Why consider it | What it costs |
|---|---|---|
| Local web app: a small Python server over the library and a browser front | Any design stack works, runs on every system, nothing to install beyond ragwiki. A good first step | Needs a thin HTTP layer that does not exist yet |
| Obsidian plugin | People who keep notes are often already there, and reading and linking are solved | Plugins are TypeScript, so the Python library must run beside it |
| Desktop app | Feels like a product, works by double click | Packaging and updates for three systems. Easier once the web app exists |

Whatever the form, three ideas are worth testing early:

1. **Source beside claim.** Reading a page with the cited paragraph visible in a side panel
   is what makes the wiki trustworthy. It may be the signature of the product.
2. **The estimate as a calm step.** "This will take about 6 calls and cost about $0.01"
   with one button, instead of a warning dialog.
3. **Photos checked at a glance.** A photo and its transcription side by side, editable,
   since handwriting is where a model is most likely to be wrong.

## States that are easy to forget

- [ ] Model calls take from a few seconds to a minute; a long source takes several minutes.
- [ ] A citation was removed because it did not resolve (`dropped_citations`).
- [ ] The same file is added twice (`skipped`).
- [ ] The answer is partial: it says what is missing.
- [ ] No price is configured, so the cost is unknown rather than zero.
- [ ] The spending cap stops a command halfway through a list of files.
- [ ] The wiki is in another language than the interface. Pages follow the language of the
      source material, and the project documents itself in English and Spanish.
- [ ] Meaning never depends on color alone, and everything works with a keyboard.

## What the library does not offer yet

These are known gaps. Open an issue for whichever the design needs first.

| Gap | Today |
|---|---|
| No public HTTP API | The lab's server (`server.py`) exposes what its page needs, on localhost only; it is not a stable API yet |
| No cancel | An ingestion runs to the end or fails. `ingest` blocks, so run it off the interface thread |
| No streamed answers | `ask` returns the whole answer at once |
| No editing API | Pages are plain files anyone can edit, but a later ingestion may rewrite an edited page |
| No checks of the whole wiki | A `lint` command and saving answers as pages are planned for M3 |

## Open questions for the designer

1. Who is the first person this is for: a student with lecture notes, or anyone with
   documents? The examples and wording follow from that.
2. Is reading the wiki part of this interface, or does it hand over to Obsidian?
3. Where does model setup live? It is the least friendly step today.
4. What should a person feel when the answer is "not in your notes"?

## Next step

Run the [walkthrough](demo.md) once from the command line to see every state described
here, then sketch the "add material" moment first: it carries the most states.
