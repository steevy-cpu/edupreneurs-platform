"""Deterministic ways to find the right block when the question and the lesson
are in different languages. No model, no network, no vector database.

Four candidates, all ``Ranker`` implementations that slot into Jude-01's
``LessonRetriever`` unchanged:

* ``SectionRanker`` — not about language at all: a question often matches a
  section's HEADING best ("À quoi sert la dérivée ?"), and a heading alone is
  not usable context. Give the blocks under a matched heading its score.

* ``TwoTermBm25Ranker`` — also not about language: Jude-01 calls a passage
  relevant only if it covers a third of the question's weight, so one ordinary
  extra sentence ("J'ai peur d'échouer en maths. Comment ...") makes every
  passage "irrelevant". Also accept a passage that matches two solid terms.
* ``GlossaryRanker`` — translate the question's words into the lesson's language
  with a small bilingual school-mathematics glossary, then rank lexically.
* ``SiblingKeyRanker`` — a lesson exists as one revision per language. Rank the
  question against BOTH revisions and map the sibling's hits back by block key.
  Only valid when the two revisions are verified to have the same keys.

Neither is wired into the service here; the benchmark decides whether they earn it.
"""

from __future__ import annotations

import functools
import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from edu_api.tutor.content import ApprovedLesson
from edu_api.tutor.retrieval import Bm25Ranker, Passage, Ranker, ScoredPassage, lesson_passages
from edu_api.tutor.text import normalize, stem, tokenize
from jude_eval import DATASET_DIR


@dataclass(frozen=True)
class Glossary:
    """Stem-level translation tables in both directions."""

    to_ht: dict[str, tuple[str, ...]]
    to_fr: dict[str, tuple[str, ...]]
    entries: int

    def toward(self, locale: str) -> dict[str, tuple[str, ...]]:
        return self.to_ht if locale == "ht" else self.to_fr


def _stems(words: Sequence[str]) -> tuple[str, ...]:
    # Not ``tokenize``: it drops stop words, and a glossary may legitimately map a
    # content word to one (French "côté" is Creole "kote", also "where").
    return tuple(dict.fromkeys(stem(normalize(word)) for word in words))


def load_glossary(path: Path | None = None, *, exclude_scopes: Sequence[str] = ()) -> Glossary:
    return _load_glossary(path or DATASET_DIR / "glossary.fr-ht.json", tuple(exclude_scopes))


@functools.lru_cache(maxsize=32)
def _load_glossary(path: Path, exclude_scopes: tuple[str, ...]) -> Glossary:
    raw = json.loads(path.read_text(encoding="utf-8"))
    to_ht: dict[str, tuple[str, ...]] = {}
    to_fr: dict[str, tuple[str, ...]] = {}
    used = 0
    for entry in raw["entries"]:
        if entry["scope"] in exclude_scopes:
            continue
        used += 1
        french, creole = _stems(entry["fr"]), _stems(entry["ht"])
        for word in french:
            to_ht[word] = tuple(dict.fromkeys((*to_ht.get(word, ()), *creole)))
        for word in creole:
            to_fr[word] = tuple(dict.fromkeys((*to_fr.get(word, ()), *french)))
    return Glossary(to_ht, to_fr, used)


class GlossaryRanker:
    """BM25 after translating the question's words into the lesson's language.

    A word with a glossary entry is REPLACED by its translation(s); a word
    without one is kept, so numbers, symbols and shared spellings still match.
    When the question is already in the lesson's language the table for the
    other direction does not apply and the ranking equals plain BM25, apart from
    the few words spelled the same in both languages.
    """

    def __init__(self, glossary: Glossary, *, min_coverage: float = 0.34) -> None:
        self._glossary = glossary
        self._bm25 = Bm25Ranker(min_coverage=min_coverage)
        self.name = f"glossary({glossary.entries})+bm25-v1"

    def translate(self, query: str, target_locale: str) -> str:
        table = self._glossary.toward(target_locale)
        words: list[str] = []
        for raw in normalize(query).replace("'", " ").split():
            word = raw.strip('.,;:!?()«»"')
            translated = table.get(stem(word))
            words.extend(translated if translated else (word,))
        return " ".join(words)

    def rank(self, query: str, passages: Sequence[Passage]) -> list[ScoredPassage]:
        if not passages:
            return []
        return self._bm25.rank(self.translate(query, passages[0].ref.locale), passages)


class KeyAlignmentError(ValueError):
    """The two revisions do not have the same blocks; mapping by key would be wrong."""


