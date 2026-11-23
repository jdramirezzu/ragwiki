"""Comparing the wiki and the retrieval baseline on the same question, model and sources.

The only thing that changes between the two arms is how knowledge reaches the model: pages
the model wrote beforehand (`ask`) or source paragraphs retrieved at question time
(`ask_rag`). Each comparison records answers, citations, tokens, time and price, and can
carry the person's verdict, so a set of questions becomes a small experiment on their own
material.
"""

import json
import re
import time
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ragwiki.ask import ask
from ragwiki.models import Image, Model, Reply
from ragwiki.rag import DEFAULT_K, Embedder, ask_rag
from ragwiki.vault import STATE_DIR, Vault

ARMS = ("wiki", "rag")
VERDICTS = ("wiki", "rag", "tie", "neither")
COMPARISONS = "comparisons.jsonl"
INGESTIONS = "ingestions.jsonl"


class Tally:
    """Counts calls, tokens and time of one arm, whatever model it wraps."""

    def __init__(self, inner: Model) -> None:
        self.inner = inner
        self.calls = self.input_tokens = self.output_tokens = 0
        self.seconds = 0.0

    def complete(self, system: str, user: str, images: Sequence[Image] = ()) -> Reply:
        start = time.monotonic()
        reply = (
            self.inner.complete(system, user, images=images)
            if images
            else self.inner.complete(system, user)
        )
        self.seconds += time.monotonic() - start
        self.calls += 1
        self.input_tokens += reply.input_tokens
        self.output_tokens += reply.output_tokens
        return reply


@dataclass
class ArmResult:
    arm: str
    found: bool
    text: str
    citations: list[str]
    calls: int
    input_tokens: int
    output_tokens: int
    seconds: float
    usd: float | None
    """None when no price is configured, so the cost is unknown rather than free."""
    detail: dict = field(default_factory=dict)


def _normal(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w.%]+", " ", plain)).strip()


def check_expected(answer: ArmResult, expected: str) -> bool | None:
    """Whether an answer contains every key of the expected answer. None when there is none.

    Keys are separated by commas or semicolons, such as `ATP, mitochondria`. Matching
    ignores case, accents and punctuation. For an unanswerable question write `none`: the
    answer is then correct only when the arm abstains. This is a deterministic first check,
    like the one in the study; a person's verdict decides the rest.
    """
    keys = [_normal(key) for key in re.split(r"[;,]", expected) if _normal(key)]
    if not keys:
        return None
    if keys == ["none"]:
        return not answer.found
    if not answer.found:
        return False
    text = _normal(answer.text)
    return all(key in text for key in keys)


@dataclass
class Comparison:
    id: str
    time: str
    question: str
    wiki: ArmResult
    rag: ArmResult
    verdict: str | None = None
    note: str = ""
    expected: str = ""

    def arm(self, name: str) -> ArmResult:
        return self.wiki if name == "wiki" else self.rag

    def correct(self, name: str) -> bool | None:
        return check_expected(self.arm(name), self.expected) if self.expected else None

    @property
    def shared_citations(self) -> list[str]:
        return sorted(set(self.wiki.citations) & set(self.rag.citations))


def _prices(model: Model) -> tuple[float, float]:
    return float(getattr(model, "price_input", 0.0)), float(getattr(model, "price_output", 0.0))


def _usd(tally: Tally, prices: tuple[float, float]) -> float | None:
    if prices == (0.0, 0.0):
        return None
    return (tally.input_tokens * prices[0] + tally.output_tokens * prices[1]) / 1_000_000


