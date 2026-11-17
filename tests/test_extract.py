import pytest
from files import make_docx, make_pdf, make_pptx, make_xlsx

from wikinotes.extract import UnreadableSource, UnsupportedFormat, extract

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


def test_a_spreadsheet_becomes_one_citable_table_per_sheet(tmp_path):
    path = make_xlsx(
        tmp_path / "organelles.xlsx", "Organelles", [["Name", "Role"], ["Ribosome", "Proteins"]]
    )

    source = extract(path)

    assert [block.text for block in source.blocks if block.anchor is None] == ["## Organelles"]
    assert source.paragraphs == {
        "p1": "| Name | Role |\n| --- | --- |\n| Ribosome | Proteins |",
    }


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
