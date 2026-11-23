from conftest import ScriptedModel
from files import PNG
from test_ingest import CELLS, PART_1, PART_2, PLAN, SMALL_WINDOW, TRANSCRIPTION, WRITE
from typer.testing import CliRunner

from ragwiki import __version__
from ragwiki.cli import app

runner = CliRunner()


def test_version_flag_prints_the_version_and_exits_cleanly():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"ragwiki {__version__}"


def test_init_creates_a_vault_and_status_reports_it_empty(tmp_path):
    target = tmp_path / "my-wiki"

    created = runner.invoke(app, ["init", str(target)])
    status = runner.invoke(app, ["status", "--vault", str(target)])

    assert created.exit_code == 0
    assert (target / "SCHEMA.md").is_file()
    assert status.exit_code == 0
    assert "Sources: 0" in status.output
    assert "Pages: 0" in status.output


def test_init_twice_fails_without_touching_the_vault(tmp_path):
    runner.invoke(app, ["init", str(tmp_path)])
    schema = tmp_path / "SCHEMA.md"
    schema.write_text("my conventions", encoding="utf-8")

    again = runner.invoke(app, ["init", str(tmp_path)])

    assert again.exit_code == 1
    assert "already" in again.output
    assert schema.read_text(encoding="utf-8") == "my conventions"


def make_vault_with_note(tmp_path):
    vault = tmp_path / "vault"
    runner.invoke(app, ["init", str(vault)])
    note = tmp_path / "cells.md"
    note.write_text(CELLS, encoding="utf-8")
    return vault, note


def test_add_ingests_a_file_and_reports_what_changed(tmp_path, monkeypatch):
    vault, note = make_vault_with_note(tmp_path)
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: ScriptedModel(PLAN, WRITE))

    result = runner.invoke(app, ["add", str(note), "--vault", str(vault)])
    status = runner.invoke(app, ["status", "--vault", str(vault)])

    assert result.exit_code == 0
    assert "added as src-cell-biology" in result.output
    assert "created: cell, mitochondria" in result.output
    assert "removed 1 citation(s)" in result.output
    assert "Sources: 1" in status.output
    assert "Pages: 2" in status.output


def test_add_without_a_configured_model_names_the_variable_and_changes_nothing(
    tmp_path, monkeypatch
):
    vault, note = make_vault_with_note(tmp_path)
    monkeypatch.delenv("RAGWIKI_MODEL", raising=False)

    result = runner.invoke(app, ["add", str(note), "--vault", str(vault)])

    assert result.exit_code == 1
    assert "RAGWIKI_MODEL" in result.output
    assert not list((vault / "wiki").iterdir())


def test_add_rejects_a_format_it_cannot_read(tmp_path, monkeypatch):
    vault, _ = make_vault_with_note(tmp_path)
    odd = tmp_path / "slides.xyz"
    odd.write_bytes(b"\x00")
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: ScriptedModel())

    result = runner.invoke(app, ["add", str(odd), "--vault", str(vault)])

    assert result.exit_code == 1
    assert ".xyz" in result.output


def test_add_shows_the_estimate_and_does_not_ask_when_the_price_is_unknown(tmp_path, monkeypatch):
    vault, note = make_vault_with_note(tmp_path)
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: ScriptedModel(PLAN, WRITE))

    result = runner.invoke(app, ["add", str(note), "--vault", str(vault)])

    assert result.exit_code == 0
    assert "Estimate: 1 file(s), about 2 model call(s)" in result.output
    assert "RAGWIKI_PRICE_INPUT" in result.output
    assert result.output.index("Estimate:") < result.output.index("added as")


def test_add_asks_before_spending_and_stops_on_no(tmp_path, monkeypatch):
    vault, note = make_vault_with_note(tmp_path)
    monkeypatch.setenv("RAGWIKI_PRICE_INPUT", "0.5")
    monkeypatch.setenv("RAGWIKI_PRICE_OUTPUT", "2")
    model = ScriptedModel(PLAN, WRITE)
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: model)

    result = runner.invoke(app, ["add", str(note), "--vault", str(vault)], input="n\n")

    assert result.exit_code == 1
    assert "about $0.00" in result.output
    assert "Continue?" in result.output
    assert model.calls == []
    assert not list((vault / "wiki").iterdir())


