"""Lesson-scoped retrieval: which approved passages go into the prompt.

The corpus is ONE lesson revision (a few dozen short blocks), so the baseline
is a transparent in-memory ranker with no index, no vector database and no
network call. ``Ranker`` is the seam: an embedding ranker can replace
``Bm25Ranker`` without touching the tutoring contract or the service.

A passage only becomes context when the ranker calls it *relevant*. When
nothing is relevant the tutor says so instead of answering from thin air.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from edu_api.tutor.content import ApprovedLesson
from edu_api.tutor.text import normalize, tokenize
from edu_api.tutor.types import LessonReference

PassageKind = Literal[
    "heading", "paragraph", "example", "callout", "question_prompt", "question_explanation"
]


@dataclass(frozen=True)
class Passage:
    ref: LessonReference
    kind: PassageKind
    text: str
    #: Order inside the lesson; questions come after every block.
    position: int


@dataclass(frozen=True)
class ScoredPassage:
    passage: Passage
    score: float
    relevant: bool


@dataclass(frozen=True)
class ContextPassage:
    """A passage as shown to the model: ``id`` is the only handle the model gets."""

    id: str
    passage: Passage


@dataclass(frozen=True)
class RetrievedContext:
    passages: tuple[ContextPassage, ...]
    #: Name of the ranking strategy, recorded as operational metadata.
    strategy: str
    truncated: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.passages

    def by_id(self) -> dict[str, Passage]:
        return {p.id: p.passage for p in self.passages}


def lesson_passages(lesson: ApprovedLesson) -> list[Passage]:
    """Every block of the lesson as a passage with a stable reference."""
    return [
        Passage(
            ref=LessonReference(
                lesson_id=lesson.lesson_id,
                lesson_revision_id=lesson.revision_id,
                locale=lesson.locale,
                kind="block",
                key=block.key,
            ),
            kind=block.type,
            text=block.text,
            position=index,
        )
        for index, block in enumerate(lesson.blocks)
    ]


def question_passage(
    lesson: ApprovedLesson, question_key: str, *, with_explanation: bool
) -> Passage | None:
    """A practice question as context.

    The reviewed explanation (which gives the answer away) is included only
    when the caller asks for it; the answer key itself never is.
    """
    question = lesson.question(question_key)
    if question is None:
        return None
    lines = [question.prompt, *(f"{choice.id}) {choice.text}" for choice in question.choices)]
    kind: PassageKind = "question_prompt"
    if with_explanation and question.explanation:
        lines.append(question.explanation)
        kind = "question_explanation"
    return Passage(
        ref=LessonReference(
            lesson_id=lesson.lesson_id,
            lesson_revision_id=lesson.revision_id,
            locale=lesson.locale,
            kind="question",
            key=question.question_key,
        ),
        kind=kind,
        text="\n".join(line for line in lines if line),
        position=len(lesson.blocks) + 1,
    )


class Ranker(Protocol):
    name: str

    def rank(self, query: str, passages: Sequence[Passage]) -> list[ScoredPassage]:
        """All passages, best first, each marked relevant or not."""
        ...


def _ordered(scored: list[ScoredPassage]) -> list[ScoredPassage]:
    # Ties break on lesson order so results never depend on dict or set order.
    return sorted(scored, key=lambda s: (-s.score, s.passage.position))


class Bm25Ranker:
    """Okapi BM25 over stemmed words. Deterministic; explains itself by term overlap.

    ``min_coverage`` is the share of the question's informative weight that
    must occur in a passage. It stops a passage being called relevant because
    it shares one common word (or the digit 5) with an unrelated question.
    """

    name = "bm25-v1"

    def __init__(self, *, k1: float = 1.4, b: float = 0.6, min_coverage: float = 0.34) -> None:
        self._k1 = k1
        self._b = b
        self._min_coverage = min_coverage

    def rank(self, query: str, passages: Sequence[Passage]) -> list[ScoredPassage]:
        if not passages:
            return []
        documents = [Counter(tokenize(p.text)) for p in passages]
        lengths = [sum(doc.values()) for doc in documents]
        average = (sum(lengths) / len(lengths)) or 1.0
        total = len(documents)
        terms = list(dict.fromkeys(tokenize(query)))
        idf = {
            term: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for term in terms
            for df in [sum(1 for doc in documents if term in doc)]
        }
        query_weight = sum(idf.values())
        scored: list[ScoredPassage] = []
        for passage, document, length in zip(passages, documents, lengths, strict=True):
            score = 0.0
            matched_weight = 0.0
            for term in terms:
                frequency = document.get(term, 0)
                if not frequency:
                    continue
                matched_weight += idf[term]
                norm = frequency + self._k1 * (1 - self._b + self._b * length / average)
                score += idf[term] * frequency * (self._k1 + 1) / norm
            coverage = matched_weight / query_weight if query_weight else 0.0
            scored.append(
                ScoredPassage(passage, score, score > 0 and coverage >= self._min_coverage)
            )
        return _ordered(scored)


def _char_ngrams(text: str, n: int = 3) -> Counter[str]:
    joined = " ".join(tokenize(text))
    padded = f" {joined} "
    return Counter(padded[i : i + n] for i in range(max(len(padded) - n + 1, 0)))


class CharNgramRanker:
    """TF-IDF cosine over character trigrams.

    A cheap stand-in for *fuzzy* matching (spelling variants, word forms) used
    as the comparison point in the retrieval evaluation. It is NOT a semantic
    embedding and makes no claim to be one.
    """

    name = "char3-tfidf-v1"

    def __init__(self, *, min_similarity: float = 0.12) -> None:
        self._min_similarity = min_similarity

    def rank(self, query: str, passages: Sequence[Passage]) -> list[ScoredPassage]:
        if not passages:
            return []
        documents = [_char_ngrams(p.text) for p in passages]
        total = len(documents)
        frequency: Counter[str] = Counter()
        for document in documents:
            frequency.update(document.keys())

        def weigh(grams: Counter[str]) -> dict[str, float]:
            return {
                gram: count * math.log(1 + total / (1 + frequency.get(gram, 0)))
                for gram, count in grams.items()
            }

        def norm(vector: dict[str, float]) -> float:
            return math.sqrt(sum(v * v for v in vector.values()))

        query_vector = weigh(_char_ngrams(query))
        query_norm = norm(query_vector)
        scored: list[ScoredPassage] = []
        for passage, document in zip(passages, documents, strict=True):
            vector = weigh(document)
            denominator = query_norm * norm(vector)
            similarity = (
                sum(weight * vector.get(gram, 0.0) for gram, weight in query_vector.items())
                / denominator
                if denominator
                else 0.0
            )
            scored.append(ScoredPassage(passage, similarity, similarity >= self._min_similarity))
        return _ordered(scored)


class HybridRanker:
    """Reciprocal-rank fusion of several rankers; relevant when ANY of them says so."""

    def __init__(self, rankers: Sequence[Ranker], *, k: int = 20) -> None:
        if not rankers:
            raise ValueError("HybridRanker needs at least one ranker")
        self._rankers = tuple(rankers)
        self._k = k
        self.name = "rrf(" + "+".join(r.name for r in self._rankers) + ")"

    def rank(self, query: str, passages: Sequence[Passage]) -> list[ScoredPassage]:
        fused: dict[int, float] = {}
        relevant: set[int] = set()
        for ranker in self._rankers:
            for rank, item in enumerate(ranker.rank(query, passages), start=1):
                position = item.passage.position
                fused[position] = fused.get(position, 0.0) + 1.0 / (self._k + rank)
                if item.relevant:
                    relevant.add(position)
        return _ordered(
            [ScoredPassage(p, fused.get(p.position, 0.0), p.position in relevant) for p in passages]
        )


@dataclass(frozen=True)
class RetrievalQuery:
    #: The student's words (already screened and redacted), if any.
    text: str | None = None
    focus_block_key: str | None = None
    question_key: str | None = None
    #: Include the reviewed explanation of ``question_key`` (it reveals the answer).
    reveal_question_explanation: bool = False


class LessonRetriever:
    """Chooses a bounded, ordered set of passages from one approved lesson."""

    def __init__(self, ranker: Ranker, *, top_k: int = 4, max_context_chars: int = 6000) -> None:
        if top_k < 1 or max_context_chars < 200:
            raise ValueError("top_k must be >= 1 and max_context_chars >= 200")
        self._ranker = ranker
        self._top_k = top_k
        self._max_chars = max_context_chars

    @property
    def strategy(self) -> str:
        return self._ranker.name

    def retrieve(self, lesson: ApprovedLesson, query: RetrievalQuery) -> RetrievedContext:
        passages = lesson_passages(lesson)
        by_key = {p.ref.key: p for p in passages}
        chosen: dict[int, Passage] = {}

        # 1. What the learner explicitly pointed at is always context.
        if query.question_key:
            question = question_passage(
                lesson, query.question_key, with_explanation=query.reveal_question_explanation
            )
            if question is not None:
                chosen[question.position] = question
        focus = by_key.get(query.focus_block_key) if query.focus_block_key else None

        # 2. Rank the lesson against the learner's words, else against what they pointed at.
        search_text = query.text
        if not search_text and query.question_key:
            pointed = lesson.question(query.question_key)
            search_text = pointed.prompt if pointed else None
        ranked = self._ranker.rank(search_text, passages) if search_text else []
        hits = [s.passage for s in ranked if s.relevant][: self._top_k]

        # A question in the learner's own words that matches nothing in the
        # lesson stays unanswered, even when a block is in focus: the focus says
        # where they are reading, not that the lesson covers what they asked.
        if query.text and not hits:
            return RetrievedContext((), self.strategy)

        if focus is not None:
            chosen[focus.position] = focus
        for passage in hits:
            chosen.setdefault(passage.position, passage)

        # 3. Give each chosen passage its section heading: cheap, and it orients the model.
        for position in sorted(chosen):
            heading = self._heading_before(passages, position)
            if heading is not None:
                chosen.setdefault(heading.position, heading)

        if not any(p.kind != "heading" for p in chosen.values()):
            return RetrievedContext((), self.strategy)

        # 4. Enforce the size bound, keeping the most useful passages, then restore lesson order.
        priority = {p.position: rank for rank, p in enumerate(hits)}
        if focus is not None:
            priority[focus.position] = -1
        kept: list[Passage] = []
        used = 0
        truncated = False
        ordered_by_value = sorted(
            chosen.values(),
            key=lambda p: (
                0 if p.ref.kind == "question" else 1,
                priority.get(p.position, len(hits) + 1),
                p.position,
            ),
        )
        for passage in ordered_by_value:
            if used + len(passage.text) > self._max_chars:
                truncated = True
                continue
            kept.append(passage)
            used += len(passage.text)
        kept.sort(key=lambda p: p.position)
        if not any(p.kind != "heading" for p in kept):
            return RetrievedContext((), self.strategy, truncated)
        return RetrievedContext(
            tuple(ContextPassage(f"P{i}", p) for i, p in enumerate(kept, start=1)),
            self.strategy,
            truncated,
        )

    @staticmethod
    def _heading_before(passages: Sequence[Passage], position: int) -> Passage | None:
        for passage in reversed(passages[: min(position, len(passages))]):
            if passage.kind == "heading":
                return passage
        return None


def contains_text(context: RetrievedContext, needle: str) -> bool:
    """True when ``needle`` appears in any context passage (accent-insensitive)."""
    target = normalize(needle)
    return any(target in normalize(p.passage.text) for p in context.passages)
