from conftest import ScriptedModel
from test_ingest import CELLS, PLAN, WRITE
from typer.testing import CliRunner

from wikinotes import __version__
from wikinotes.cli import app

runner = CliRunner()


def test_version_flag_prints_the_version_and_exits_cleanly():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"wikinotes {__version__}"


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
    monkeypatch.setattr("wikinotes.cli.build_model", lambda _: ScriptedModel(PLAN, WRITE))

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
    monkeypatch.delenv("WIKINOTES_MODEL", raising=False)

    result = runner.invoke(app, ["add", str(note), "--vault", str(vault)])

    assert result.exit_code == 1
    assert "WIKINOTES_MODEL" in result.output
    assert not list((vault / "wiki").iterdir())


def test_add_rejects_a_format_it_cannot_read(tmp_path, monkeypatch):
    vault, _ = make_vault_with_note(tmp_path)
    odd = tmp_path / "slides.xyz"
    odd.write_bytes(b"\x00")
    monkeypatch.setattr("wikinotes.cli.build_model", lambda _: ScriptedModel())

    result = runner.invoke(app, ["add", str(odd), "--vault", str(vault)])

    assert result.exit_code == 1
    assert ".xyz" in result.output


def test_status_outside_a_vault_explains_how_to_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WIKINOTES_VAULT", raising=False)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "wikinotes init" in result.output
