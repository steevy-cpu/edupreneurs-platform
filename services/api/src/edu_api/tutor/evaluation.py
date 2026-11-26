"""A small, repeatable comparison of retrieval strategies on synthetic lessons.

    uv run python -m edu_api.tutor.evaluation

It answers one question before anyone reaches for a vector database: for a
single lesson, how well does plain lexical ranking find the right block?

What it compares: BM25 over stemmed words, TF-IDF over character trigrams, and
their rank fusion. What it does NOT compare: semantic embeddings. No embedding
model is authorised or available offline in Jude-01, so that column is absent
rather than faked; ``Ranker`` is the seam for adding it (see
docs/jude-01/03-retrieval.md).

The questions are synthetic and few. The numbers are a smoke signal for
regressions and a baseline to beat, not a measurement of real students.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass

from edu_api.tutor import demo_content
from edu_api.tutor.content import ApprovedLesson
from edu_api.tutor.retrieval import (
    Bm25Ranker,
    CharNgramRanker,
    HybridRanker,
    Ranker,
    lesson_passages,
)


@dataclass(frozen=True)
class Case:
    question: str
    #: Any of these block keys counts as a correct find.
    expected: frozenset[str]


def _case(question: str, *expected: str) -> Case:
    return Case(question, frozenset(expected))


_BALANCE = ("balance", "regle", "exemple-addition")
_DIVISION = ("multiplication", "exemple-deux-etapes")

SAME_LANGUAGE_FR: tuple[Case, ...] = (
    _case("Pourquoi on soustrait 5 des deux côtés ?", *_BALANCE),
    _case("C'est quoi une équation ?", "definition", "definition-titre"),
    _case("Que veut dire résoudre une équation ?", "definition"),
    _case("Pourquoi la balance reste en équilibre ?", "balance", "balance-titre"),
    _case("Comment vérifier ma réponse ?", "astuce-verification"),
    _case("Est-ce qu'on peut diviser par zéro ?", "attention-zero"),
    _case("Que faire quand l'inconnue est multipliée par un nombre ?", *_DIVISION),
    _case("Comment résoudre 2x + 3 = 11 ?", "exemple-deux-etapes"),
    _case("Qu'est-ce que l'inconnue ?", "definition"),
    _case("Pourquoi faut-il faire la même chose de l'autre côté ?", "regle", "balance"),
    _case("Comment trouver x dans x + 5 = 12 ?", "exemple-addition"),
    _case("Dans 3x = 12, pourquoi on divise par 3 ?", *_DIVISION),
)

SAME_LANGUAGE_HT: tuple[Case, ...] = (
    _case("Poukisa nou soustrè 5 nan de bò yo?", *_BALANCE),
    _case("Kisa yon ekwasyon ye?", "definition", "definition-titre"),
    _case("Kisa sa vle di rezoud yon ekwasyon?", "definition"),
    _case("Poukisa balans lan rete an ekilib?", "balance", "balance-titre"),
    _case("Kijan pou m verifye repons mwen?", "astuce-verification"),
    _case("Èske nou ka divize pa zewo?", "attention-zero"),
    _case("Kisa pou m fè lè enkoni an miltipliye pa yon nonm?", *_DIVISION),
    _case("Kijan pou m rezoud 2x + 3 = 11?", "exemple-deux-etapes"),
    _case("Kisa enkoni an ye?", "definition"),
    _case("Poukisa mwen dwe fè menm bagay la nan lòt bò a?", "regle", "balance"),
    _case("Kijan pou m jwenn x nan x + 5 = 12?", "exemple-addition"),
    _case("Nan 3x = 12, poukisa nou divize pa 3?", *_DIVISION),
)

#: Creole questions asked against the FRENCH lesson: where lexical ranking is expected to struggle.
CROSS_LANGUAGE_HT_ON_FR: tuple[Case, ...] = SAME_LANGUAGE_HT

#: Nothing in the equations lesson answers these; a good retriever returns nothing.
UNRELATED: tuple[str, ...] = (
    "Qui a gagné la Coupe du monde de football en 1998 ?",
    "Quelle est la capitale de la France ?",
    "Comment les plantes fabriquent leur nourriture ?",
    "Raconte-moi une blague.",
    "Ki moun ki te premye prezidan Ayiti?",
    "Ki jan yo fè diri ak pwa?",
)


@dataclass(frozen=True)
class Scores:
    ranker: str
    dataset: str
    cases: int
    hit_at_1: float
    hit_at_3: float
    mrr: float


def score(ranker: Ranker, lesson: ApprovedLesson, cases: Sequence[Case], dataset: str) -> Scores:
    """Hit@k and MRR, counting only passages the ranker itself calls relevant."""
    passages = lesson_passages(lesson)
    hits_1 = hits_3 = 0
    reciprocal = 0.0
    for case in cases:
        ranked = [s.passage.ref.key for s in ranker.rank(case.question, passages) if s.relevant]
        position = next((i for i, key in enumerate(ranked, 1) if key in case.expected), None)
        if position == 1:
            hits_1 += 1
        if position is not None and position <= 3:
            hits_3 += 1
        if position is not None:
            reciprocal += 1.0 / position
    total = len(cases)
    return Scores(ranker.name, dataset, total, hits_1 / total, hits_3 / total, reciprocal / total)


def false_positive_rate(ranker: Ranker, lesson: ApprovedLesson, questions: Sequence[str]) -> float:
    """Share of unrelated questions for which the ranker still calls something relevant."""
    passages = lesson_passages(lesson)
    wrong = sum(1 for q in questions if any(s.relevant for s in ranker.rank(q, passages)))
    return wrong / len(questions)


def rankers() -> list[Ranker]:
    bm25 = Bm25Ranker()
    chars = CharNgramRanker()
    return [bm25, chars, HybridRanker([bm25, chars])]


def run() -> tuple[list[Scores], dict[str, float]]:
    french, creole = demo_content.equations_fr(), demo_content.equations_ht()
    results: list[Scores] = []
    false_positives: dict[str, float] = {}
    for ranker in rankers():
        results.append(score(ranker, french, SAME_LANGUAGE_FR, "fr question / fr lesson"))
        results.append(score(ranker, creole, SAME_LANGUAGE_HT, "ht question / ht lesson"))
        results.append(score(ranker, french, CROSS_LANGUAGE_HT_ON_FR, "ht question / fr lesson"))
        false_positives[ranker.name] = false_positive_rate(ranker, french, UNRELATED)
    return results, false_positives


def report() -> str:
    results, false_positives = run()
    lines = [
        "| Ranker | Dataset | Cases | Hit@1 | Hit@3 | MRR |",
        "|---|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| `{r.ranker}` | {r.dataset} | {r.cases} | {r.hit_at_1:.2f} | {r.hit_at_3:.2f} | "
        f"{r.mrr:.2f} |"
        for r in results
    ]
    lines += ["", "| Ranker | Unrelated questions wrongly matched |", "|---|---:|"]
    lines += [f"| `{name}` | {rate:.2f} |" for name, rate in false_positives.items()]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.write(report() + "\n")
