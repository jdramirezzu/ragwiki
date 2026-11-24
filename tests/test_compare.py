import pytest
from conftest import ScriptedModel
from test_ask import ANSWER, READ, SEARCH
from test_ingest import CELLS, PLAN, WRITE

from ragwiki.compare import (
    Ingestion,
    compare,
    load_comparisons,
    load_ingestions,
    record_ingestion,
    save_comparison,
    set_verdict,
    summarize,
)
from ragwiki.ingest import ingest
from ragwiki.models import MeteredModel

RAG_ANSWER = {"found": True, "text": "Mitochondria [[src-cell-biology#^p2]]."}


@pytest.fixture
def wiki(vault, note):
    ingest(vault, ScriptedModel(PLAN, WRITE), note("cells.md", CELLS))
    return vault


def test_compare_asks_both_arms_with_the_same_model_and_measures_each(wiki):
    model = ScriptedModel(SEARCH, READ, ANSWER, RAG_ANSWER)

    result = compare(wiki, model, "What produces ATP?", k=2, prices=(1.0, 2.0))

    assert result.question == "What produces ATP?"
    assert result.wiki.found and result.rag.found
    assert result.wiki.calls == 3 and result.rag.calls == 1
    # The scripted model reports 1000 input and 500 output tokens per call.
    assert (result.wiki.input_tokens, result.wiki.output_tokens) == (3000, 1500)
    assert (result.rag.input_tokens, result.rag.output_tokens) == (1000, 500)
    assert result.wiki.usd == pytest.approx(0.006)
    assert result.rag.usd == pytest.approx(0.002)
    assert result.wiki.detail["pages_read"] == ["mitochondria"]
    assert result.rag.detail["retrieved"][0] == "src-cell-biology#^p2"
    assert result.shared_citations == ["src-cell-biology#^p2"]


def test_compare_reads_prices_from_a_metered_model_and_unknown_price_is_none(wiki, tmp_path):
    metered = MeteredModel(
        ScriptedModel(SEARCH, READ, ANSWER, RAG_ANSWER),
        tmp_path / "calls.jsonl",
        price_input=1.0,
        price_output=1.0,
    )
    priced = compare(wiki, metered, "What produces ATP?")
    unpriced = compare(wiki, ScriptedModel(SEARCH, READ, ANSWER, RAG_ANSWER), "ATP?")

    assert priced.rag.usd == pytest.approx(0.0015)
    assert unpriced.wiki.usd is None and unpriced.rag.usd is None


def test_comparisons_are_saved_judged_and_summarized(wiki):
    first = compare(wiki, ScriptedModel(SEARCH, READ, ANSWER, RAG_ANSWER), "ATP?")
    no_rag = {"found": False, "text": "Not in the excerpts."}
    second = compare(wiki, ScriptedModel(SEARCH, READ, ANSWER, no_rag), "ATP again?")
    save_comparison(wiki, first)
    save_comparison(wiki, second)

    set_verdict(wiki, first.id, "tie")
    set_verdict(wiki, second.id, "wiki", note="RAG missed it")
    record_ingestion(wiki, Ingestion("cells.md", 2, 2000, 1000, 1.5, 0.01))

    saved = load_comparisons(wiki)
    summary = summarize(saved, load_ingestions(wiki))
    assert [item.verdict for item in saved] == ["tie", "wiki"]
    assert saved[1].note == "RAG missed it"
    assert summary.questions == 2 and summary.judged == 2 and summary.ties == 1
    assert summary.arms["wiki"].answered == 2 and summary.arms["rag"].answered == 1
    assert summary.arms["wiki"].preferred == 1 and summary.arms["rag"].preferred == 0
    assert summary.arms["wiki"].mean_input_tokens == 3000
    assert summary.ingestion_usd == pytest.approx(0.01)
    assert summary.ingestion_calls == 2


def test_set_verdict_rejects_unknown_values_and_ids(wiki):
    result = compare(wiki, ScriptedModel(SEARCH, READ, ANSWER, RAG_ANSWER), "ATP?")
    save_comparison(wiki, result)

    with pytest.raises(ValueError, match="verdict must be one of"):
        set_verdict(wiki, result.id, "both")
    with pytest.raises(KeyError):
        set_verdict(wiki, "missing", "wiki")


def test_summary_of_nothing_is_empty(vault):
    summary = summarize([])

    assert summary.questions == 0
    assert summary.arms["rag"].total_usd is None
    assert summary.ingestion_usd is None


def _arm(found, text="", usd=None, tokens=1000):
    from ragwiki.compare import ArmResult

    return ArmResult("x", found, text, [], 1, tokens, 100, 1.0, usd)


