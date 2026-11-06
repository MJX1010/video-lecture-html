from typer.testing import CliRunner

from vlh.cli import app

runner = CliRunner()


def test_help():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "process" in r.stdout
    assert "batch" in r.stdout


def test_version():
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0
    assert "0.2.0" in r.stdout
