import pytest
from conftest import ScriptedModel
from test_ingest import CELLS, PLAN, WRITE

from ragwiki.ask import MAX_STEPS, ask
from ragwiki.ingest import ingest
from ragwiki.search import rank

SEARCH = {"action": "search", "query": "what produces ATP"}
READ = {"action": "read", "pages": ["mitochondria"]}
ANSWER = {
    "action": "answer",
    "found": True,
    "text": "Mitochondria produce ATP [[src-cell-biology#^p2]].",
}


@pytest.fixture
def wiki(vault, note):
    ingest(vault, ScriptedModel(PLAN, WRITE), note("cells.md", CELLS))
    return vault


def test_search_read_answer_returns_a_cited_answer(wiki):
    model = ScriptedModel(SEARCH, READ, ANSWER)

    answer = ask(wiki, model, "What produces ATP?")

    assert answer.found
    assert answer.text == "Mitochondria produce ATP [[src-cell-biology#^p2]]."
    assert answer.citations == ["src-cell-biology#^p2"]
    assert answer.pages_read == ["mitochondria"]
    assert answer.steps == 3
    assert "mitochondria: Mitochondria" in model.calls[1][1]
    assert "Mitochondria produce ATP [[src-cell-biology#^p2]]." in model.calls[2][1]


def test_a_citation_that_was_not_in_the_pages_read_is_removed(wiki):
    reply = {
        "action": "answer",
        "found": True,
        "text": "Mitochondria produce ATP [[src-cell-biology#^p2]]. "
        "Cells are the unit of life [[src-cell-biology#^p1]].",
    }

    answer = ask(wiki, ScriptedModel(READ, reply), "What produces ATP?")

    assert answer.citations == ["src-cell-biology#^p2"]
    assert answer.text == (
        "Mitochondria produce ATP [[src-cell-biology#^p2]]. Cells are the unit of life."
    )


def test_answering_before_reading_any_page_is_refused(wiki):
    model = ScriptedModel(ANSWER, READ, ANSWER)

    answer = ask(wiki, model, "What produces ATP?")

    assert answer.found
    assert answer.steps == 3
    assert "read at least one page" in model.calls[1][1]


def test_the_model_can_say_the_notes_do_not_answer(wiki):
    reply = {"action": "answer", "found": False, "text": "Nothing about photosynthesis."}

    answer = ask(wiki, ScriptedModel(SEARCH, reply), "How does photosynthesis work?")

    assert not answer.found
    assert answer.text == "Nothing about photosynthesis."
    assert answer.citations == []


def test_three_searches_without_results_end_in_abstention(wiki):
    nothing = {"action": "search", "query": "zzzz qqqq"}
    model = ScriptedModel(nothing, nothing, nothing)

    answer = ask(wiki, model, "zzzz?")

    assert not answer.found
    assert len(model.calls) == 3


def test_answers_without_valid_citations_and_broken_replies_never_get_through(wiki):
    uncited = {"action": "answer", "found": True, "text": "Trust me."}
    model = ScriptedModel(READ, "not json", *[uncited] * (MAX_STEPS - 2))

    answer = ask(wiki, model, "What produces ATP?")

    assert not answer.found
    assert answer.citations == []
    assert len(model.calls) == MAX_STEPS


def test_reading_the_index_or_a_missing_page_is_reported_back(wiki):
    read = {"action": "read", "pages": ["index", "ghost"]}
    model = ScriptedModel(read, READ, ANSWER)

    ask(wiki, model, "What produces ATP?")

    assert "# Index" in model.calls[1][1]
    assert "ghost does not exist" in model.calls[1][1]


def test_rank_orders_by_relevance_and_ignores_unrelated_documents():
    documents = {
        "cell": "The cell is the unit of life",
        "mitochondria": "Mitochondria produce ATP, the energy of the cell",
        "history": "The French revolution began in 1789",
    }

    assert [hit.key for hit in rank("ATP energy", documents)] == ["mitochondria"]
    assert [hit.key for hit in rank("cell", documents)] == ["cell", "mitochondria"]
    assert rank("quantum", documents) == []
