"""SYNTHETIC lesson content for the demonstration and the test suite.

Nothing here is approved curriculum and nothing here is read by the service at
run time. It follows ``packages/contracts/content/lesson-blocks.schema.json``
and ``question-mcq.schema.json`` so the tutor is exercised on the real shapes.
The Haitian Creole text was written for testing and has NOT been reviewed by a
native-speaking editor.
"""

# ruff: noqa: RUF001  (lessons use real typographic minus and multiplication signs, like the seed)
from __future__ import annotations

import uuid
from typing import Any

from edu_api.tutor.content import ApprovedLesson, parse_blocks, parse_question
from edu_api.tutor.types import Locale

EQUATIONS_LESSON_ID = uuid.UUID("b1000000-0000-4000-8000-000000000001")
EQUATIONS_FR_REVISION_ID = uuid.UUID("c1000000-0000-4000-8000-0000000000f1")
EQUATIONS_HT_REVISION_ID = uuid.UUID("c1000000-0000-4000-8000-0000000000a1")
PHOTOSYNTHESIS_LESSON_ID = uuid.UUID("b1000000-0000-4000-8000-000000000002")
PHOTOSYNTHESIS_FR_REVISION_ID = uuid.UUID("c1000000-0000-4000-8000-0000000000f2")

_EQUATIONS_FR_BLOCKS: list[dict[str, Any]] = [
    {"key": "definition-titre", "type": "heading", "text": "Qu'est-ce qu'une équation ?"},
    {
        "key": "definition",
        "type": "paragraph",
        "text": "Une équation est une égalité qui contient une quantité inconnue, appelée "
        "l'inconnue. On la note souvent x. Résoudre une équation, c'est trouver la valeur "
        "de x qui rend l'égalité vraie.",
    },
    {"key": "balance-titre", "type": "heading", "text": "Le principe de la balance"},
    {
        "key": "balance",
        "type": "paragraph",
        "text": "Une équation est comme une balance en équilibre. Si l'on retire la même "
        "quantité des deux côtés, la balance reste en équilibre. C'est pourquoi on peut "
        "soustraire le même nombre des deux côtés d'une équation sans changer sa solution.",
    },
    {
        "key": "regle",
        "type": "callout",
        "tone": "remember",
        "text": "Tout ce que tu fais d'un côté de l'équation, tu dois le faire aussi de "
        "l'autre côté.",
    },
    {
        "key": "exemple-addition",
        "type": "example",
        "title": "Résoudre x + 5 = 12",
        "steps": [
            "On veut que x reste seul du côté gauche.",
            "On soustrait 5 des deux côtés : x + 5 − 5 = 12 − 5.",
            "On obtient x = 7.",
            "Vérification : 7 + 5 = 12. L'égalité est vraie.",
        ],
    },
    {"key": "multiplication-titre", "type": "heading", "text": "Quand l'inconnue est multipliée"},
    {
        "key": "multiplication",
        "type": "paragraph",
        "text": "Si l'inconnue est multipliée par un nombre, on divise les deux côtés par ce "
        "même nombre. Par exemple, dans 3x = 12, on divise les deux côtés par 3.",
    },
    {
        "key": "exemple-deux-etapes",
        "type": "example",
        "title": "Résoudre 2x + 3 = 11",
        "steps": [
            "On soustrait 3 des deux côtés : 2x = 8.",
            "On divise les deux côtés par 2 : x = 4.",
            "Vérification : 2 × 4 + 3 = 11.",
        ],
    },
    {
        "key": "attention-zero",
        "type": "callout",
        "tone": "warning",
        "text": "Attention : on ne divise jamais par zéro.",
    },
    {
        "key": "astuce-verification",
        "type": "callout",
        "tone": "tip",
        "text": "Vérifie toujours ta réponse : remplace x par la valeur trouvée et regarde "
        "si l'égalité est vraie.",
    },
]

