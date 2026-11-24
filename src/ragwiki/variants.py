"""Kinds of RAG: the same answer step over different ways of finding the paragraphs.

A variant is a retrieval recipe: a search (`bm25` words, `vector` meaning, or `hybrid`, both
fused by reciprocal rank), optionally a local reranker over a wider pool, and optionally a
window that adds each paragraph's neighbours. The citation stays the retrieved paragraph,
so answers remain checkable.

`search_bench` compares variants for free: with the expected answers a person wrote, it
checks whether each variant brings a paragraph that contains the answer within its first
`k`. No model is called. `answer_variants` then answers with the variants worth paying for.
"""

import json
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from ragwiki.compare import NO_ANSWER, ArmResult, Tally, _normal, _prices, _usd, check_expected
from ragwiki.language import language_of
from ragwiki.models import ConfigError, Model
from ragwiki.rag import (
    DEFAULT_K,
    Embedder,
    Passage,
    _by_score,
    _cached_vectors,
    _cosine,
    _paragraphs,
    ask_rag,
)
from ragwiki.search import rank
from ragwiki.vault import STATE_DIR, Vault

SEARCHES = ("bm25", "vector", "hybrid")
POOL = 30
"""How many paragraphs a reranker or the hybrid fusion looks at before keeping `k`."""
RRF = 60
"""The usual reciprocal rank fusion constant: a paragraph scores 1 / (RRF + its rank)."""

RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
# On the study's Spanish documents the English reranker halved the right-first answers (4 of 11
# against 8 for hybrid search alone); this multilingual one kept 8, and is the smaller download.
MULTILINGUAL_RERANK_MODEL = "BAAI/bge-reranker-v2-m3-int8"


@dataclass(frozen=True)
class Variant:
    search: str
    rerank: bool = False
    window: int = 0
    """Neighbouring paragraphs added on each side of a retrieved one."""

    def __post_init__(self) -> None:
        if self.search not in SEARCHES:
            raise ValueError(f"search must be one of {', '.join(SEARCHES)}, got '{self.search}'")
        if self.window < 0:
            raise ValueError("window cannot be negative")

    @property
    def name(self) -> str:
        parts = [self.search] + ["rerank"] * self.rerank
        if self.window:
            parts.append("window" if self.window == 1 else f"window{self.window}")
        return "+".join(parts)

    @property
    def needs_vectors(self) -> bool:
        return self.search != "bm25"

    @classmethod
    def parse(cls, name: str) -> "Variant":
        search, *extras = name.strip().split("+")
        rerank, window = False, 0
        for extra in extras:
            if extra == "rerank":
                rerank = True
            elif extra.startswith("window") and (extra[6:] or "1").isdigit():
                window = int(extra[6:] or "1")
            else:
                raise ValueError(f"unknown part '{extra}' in variant '{name}'")
        return cls(search, rerank, window)


PRESETS = (
    Variant("bm25"),
    Variant("vector"),
    Variant("hybrid"),
    Variant("hybrid", rerank=True),
    Variant("vector", window=1),
)


class Reranker(Protocol):
    name: str

    def scores(self, question: str, texts: Sequence[str]) -> list[float]: ...


class LocalReranker:
    """A cross-encoder run on this computer with fastembed. Downloaded once, on first use."""

    def __init__(self, model: str = RERANK_MODEL) -> None:
        self.model = model
        self.name = f"local/{model}"
        self._engine = None

    def scores(self, question: str, texts: Sequence[str]) -> list[float]:
        if self._engine is None:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
            except ImportError as error:
                raise ConfigError("Reranking needs fastembed: `uv sync --extra lab`.") from error
            self._engine = TextCrossEncoder(model_name=self.model)
        return [float(score) for score in self._engine.rerank(question, list(texts))]


def default_rerank_model(vault: Vault) -> str:
    """A multilingual reranker when most text is Spanish, a small English one otherwise."""
    paragraphs = [text for _, text in _paragraphs(vault).values()][:400]
    spanish = sum(language_of(text) == "es" for text in paragraphs)
    return MULTILINGUAL_RERANK_MODEL if spanish > len(paragraphs) / 2 else RERANK_MODEL


