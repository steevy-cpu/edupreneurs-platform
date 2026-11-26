"""Retrieval: the right approved passages, stable references, nothing when nothing fits."""

from __future__ import annotations

from edu_api.tutor import demo_content, evaluation
from edu_api.tutor.content import parse_blocks
from edu_api.tutor.retrieval import (
    Bm25Ranker,
    CharNgramRanker,
    HybridRanker,
    LessonRetriever,
    RetrievalQuery,
    contains_text,
    lesson_passages,
)
from edu_api.tutor.text import tokenize


def keys(context: object) -> list[str]:
    return [p.passage.ref.key for p in context.passages]  # type: ignore[attr-defined]


def retriever(**kwargs: int) -> LessonRetriever:
    return LessonRetriever(Bm25Ranker(), **kwargs)


def test_tokenizer_bridges_french_and_creole_word_forms() -> None:
    assert tokenize("On soustrait")[-1] == tokenize("soustraire")[0] == tokenize("soustrè")[0]
    assert tokenize("Les côtés") == tokenize("cote")
    assert "x" in tokenize("Trouve x") and "5" in tokenize("retire 5")
    assert tokenize("Pourquoi est-ce que le la les") == []


def test_question_about_subtracting_finds_the_balance_principle() -> None:
    lesson = demo_content.equations_fr()
    context = retriever().retrieve(
        lesson, RetrievalQuery(text="Pourquoi on soustrait 5 des deux côtés ?")
    )
    assert "balance" in keys(context)
    assert "exemple-addition" in keys(context)
    assert contains_text(context, "la balance reste en équilibre")
    # ids are positional and local to this request
    assert [p.id for p in context.passages] == [
        f"P{i}" for i in range(1, len(context.passages) + 1)
    ]


def test_every_passage_carries_a_stable_reference_to_the_exact_revision() -> None:
    lesson = demo_content.equations_ht()
    for passage in lesson_passages(lesson):
        assert passage.ref.lesson_id == lesson.lesson_id
        assert passage.ref.lesson_revision_id == lesson.revision_id
        assert passage.ref.locale == "ht"
        assert passage.ref.kind == "block"
        assert lesson.block(passage.ref.key) is not None


def test_passages_come_back_in_lesson_order_with_their_section_heading() -> None:
    lesson = demo_content.equations_fr()
    context = retriever().retrieve(lesson, RetrievalQuery(text="Peut-on diviser par zéro ?"))
    found = keys(context)
    assert "attention-zero" in found
    assert "multiplication-titre" in found  # the heading above the matched block
    order = [b.key for b in lesson.blocks]
    assert found == sorted(found, key=order.index)


def test_unrelated_question_retrieves_nothing() -> None:
    lesson = demo_content.equations_fr()
    for question in evaluation.UNRELATED:
        assert retriever().retrieve(lesson, RetrievalQuery(text=question)).is_empty, question


def test_unrelated_question_stays_unanswered_even_with_a_block_in_focus() -> None:
    lesson = demo_content.equations_fr()
    context = retriever().retrieve(
        lesson,
        RetrievalQuery(text="Qui a gagné la Coupe du monde ?", focus_block_key="balance"),
    )
    assert context.is_empty


def test_focus_block_alone_is_enough_context() -> None:
    lesson = demo_content.equations_fr()
    context = retriever().retrieve(lesson, RetrievalQuery(focus_block_key="regle"))
    assert keys(context) == ["balance-titre", "regle"]


def test_only_passages_of_the_requested_lesson_are_ever_returned() -> None:
    equations = demo_content.equations_fr()
    context = retriever().retrieve(
        equations, RetrievalQuery(text="Comment la plante utilise la lumière du soleil ?")
    )
    assert context.is_empty  # photosynthesis is another lesson; nothing leaks across
    photosynthesis = demo_content.photosynthesis_fr()
    context = retriever().retrieve(
        photosynthesis, RetrievalQuery(text="Comment la plante utilise la lumière du soleil ?")
    )
    assert {p.passage.ref.lesson_id for p in context.passages} == {photosynthesis.lesson_id}


def test_question_explanation_is_withheld_unless_asked_for() -> None:
    lesson = demo_content.equations_fr()
    hidden = retriever().retrieve(lesson, RetrievalQuery(question_key="q-addition"))
    question = next(p for p in hidden.passages if p.passage.ref.kind == "question")
    assert question.passage.kind == "question_prompt"
    assert "donc x = 7" not in question.passage.text
    shown = retriever().retrieve(
        lesson, RetrievalQuery(question_key="q-addition", reveal_question_explanation=True)
    )
    question = next(p for p in shown.passages if p.passage.ref.kind == "question")
    assert question.passage.kind == "question_explanation"
    assert "donc x = 7" in question.passage.text
    # The raw answer key (the choice id) is never part of any passage.
    assert question.passage.ref.key == "q-addition"


def test_context_is_bounded_and_says_when_it_dropped_something() -> None:
    lesson = demo_content.equations_fr()
    small = LessonRetriever(Bm25Ranker(), top_k=4, max_context_chars=260)
    context = small.retrieve(lesson, RetrievalQuery(text="Pourquoi on soustrait des deux côtés ?"))
    assert sum(len(p.passage.text) for p in context.passages) <= 260
    assert context.truncated
    assert not context.is_empty


def test_unknown_block_types_are_skipped_not_guessed() -> None:
    blocks = parse_blocks(
        [
            {"key": "a", "type": "paragraph", "text": "Texte."},
            {"key": "b", "type": "video", "src": "x"},
            {"key": "c", "type": "example", "title": "T", "steps": ["un", "deux"]},
            {"type": "paragraph", "text": "sans clé"},
        ]
    )
    assert [(b.key, b.type) for b in blocks] == [("a", "paragraph"), ("c", "example")]
    assert blocks[1].text == "T\nun\ndeux"


def test_ranking_is_deterministic() -> None:
    lesson = demo_content.equations_fr()
    passages = lesson_passages(lesson)
    for ranker in (
        Bm25Ranker(),
        CharNgramRanker(),
        HybridRanker([Bm25Ranker(), CharNgramRanker()]),
    ):
        first = [
            (s.passage.ref.key, s.score) for s in ranker.rank("soustraire des deux côtés", passages)
        ]
        again = [
            (s.passage.ref.key, s.score) for s in ranker.rank("soustraire des deux côtés", passages)
        ]
        assert first == again


# --- the lexical baseline, measured ---------------------------------------------------
def test_lexical_baseline_meets_its_bar_in_both_languages() -> None:
    results, false_positives = evaluation.run()
    bm25 = {r.dataset: r for r in results if r.ranker == "bm25-v1"}
    assert bm25["fr question / fr lesson"].hit_at_3 >= 0.9
    assert bm25["ht question / ht lesson"].hit_at_3 >= 0.9
    assert bm25["fr question / fr lesson"].hit_at_1 >= 0.8
    assert bm25["ht question / ht lesson"].hit_at_1 >= 0.8
    assert false_positives["bm25-v1"] == 0.0


def test_cross_language_retrieval_is_a_known_weakness_of_the_lexical_baseline() -> None:
    """Documented limit, pinned so nobody assumes otherwise (see docs/jude-01/03-retrieval.md)."""
    results, _ = evaluation.run()
    cross = next(
        r for r in results if r.ranker == "bm25-v1" and r.dataset == "ht question / fr lesson"
    )
    assert cross.hit_at_3 < 0.6
