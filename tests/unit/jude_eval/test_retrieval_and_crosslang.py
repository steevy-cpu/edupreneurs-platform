"""Cross-language retrieval: the measured claims in docs/jude-02a/03 are pinned here."""

from __future__ import annotations

from jude_eval.crosslang import (
    GlossaryRanker,
    SectionRanker,
    SiblingKeyRanker,
    TwoTermBm25Ranker,
    load_glossary,
)
from jude_eval.dataset import load_packs
from jude_eval.retrieval_bench import (
    RECOMMENDED,
    STRATEGIES,
    padded_messages,
    run_retrieval_benchmark,
)

from edu_api.tutor.retrieval import Bm25Ranker, LessonRetriever, RetrievalQuery, lesson_passages

PACKS = load_packs()
SCORES, FALSE_POSITIVES = run_retrieval_benchmark(PACKS)
BASELINE = "A. bm25 (Jude-01 baseline)"


def score(strategy: str, direction: str) -> float:
    return next(s.in_context for s in SCORES if s.strategy == strategy and s.direction == direction)


def keys(ranker: object, lesson: object, question: str) -> list[str]:
    context = LessonRetriever(ranker).retrieve(lesson, RetrievalQuery(text=question))  # type: ignore[arg-type]
    return [p.passage.ref.key for p in context.passages]


def test_the_jude_01_baseline_is_weak_across_languages_on_the_wider_benchmark() -> None:
    assert score(BASELINE, "fr question / ht lesson") < 0.2
    assert score(BASELINE, "ht question / fr lesson") < 0.2
    # ... and less strong in the same language than Jude-01's single lesson suggested.
    assert 0.6 <= score(BASELINE, "fr question / fr lesson") <= 0.8


def test_sibling_block_keys_make_cross_language_as_good_as_same_language() -> None:
    strategy = "E. sections + sibling block keys"
    same = min(
        score(strategy, "fr question / fr lesson"), score(strategy, "ht question / ht lesson")
    )
    for direction in ("fr question / ht lesson", "ht question / fr lesson"):
        assert score(strategy, direction) >= 0.8
        assert score(strategy, direction) >= same


def test_glossary_helps_but_depends_on_having_the_lessons_own_terms() -> None:
    full, general = (
        "D. sections + glossary",
        "D'. sections + glossary without the lesson's own topic terms",
    )
    for direction in ("fr question / ht lesson", "ht question / fr lesson"):
        assert score(full, direction) >= 0.6 > score(BASELINE, direction)
        assert score(general, direction) < score(full, direction)


def test_no_new_strategy_matches_unrelated_questions() -> None:
    for row in FALSE_POSITIVES:
        if row.strategy.startswith(("B.",)):
            continue  # the Jude-01 trigram ranker does; that is why it is not the default
        assert row.wrongly_matched == 0, row


def test_ordinary_talk_before_the_question_breaks_the_baseline_and_not_the_recommended() -> None:
    rows = {r.strategy: r for r in padded_messages(PACKS)}
    assert rows[BASELINE].padded < 0.15
    assert rows["E. sections + sibling block keys"].padded < 0.2
    recommended = rows[RECOMMENDED]
    assert recommended.padded >= 0.65 and recommended.plain >= 0.85
    assert recommended.unrelated_matched == recommended.padded_unrelated_matched == 0


def test_section_ranker_brings_in_the_body_under_a_matched_heading() -> None:
    lesson = PACKS["ns4-derivee"].lesson("fr")
    question = "À quoi sert la dérivée ?"
    assert "idee" not in keys(Bm25Ranker(), lesson, question)  # heading only: nothing usable
    assert "idee" in keys(SectionRanker(Bm25Ranker()), lesson, question)


def test_sibling_ranker_cites_the_revision_being_read_never_the_sibling() -> None:
    pack = PACKS["ns1-pythagore"]
    french, creole = pack.lesson("fr"), pack.lesson("ht")
    ranker = SiblingKeyRanker(SectionRanker(Bm25Ranker()), french, creole)
    context = LessonRetriever(ranker).retrieve(
        french, RetrievalQuery(text="Kisa teyorèm Pitagò a di?")
    )
    assert "theoreme" in [p.passage.ref.key for p in context.passages]
    assert {p.passage.ref.lesson_revision_id for p in context.passages} == {french.revision_id}
    assert {p.passage.ref.locale for p in context.passages} == {"fr"}
    creole_text = {b.text for b in creole.blocks}
    assert not any(p.passage.text in creole_text for p in context.passages)


def test_glossary_translates_toward_the_lesson_language_only() -> None:
    ranker = GlossaryRanker(load_glossary())
    assert "ipoten" in ranker.translate("C'est quoi l'hypoténuse ?", "ht")
    assert "hypote" in ranker.translate("Kisa ipoteniz la ye?", "fr")
    # Numbers and unknown words pass through untouched.
    assert "25" in ranker.translate("Que veut dire 25 % ?", "ht")


def test_two_term_rule_is_bm25_plus_a_second_way_to_be_relevant() -> None:
    lesson = PACKS["7af-fractions"].lesson("fr")
    passages = lesson_passages(lesson)
    padded = (
        "Mon professeur a dit que c'est important pour l'examen de demain et j'ai peur "
        "d'échouer en maths cette année. Comment additionner deux fractions qui ont le même "
        "dénominateur ?"
    )
    strict = [s.passage.ref.key for s in Bm25Ranker().rank(padded, passages) if s.relevant]
    lenient = [s.passage.ref.key for s in TwoTermBm25Ranker().rank(padded, passages) if s.relevant]
    assert "meme" not in strict and "meme" in lenient
    # Same scores and order as Jude-01's BM25; only the relevance decision differs.
    assert [s.passage.ref.key for s in Bm25Ranker().rank(padded, passages)] == [
        s.passage.ref.key for s in TwoTermBm25Ranker().rank(padded, passages)
    ]


def test_every_strategy_is_deterministic() -> None:
    again, _ = run_retrieval_benchmark(PACKS)
    assert again == SCORES
    assert RECOMMENDED in STRATEGIES
