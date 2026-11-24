import pytest
from conftest import ScriptedModel
from test_ingest import CELLS, PLAN, WRITE

from ragwiki.ask import SYSTEM as WIKI_SYSTEM
from ragwiki.ask import ask
from ragwiki.ingest import ingest
from ragwiki.language import language_of, not_found
from ragwiki.rag import SYSTEM as RAG_SYSTEM
from ragwiki.rag import ask_rag


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("¿Qué produce el ATP en la célula?", "es"),
        ("que modelo usan los dos sistemas", "es"),
        ("What produces ATP in the cell?", "en"),
        ("ATP", "en"),
    ],
)
def test_language_of_tells_spanish_from_english(text, lang):
    assert language_of(text) == lang


def test_not_found_speaks_the_language_of_the_question():
    assert not_found("¿Dónde está el dato?") == "Tus documentos no responden esta pregunta."
    assert not_found("Where is it?") == "Your notes do not answer this question."


def test_both_architectures_are_told_to_answer_in_the_language_of_the_question():
    for system in (WIKI_SYSTEM, RAG_SYSTEM):
        assert "same language as the question" in system


def test_an_abstention_without_text_is_in_spanish_for_a_spanish_question(vault, note):
    ingest(vault, ScriptedModel(PLAN, WRITE), note("cells.md", CELLS))
    model = ScriptedModel({"action": "answer", "found": False, "text": ""})

    answer = ask(vault, model, "¿Qué hacen los ribosomas?")

    assert answer.text == "Tus documentos no responden esta pregunta."


def test_retrieval_with_nothing_found_abstains_in_spanish(vault):
    answer = ask_rag(vault, ScriptedModel(), "¿Qué hacen los ribosomas?")

    assert answer.text == "Tus documentos no responden esta pregunta."
