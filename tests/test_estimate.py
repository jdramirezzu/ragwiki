from conftest import ScriptedModel
from files import PNG
from test_ingest import CELLS, ENERGY, PLAN, SMALL_WINDOW, WRITE

from ragwiki.estimate import estimate_ingest, reply_tokens
from ragwiki.ingest import ingest


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


def test_a_photo_adds_a_transcription_call(vault, tmp_path):
    path = tmp_path / "board.png"
    path.write_bytes(PNG)

    estimate = estimate_ingest(vault, [path])

    assert (estimate.files, estimate.calls) == (1, 3)


# Real DeepSeek ingestions: (part tokens, plan reply, write reply). Ten short Spanish decision
# records and five English arXiv papers (one in two parts), both on 2026-11-24 and 11-23.
MEASURED = {
    "es": [
        (936, 662, 4498),
        (390, 680, 5658),
        (871, 1068, 16657),
        (675, 643, 5498),
        (514, 1081, 6148),
        (584, 881, 11257),
        (737, 865, 7182),
        (836, 1224, 5916),
        (1939, 1018, 14486),
        (651, 5763, 18625),
    ],
    "en": [
        (8664, 1050, 6996),
        (10448, 636, 19904),
        (12874, 3531, 23302),
        (12269, 4521, 28840),
        (15650, 1072, 21599),
        (7029, 1079, 29923),
    ],
}


def test_reply_forecasts_stay_close_to_real_ingestions():
    for name, rows in MEASURED.items():
        real = sum(plan + write for _, plan, write in rows)
        forecast = sum(sum(reply_tokens(part)) for part, _, _ in rows)
        assert abs(forecast - real) / real < 0.2, (name, forecast, real)


def test_later_files_in_one_batch_read_a_bigger_wiki(vault, note):
    first = note("a.md", "# Alpha\n\n" + "alpha words here. " * 40)
    second = note("b.md", "# Beta\n\n" + "beta words there. " * 40)

    alone = [estimate_ingest(vault, [path]).input_tokens for path in (first, second)]
    together = estimate_ingest(vault, [first, second]).input_tokens

    assert together > sum(alone)
