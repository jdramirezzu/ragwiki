import subprocess

import pytest
from conftest import ScriptedModel
from files import PNG

from wikinotes.domain import Source
from wikinotes.extract import number_blocks
from wikinotes.ingest import IngestError, ingest, split_source
from wikinotes.models import Image

CELLS = "# Cell biology\n\nThe cell is the unit of life.\n\nMitochondria produce ATP.\n"
ENERGY = "# Energy\n\nATP stores energy in phosphate bonds.\n"

PLAN = {
    "update": [],
    "create": [
        {"slug": "cell", "title": "Cell", "summary": "Basic unit of life."},
        {"slug": "mitochondria", "title": "Mitochondria", "summary": "Produces ATP."},
    ],
}
WRITE = {
    "pages": [
        {
            "slug": "cell",
            "title": "Cell",
            "type": "concept",
            "summary": "Basic unit of life.",
            "body": "The cell is the unit of life [[src-cell-biology#^p1]]. "
            "It contains [[mitochondria]] and a [[nucleus]].",
        },
        {
            "slug": "mitochondria",
            "title": "Mitochondria",
            "type": "concept",
            "summary": "Produces ATP.",
            "body": "Mitochondria produce ATP [[src-cell-biology#^p2]]. "
            "They are very old [[src-cell-biology#^p9]].",
        },
    ]
}


