from typer.testing import CliRunner

from wikinotes import __version__
from wikinotes.cli import app

runner = CliRunner()


def test_version_flag_prints_the_version_and_exits_cleanly():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"wikinotes {__version__}"