class _Corpus:
    """The vault's paragraphs, loaded once for many questions."""

    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        self.paragraphs = _paragraphs(vault)
        self.documents = {key: f"{title} {text}" for key, (title, text) in self.paragraphs.items()}
        self.order = list(self.paragraphs)
        self._vectors: dict[str, dict[str, list]] = {}

    def words(self, question: str, limit: int) -> list[tuple[str, float]]:
        return [(hit.key, hit.score) for hit in rank(question, self.documents, limit=limit)]

    def meaning(self, question: str, limit: int, embedder: Embedder) -> list[tuple[str, float]]:
        if embedder.name not in self._vectors:
            texts = {key: text for key, (_, text) in self.paragraphs.items()}
            self._vectors[embedder.name] = _cached_vectors(self.vault, embedder, texts)
        query = embedder.embed([question])[0]
        vectors = self._vectors[embedder.name]
        return sorted(((key, _cosine(query, v)) for key, v in vectors.items()), key=_by_score)[
            :limit
        ]

    def text(self, key: str, window: int) -> str:
        if not window:
            return self.paragraphs[key][1]
        source = key.split("#", 1)[0]
        at = self.order.index(key)
        around = self.order[max(0, at - window) : at + window + 1]
        return "\n\n".join(self.paragraphs[k][1] for k in around if k.split("#", 1)[0] == source)

    def retrieve(
        self,
        question: str,
        variant: Variant,
        k: int,
        embedder: Embedder | None,
        reranker: Reranker | None,
    ) -> list[Passage]:
        if variant.needs_vectors and embedder is None:
            raise ConfigError(f"The '{variant.name}' search needs embeddings.")
        if variant.rerank and reranker is None:
            raise ConfigError(f"The '{variant.name}' search needs a reranker.")
        if not self.paragraphs:
            return []
        wanted = max(k, POOL) if variant.rerank else k
        if variant.search == "bm25":
            scored = self.words(question, wanted)
        elif variant.search == "vector":
            scored = self.meaning(question, wanted, embedder)
        else:
            fused: dict[str, float] = {}
            pool = max(wanted, POOL)
            for ranking in (self.words(question, pool), self.meaning(question, pool, embedder)):
                for position, (key, _) in enumerate(ranking, start=1):
                    fused[key] = fused.get(key, 0.0) + 1 / (RRF + position)
            scored = sorted(fused.items(), key=_by_score)[:wanted]
        if variant.rerank and scored:
            keys = [key for key, _ in scored]
            new = reranker.scores(question, [self.paragraphs[key][1] for key in keys])
            scored = sorted(zip(keys, new, strict=True), key=_by_score)
        return [
            Passage(key, self.paragraphs[key][0], self.text(key, variant.window), score)
            for key, score in scored[:k]
        ]


