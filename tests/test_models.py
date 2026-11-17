import json

import pytest
from conftest import ScriptedModel

from wikinotes.models import BudgetExceeded, ConfigError, MeteredModel, extract_json, model_from_env


def test_every_call_is_logged_with_tokens_time_and_price(tmp_path):
    log = tmp_path / "calls.jsonl"
    model = MeteredModel(ScriptedModel("a", "b"), log, price_input=2.0, price_output=4.0)

    model.complete("system", "user")
    model.complete("system", "user")

    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 2
    assert entries[0]["input_tokens"] == 1000
    assert entries[0]["output_tokens"] == 500
    assert entries[0]["usd"] == pytest.approx(0.004)
    assert entries[0]["seconds"] >= 0
    assert "user" not in json.dumps(entries)
    assert model.calls == 2
    assert model.spent_usd == pytest.approx(0.008)


def test_the_spending_cap_stops_further_calls(tmp_path):
    inner = ScriptedModel("a", "b")
    model = MeteredModel(inner, tmp_path / "calls.jsonl", price_input=2.0, max_usd=0.002)

    model.complete("system", "user")
    with pytest.raises(BudgetExceeded):
        model.complete("system", "user")

    assert len(inner.calls) == 1


def test_model_from_env_names_the_missing_variable(monkeypatch):
    monkeypatch.delenv("WIKINOTES_MODEL", raising=False)

    with pytest.raises(ConfigError) as error:
        model_from_env()

    assert "WIKINOTES_MODEL" in str(error.value)


def test_extract_json_accepts_fenced_replies_and_rejects_prose():
    assert extract_json('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("no json at all")
    with pytest.raises(ValueError):
        extract_json("[1, 2]")