_EQUATIONS_HT_BLOCKS: list[dict[str, Any]] = [
    {"key": "definition-titre", "type": "heading", "text": "Kisa yon ekwasyon ye?"},
    {
        "key": "definition",
        "type": "paragraph",
        "text": "Yon ekwasyon se yon egalite ki gen yon kantite nou pa konnen, yo rele l "
        "enkoni. Nou souvan ekri l ak lèt x. Rezoud yon ekwasyon vle di jwenn valè x ki fè "
        "egalite a vre.",
    },
    {"key": "balance-titre", "type": "heading", "text": "Prensip balans lan"},
    {
        "key": "balance",
        "type": "paragraph",
        "text": "Yon ekwasyon tankou yon balans ki an ekilib. Si nou retire menm kantite a "
        "nan de bò yo, balans lan rete an ekilib. Se poutèt sa nou ka soustrè menm nonm nan "
        "nan de bò ekwasyon an san nou pa chanje solisyon an.",
    },
    {
        "key": "regle",
        "type": "callout",
        "tone": "remember",
        "text": "Tout sa ou fè nan yon bò ekwasyon an, ou dwe fè l nan lòt bò a tou.",
    },
    {
        "key": "exemple-addition",
        "type": "example",
        "title": "Rezoud x + 5 = 12",
        "steps": [
            "Nou vle x rete pou kont li nan bò goch la.",
            "Nou soustrè 5 nan de bò yo: x + 5 − 5 = 12 − 5.",
            "Nou jwenn x = 7.",
            "Verifikasyon: 7 + 5 = 12. Egalite a vre.",
        ],
    },
    {"key": "multiplication-titre", "type": "heading", "text": "Lè enkoni an miltipliye"},
    {
        "key": "multiplication",
        "type": "paragraph",
        "text": "Si enkoni an miltipliye pa yon nonm, nou divize de bò yo pa menm nonm sa a. "
        "Pa egzanp, nan 3x = 12, nou divize de bò yo pa 3.",
    },
    {
        "key": "exemple-deux-etapes",
        "type": "example",
        "title": "Rezoud 2x + 3 = 11",
        "steps": [
            "Nou soustrè 3 nan de bò yo: 2x = 8.",
            "Nou divize de bò yo pa 2: x = 4.",
            "Verifikasyon: 2 × 4 + 3 = 11.",
        ],
    },
    {
        "key": "attention-zero",
        "type": "callout",
        "tone": "warning",
        "text": "Atansyon: nou pa janm divize pa zewo.",
    },
    {
        "key": "astuce-verification",
        "type": "callout",
        "tone": "tip",
        "text": "Toujou verifye repons ou: ranplase x ak valè ou jwenn nan epi gade si "
        "egalite a vre.",
    },
]

_EQUATIONS_FR_QUESTIONS: list[dict[str, Any]] = [
    {
        "question_key": "q-addition",
        "kind": "mcq",
        "prompt": {"text": "Quelle est la solution de x + 5 = 12 ?"},
        "response_spec": {
            "choices": [
                {"id": "a", "text": "x = 17"},
                {"id": "b", "text": "x = 7"},
                {"id": "c", "text": "x = 5"},
                {"id": "d", "text": "x = 12"},
            ]
        },
        "answer_key": {"correct_choice_id": "b"},
        "explanation": {
            "text": "On soustrait 5 des deux côtés : x = 12 − 5, donc x = 7. "
            "Vérification : 7 + 5 = 12."
        },
    },
    {
        "question_key": "q-division",
        "kind": "mcq",
        "prompt": {"text": "Pour résoudre 3x = 12, que fait-on ?"},
        "response_spec": {
            "choices": [
                {"id": "a", "text": "On soustrait 3 des deux côtés"},
                {"id": "b", "text": "On multiplie les deux côtés par 3"},
                {"id": "c", "text": "On divise les deux côtés par 3"},
            ]
        },
        "answer_key": {"correct_choice_id": "c"},
        "explanation": {
            "text": "L'inconnue est multipliée par 3, donc on divise les deux côtés par 3 : x = 4."
        },
    },
]

