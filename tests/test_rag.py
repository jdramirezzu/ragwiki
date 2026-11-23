import pytest
from conftest import ScriptedModel
from test_ingest import CELLS, PLAN, WRITE

from wikinotes.ask import NOT_FOUND
from wikinotes.ingest import ingest
from wikinotes.models import ConfigError
from wikinotes.rag import ask_rag, retrieve


@pytest.fixture
def wiki(vault, note):
    ingest(vault, ScriptedModel(PLAN, WRITE), note("cells.md", CELLS))
    return vault


class FakeEmbedder:
    """Maps each text to a vector of keyword counts, so similarity is predictable."""

    name = "fake/embedder"

    def __init__(self):
        self.batches: list[list[str]] = []

    def embed(self, texts):
        self.batches.append(list(texts))
        return [[t.lower().count("atp"), t.lower().count("cell")] for t in texts]


def test_retrieve_returns_the_paragraphs_that_match_the_question(wiki):
    passages = retrieve(wiki, "Which organelle produces ATP?", k=1)

    assert [p.citation for p in passages] == ["src-cell-biology#^p2"]
    assert passages[0].text == "Mitochondria produce ATP."
    assert passages[0].source_title == "Cell biology"


def test_retrieve_with_embeddings_ranks_by_similarity_and_caches_vectors(wiki):
    embedder = FakeEmbedder()

    first = retrieve(wiki, "ATP", k=1, embedder=embedder)
    retrieve(wiki, "ATP", k=1, embedder=embedder)

    assert [p.citation for p in first] == ["src-cell-biology#^p2"]
    # Paragraphs are embedded once; later calls only embed the question.
    assert [len(batch) for batch in embedder.batches] == [2, 1, 1]
    assert (wiki.root / ".wikinotes" / "embeddings" / "fake-embedder.json").is_file()


def test_ask_rag_answers_from_retrieved_paragraphs_with_one_call(wiki):
    model = ScriptedModel({"found": True, "text": "Mitochondria [[src-cell-biology#^p2]]."})

    answer = ask_rag(wiki, model, "What produces ATP?", k=2)

    assert answer.found
    assert answer.text == "Mitochondria [[src-cell-biology#^p2]]."
    assert answer.citations == ["src-cell-biology#^p2"]
    assert answer.retrieval == "bm25"
    assert len(model.calls) == 1
    assert '<excerpt id="[[src-cell-biology#^p2]]"' in model.calls[0][1]
    assert answer.context_tokens > 0


def test_ask_rag_drops_citations_that_were_not_retrieved(wiki):
    reply = {
        "found": True,
        "text": "ATP [[src-cell-biology#^p2]]. Old [[src-cell-biology#^p9]].",
    }

    answer = ask_rag(wiki, ScriptedModel(reply), "What produces ATP?", k=1)

    assert answer.text == "ATP [[src-cell-biology#^p2]]. Old."
    assert answer.citations == ["src-cell-biology#^p2"]


def test_ask_rag_without_valid_citations_abstains(wiki):
    reply = {"found": True, "text": "Mitochondria, from memory."}

    answer = ask_rag(wiki, ScriptedModel(reply), "What produces ATP?")

    assert not answer.found
    assert answer.text == NOT_FOUND
    assert answer.citations == []


def test_ask_rag_reports_what_is_missing(wiki):
    reply = {"found": False, "text": "The documents do not mention ribosomes."}

    answer = ask_rag(wiki, ScriptedModel(reply), "What do ribosomes do with ATP?")

    assert not answer.found
    assert answer.text == "The documents do not mention ribosomes."


def test_ask_rag_on_an_empty_vault_abstains_without_calling_the_model(vault):
    model = ScriptedModel()

    answer = ask_rag(vault, model, "Anything?")

    assert not answer.found
    assert model.calls == []


def test_ask_rag_rejects_k_below_one(wiki):
    with pytest.raises(ConfigError, match="k must be at least 1"):
        ask_rag(wiki, ScriptedModel(), "ATP?", k=0)


def test_build_index_embeds_every_paragraph_once_and_reports_progress(vault, note):
    from wikinotes.ingest import add_source_only
    from wikinotes.rag import build_index, index_status

    add_source_only(vault, note("cells.md", CELLS))
    embedder, seen = FakeEmbedder(), []

    before = index_status(vault, embedder)
    after = build_index(vault, embedder, lambda done, total: seen.append((done, total)))

    assert (before.indexed, before.paragraphs, before.ready) == (0, 2, False)
    assert (after.indexed, after.paragraphs, after.ready) == (2, 2, True)
    assert seen == [(2, 2)]
    assert embedder.batches == [["The cell is the unit of life.", "Mitochondria produce ATP."]]