def test_add_goes_ahead_on_yes_and_with_the_yes_flag(tmp_path, monkeypatch):
    vault, note = make_vault_with_note(tmp_path)
    other = tmp_path / "energy.md"
    other.write_text("# Energy\n\nATP stores energy.\n", encoding="utf-8")
    monkeypatch.setenv("RAGWIKI_PRICE_INPUT", "0.5")
    monkeypatch.setenv("RAGWIKI_PRICE_OUTPUT", "2")
    monkeypatch.setattr(
        "ragwiki.cli.build_model", lambda _: ScriptedModel(PLAN, WRITE, PLAN, WRITE)
    )

    answered = runner.invoke(app, ["add", str(note), "--vault", str(vault)], input="y\n")
    flagged = runner.invoke(app, ["add", str(other), "--vault", str(vault), "--yes"])

    assert answered.exit_code == 0
    assert "added as src-cell-biology" in answered.output
    assert flagged.exit_code == 0
    assert "Continue?" not in flagged.output
    assert "added as src-energy" in flagged.output


def test_add_estimate_only_needs_no_model_and_writes_nothing(tmp_path):
    vault, note = make_vault_with_note(tmp_path)

    result = runner.invoke(app, ["add", str(note), "--vault", str(vault), "--estimate"])

    assert result.exit_code == 0
    assert "Estimate: 1 file(s), about 2 model call(s)" in result.output
    assert "added as" not in result.output
    assert not list((vault / "wiki").iterdir())


def test_add_splits_a_source_larger_than_the_configured_window(tmp_path, monkeypatch):
    vault, note = make_vault_with_note(tmp_path)
    monkeypatch.setenv("RAGWIKI_CONTEXT_TOKENS", str(SMALL_WINDOW))
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: ScriptedModel(*PART_1, *PART_2))

    result = runner.invoke(app, ["add", str(note), "--vault", str(vault)])

    assert result.exit_code == 0
    assert "cells.md: part 2 of 2, writing" in result.output
    assert "created: cell" in result.output


def test_add_rejects_a_context_window_that_is_not_a_positive_number(tmp_path, monkeypatch):
    vault, note = make_vault_with_note(tmp_path)
    monkeypatch.setenv("RAGWIKI_CONTEXT_TOKENS", "big")
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: ScriptedModel())

    result = runner.invoke(app, ["add", str(note), "--vault", str(vault)])

    assert result.exit_code == 1
    assert "RAGWIKI_CONTEXT_TOKENS" in result.output
    assert not list((vault / "wiki").iterdir())


def test_add_transcribes_a_photo_and_says_so(tmp_path, monkeypatch):
    vault, _ = make_vault_with_note(tmp_path)
    photo = tmp_path / "board.png"
    photo.write_bytes(PNG)
    monkeypatch.setattr(
        "ragwiki.cli.build_model", lambda _: ScriptedModel(TRANSCRIPTION, PLAN, WRITE)
    )

    result = runner.invoke(app, ["add", str(photo), "--vault", str(vault)])

    assert result.exit_code == 0
    assert "Estimate: 1 file(s), about 3 model call(s)" in result.output
    assert "board.png: transcribing the photo" in result.output
    assert "added as src-cell-biology" in result.output


def test_add_reports_a_damaged_document_and_changes_nothing(tmp_path, monkeypatch):
    vault, _ = make_vault_with_note(tmp_path)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a real document")
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: ScriptedModel())

    result = runner.invoke(app, ["add", str(broken), "--vault", str(vault)])

    assert result.exit_code == 1
    assert "broken.pdf is damaged" in result.output
    assert not list((vault / "wiki").iterdir())


def test_ask_prints_the_answer_and_where_it_comes_from(tmp_path, monkeypatch):
    vault, note = make_vault_with_note(tmp_path)
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: ScriptedModel(PLAN, WRITE))
    runner.invoke(app, ["add", str(note), "--vault", str(vault)])
    replies = [
        {"action": "read", "pages": ["mitochondria"]},
        {"action": "answer", "found": True, "text": "ATP [[src-cell-biology#^p2]]."},
    ]
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: ScriptedModel(*replies))

    result = runner.invoke(app, ["ask", "What produces ATP?", "--vault", str(vault)])

    assert result.exit_code == 0
    assert "ATP [[src-cell-biology#^p2]]." in result.output
    assert "src-cell-biology#^p2 (Cell biology): Mitochondria produce ATP." in result.output


def test_ask_says_so_when_the_notes_do_not_answer(tmp_path, monkeypatch):
    vault, _ = make_vault_with_note(tmp_path)
    reply = {"action": "answer", "found": False, "text": "The wiki is empty."}
    monkeypatch.setattr("ragwiki.cli.build_model", lambda _: ScriptedModel(reply))

    result = runner.invoke(app, ["ask", "Anything?", "--vault", str(vault)])

    assert result.exit_code == 0
    assert "Not in your notes: The wiki is empty." in result.output


def test_status_outside_a_vault_explains_how_to_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAGWIKI_VAULT", raising=False)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "ragwiki init" in result.output
