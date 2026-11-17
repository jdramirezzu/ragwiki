from conftest import ScriptedModel
from test_ingest import CELLS, ENERGY, PLAN, SMALL_WINDOW, WRITE

from wikinotes.estimate import estimate_ingest
from wikinotes.ingest import ingest


def test_a_new_note_is_forecast_as_one_plan_call_and_one_write_call(vault, note):
    estimate = estimate_ingest(vault, [note("cells.md", CELLS)])

    assert (estimate.files, estimate.calls) == (1, 2)
    # Both calls carry the system prompt, the conventions and the whole note.
    assert estimate.input_tokens > 2 * len(CELLS) // 4
    assert estimate.output_tokens > 0
    assert estimate.usd is None


def test_prices_turn_the_forecast_into_dollars(vault, note):
    estimate = estimate_ingest(vault, [note("cells.md", CELLS)], price_input=0.5, price_output=2.0)

    expected = (estimate.input_tokens * 0.5 + estimate.output_tokens * 2.0) / 1_000_000
    assert estimate.usd == expected
    assert estimate.usd > 0


def test_a_file_already_in_the_vault_costs_nothing(vault, note):
    path = note("cells.md", CELLS)
    ingest(vault, ScriptedModel(PLAN, WRITE), path)

    estimate = estimate_ingest(vault, [path], price_input=0.5, price_output=2.0)

    assert (estimate.files, estimate.calls, estimate.usd) == (0, 0, 0.0)


def test_every_part_of_a_long_source_and_every_file_adds_two_calls(vault, note):
    paths = [note("cells.md", CELLS), note("energy.md", ENERGY)]

    estimate = estimate_ingest(vault, paths, context_tokens=SMALL_WINDOW)

    assert (estimate.files, estimate.calls) == (2, 6)


def test_estimating_never_changes_the_vault(vault, note):
    before = sorted(str(path) for path in vault.root.rglob("*") if ".git" not in path.parts)

    estimate_ingest(vault, [note("cells.md", CELLS)])

    assert sorted(str(p) for p in vault.root.rglob("*") if ".git" not in p.parts) == before
