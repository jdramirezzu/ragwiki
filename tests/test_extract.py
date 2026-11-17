import pytest

from wikinotes.extract import UnsupportedFormat, extract

NOTE = """---
tags: [biology]
---
# Cell biology

The cell is the basic unit of life.

## Organelles

Mitochondria produce ATP.
They have their own DNA.

```python
print("a blank line inside a fence")

print("stays in one block")
```
"""


def test_markdown_gets_a_title_and_numbered_paragraphs(tmp_path):
    path = tmp_path / "cells.md"
    path.write_text(NOTE, encoding="utf-8")

    source = extract(path)

    assert source.title == "Cell biology"
    assert source.original == "cells.md"
    assert len(source.sha256) == 64
    assert source.paragraphs == {
        "p1": "The cell is the basic unit of life.",
        "p2": "Mitochondria produce ATP.\nThey have their own DNA.",
        "p3": '```python\nprint("a blank line inside a fence")\n\nprint("stays in one block")\n```',
    }


def test_headings_are_kept_but_cannot_be_cited(tmp_path):
    path = tmp_path / "cells.md"
    path.write_text(NOTE, encoding="utf-8")

    source = extract(path)

    headings = [block.text for block in source.blocks if block.anchor is None]
    assert headings == ["# Cell biology", "## Organelles"]


def test_a_note_without_heading_takes_its_title_from_the_file_name(tmp_path):
    path = tmp_path / "lecture-3_notes.txt"
    path.write_text("Just one paragraph.", encoding="utf-8")

    assert extract(path).title == "lecture 3 notes"


def test_unsupported_format_names_the_supported_ones(tmp_path):
    path = tmp_path / "slides.xyz"
    path.write_bytes(b"\x00")

    with pytest.raises(UnsupportedFormat) as error:
        extract(path)

    assert ".xyz" in str(error.value)
    assert ".md" in str(error.value)
