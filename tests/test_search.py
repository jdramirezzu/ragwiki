from ragwiki.search import rank, tokenize

DOCS = {
    "costos": "La información de costos está en la página de resultados.",
    "modelo": "El modelo responde preguntas sobre los artículos.",
}


def test_a_question_without_accents_finds_a_paragraph_with_them():
    hits = rank("informacion", DOCS)

    assert [hit.key for hit in hits] == ["costos"]


def test_singular_and_plural_words_match_in_spanish_and_english():
    assert rank("páginas", DOCS)[0].key == "costos"
    assert (
        rank("article", {"a": "Two articles about wikis.", "b": "A note on search."})[0].key == "a"
    )


def test_tokenize_folds_accents_and_case_and_keeps_short_words():
    assert tokenize("Información, PÁGINAS y es") == ["informacion", "pagina", "y", "es"]


def test_exact_words_still_rank_first():
    assert rank("modelo responde", DOCS)[0].key == "modelo"
