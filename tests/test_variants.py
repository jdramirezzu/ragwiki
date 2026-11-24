import pytest
from conftest import ScriptedModel

from ragwiki.ingest import add_source_only
from ragwiki.models import ConfigError
from ragwiki.rag import retrieve
from ragwiki.variants import (
    Variant,
    answer_variants,
    load_benches,
    retrieve_variant,
    search_bench,
)

PLANTS = (
    "# Plants\n\n"
    "Leaves capture light.\n\n"
    "Chlorophyll is green.\n\n"
    "Photosynthesis makes sugar from light.\n\n"
    "Roots take water.\n"
)
ANIMALS = "# Animals\n\nMuscles burn sugar.\n\nBones hold the body.\n"


@pytest.fixture
def corpus(vault, note):
    add_source_only(vault, note("plants.md", PLANTS))
    add_source_only(vault, note("animals.md", ANIMALS))
    return vault


class WordVectors:
    """Each text becomes counts of a few words, so vector similarity is predictable."""

    name = "fake/words"
    WORDS = ("green", "light", "water", "body")

    def embed(self, texts):
        return [[t.lower().count(w) for w in self.WORDS] for t in texts]


class LongestFirst:
    """A reranker stand-in: longer paragraphs score higher."""

    name = "fake/longest"

    def __init__(self):
        self.pools: list[int] = []

    def scores(self, question, texts):
        self.pools.append(len(texts))
        return [float(len(text)) for text in texts]


def citations(passages):
    return [p.citation for p in passages]


def test_a_variant_name_round_trips_and_unknown_names_are_refused():
    variant = Variant("hybrid", rerank=True, window=1)
    assert variant.name == "hybrid+rerank+window"
    assert Variant.parse(variant.name) == variant
    assert Variant.parse("bm25") == Variant("bm25")
    with pytest.raises(ValueError):
        Variant.parse("magic")
    with pytest.raises(ValueError):
        Variant.parse("bm25+turbo")


def test_bm25_and_vector_variants_match_the_plain_retrieval(corpus):
    question = "What is green?"
    vectors = WordVectors()
    assert citations(retrieve_variant(corpus, question, Variant("bm25"), 2)) == citations(
        retrieve(corpus, question, 2)
    )
    assert citations(
        retrieve_variant(corpus, question, Variant("vector"), 2, embedder=vectors)
    ) == citations(retrieve(corpus, question, 2, vectors))


def test_hybrid_keeps_what_either_search_found(corpus):
    # "sugar" is only found by words; "light" leads the vectors ("light" counts, "sugar" not).
    question = "sugar light"
    words_only = citations(retrieve_variant(corpus, question, Variant("bm25"), 1))
    vectors_only = citations(
        retrieve_variant(corpus, question, Variant("vector"), 1, embedder=WordVectors())
    )
    hybrid = citations(
        retrieve_variant(corpus, question, Variant("hybrid"), 3, embedder=WordVectors())
    )
    assert set(words_only + vectors_only) <= set(hybrid)
    assert hybrid == citations(
        retrieve_variant(corpus, question, Variant("hybrid"), 3, embedder=WordVectors())
    )


def test_rerank_reorders_a_wider_pool_and_keeps_k(corpus):
    reranker = LongestFirst()
    passages = retrieve_variant(
        corpus, "light sugar water", Variant("bm25", rerank=True), 2, reranker=reranker
    )
    assert len(passages) == 2
    assert reranker.pools[0] > 2
    assert [p.text for p in passages][0] == "Photosynthesis makes sugar from light."
    assert passages[0].score >= passages[1].score


def test_window_adds_neighbours_from_the_same_source_and_keeps_the_citation(corpus):
    plain = retrieve_variant(corpus, "chlorophyll", Variant("bm25"), 1)
    wide = retrieve_variant(corpus, "chlorophyll", Variant("bm25", window=1), 1)
    assert citations(plain) == citations(wide)
    assert wide[0].text == (
        "Leaves capture light.\n\nChlorophyll is green.\n\nPhotosynthesis makes sugar from light."
    )
    # The last paragraph of a source gets no text from the next source.
    edge = retrieve_variant(corpus, "roots", Variant("bm25", window=1), 1)
    assert "Muscles" not in edge[0].text


def test_vector_variants_need_an_embedder_and_rerank_needs_a_reranker(corpus):
    with pytest.raises(ConfigError):
        retrieve_variant(corpus, "green", Variant("vector"), 2)
    with pytest.raises(ConfigError):
        retrieve_variant(corpus, "green", Variant("hybrid"), 2)
    with pytest.raises(ConfigError):
        retrieve_variant(corpus, "green", Variant("bm25", rerank=True), 2)


def test_search_bench_scores_each_variant_without_a_model_and_saves_it(corpus):
    items = [
        ("Which pigment is green?", "chlorophyll"),
        ("What do roots take?", "water"),
        ("What do muscles burn?", "sugar"),
        ("Who wrote Hamlet?", "none"),
        ("Tell me about leaves", ""),
    ]
    bench = search_bench(
        corpus, items, [Variant("bm25"), Variant("vector")], k=1, embedder=WordVectors()
    )
    scores = {score.variant: score for score in bench.scores}
    assert scores["bm25"].checked == 3
    assert scores["bm25"].found == 3
    assert scores["bm25"].mrr == 1.0
    assert scores["vector"].checked == 3
    assert scores["vector"].found < 3
    first = scores["bm25"].questions[0]
    assert first["rank"] == 1 and first["retrieved"] == [first["retrieved"][0]]
    assert bench.best == "bm25"
    assert [b.id for b in load_benches(corpus)] == [bench.id]


def test_search_bench_with_nothing_to_check_has_no_best(corpus):
    bench = search_bench(corpus, [("Tell me about leaves", "")], [Variant("bm25")], k=2)
    assert bench.scores[0].checked == 0
    assert bench.best is None


def test_answer_variants_asks_the_model_once_per_question_and_variant(corpus):
    reply = {"found": True, "text": "Chlorophyll [[src-plants#^p2]]."}
    model = ScriptedModel(reply, reply)
    results = answer_variants(
        corpus,
        model,
        [("Which pigment is green?", "chlorophyll")],
        [Variant("bm25"), Variant("bm25", window=1)],
        k=1,
        prices=(1.0, 2.0),
    )
    assert len(model.calls) == 2
    assert [r["variant"] for r in results] == ["bm25", "bm25+window"]
    assert all(r["correct"] is True for r in results)
    assert results[0]["result"]["calls"] == 1
    assert results[0]["result"]["usd"] == pytest.approx(0.002)
    assert results[0]["result"]["detail"]["retrieval"] == "bm25"
    assert "Leaves capture light." in model.calls[1][1]
    assert "Leaves capture light." not in model.calls[0][1]