_EQUATIONS_HT_QUESTIONS: list[dict[str, Any]] = [
    {
        "question_key": "q-addition",
        "kind": "mcq",
        "prompt": {"text": "Ki solisyon x + 5 = 12?"},
        "response_spec": {
            "choices": [
                {"id": "a", "text": "x = 17"},
                {"id": "b", "text": "x = 7"},
                {"id": "c", "text": "x = 5"},
                {"id": "d", "text": "x = 12"},
            ]
        },
        "answer_key": {"correct_choice_id": "b"},
        "explanation": {
            "text": "Nou soustrè 5 nan de bò yo: x = 12 − 5, kidonk x = 7. "
            "Verifikasyon: 7 + 5 = 12."
        },
    },
    {
        "question_key": "q-division",
        "kind": "mcq",
        "prompt": {"text": "Pou rezoud 3x = 12, kisa nou fè?"},
        "response_spec": {
            "choices": [
                {"id": "a", "text": "Nou soustrè 3 nan de bò yo"},
                {"id": "b", "text": "Nou miltipliye de bò yo pa 3"},
                {"id": "c", "text": "Nou divize de bò yo pa 3"},
            ]
        },
        "answer_key": {"correct_choice_id": "c"},
        "explanation": {
            "text": "Enkoni an miltipliye pa 3, kidonk nou divize de bò yo pa 3: x = 4."
        },
    },
]

_PHOTOSYNTHESIS_FR_BLOCKS: list[dict[str, Any]] = [
    {"key": "intro-titre", "type": "heading", "text": "La photosynthèse"},
    {
        "key": "intro",
        "type": "paragraph",
        "text": "Les plantes vertes fabriquent leur propre nourriture grâce à la lumière du "
        "soleil. Ce processus s'appelle la photosynthèse.",
    },
    {
        "key": "ingredients",
        "type": "paragraph",
        "text": "Pour réaliser la photosynthèse, la plante utilise l'eau puisée par les "
        "racines, le dioxyde de carbone de l'air et la lumière captée par la chlorophylle "
        "des feuilles.",
    },
    {
        "key": "produits",
        "type": "callout",
        "tone": "remember",
        "text": "La photosynthèse produit du glucose, qui nourrit la plante, et du dioxygène, "
        "rejeté dans l'air.",
    },
]


def _lesson(
    lesson_id: uuid.UUID,
    revision_id: uuid.UUID,
    locale: Locale,
    title: str,
    blocks: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    revision: int = 1,
) -> ApprovedLesson:
    return ApprovedLesson(
        lesson_id=lesson_id,
        revision_id=revision_id,
        revision=revision,
        locale=locale,
        title=title,
        blocks=parse_blocks(blocks),
        questions=tuple(parse_question(**q) for q in questions),
    )


def equations_fr() -> ApprovedLesson:
    return _lesson(
        EQUATIONS_LESSON_ID,
        EQUATIONS_FR_REVISION_ID,
        "fr",
        "Les équations du premier degré",
        _EQUATIONS_FR_BLOCKS,
        _EQUATIONS_FR_QUESTIONS,
    )


def equations_ht() -> ApprovedLesson:
    return _lesson(
        EQUATIONS_LESSON_ID,
        EQUATIONS_HT_REVISION_ID,
        "ht",
        "Ekwasyon premye degre",
        _EQUATIONS_HT_BLOCKS,
        _EQUATIONS_HT_QUESTIONS,
    )


def photosynthesis_fr() -> ApprovedLesson:
    return _lesson(
        PHOTOSYNTHESIS_LESSON_ID,
        PHOTOSYNTHESIS_FR_REVISION_ID,
        "fr",
        "La photosynthèse",
        _PHOTOSYNTHESIS_FR_BLOCKS,
        [],
    )


def raw_blocks(locale: Locale) -> list[dict[str, Any]]:
    """The equations lesson in the stored JSON shape (for contract tests)."""
    return _EQUATIONS_FR_BLOCKS if locale == "fr" else _EQUATIONS_HT_BLOCKS


def raw_questions(locale: Locale) -> list[dict[str, Any]]:
    return _EQUATIONS_FR_QUESTIONS if locale == "fr" else _EQUATIONS_HT_QUESTIONS