def retrieve_variant(
    vault: Vault,
    question: str,
    variant: Variant,
    k: int = DEFAULT_K,
    *,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> list[Passage]:
    """The `k` paragraphs this variant gives the model, best first. No chat model call."""
    return _Corpus(vault).retrieve(question, variant, k, embedder, reranker)


# --- free comparison of the searches -----------------------------------------------------


def _keys(expected: str) -> list[str] | None:
    """The keys to look for, or None when the question cannot be checked by search."""
    keys = [_normal(key) for key in expected.replace(";", ",").split(",") if _normal(key)]
    if not keys or (len(keys) == 1 and keys[0] in NO_ANSWER):
        return None
    return keys


@dataclass
class VariantScore:
    variant: str
    checked: int
    found: int
    mrr: float
    """Mean of 1 / rank of the first paragraph with the answer (0 when none in the top k)."""
    seconds: float
    questions: list[dict] = field(default_factory=list)


@dataclass
class Bench:
    id: str
    time: str
    k: int
    embedder: str | None
    reranker: str | None
    scores: list[VariantScore]

    @property
    def best(self) -> str | None:
        ranked = [s for s in self.scores if s.checked]
        if not ranked:
            return None
        return max(ranked, key=lambda s: (s.found / s.checked, s.mrr, -s.seconds)).variant


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def search_bench(
    vault: Vault,
    items: Iterable[tuple[str, str]],
    variants: Sequence[Variant],
    *,
    k: int = DEFAULT_K,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> Bench:
    """Score each variant on (question, expected answer) pairs and save the result. Free.

    A question counts as found when a retrieved paragraph contains every key of its
    expected answer. Questions with no expected answer, or with `none`, are listed but not
    scored: search alone cannot tell a right abstention.
    """
    if k < 1:
        raise ConfigError(f"k must be at least 1, got {k}")
    corpus = _Corpus(vault)
    items = list(items)
    scores = []
    for variant in variants:
        rows, found, reciprocal, seconds = [], 0, 0.0, 0.0
        for question, expected in items:
            start = time.monotonic()
            passages = corpus.retrieve(question, variant, k, embedder, reranker)
            seconds += time.monotonic() - start
            keys = _keys(expected)
            position = None
            if keys is not None:
                for number, passage in enumerate(passages, start=1):
                    text = _normal(passage.text)
                    if all(key in text for key in keys):
                        position = number
                        break
                found += position is not None
                reciprocal += 1 / position if position else 0.0
            rows.append(
                {
                    "question": question,
                    "expected": expected,
                    "checked": keys is not None,
                    "rank": position,
                    "retrieved": [p.citation for p in passages],
                }
            )
        checked = sum(row["checked"] for row in rows)
        scores.append(
            VariantScore(
                variant.name,
                checked,
                found,
                round(reciprocal / checked, 3) if checked else 0.0,
                round(seconds / max(1, len(items)), 3),
                rows,
            )
        )
    bench = Bench(
        uuid.uuid4().hex[:12],
        _now(),
        k,
        embedder.name if embedder and any(v.needs_vectors for v in variants) else None,
        reranker.name if reranker and any(v.rerank for v in variants) else None,
        scores,
    )
    _append(vault, "rag-variants.jsonl", asdict(bench) | {"best": bench.best})
    return bench


def load_benches(vault: Vault) -> list[Bench]:
    benches = []
    for data in _read(vault, "rag-variants.jsonl"):
        data.pop("best", None)
        data["scores"] = [VariantScore(**score) for score in data["scores"]]
        benches.append(Bench(**data))
    return benches


# --- paid answers with chosen variants --------------------------------------------------


def answer_variants(
    vault: Vault,
    model: Model,
    items: Iterable[tuple[str, str]],
    variants: Sequence[Variant],
    *,
    k: int = DEFAULT_K,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    prices: tuple[float, float] | None = None,
    on_progress: Callable[[int, int, str, str], None] | None = None,
) -> list[dict]:
    """Answer every question with every variant: one model call each. Saved as they finish.

    `on_progress(done, total, question, variant)` is called before every model call.
    """
    prices = prices if prices is not None else _prices(model)
    corpus = _Corpus(vault)
    items = list(items)
    total = len(items) * len(variants)
    done = []
    for question, expected in items:
        for variant in variants:
            if on_progress is not None:
                on_progress(len(done), total, question, variant.name)
            tally = Tally(model)
            passages = corpus.retrieve(question, variant, k, embedder, reranker)
            rag = ask_rag(vault, tally, question, k=k, passages=passages, retrieval=variant.name)
            result = ArmResult(
                variant.name,
                rag.found,
                rag.text,
                rag.citations,
                tally.calls,
                tally.input_tokens,
                tally.output_tokens,
                round(tally.seconds, 3),
                _usd(tally, prices),
                {
                    "retrieval": variant.name,
                    "k": k,
                    "retrieved": [p.citation for p in passages],
                    "context_tokens": rag.context_tokens,
                },
            )
            record = {
                "id": uuid.uuid4().hex[:12],
                "time": _now(),
                "question": question,
                "expected": expected.strip(),
                "variant": variant.name,
                "correct": check_expected(result, expected) if expected.strip() else None,
                "result": asdict(result),
            }
            _append(vault, "rag-variant-answers.jsonl", record)
            done.append(record)
    return done


def load_variant_answers(vault: Vault) -> list[dict]:
    return list(_read(vault, "rag-variant-answers.jsonl"))


def _path(vault: Vault, name: str) -> Path:
    return vault.root / STATE_DIR / name


def _append(vault: Vault, name: str, data: dict) -> None:
    with _path(vault, name).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


def _read(vault: Vault, name: str) -> Iterable[dict]:
    path = _path(vault, name)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
