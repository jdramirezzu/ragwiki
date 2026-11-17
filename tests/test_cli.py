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


def test_status_outside_a_vault_explains_how_to_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WIKINOTES_VAULT", raising=False)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "wikinotes init" in result.output
