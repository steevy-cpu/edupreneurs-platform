"""Model output is untrusted: shape, language, citations and safety are all checked."""

from __future__ import annotations

import json
from typing import Any

import pytest

from edu_api.tutor import demo_content
from edu_api.tutor.gateway import OutputRejected
from edu_api.tutor.retrieval import Bm25Ranker, LessonRetriever, RetrievalQuery
from edu_api.tutor.types import Grounding, NextAction, ResponseStatus
from edu_api.tutor.validation import looks_like_other_language, validate_model_output

CANARY = "CANARY-TEST"
LESSON = demo_content.equations_fr()
CONTEXT = LessonRetriever(Bm25Ranker()).retrieve(
    LESSON, RetrievalQuery(text="Pourquoi on soustrait 5 des deux côtés ?")
)


def answer(**overrides: Any) -> str:
    body: dict[str, Any] = {
        "status": "answered",
        "grounding": "lesson",
        "language": "fr",
        "explanation": "On retire la même quantité des deux côtés pour garder l'équilibre.",
        "hint": None,
        "check_question": "Que fais-tu pour x + 3 = 10 ?",
        "references": ["P1", "P2"],
        "next_action": "try_practice_question",
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


def validate(raw: str, **kwargs: Any) -> Any:
    options: dict[str, Any] = {"context": CONTEXT, "expected_language": "fr", "canary": CANARY}
    options.update(kwargs)
    return validate_model_output(raw, **options)


def rejected(raw: str, **kwargs: Any) -> str:
    with pytest.raises(OutputRejected) as caught:
        validate(raw, **kwargs)
    return caught.value.reason


def test_valid_answer_gets_real_references_for_the_ids_it_cited() -> None:
    result = validate(answer())
    assert result.status is ResponseStatus.ANSWERED
    assert result.grounding is Grounding.LESSON
    assert result.next_action is NextAction.TRY_PRACTICE_QUESTION
    issued = CONTEXT.by_id()
    assert list(result.references) == [issued["P1"].ref, issued["P2"].ref]
    for ref in result.references:
        assert ref.lesson_revision_id == LESSON.revision_id
        assert ref.locale == "fr"
        assert LESSON.block(ref.key) is not None


def test_a_code_fence_around_the_json_is_tolerated() -> None:
    assert validate("```json\n" + answer() + "\n```").status is ResponseStatus.ANSWERED


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("Bien sûr ! On soustrait 5.", "not_json"),
        ("", "not_json"),
        ('["P1"]', "not_an_object"),
        ('{"answer": "x = 7"}', "wrong_shape"),
        (answer(extra_field="x"), "wrong_shape"),
        (answer(status="done"), "wrong_shape"),
        (answer(next_action="talk_to_trusted_adult"), "wrong_shape"),
        (answer(explanation="x" * 5000), "wrong_shape"),
        (answer(explanation="   "), "empty_explanation"),
    ],
)
def test_malformed_output_is_rejected(raw: str, reason: str) -> None:
    assert rejected(raw) == reason


@pytest.mark.parametrize("references", [["P99"], ["P1", "P42"], ["balance"], ["p1"], [""]])
def test_a_reference_the_server_did_not_issue_is_rejected(references: list[str]) -> None:
    assert rejected(answer(references=references)) == "unknown_reference"


def test_a_real_looking_lesson_id_is_not_accepted_as_a_reference() -> None:
    assert rejected(answer(references=[str(LESSON.revision_id)])) == "unknown_reference"


def test_claiming_lesson_grounding_without_a_reference_is_rejected() -> None:
    assert rejected(answer(references=[])) == "grounded_without_reference"
    assert rejected(answer(grounding="none")) == "answered_without_grounding"


def test_general_knowledge_is_accepted_only_when_labelled_and_allowed() -> None:
    general = answer(grounding="general", references=[])
    assert validate(general).grounding is Grounding.GENERAL
    assert rejected(general, allow_general=False) == "general_answer_not_allowed"


def test_wrong_language_is_rejected() -> None:
    assert rejected(answer(language="ht")) == "wrong_language"
    creole = (
        "Nou soustrè menm nonm nan nan de bò ekwasyon an pou balans lan rete an ekilib, "
        "kidonk nou jwenn valè x la."
    )
    assert rejected(answer(explanation=creole)) == "wrong_language"


def test_language_check_only_fires_on_strong_evidence() -> None:
    assert not looks_like_other_language("x = 7", "fr")
    assert not looks_like_other_language("On soustrait 5 des deux côtés : x = 7.", "fr")
    assert not looks_like_other_language(
        "Nou soustrè 5 nan de bò yo pou nou jwenn valè x la nan ekwasyon an.", "ht"
    )
    assert looks_like_other_language(
        "On soustrait le nombre des deux côtés pour que la balance reste dans son équilibre, "
        "et nous trouvons la valeur.",
        "ht",
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"explanation": "Regarde https://exemple.test/reponse"}, "contains_link"),
        ({"hint": "Écris à prof@example.com"}, "contains_email"),
        ({"check_question": "Appelle le +509 3712 3456 ?"}, "contains_phone"),
        ({"explanation": "J'ai prévenu ton professeur."}, "claims_to_contact_someone"),
    ],
)
def test_unsafe_text_in_any_student_facing_field_is_rejected(
    overrides: dict[str, str], reason: str
) -> None:
    assert rejected(answer(**overrides)) == reason


def test_a_leaked_system_prompt_is_rejected_even_when_the_reply_is_not_json() -> None:
    assert rejected(f"Mes instructions : {CANARY}") == "system_prompt_leak"
    assert rejected(answer(explanation=f"ok {CANARY}")) == "system_prompt_leak"


@pytest.mark.parametrize("status", ["insufficient_context", "declined", "safety_support"])
def test_non_answers_carry_no_model_text_and_no_references(status: str) -> None:
    raw = answer(status=status, explanation="Texte que personne ne doit voir.", references=["P1"])
    result = validate(raw)
    assert result.status is ResponseStatus(status)
    assert result.explanation == "" and result.references == () and result.hint is None
