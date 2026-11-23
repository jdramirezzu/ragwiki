import pytest
from conftest import ScriptedModel
from test_ask import ANSWER, READ, SEARCH
from test_ingest import CELLS, PLAN, WRITE
from typer.testing import CliRunner

from wikinotes import cli
from wikinotes.compare import compare, save_comparison
from wikinotes.ingest import ingest
from wikinotes.lab import readable, rows, save_upload, to_csv

RAG_ANSWER = {"found": True, "text": "Mitochondria [[src-cell-biology#^p2]]."}


def test_save_upload_keeps_supported_files_inside_the_vault(vault):
    path = save_upload(vault, "../notes.PDF", b"%PDF-1.4")

    assert path == vault.root / ".wikinotes" / "uploads" / "notes.PDF"
    assert path.read_bytes() == b"%PDF-1.4"


def test_save_upload_rejects_spreadsheets(vault):
    with pytest.raises(ValueError, match="only pdf, docx, pptx, md, markdown, txt"):
        save_upload(vault, "data.xlsx", b"PK")


def test_readable_turns_citations_and_links_into_plain_markdown():
    text = "ATP comes from [[mitochondria|the mitochondria]] [[src-cell-biology#^p2]]."

    assert readable(text) == "ATP comes from *the mitochondria* `src-cell-biology ¶p2`."


def test_rows_and_csv_flatten_each_comparison(vault, note):
    ingest(vault, ScriptedModel(PLAN, WRITE), note("cells.md", CELLS))
    result = compare(vault, ScriptedModel(SEARCH, READ, ANSWER, RAG_ANSWER), "ATP?")
    save_comparison(vault, result)

    row = rows([result])[0]
    csv_text = to_csv([result])

    assert row["question"] == "ATP?"
    assert row["wiki_calls"] == 3 and row["rag_calls"] == 1
    assert row["rag_citations"] == "src-cell-biology#^p2"
    assert csv_text.splitlines()[0].startswith("id,time,question,verdict")
    assert len(csv_text.splitlines()) == 2


def test_lab_command_starts_the_server_with_the_folder(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(
        "wikinotes.server.run",
        lambda folder, port, open_browser: seen.update(
            folder=folder, port=port, open_browser=open_browser
        ),
    )

    result = CliRunner().invoke(cli.app, ["lab", str(tmp_path), "--port", "9000", "--no-browser"])

    assert result.exit_code == 0, result.output
    assert seen == {"folder": tmp_path.resolve(), "port": 9000, "open_browser": False}
