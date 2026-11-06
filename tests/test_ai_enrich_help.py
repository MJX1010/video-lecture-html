from typer.testing import CliRunner
from vlh.cli import app
from vlh.llm.client import extract_json_object


def test_ai_enrich_help():
    r = CliRunner().invoke(app, ["ai-enrich", "--help"])
    assert r.exit_code == 0
    assert "AI Agent" in r.stdout or "meta.json" in r.stdout


def test_extract_json_object_fence():
    obj = extract_json_object('```json\n{"a": 1, "b": "x"}\n```')
    assert obj["a"] == 1
