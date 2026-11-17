import subprocess

import pytest
from conftest import ScriptedModel

from wikinotes.ingest import IngestError, ingest

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