def compare(
    vault: Vault,
    model: Model,
    question: str,
    *,
    k: int = DEFAULT_K,
    embedder: Embedder | None = None,
    prices: tuple[float, float] | None = None,
    expected: str = "",
) -> Comparison:
    """Ask the same question to both arms with the same model. Nothing is saved.

    `prices` are USD per million tokens; by default they are read from a `MeteredModel`.
    """
    prices = prices if prices is not None else _prices(model)
    return Comparison(
        id=uuid.uuid4().hex[:12],
        time=_now(),
        question=question,
        expected=expected.strip(),
        wiki=answer_with(vault, model, question, "wiki", prices=prices),
        rag=answer_with(vault, model, question, "rag", k=k, embedder=embedder, prices=prices),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def answer_with(
    vault: Vault,
    model: Model,
    question: str,
    arm: str,
    *,
    k: int = DEFAULT_K,
    embedder: Embedder | None = None,
    prices: tuple[float, float] | None = None,
) -> ArmResult:
    """Answer with one architecture only, measured the same way as in a comparison."""
    if arm not in ARMS:
        raise ValueError(f"arm must be one of {', '.join(ARMS)}, got '{arm}'")
    prices = prices if prices is not None else _prices(model)
    tally = Tally(model)
    if arm == "wiki":
        wiki = ask(vault, tally, question)
        found, text, citations = wiki.found, wiki.text, wiki.citations
        detail: dict = {"pages_read": wiki.pages_read, "steps": wiki.steps}
    else:
        rag = ask_rag(vault, tally, question, k=k, embedder=embedder)
        found, text, citations = rag.found, rag.text, rag.citations
        detail = {
            "retrieval": rag.retrieval,
            "k": k,
            "retrieved": [passage.citation for passage in rag.passages],
            "context_tokens": rag.context_tokens,
        }
    return ArmResult(
        arm,
        found,
        text,
        citations,
        tally.calls,
        tally.input_tokens,
        tally.output_tokens,
        round(tally.seconds, 3),
        _usd(tally, prices),
        detail,
    )


# --- saved experiment ------------------------------------------------------------------


def _path(vault: Vault, name: str) -> Path:
    return vault.root / STATE_DIR / name


def save_comparison(vault: Vault, comparison: Comparison) -> None:
    path = _path(vault, COMPARISONS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(comparison), ensure_ascii=False) + "\n")


def _from_dict(data: dict) -> Comparison:
    return Comparison(
        id=data["id"],
        time=data["time"],
        question=data["question"],
        wiki=ArmResult(**data["wiki"]),
        rag=ArmResult(**data["rag"]),
        verdict=data.get("verdict"),
        note=data.get("note", ""),
        expected=data.get("expected", ""),
    )


def load_comparisons(vault: Vault) -> list[Comparison]:
    path = _path(vault, COMPARISONS)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [_from_dict(json.loads(line)) for line in lines if line.strip()]


def set_verdict(vault: Vault, comparison_id: str, verdict: str | None, note: str = "") -> None:
    """Record which answer the person found better: wiki, rag, tie or neither."""
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}, got '{verdict}'")
    comparisons = load_comparisons(vault)
    if not any(item.id == comparison_id for item in comparisons):
        raise KeyError(f"Unknown comparison: {comparison_id}")
    path = _path(vault, COMPARISONS)
    with path.open("w", encoding="utf-8") as handle:
        for item in comparisons:
            if item.id == comparison_id:
                item.verdict, item.note = verdict, note
            handle.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class Ingestion:
    """The one-time cost of building the wiki from a file. The baseline has none."""

    file: str
    calls: int
    input_tokens: int
    output_tokens: int
    seconds: float
    usd: float | None


def record_ingestion(vault: Vault, ingestion: Ingestion) -> None:
    path = _path(vault, INGESTIONS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(ingestion), ensure_ascii=False) + "\n")


def load_ingestions(vault: Vault) -> list[Ingestion]:
    path = _path(vault, INGESTIONS)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Ingestion(**json.loads(line)) for line in lines if line.strip()]


@dataclass(frozen=True)
class ArmSummary:
    arm: str
    questions: int
    answered: int
    mean_input_tokens: float
    mean_output_tokens: float
    mean_seconds: float
    total_usd: float | None
    preferred: int
    checked: int
    correct: int


@dataclass(frozen=True)
class Summary:
    questions: int
    judged: int
    ties: int
    neither: int
    arms: dict[str, ArmSummary]
    ingestion_usd: float | None
    ingestion_calls: int


