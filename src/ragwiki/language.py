"""Which language a question is in, so answers and abstentions can follow it.

Only Spanish and English are told apart; anything else is treated as English. The check is
a small word count, offline and free, good enough for a question of a few words.
"""

import re

_SPANISH = set(
    "que qué cual cuál cuales cuáles como cómo donde dónde cuando cuándo cuanto cuánto cuantos "
    "cuántos quien quién por para con sin los las del una unos unas el la es son esta este "
    "estos estas se su sus hay entre sobre tiene tienen usan hace hacen".split()
)
_ENGLISH = set(
    "what which how where when who why the a an of is are was were does do did this these "
    "that with without for about there have has use used between".split()
)

NOT_FOUND = {
    "en": "Your notes do not answer this question.",
    "es": "Tus documentos no responden esta pregunta.",
}


def language_of(text: str) -> str:
    """ "es" or "en". Spanish punctuation and letters count as strong signs."""
    if re.search(r"[¿¡ñÑ]", text):
        return "es"
    words = re.findall(r"\w+", text.lower())
    spanish = sum(word in _SPANISH for word in words) + len(re.findall(r"[áéíóúü]", text))
    english = sum(word in _ENGLISH for word in words)
    return "es" if spanish > english else "en"


def not_found(question: str) -> str:
    return NOT_FOUND[language_of(question)]
