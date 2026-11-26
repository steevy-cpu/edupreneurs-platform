"""Benchmark of retrieval strategies on the bilingual probes.

Reports, per strategy and per direction (question language / lesson language):
Hit@1, Hit@3, MRR over passages the strategy itself calls relevant, and how
often an unrelated question is wrongly matched. Same definitions as Jude-01's
``edu_api.tutor.evaluation`` so the numbers are comparable.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import edu_api.tutor.retrieval as tutor_retrieval
from edu_api.tutor.content import ApprovedLesson
from edu_api.tutor.retrieval import (
    Bm25Ranker,
    CharNgramRanker,
    LessonRetriever,
    Ranker,
    RetrievalQuery,
    lesson_passages,
)
from jude_eval import crosslang
from jude_eval.crosslang import (
    GlossaryRanker,
    SectionRanker,
    SiblingKeyRanker,
    TwoTermBm25Ranker,
    load_glossary,
)
from jude_eval.dataset import LOCALES, LessonPack, build_cases, load_packs

#: Questions no lesson in the benchmark answers, in both languages.
UNRELATED: dict[str, tuple[str, ...]] = {
    "fr": (
        "Qui a gagné la Coupe du monde de football en 1998 ?",
        "Quelle est la capitale de la France ?",
        "Comment les plantes fabriquent leur nourriture ?",
        "Raconte-moi une blague.",
        "Quel temps fera-t-il demain à Port-au-Prince ?",
        "Qui a écrit Gouverneurs de la rosée ?",
    ),
    "ht": (
        "Ki moun ki te premye prezidan Ayiti?",
        "Kijan yo fè diri ak pwa?",
        "Ki kapital peyi Lafrans?",
        "Rakonte m yon blag.",
        "Ki jou fèt drapo a ye?",
        "Ki moun ki ekri Gouverneurs de la rosée?",
    ),
}

RankerFactory = Callable[[LessonPack, str], Ranker]


@contextmanager
def memoised_tokenizer() -> Iterator[None]:
    """Benchmark-only speed-up: the same few hundred synthetic strings are tokenised
    tens of thousands of times. The cache lives for one benchmark call and is then
    discarded; the service itself never caches text. Re-entrant.
    """
    original = tutor_retrieval.tokenize  # type: ignore[attr-defined]
    if getattr(original, "_jude_eval_memoised", False):
        yield
        return

    @functools.cache
    def cached(text: str) -> tuple[str, ...]:
        return tuple(original(text))

    def tokenize(text: str) -> list[str]:
        return list(cached(text))

    tokenize._jude_eval_memoised = True  # type: ignore[attr-defined]
    tutor_retrieval.tokenize = tokenize  # type: ignore[attr-defined]
    crosslang.tokenize = tokenize  # type: ignore[attr-defined]
    try:
        yield
    finally:
        tutor_retrieval.tokenize = original  # type: ignore[attr-defined]
        crosslang.tokenize = original  # type: ignore[attr-defined]


def _strategies() -> dict[str, RankerFactory]:
    full = load_glossary()

    def other(locale: str) -> str:
        return "ht" if locale == "fr" else "fr"

    def bm25(pack: LessonPack, locale: str) -> Ranker:
        return Bm25Ranker()

    def chars(pack: LessonPack, locale: str) -> Ranker:
        return CharNgramRanker()

    def sections(pack: LessonPack, locale: str) -> Ranker:
        return SectionRanker(Bm25Ranker())

    def glossary(pack: LessonPack, locale: str) -> Ranker:
        return SectionRanker(GlossaryRanker(full))

    def glossary_general_only(pack: LessonPack, locale: str) -> Ranker:
        # The lesson's own topic vocabulary removed: what the glossary is worth
        # for a lesson nobody has written terms for yet.
        return SectionRanker(GlossaryRanker(load_glossary(exclude_scopes=(pack.slug,))))

    def sibling(pack: LessonPack, locale: str) -> Ranker:
        return SiblingKeyRanker(
            SectionRanker(Bm25Ranker()), pack.lesson(locale), pack.lesson(other(locale))
        )

    def sibling_glossary(pack: LessonPack, locale: str) -> Ranker:
        return SiblingKeyRanker(
            SectionRanker(GlossaryRanker(full)), pack.lesson(locale), pack.lesson(other(locale))
        )

    def robust(pack: LessonPack, locale: str) -> Ranker:
        return SiblingKeyRanker(
            SectionRanker(TwoTermBm25Ranker()), pack.lesson(locale), pack.lesson(other(locale))
        )

    return {
        "A. bm25 (Jude-01 baseline)": bm25,
        "B. char-trigram tf-idf (Jude-01)": chars,
        "C. sections + bm25": sections,
        "D. sections + glossary": glossary,
        "D'. sections + glossary without the lesson's own topic terms": glossary_general_only,
        "E. sections + sibling block keys": sibling,
        "F. sections + sibling block keys + glossary": sibling_glossary,
        "G. sections + sibling block keys + two-term rule": robust,
    }


STRATEGIES: dict[str, RankerFactory] = _strategies()
#: The strategy the model-layer benchmark uses to build prompts.
RECOMMENDED = "G. sections + sibling block keys + two-term rule"


def recommended_ranker(pack: LessonPack, locale: str) -> Ranker:
    return STRATEGIES[RECOMMENDED](pack, locale)


@dataclass(frozen=True)
class RetrievalScore:
    strategy: str
    direction: str
    cases: int
    hit_at_1: float
    hit_at_3: float
    mrr: float
    #: Share of questions whose gold block is in the context the retriever would
    #: actually hand to the model (top 4, Jude-01 rules). The number that matters.
    in_context: float


@dataclass(frozen=True)
class FalsePositives:
    strategy: str
    question_locale: str
    lesson_locale: str
    wrongly_matched: int
    total: int


def _relevant_keys(ranker: Ranker, lesson: ApprovedLesson, question: str) -> list[str]:
    return [s.passage.ref.key for s in ranker.rank(question, lesson_passages(lesson)) if s.relevant]


def _run_retrieval_benchmark(
    packs: dict[str, LessonPack] | None = None,
) -> tuple[list[RetrievalScore], list[FalsePositives]]:
    packs = packs or load_packs()
    scores: list[RetrievalScore] = []
    false_positives: list[FalsePositives] = []
    for name, factory in STRATEGIES.items():
        for question_locale in LOCALES:
            for lesson_locale in LOCALES:
                hits_1 = hits_3 = total = in_context = 0
                reciprocal = 0.0
                wrong = unrelated = 0
                for pack in packs.values():
                    ranker = factory(pack, lesson_locale)
                    lesson = pack.lesson(lesson_locale)
                    for probe in pack.probes:
                        ranked = _relevant_keys(ranker, lesson, probe.text[question_locale])
                        position = next(
                            (i for i, key in enumerate(ranked, 1) if key in probe.gold), None
                        )
                        total += 1
                        hits_1 += position == 1
                        hits_3 += position is not None and position <= 3
                        reciprocal += 1.0 / position if position else 0.0
                        context = LessonRetriever(ranker).retrieve(
                            lesson, RetrievalQuery(text=probe.text[question_locale])
                        )
                        in_context += any(p.passage.ref.key in probe.gold for p in context.passages)
                    for question in UNRELATED[question_locale]:
                        unrelated += 1
                        wrong += bool(_relevant_keys(ranker, lesson, question))
                scores.append(
                    RetrievalScore(
                        name,
                        f"{question_locale} question / {lesson_locale} lesson",
                        total,
                        hits_1 / total,
                        hits_3 / total,
                        reciprocal / total,
                        in_context / total,
                    )
                )
                false_positives.append(
                    FalsePositives(name, question_locale, lesson_locale, wrong, unrelated)
                )
    return scores, false_positives


def _colloquial_creole(packs: dict[str, LessonPack] | None = None) -> list[tuple[str, int, int]]:
    """How each strategy does on the informally written Creole questions (ht lesson)."""
    packs = packs or load_packs()
    cases = [c for c in build_cases(packs) if c.suite == "creole_fluency" and c.expect_model]
    rows: list[tuple[str, int, int]] = []
    for name, factory in STRATEGIES.items():
        found = 0
        for case in cases:
            pack = packs[case.lesson]
            assert case.message is not None and case.expect_model is not None
            context = LessonRetriever(factory(pack, "ht")).retrieve(
                pack.lesson("ht"), RetrievalQuery(text=case.message)
            )
            found += any(p.passage.ref.key in case.expect_model.gold for p in context.passages)
        rows.append((name, found, len(cases)))
    return rows


#: One ordinary sentence a learner might put before the real question.
PADDING: dict[str, tuple[str, ...]] = {
    "fr": (
        "J'ai peur d'échouer en maths. ",
        "Mon professeur a dit que c'est important pour l'examen de demain. ",
        "Je m'appelle Roseline et je révise ce soir. ",
    ),
    "ht": (
        "Mwen pa fò nan matematik ditou. ",
        "Pwofesè mwen di sa enpòtan pou egzamen demen an. ",
        "Mwen rele Roseline epi m ap revize aswè a. ",
    ),
}


@dataclass(frozen=True)
class PaddedScore:
    strategy: str
    plain: float
    padded: float
    plain_cases: int
    padded_cases: int
    unrelated_matched: int
    padded_unrelated_matched: int
    unrelated_cases: int


def _padded_messages(packs: dict[str, LessonPack] | None = None) -> list[PaddedScore]:
    """Gold-in-context when the same question follows a sentence of ordinary talk.

    All four language directions pooled. The unrelated questions are padded too,
    to see whether a looser rule starts matching things it should not.
    """
    packs = packs or load_packs()
    rows: list[PaddedScore] = []
    for name, factory in STRATEGIES.items():
        plain = padded = plain_n = padded_n = wrong = padded_wrong = unrelated_n = 0
        for pack in packs.values():
            for lesson_locale in LOCALES:
                lesson = pack.lesson(lesson_locale)
                retriever = LessonRetriever(factory(pack, lesson_locale))

                def found(text: str, gold: tuple[str, ...]) -> bool:
                    context = retriever.retrieve(lesson, RetrievalQuery(text=text))  # noqa: B023
                    return any(p.passage.ref.key in gold for p in context.passages)

                def matched(text: str) -> bool:
                    return not retriever.retrieve(lesson, RetrievalQuery(text=text)).is_empty  # noqa: B023

                for question_locale in LOCALES:
                    for probe in pack.probes:
                        plain_n += 1
                        plain += found(probe.text[question_locale], probe.gold)
                        for prefix in PADDING[question_locale]:
                            padded_n += 1
                            padded += found(prefix + probe.text[question_locale], probe.gold)
                    for question in UNRELATED[question_locale]:
                        unrelated_n += 1
                        wrong += matched(question)
                        padded_wrong += matched(PADDING[question_locale][0] + question)
        rows.append(
            PaddedScore(
                name,
                plain / plain_n,
                padded / padded_n,
                plain_n,
                padded_n,
                wrong,
                padded_wrong,
                unrelated_n,
            )
        )
    return rows


def run_retrieval_benchmark(
    packs: dict[str, LessonPack] | None = None,
) -> tuple[list[RetrievalScore], list[FalsePositives]]:
    with memoised_tokenizer():
        return _run_retrieval_benchmark(packs)


def padded_messages(packs: dict[str, LessonPack] | None = None) -> list[PaddedScore]:
    with memoised_tokenizer():
        return _padded_messages(packs)


def colloquial_creole(packs: dict[str, LessonPack] | None = None) -> list[tuple[str, int, int]]:
    with memoised_tokenizer():
        return _colloquial_creole(packs)


def report() -> str:
    scores, false_positives = run_retrieval_benchmark()
    lines = [
        "| Strategy | Direction | Cases | Hit@1 | Hit@3 | MRR | Gold in context |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {s.strategy} | {s.direction} | {s.cases} | {s.hit_at_1:.2f} | {s.hit_at_3:.2f} | "
        f"{s.mrr:.2f} | {s.in_context:.2f} |"
        for s in scores
    ]
    lines += [
        "",
        "Unrelated questions wrongly matched (lower is better):",
        "",
        "| Strategy | fr→fr | fr→ht | ht→fr | ht→ht |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in STRATEGIES:
        cells = {
            (f.question_locale, f.lesson_locale): f"{f.wrongly_matched}/{f.total}"
            for f in false_positives
            if f.strategy == name
        }
        lines.append(
            f"| {name} | {cells['fr', 'fr']} | {cells['fr', 'ht']} | {cells['ht', 'fr']} | "
            f"{cells['ht', 'ht']} |"
        )
    lines += [
        "",
        "Informally written Creole questions on the Creole lesson (gold block in context):",
        "",
        "| Strategy | Found |",
        "|---|---:|",
    ]
    lines += [f"| {name} | {found}/{total} |" for name, found, total in colloquial_creole()]
    lines += [
        "",
        "Same questions after one sentence of ordinary talk (all four directions pooled):",
        "",
        "| Strategy | Gold in context, plain | Gold in context, padded | Unrelated matched | "
        "Padded unrelated matched |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {r.strategy} | {r.plain:.2f} (n={r.plain_cases}) | {r.padded:.2f} "
        f"(n={r.padded_cases}) | {r.unrelated_matched}/{r.unrelated_cases} | "
        f"{r.padded_unrelated_matched}/{r.unrelated_cases} |"
        for r in padded_messages()
    ]
    return "\n".join(lines)