def snapshot(vault):
    return {
        str(path.relative_to(vault.root)): path.read_bytes()
        for path in sorted(vault.root.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


def test_ingest_writes_pages_source_index_log_and_a_git_snapshot(vault, note):
    model = ScriptedModel(PLAN, WRITE)

    result = ingest(vault, model, note("cells.md", CELLS))

    assert result.source_id == "src-cell-biology"
    assert result.created == ["cell", "mitochondria"]
    assert result.updated == []
    assert not result.skipped
    assert vault.page_slugs() == ["cell", "mitochondria"]
    assert vault.read_page("cell").sources == ["src-cell-biology"]
    assert vault.load_source("src-cell-biology").paragraphs["p2"] == "Mitochondria produce ATP."
    assert "[[cell]]" in vault.index()
    assert "[[src-cell-biology]]" in vault.index()
    assert "Cell biology" in (vault.root / "log.md").read_text(encoding="utf-8")
    subjects = subprocess.run(
        ["git", "log", "--format=%s"], cwd=vault.root, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert subjects[0] == "add: Cell biology"


def test_citations_that_do_not_resolve_and_links_to_missing_pages_are_removed(vault, note):
    result = ingest(vault, ScriptedModel(PLAN, WRITE), note("cells.md", CELLS))

    assert result.dropped_citations == 1
    assert vault.read_page("mitochondria").body == (
        "Mitochondria produce ATP [[src-cell-biology#^p2]]. They are very old."
    )
    assert vault.read_page("cell").body == (
        "The cell is the unit of life [[src-cell-biology#^p1]]. "
        "It contains [[mitochondria]] and a nucleus."
    )


def test_the_model_sees_numbered_paragraphs_the_index_and_the_user_conventions(vault, note):
    (vault.root / "SCHEMA.md").write_text("Write everything in Spanish.", encoding="utf-8")
    model = ScriptedModel(PLAN, WRITE)

    ingest(vault, model, note("cells.md", CELLS))

    system, plan_prompt = model.calls[0]
    assert "Write everything in Spanish." in system
    assert "[p2] Mitochondria produce ATP." in plan_prompt
    assert "src-cell-biology" in plan_prompt
    assert "# Index" in plan_prompt


def test_a_second_source_updates_an_existing_page_and_keeps_its_sources(vault, note):
    ingest(vault, ScriptedModel(PLAN, WRITE), note("cells.md", CELLS))
    plan = {"update": ["mitochondria"], "create": []}
    write = {
        "pages": [
            {
                "slug": "mitochondria",
                "title": "Mitochondria",
                "type": "concept",
                "summary": "Produces ATP, the cell's energy store.",
                "body": "Mitochondria produce ATP [[src-cell-biology#^p2]]. "
                "ATP stores energy in phosphate bonds [[src-energy#^p1]].",
            }
        ]
    }
    model = ScriptedModel(plan, write)

    result = ingest(vault, model, note("energy.md", ENERGY))

    assert (result.created, result.updated) == ([], ["mitochondria"])
    page = vault.read_page("mitochondria")
    assert page.sources == ["src-cell-biology", "src-energy"]
    assert page.summary == "Produces ATP, the cell's energy store."
    write_prompt = model.calls[1][1]
    assert "They are very old." in write_prompt


def test_invalid_json_is_retried_once_with_the_reason(vault, note):
    model = ScriptedModel("I cannot do that", PLAN, WRITE)

    result = ingest(vault, model, note("cells.md", CELLS))

    assert result.created == ["cell", "mitochondria"]
    assert len(model.calls) == 3
    assert "rejected" in model.calls[1][1]


def test_two_invalid_replies_fail_and_leave_the_vault_untouched(vault, note):
    before = snapshot(vault)

    with pytest.raises(IngestError):
        ingest(vault, ScriptedModel("nope", "still nope"), note("cells.md", CELLS))

    assert snapshot(vault) == before


def test_pages_outside_the_plan_or_without_valid_citations_are_not_written(vault, note):
    before = snapshot(vault)
    write = {
        "pages": [
            {"slug": "surprise", "title": "Surprise", "summary": "x", "body": "Unplanned."},
            {"slug": "cell", "title": "Cell", "summary": "x", "body": "No citation here."},
        ]
    }

    with pytest.raises(IngestError):
        ingest(vault, ScriptedModel(PLAN, write, write), note("cells.md", CELLS))

    assert snapshot(vault) == before


def test_the_same_file_is_not_ingested_twice(vault, note):
    path = note("cells.md", CELLS)
    ingest(vault, ScriptedModel(PLAN, WRITE), path)
    model = ScriptedModel()

    result = ingest(vault, model, path)

    assert result.skipped
    assert result.source_id == "src-cell-biology"
    assert model.calls == []


# With a 48-token window a part holds 12 tokens: the heading and the first paragraph of
# CELLS fill one part and the second paragraph goes to the next.
SMALL_WINDOW = 48
PART_1 = (
    {"update": [], "create": [{"slug": "cell", "title": "Cell", "summary": "Unit of life."}]},
    {
        "pages": [
            {
                "slug": "cell",
                "title": "Cell",
                "summary": "Unit of life.",
                "body": "The cell is the unit of life [[src-cell-biology#^p1]].",
            }
        ]
    },
)
PART_2 = (
    {"update": ["cell"], "create": []},
    {
        "pages": [
            {
                "slug": "cell",
                "title": "Cell",
                "summary": "Unit of life, powered by mitochondria.",
                "body": "The cell is the unit of life [[src-cell-biology#^p1]]. "
                "Mitochondria produce ATP [[src-cell-biology#^p2]].",
            }
        ]
    },
)


def test_split_source_keeps_a_heading_with_its_text_and_an_oversized_block_alone():
    blocks = number_blocks("# A\n\nshort one\n\n## B\n\n" + "long " * 40 + "\n\nshort two")
    source = Source(title="A", original="a.md", sha256="0", blocks=blocks, id="src-a")

    parts = split_source(source, max_tokens=8)

    assert [[block.anchor or block.text for block in part] for part in parts] == [
        ["# A", "p1"],
        ["## B", "p2"],
        ["p3"],
    ]


def test_a_source_larger_than_the_window_is_ingested_in_parts(vault, note):
    model = ScriptedModel(*PART_1, *PART_2)
    progress = []

    result = ingest(
        vault,
        model,
        note("cells.md", CELLS),
        context_tokens=SMALL_WINDOW,
        on_progress=progress.append,
    )

    prompts = [user for _, user in model.calls]
    assert len(prompts) == 4
    assert "[p1] The cell is the unit of life." in prompts[0]
    assert "Mitochondria produce ATP." not in prompts[0]
    assert "part 2 of 2" in prompts[2]
    assert "[p2] Mitochondria produce ATP." in prompts[2]
    # The second part sees the page the first part wrote, although it is not on disk yet.
    assert "- [[cell]] (concept): Unit of life." in prompts[2]
    assert '<page slug="cell" title="Cell">' in prompts[3]
    assert (result.created, result.updated) == (["cell"], [])
    assert vault.read_page("cell").summary == "Unit of life, powered by mitochondria."
    assert list(vault.sources()) == ["src-cell-biology"]
    assert vault.load_source("src-cell-biology").paragraphs["p2"] == "Mitochondria produce ATP."
    assert [(p.part, p.parts, p.stage) for p in progress] == [
        (1, 2, "planning"),
        (1, 2, "writing"),
        (2, 2, "planning"),
        (2, 2, "writing"),
    ]


def test_a_failure_in_a_later_part_leaves_the_vault_untouched(vault, note):
    before = snapshot(vault)
    model = ScriptedModel(*PART_1, "nope", "still nope")

    with pytest.raises(IngestError):
        ingest(vault, model, note("cells.md", CELLS), context_tokens=SMALL_WINDOW)

    assert snapshot(vault) == before


TRANSCRIPTION = {
    "markdown": "# Cell biology\n\nThe cell is the unit of life.\n\nMitochondria produce ATP."
}


def photo(tmp_path, name="board.png"):
    path = tmp_path / name
    path.write_bytes(PNG)
    return path


def test_a_photo_is_transcribed_first_and_then_ingested_like_any_source(vault, tmp_path):
    model = ScriptedModel(TRANSCRIPTION, PLAN, WRITE)
    progress = []

    result = ingest(vault, model, photo(tmp_path), on_progress=progress.append)

    assert result.source_id == "src-cell-biology"
    assert result.created == ["cell", "mitochondria"]
    assert model.images == [(Image("image/png", PNG),), (), ()]
    assert "[p2] Mitochondria produce ATP." in model.calls[1][1]
    assert vault.load_source("src-cell-biology").paragraphs["p2"] == "Mitochondria produce ATP."
    assert (vault.root / "sources" / "src-cell-biology.png").read_bytes() == PNG
    assert [p.stage for p in progress] == ["transcribing", "planning", "writing"]


def test_a_photo_the_model_cannot_transcribe_fails_and_leaves_the_vault_untouched(vault, tmp_path):
    before = snapshot(vault)
    model = ScriptedModel({"markdown": ""}, {"text": "no notes here"})

    with pytest.raises(IngestError):
        ingest(vault, model, photo(tmp_path))

    assert len(model.calls) == 2
    assert snapshot(vault) == before


def test_the_same_photo_is_not_transcribed_twice(vault, tmp_path):
    path = photo(tmp_path)
    ingest(vault, ScriptedModel(TRANSCRIPTION, PLAN, WRITE), path)
    model = ScriptedModel()

    result = ingest(vault, model, path)

    assert result.skipped
    assert model.calls == []


def test_add_source_only_extracts_without_a_model_and_ingest_builds_the_wiki_later(vault, note):
    from wikinotes.ingest import add_source_only

    path = note("cells.md", CELLS)

    added = add_source_only(vault, path)
    again = add_source_only(vault, path)

    assert (added.source_id, added.paragraphs, added.skipped) == ("src-cell-biology", 2, False)
    assert again.skipped
    assert vault.in_wiki("src-cell-biology") is False
    assert vault.page_slugs() == []
    assert vault.original_path("src-cell-biology").name == "src-cell-biology.md"

    result = ingest(vault, ScriptedModel(PLAN, WRITE), path)

    assert result.source_id == "src-cell-biology" and not result.skipped
    assert result.created == ["cell", "mitochondria"]
    assert vault.in_wiki("src-cell-biology") is True
    assert list(vault.sources()) == ["src-cell-biology"]
    assert ingest(vault, ScriptedModel(), path).skipped
