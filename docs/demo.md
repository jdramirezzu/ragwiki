# Walkthrough: three notes become a wiki

In about five minutes you turn three lecture notes into linked wiki pages and ask them
three questions: one a single note answers, one that needs two notes, and one the notes
cannot answer.

## Before you start

- wikinotes installed from a clone (`uv sync`), and a model configured as in the
  [README](../README.md#quick-start).
- Optional but recommended: set `WIKINOTES_PRICE_INPUT` and `WIKINOTES_PRICE_OUTPUT` so you
  see prices, and `WIKINOTES_MAX_USD=0.10` as a safety cap.

## Steps

Run every command from the repository folder.

1. Create a vault outside the repository:

   ```bash
   uv run wikinotes init ~/wikinotes-demo
   ```

2. See what adding the notes would cost. Nothing is sent to the model yet:

   ```bash
   uv run wikinotes add examples/cell-biology/*.md --vault ~/wikinotes-demo --estimate
   ```

3. Add the notes. Each file reports the pages it created or updated:

   ```bash
   uv run wikinotes add examples/cell-biology/*.md --vault ~/wikinotes-demo
   ```

4. Ask the three questions:

   ```bash
   uv run wikinotes ask "What do mitochondria do?" --vault ~/wikinotes-demo
   uv run wikinotes ask "In a plant, where does the glucose used in cellular respiration come from?" --vault ~/wikinotes-demo
   uv run wikinotes ask "How many chromosomes does a human cell have?" --vault ~/wikinotes-demo
   ```

5. Open `~/wikinotes-demo` in [Obsidian](https://obsidian.md) and click a citation: it
   opens the exact paragraph of the note it came from.

## What to check

| Step | You should see |
|---|---|
| Estimate | Three files, about six model calls, and a price if you configured one |
| Add | Pages such as a cell, mitochondria or photosynthesis page. The exact pages depend on the model |
| Question 1 | An answer with citations to the respiration or cell note |
| Question 2 | An answer that cites **both** the respiration and the photosynthesis notes |
| Question 3 | `Not in your notes:` and no made-up number. The notes never mention chromosomes |
| Any answer | Every citation listed under `Sources:` shows the paragraph it points to |

If question 3 gets an answer, or a citation does not match its claim, that is a bug worth
[reporting](https://github.com/jdramirezzu/wikinotes/issues): include the model you used.

## Trying other formats

The same commands accept PDF, Word, PowerPoint and photos of notes. A photo needs a
model that can see images; see the README for `WIKINOTES_VISION_MODEL`.

## Undo

The vault is a Git repository and every `add` is one commit, so `git -C ~/wikinotes-demo
revert HEAD` undoes the last one. Delete the folder to start over.
