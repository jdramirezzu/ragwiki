import pytest
from files import PNG, make_docx, make_pdf, make_pptx

from wikinotes.extract import (
    MAX_BLOCK_TOKENS,
    UnreadableSource,
    UnsupportedFormat,
    extract,
    number_blocks,
)
from wikinotes.models import estimate_tokens

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
    assert ".png" in str(error.value)


def test_a_pdf_becomes_numbered_paragraphs_titled_after_the_file(tmp_path):
    path = make_pdf(
        tmp_path / "cell-biology.pdf", ["The cell is the unit of life.", "ATP is fuel."]
    )

    source = extract(path)

    assert source.title == "cell biology"
    assert source.original == "cell-biology.pdf"
    assert source.paragraphs == {"p1": "The cell is the unit of life.", "p2": "ATP is fuel."}


def test_a_word_document_becomes_numbered_paragraphs(tmp_path):
    path = make_docx(tmp_path / "cells.docx", ["The cell is the unit of life.", "ATP is fuel."])

    assert extract(path).paragraphs == {"p1": "The cell is the unit of life.", "p2": "ATP is fuel."}


def test_slides_keep_their_titles_as_headings_and_drop_converter_comments(tmp_path):
    path = make_pptx(
        tmp_path / "deck.pptx",
        [("Cell biology", "The cell is the unit of life."), ("Organelles", "ATP is fuel.")],
    )

    source = extract(path)

    assert source.title == "Cell biology"
    assert [block.text for block in source.blocks] == [
        "# Cell biology",
        "The cell is the unit of life.",
        "# Organelles",
        "ATP is fuel.",
    ]


def test_spreadsheets_are_not_read(tmp_path):
    # They hold data rather than notes: real ones came out as hundreds of thousands of tokens.
    path = tmp_path / "grades.xlsx"
    path.write_bytes(b"PK")

    with pytest.raises(UnsupportedFormat):
        extract(path)


@pytest.mark.parametrize("name", ["broken.pdf", "broken.docx"])
def test_a_file_that_is_not_what_its_extension_says_is_rejected(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"this is not a real document")

    with pytest.raises(UnreadableSource) as error:
        extract(path)

    assert name in str(error.value)


def test_a_document_without_text_is_rejected_and_suggests_photos(tmp_path):
    path = make_pdf(tmp_path / "scan.pdf", [])

    with pytest.raises(UnreadableSource) as error:
        extract(path)

    assert "scan.pdf" in str(error.value)
    assert "photo" in str(error.value)


def test_a_photo_is_transcribed_by_the_reader_it_is_given(tmp_path):
    path = tmp_path / "board.jpg"
    path.write_bytes(PNG)

    source = extract(path, read_image=lambda _: "# Cell biology\n\nThe cell is the unit of life.")

    assert source.title == "Cell biology"
    assert source.original == "board.jpg"
    assert source.paragraphs == {"p1": "The cell is the unit of life."}


def test_a_photo_without_a_reader_says_it_needs_a_model(tmp_path):
    path = tmp_path / "board.png"
    path.write_bytes(PNG)

    with pytest.raises(UnreadableSource) as error:
        extract(path)

    assert "board.png" in str(error.value)
    assert "model" in str(error.value)


def test_a_huge_table_is_cut_into_citable_tables_that_repeat_the_header():
    rows = [f"| organelle {n} | role {n} |" for n in range(200)]
    table = "\n".join(["| Name | Role |", "| --- | --- |", *rows])

    blocks = number_blocks(table)

    assert len(blocks) > 1
    assert all(block.anchor for block in blocks)
    assert all(block.text.startswith("| Name | Role |\n| --- | --- |\n") for block in blocks)
    assert all(estimate_tokens(block.text) <= MAX_BLOCK_TOKENS for block in blocks)
    assert [line for block in blocks for line in block.text.split("\n")[2:]] == rows


def test_a_huge_paragraph_is_cut_between_lines_without_losing_text():
    lines = [f"Sentence number {n} of a very long paragraph." for n in range(200)]

    blocks = number_blocks("\n".join(lines))

    assert len(blocks) > 1
    assert all(estimate_tokens(block.text) <= MAX_BLOCK_TOKENS for block in blocks)
    assert "\n".join(block.text for block in blocks).split("\n") == lines


def test_a_single_endless_line_is_cut_between_words():
    words = [f"word{n}" for n in range(2000)]

    blocks = number_blocks(" ".join(words))

    assert len(blocks) > 1
    assert all(estimate_tokens(block.text) <= MAX_BLOCK_TOKENS for block in blocks)
    assert " ".join(block.text for block in blocks).split() == words


def test_long_code_stays_in_one_block():
    code = "```\n" + "\n".join(f"line_{n} = {n}" for n in range(400)) + "\n```"

    assert [block.text for block in number_blocks(code)] == [code]
