"""Regenerate content/pilots/7af-math from the authoring modules.

    cd tools/content-pilot && python -m authoring.build

Writes JSON (2-space indent, UTF-8, trailing newline). Re-running changes nothing unless a source text changed.
"""

from __future__ import annotations

import json
from pathlib import Path

from content_pilot.model import LOCALES, PILOT_ID, stable_id

from .lessons import l01, l02, l03, l04, l05, l06
from .lib import Lesson, question_files, verification_file

ROOT = Path(__file__).resolve().parents[3] / "content" / "pilots" / "7af-math"
DATE = "2026-11-26"
LESSONS: list[Lesson] = [m.LESSON for m in (l01, l02, l03, l04, l05, l06)]

SOURCES = [
    {
        "id": "S1",
        "title": "Programme du 3e cycle de l'enseignement fondamental (7e à 9e AF) — Mathématiques (« Tous Droits Réservés - 2024-2025 », MENFP / Direction de l'Enseignement Fondamental)",
        "issuer": "MENFP — Direction de l'Enseignement Fondamental",
        "kind": "official_curriculum",
        "url": "https://www.editions-jpl.com/_files/ugd/28b65f_7f7bb36133ec4f28837548f716aa384b.pdf",
        "retrieved": DATE,
        "rights_status": "all_rights_reserved_reference_only",
        "verification": "read_in_full_for_relevant_part",
        "notes": "PDF de 60 pages hébergé par un éditeur (page de téléchargement : editions-jpl.com/programmes-officiels-menfp-3e-cycle-fondamental), pas par le MENFP. Lu : sommaire, partie « Domaine des mathématiques » et unités « Nombres et calculs » (7e-9e année, p. imprimées 38-42). INCERTAIN : (a) l'hébergement par un tiers ne prouve pas que ce soit la version finale validée ; le préambule du PDF dit encore « Introduction politique à réaliser quand les programmes seront validés » ; (b) aucune page du MENFP lui-même n'a été trouvée ; (c) aucun texte n'est reproduit dans ce dépôt, seulement des références de lieu.",
    },
    {
        "id": "S2",
        "title": "Programme à compétences minimales — 7ème année fondamentale (novembre 2019)",
        "issuer": "MENFP — Direction de l'Enseignement Fondamental",
        "kind": "official_curriculum",
        "url": "https://www.haiti-now.org/wp-content/uploads/2021/02/7eme-AF.pdf",
        "retrieved": DATE,
        "rights_status": "unknown_reference_only",
        "verification": "read_in_full_for_relevant_part",
        "notes": "PDF de 82 pages (copie hébergée par haiti-now.org). Mathématiques : p. 4-15 du PDF. Le texte lui-même précise qu'il s'agit d'une mesure pour 2019-2020 qui « ne peut en aucun cas être substitué[e] aux objectifs globaux prévus dans les programmes officiels valides depuis mars 1989 ». INCERTAIN : statut actuel (probablement dépassé par S1), droits non indiqués, copie tierce. Utilisé seulement pour repérer des recoupements ; aucun texte reproduit.",
    },
    {
        "id": "S3",
        "title": "Décision ministérielle D-2(1)384 du 9 janvier 2026 : généralisation progressive des nouveaux programmes du 3e cycle (début en 7e AF en 2027-2028)",
        "issuer": "MENFP (décision) ; rapportée par Le Placentin (12 janv. 2026) et Le National (14 janv. 2026)",
        "kind": "press_report",
        "url": "https://leplacentin.com/post/12-01-2026-haiti-generalisation-progressive-des-nouveaux-programmes-du-3ecycle-de-lenseignement-fondamental",
        "retrieved": DATE,
        "rights_status": "not_used",
        "verification": "secondary_report_only",
        "notes": "Lu seulement via la presse ; le texte de la décision n'a pas été obtenu. Le rapport indique que les 7 autres disciplines (dont, présumément, les mathématiques) seront généralisées en 7e AF à partir de 2027-2028, en 8e AF en 2028-2029, en 9e AF en 2029-2030. INCERTAIN : la presse ne dit pas explicitement que les mathématiques suivent ce calendrier ; vérifier le texte de la décision auprès du MENFP.",
    },
    {
        "id": "S4",
        "title": "Cadre d'orientation curriculaire pour le système éducatif haïtien (MENFP, 2021)",
        "issuer": "MENFP",
        "kind": "framework",
        "url": "https://mit-ayiti.net/wp-content/uploads/2023/06/Cadre-d_Orientation-Curriculaire-MENFP-2021-.pdf",
        "retrieved": None,
        "rights_status": "unknown_reference_only",
        "verification": "located_not_read",
        "notes": "Localisé, non lu. Cité par S1 comme texte d'orientation commun. Une version « COC 2024 » est mentionnée par la presse : laquelle fait foi n'est pas vérifié.",
    },
    {
        "id": "S5",
        "title": "Séquences modèles de mathématiques, 7e année — portail MENFP / Projet Nectar (menfp.reseau-canope.fr)",
        "issuer": "MENFP / Projet Nectar",
        "kind": "teaching_resource",
        "url": "https://menfp.reseau-canope.fr/mod/url/view.php?id=1491",
        "retrieved": None,
        "rights_status": "not_used",
        "verification": "located_not_read",
        "notes": "Localisé (séquences sur les fractions, aires et périmètres, droites remarquables, traitement des données), non consulté : aucun contenu n'en est repris. À examiner pour Content-02B (fractions).",
    },
    {
        "id": "S6",
        "title": "Programmes officiels du fondamental en vigueur depuis mars 1989",
        "issuer": "MENFP",
        "kind": "official_curriculum",
        "url": None,
        "retrieved": None,
        "rights_status": "unknown_reference_only",
        "verification": "not_located",
        "notes": "Cités par S2 comme référence légale. Non localisés : aucun alignement avec eux n'est revendiqué.",
    },
]


def dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def lesson_descriptor(le: Lesson) -> dict[str, object]:
    d = f"lessons/{le.position:02d}-{le.slug}"
    review = {"status": "draft_unreviewed", "required_approvals": ["mathematics_teacher", "native_speaker"], "approvals": []}
    return {
        "id": stable_id("lesson", le.slug),
        "slug": le.slug,
        "position": le.position,
        "titles": le.titles,
        "objectives": le.objectives,
        "curriculum_refs": le.refs,
        "provenance": {
            "authoring": "ai_assisted_original",
            "authored_on": DATE,
            "derived_from_third_party": False,
            "translation": "ai_drafted_separately_from_french",
        },
        "rights": {
            "origin": "original",
            "third_party_material": False,
            "licence_status": "unassigned_owner_decision",
            "notes": "Texte, exemples et exercices écrits pour ce pilote avec l'aide d'une IA ; aucun passage copié d'un manuel, d'un programme ou d'un prototype. La licence de publication reste à décider par le propriétaire.",
        },
        "files": {
            "blocks": {loc: f"{d}/blocks.{loc}.json" for loc in LOCALES},
            "questions": {loc: f"{d}/questions.{loc}.json" for loc in LOCALES},
            "verification": f"{d}/verification.json",
        },
        "review": {"fr": review, "ht": {**review, "approvals": []}},
    }


def main() -> None:
    pilot = {
        "pilot_id": PILOT_ID,
        "descriptor_version": "pilot-descriptor-0",
        "grade": "7AF",
        "subject": "mathematiques",
        "proposal_status": "Pilote PROPOSÉ (7AF mathématiques) : choix non approuvé par le propriétaire ; contenu = brouillons non relus.",
        "locales": ["fr", "ht"],
        "unit": {
            "id": stable_id("unit", "nombres-entiers-naturels"),
            "slug": "nombres-entiers-naturels",
            "titles": {"fr": "Les nombres entiers naturels : lire, calculer, diviser", "ht": "Nonb antye natirèl yo: li, kalkile, divize"},
            "curriculum_domain": "Nombres et calculs",
        },
        "sources": SOURCES,
        "lessons": [lesson_descriptor(le) for le in LESSONS],
    }
    dump(ROOT / "pilot.json", pilot)
    for le in LESSONS:
        d = ROOT / f"lessons/{le.position:02d}-{le.slug}"
        for loc in LOCALES:
            dump(d / f"blocks.{loc}.json", le.blocks[loc])
            dump(d / f"questions.{loc}.json", question_files(le, loc))
        dump(d / "verification.json", verification_file(le))
    print(f"wrote {len(LESSONS)} lessons under {ROOT}")


if __name__ == "__main__":
    main()
