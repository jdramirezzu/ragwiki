"""The library surface an interface builds on: everything comes from `import ragwiki`."""

from conftest import ScriptedModel
from test_ingest import CELLS, PLAN, WRITE

import ragwiki


def test_an_interface_can_estimate_ingest_ask_and_show_the_cited_paragraph(tmp_path):
    note = tmp_path / "cells.md"
    note.write_text(CELLS, encoding="utf-8")
    vault = ragwiki.Vault.create(tmp_path / "vault")
    stages = []

    estimate = ragwiki.estimate_ingest(vault, [note])
    added = ragwiki.ingest(vault, ScriptedModel(PLAN, WRITE), note, on_progress=stages.append)
    answer = ragwiki.ask(
        vault,
        ScriptedModel(
            {"action": "read", "pages": ["mitochondria"]},
            {"action": "answer", "found": True, "text": "ATP [[src-cell-biology#^p2]]."},
        ),
        "What produces ATP?",
    )
    cited = ragwiki.cited_paragraph(vault, answer.citations[0])

    assert estimate.calls == 2
    assert added.created == ["cell", "mitochondria"]
    assert [stage.stage for stage in stages] == ["planning", "writing"]
    assert answer.found
    assert (cited.source_id, cited.anchor) == ("src-cell-biology", "p2")
    assert (cited.source_title, cited.text) == ("Cell biology", "Mitochondria produce ATP.")


def test_every_public_name_exists():
    for name in ragwiki.__all__:
        assert hasattr(ragwiki, name), name