def test_check_expected_needs_every_key_and_ignores_case_and_accents():
    from ragwiki.compare import check_expected

    answer = _arm(True, "Las mitocondrias producen **ATP** [[src-a#^p2]].")

    assert check_expected(answer, "atp, Mitocondrías") is True
    assert check_expected(answer, "ATP; ribosoma") is False
    assert check_expected(_arm(False, "Not in your notes"), "ATP") is False
    assert check_expected(_arm(False), "none") is True
    assert check_expected(answer, "none") is False
    assert check_expected(answer, " , ") is None


def test_compare_keeps_the_expected_answer_and_scores_each_arm(wiki):
    no_rag = {"found": False, "text": "Not in the excerpts."}
    model = ScriptedModel(SEARCH, READ, ANSWER, no_rag)

    result = compare(wiki, model, "What produces ATP?", expected="ATP")
    save_comparison(wiki, result)

    saved = load_comparisons(wiki)[0]
    assert saved.expected == "ATP"
    assert saved.correct("wiki") is True and saved.correct("rag") is False
    summary = summarize([saved])
    assert summary.arms["wiki"].correct == 1 and summary.arms["wiki"].checked == 1


def _comparison(wiki_ok, rag_ok, verdict=None, expected="ATP"):
    from ragwiki.compare import Comparison

    wiki = _arm(wiki_ok, "ATP" if wiki_ok else "", usd=0.007, tokens=7000)
    rag = _arm(rag_ok, "ATP" if rag_ok else "", usd=0.001, tokens=1000)
    return Comparison("id", "t", "q", wiki, rag, verdict=verdict, expected=expected)


def test_recommend_waits_for_five_evaluated_questions():
    from ragwiki.compare import recommend

    result = recommend(summarize([_comparison(True, False)] * 4))

    assert result.choice == "undecided"
    assert "at least 5" in result.headline


def test_recommend_the_wiki_only_when_it_is_clearly_better():
    from ragwiki.compare import recommend

    items = [_comparison(True, False)] * 3 + [_comparison(True, True)] * 7

    result = recommend(summarize(items), k=8)

    assert result.choice == "wiki"
    assert "wiki 1.00, RAG 0.70" in result.reasons[0]
    assert "7.0× a RAG question" in result.reasons[1]
    assert any("try a larger k" in reason for reason in result.reasons)


def test_recommend_rag_when_quality_is_similar_or_rag_is_better():
    from ragwiki.compare import recommend

    similar = recommend(summarize([_comparison(True, True)] * 5))
    better = recommend(summarize([_comparison(False, True)] * 5))

    assert similar.choice == "rag" and similar.headline.startswith("Similar quality")
    assert better.choice == "rag" and better.headline.startswith("RAG answers")


def test_recommend_uses_verdicts_when_there_are_no_expected_answers():
    from ragwiki.compare import recommend

    items = [_comparison(True, True, verdict="wiki", expected="")] * 4
    items += [_comparison(True, True, verdict="tie", expected="")]

    result = recommend(summarize(items))

    assert result.choice == "wiki"
    assert "your verdicts on 5 questions" in result.reasons[0]


def test_recommend_mentions_the_verdicts_when_expected_answers_decide():
    from ragwiki.compare import recommend

    items = [_comparison(True, True, verdict="tie")] * 5 + [_comparison(True, True, verdict="wiki")]

    result = recommend(summarize(items))

    assert result.choice == "rag"
    assert "Your verdicts on 6 questions: wiki preferred 1, RAG 0, ties 5" in result.reasons[1]


@pytest.mark.parametrize("key", ["none", "ninguna", "Ninguno", "sin respuesta", "no answer"])
def test_check_expected_accepts_no_answer_keys_in_spanish_and_english(key):
    from ragwiki.compare import check_expected

    assert check_expected(_arm(False, "No está en tus documentos."), key) is True
    assert check_expected(_arm(True, "Sí, está [[src-a#^p1]]."), key) is False


def test_recommend_speaks_spanish_when_asked():
    from ragwiki.compare import recommend

    items = [_comparison(True, False)] * 3 + [_comparison(True, True)] * 7
    waiting = recommend(summarize([_comparison(True, False)] * 4), lang="es")
    wiki = recommend(summarize(items), k=8, lang="es")
    rag = recommend(summarize([_comparison(True, True)] * 5), lang="es")

    assert waiting.headline == "Aún no hay evidencia suficiente: evalúa al menos 5 preguntas"
    assert wiki.headline == "La WikiLLM responde claramente mejor tus preguntas"
    assert "Calidad según las respuestas esperadas en 10 preguntas" in wiki.reasons[0]
    assert "prueba un k mayor" in " ".join(wiki.reasons)
    assert rag.headline == "Calidad similar: la búsqueda vectorial basta para tu corpus"