def _sum_usd(values: list[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def summarize(comparisons: list[Comparison], ingestions: list[Ingestion] = ()) -> Summary:
    """Totals and means per arm over a set of comparisons, plus the wiki's building cost."""
    count = len(comparisons)
    verdicts = [item.verdict for item in comparisons if item.verdict]
    arms = {}
    for name in ARMS:
        results = [item.arm(name) for item in comparisons]

        def mean(values: list[float]) -> float:
            return round(sum(values) / count, 3) if count else 0.0

        arms[name] = ArmSummary(
            arm=name,
            questions=count,
            answered=sum(result.found for result in results),
            mean_input_tokens=mean([r.input_tokens for r in results]),
            mean_output_tokens=mean([r.output_tokens for r in results]),
            mean_seconds=mean([r.seconds for r in results]),
            total_usd=_sum_usd([r.usd for r in results]),
            preferred=verdicts.count(name),
            checked=sum(item.correct(name) is not None for item in comparisons),
            correct=sum(item.correct(name) is True for item in comparisons),
        )
    return Summary(
        questions=count,
        judged=len(verdicts),
        ties=verdicts.count("tie"),
        neither=verdicts.count("neither"),
        arms=arms,
        ingestion_usd=_sum_usd([item.usd for item in ingestions]),
        ingestion_calls=sum(item.calls for item in ingestions),
    )


# --- recommendation ---------------------------------------------------------------------

MIN_EVIDENCE = 5
CLEAR_GAP = 0.10


@dataclass(frozen=True)
class Recommendation:
    choice: str
    """"wiki", "rag" or "undecided"."""
    headline: str
    reasons: list[str]


def _quality(summary: Summary) -> tuple[str, int, dict[str, float]] | None:
    """Each arm's quality on the person's questions: expected answers first, verdicts next."""
    checked = min(summary.arms[name].checked for name in ARMS)
    if checked >= MIN_EVIDENCE:
        rates = {name: summary.arms[name].correct / checked for name in ARMS}
        return "expected answers", checked, rates
    if summary.judged >= MIN_EVIDENCE:
        wins = {name: summary.arms[name].preferred + summary.ties for name in ARMS}
        rates = {name: wins[name] / summary.judged for name in ARMS}
        return "your verdicts", summary.judged, rates
    return None


def _ratio(wiki: float | None, rag: float | None) -> str | None:
    if not wiki or not rag:
        return None
    return f"{wiki / rag:.1f}"


def recommend(summary: Summary, k: int | None = None) -> Recommendation:
    """Which architecture suits this corpus, from the person's own evidence.

    The rule follows the study behind ragwiki: the wiki is worth its higher cost only
    when it answers clearly better (a gap of at least 0.10); with similar quality the
    cheaper retrieval wins. It needs five evaluated questions before deciding.
    """
    quality = _quality(summary)
    if quality is None:
        evaluated = max(summary.judged, *(summary.arms[n].checked for n in ARMS))
        return Recommendation(
            "undecided",
            f"Not enough evidence yet: evaluate at least {MIN_EVIDENCE} questions",
            [
                f"{evaluated} evaluated so far. Give questions an expected answer, or judge "
                "each pair of answers, so the lab can compare quality.",
                "Use questions like the real ones you will ask, including some that join "
                "several documents and some your files do not answer.",
            ],
        )
    basis, count, rates = quality
    gap = rates["wiki"] - rates["rag"]
    wiki, rag = summary.arms["wiki"], summary.arms["rag"]
    cost = _ratio(wiki.total_usd, rag.total_usd)
    tokens = _ratio(wiki.mean_input_tokens, rag.mean_input_tokens)
    reasons = [
        f"Quality from {basis} on {count} questions: wiki {rates['wiki']:.2f}, "
        f"RAG {rates['rag']:.2f} (gap {gap:+.2f}).",
    ]
    if cost:
        reasons.append(f"Each wiki question costs {cost}× a RAG question.")
    elif tokens:
        reasons.append(f"Each wiki question reads {tokens}× the tokens of a RAG question.")
    if summary.ingestion_usd is not None:
        reasons.append(
            f"Building the wiki cost ${summary.ingestion_usd:.4f} once; RAG has no building cost."
        )
    if gap >= CLEAR_GAP:
        if k is not None and k < 15:
            reasons.append(
                f"RAG retrieved {k} paragraphs. In the study the wiki's lead shrank as RAG "
                "received more context: try a larger k before adopting the wiki."
            )
        reasons.append(
            "The wiki pays off when your files change little and you ask many questions "
            "that join several documents."
        )
        return Recommendation("wiki", "The wiki answers your questions clearly better", reasons)
    if gap <= -CLEAR_GAP:
        return Recommendation("rag", "RAG answers your questions better, and costs less", reasons)
    reasons.append(
        "With similar quality, the cheaper and simpler architecture wins. Prefer the wiki only "
        "if you value reading and browsing the pages it writes."
    )
    return Recommendation("rag", "Similar quality: RAG is enough for your corpus", reasons)


# --- answers with one architecture ------------------------------------------------------

ANSWERS = "answers.jsonl"


@dataclass
class SingleAnswer:
    """A question answered with only the architecture the person chose to build."""

    id: str
    time: str
    question: str
    result: ArmResult


def record_answer(vault: Vault, question: str, result: ArmResult) -> SingleAnswer:
    answer = SingleAnswer(uuid.uuid4().hex[:12], _now(), question, result)
    path = _path(vault, ANSWERS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(answer), ensure_ascii=False) + "\n")
    return answer


def load_answers(vault: Vault) -> list[SingleAnswer]:
    path = _path(vault, ANSWERS)
    if not path.is_file():
        return []
    answers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            data = json.loads(line)
            data["result"] = ArmResult(**data["result"])
            answers.append(SingleAnswer(**data))
    return answers