def verify_key_alignment(lesson: ApprovedLesson, sibling: ApprovedLesson) -> None:
    """Same lesson, different locale, identical block keys and types in the same order."""
    if lesson.lesson_id != sibling.lesson_id:
        raise KeyAlignmentError("not two revisions of the same lesson")
    if lesson.locale == sibling.locale:
        raise KeyAlignmentError("the sibling must be in the other language")
    ours = [(b.key, b.type) for b in lesson.blocks]
    theirs = [(b.key, b.type) for b in sibling.blocks]
    if ours != theirs:
        raise KeyAlignmentError("block keys or types differ between the two revisions")


class SiblingKeyRanker:
    """Rank against the lesson and against its other-language revision; keep the better score.

    References still point at the revision the learner is reading: the sibling
    is only used to find WHICH block, never quoted or cited.
    """

    def __init__(self, base: Ranker, lesson: ApprovedLesson, sibling: ApprovedLesson) -> None:
        verify_key_alignment(lesson, sibling)
        self._base = base
        self._sibling = lesson_passages(sibling)
        self.name = f"sibling-keys+{base.name}"

    def rank(self, query: str, passages: Sequence[Passage]) -> list[ScoredPassage]:
        by_key = {s.passage.ref.key: s for s in self._base.rank(query, self._sibling)}
        merged: list[ScoredPassage] = []
        for own in self._base.rank(query, passages):
            other = by_key.get(own.passage.ref.key)
            score = max(own.score, other.score if other else 0.0)
            relevant = own.relevant or bool(other and other.relevant)
            merged.append(ScoredPassage(own.passage, score, relevant))
        return sorted(merged, key=lambda s: (-s.score, s.passage.position))


class SectionRanker:
    """Let a matched heading stand for the blocks of its section.

    Jude-01's retriever adds the heading ABOVE a chosen block, but when the
    heading itself is the best match the body under it is not pulled in, and a
    context of headings only is treated as "nothing found". Here every block
    between a heading and the next one inherits ``share`` of the heading's
    score and its relevance.
    """

    def __init__(self, base: Ranker, *, share: float = 0.9) -> None:
        self._base = base
        self._share = share
        self.name = f"sections+{base.name}"

    def rank(self, query: str, passages: Sequence[Passage]) -> list[ScoredPassage]:
        scored = {s.passage.position: s for s in self._base.rank(query, passages)}
        merged: list[ScoredPassage] = []
        heading: ScoredPassage | None = None
        for passage in sorted(passages, key=lambda p: p.position):
            own = scored[passage.position]
            if passage.kind == "heading":
                heading = own
                merged.append(own)
                continue
            if heading is not None and heading.relevant:
                merged.append(
                    ScoredPassage(
                        passage,
                        max(own.score, heading.score * self._share),
                        True,
                    )
                )
            else:
                merged.append(own)
        return sorted(merged, key=lambda s: (-s.score, s.passage.position))


class TwoTermBm25Ranker:
    """BM25 with Jude-01's scoring and a second way to be relevant.

    Relevant when the passage covers ``min_coverage`` of the question's weight
    (Jude-01's rule) OR matches at least ``min_strong_terms`` different
    non-numeric terms of four letters or more. The second rule does not care how
    much unrelated talk surrounds the question.
    """

    def __init__(
        self,
        *,
        k1: float = 1.4,
        b: float = 0.6,
        min_coverage: float = 0.34,
        min_strong_terms: int = 2,
    ) -> None:
        self._k1, self._b = k1, b
        self._min_coverage = min_coverage
        self._min_strong = min_strong_terms
        self.name = f"bm25-v1+{min_strong_terms}term"

    def rank(self, query: str, passages: Sequence[Passage]) -> list[ScoredPassage]:
        if not passages:
            return []
        documents = [Counter(tokenize(p.text)) for p in passages]
        lengths = [sum(d.values()) for d in documents]
        average = (sum(lengths) / len(lengths)) or 1.0
        total = len(documents)
        terms = list(dict.fromkeys(tokenize(query)))
        idf = {
            t: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for t in terms
            for df in [sum(1 for d in documents if t in d)]
        }
        weight = sum(idf.values())
        scored: list[ScoredPassage] = []
        for passage, document, length in zip(passages, documents, lengths, strict=True):
            score = matched = 0.0
            strong = 0
            for term in terms:
                frequency = document.get(term, 0)
                if not frequency:
                    continue
                matched += idf[term]
                norm = frequency + self._k1 * (1 - self._b + self._b * length / average)
                score += idf[term] * frequency * (self._k1 + 1) / norm
                strong += len(term) >= 4 and not term.isdigit()
            coverage = matched / weight if weight else 0.0
            relevant = score > 0 and (coverage >= self._min_coverage or strong >= self._min_strong)
            scored.append(ScoredPassage(passage, score, relevant))
        return sorted(scored, key=lambda s: (-s.score, s.passage.position))
