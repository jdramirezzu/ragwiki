"""Lexical search (BM25). Deterministic, offline and free: no embeddings needed."""

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

_K1 = 1.5
_B = 0.75


@dataclass(frozen=True)
class Hit:
    key: str
    score: float


def _fold(word: str) -> str:
    """Drop accents and a plural -s, so "Páginas" and "pagina" are the same word.

    People often type without accents, and a question may use the singular where the text
    uses the plural. Short words are kept whole so "es" and "is" do not collapse.
    """
    plain = "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))
    return plain[:-1] if len(plain) > 3 and plain.endswith("s") else plain


def tokenize(text: str) -> list[str]:
    return [_fold(word) for word in re.findall(r"\w+", text.lower())]


def rank(query: str, documents: dict[str, str], limit: int = 5) -> list[Hit]:
    """Return the documents that share words with the query, best first."""
    terms = set(tokenize(query))
    tokens = {key: tokenize(text) for key, text in documents.items()}
    if not terms or not tokens:
        return []
    average = sum(len(words) for words in tokens.values()) / len(tokens) or 1.0
    containing = Counter(term for words in tokens.values() for term in terms & set(words))

    hits: list[Hit] = []
    for key, words in tokens.items():
        counts = Counter(words)
        score = 0.0
        for term in terms:
            frequency = counts[term]
            if not frequency:
                continue
            idf = math.log((len(tokens) - containing[term] + 0.5) / (containing[term] + 0.5) + 1)
            length = 1 - _B + _B * len(words) / average
            score += idf * frequency * (_K1 + 1) / (frequency + _K1 * length)
        if score > 0:
            hits.append(Hit(key, score))
    return sorted(hits, key=lambda hit: (-hit.score, hit.key))[:limit]
