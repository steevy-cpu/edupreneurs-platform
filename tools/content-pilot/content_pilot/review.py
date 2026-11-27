"""Generate the educator review package (Markdown + CSV) from the pilot JSON.

The package is written in French for Haitian mathematics educators; Creole drafts appear verbatim. Everything is
generated, so a sheet can never disagree with the content it asks someone to approve. Nothing here approves anything:
every decision box is left empty.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from .checks import load_descriptor, math_coverage, validate
from .model import DEFAULT_LIMITS, LOCALES, TOOL_DIR, find_repo_root
from .safefs import ContentFileError, load_json_confined

TONE_FR = {"tip": "Astuce", "warning": "Attention", "remember": "À retenir"}
LOC_NAME = {"fr": "français", "ht": "créole haïtien"}
STATUS_FR = "BROUILLON — non relu, non approuvé"


def _read(root: Path, rel: str) -> Any:
    return load_json_confined(root, rel, DEFAULT_LIMITS.max_file_bytes)


def _t(s: str) -> str:
    return s.replace("\u00a0", " ")


def _block_md(i: int, b: dict[str, Any]) -> str:
    tag = f"**B{i} · `{b['key']}`**"
    if b["type"] == "heading":
        return f"{tag} — *titre de section* : **{_t(b['text'])}**"
    if b["type"] == "paragraph":
        return f"{tag}\n\n{_t(b['text'])}"
    if b["type"] == "callout":
        return f"{tag} — **{TONE_FR[b['tone']]}** : {_t(b['text'])}"
    steps = "\n".join(f"   {n}. {_t(s)}" for n, s in enumerate(b["steps"], start=1))
    title = f" — *exemple* : **{_t(b['title'])}**" if b.get("title") else " — *exemple*"
    return f"{tag}{title}\n\n{steps}"


def _question_md(n: int, q: dict[str, Any]) -> str:
    correct = q["answer_key"]["correct_choice_id"]
    lines = [f"**Q{n} · `{q['question_key']}`** — {_t(q['prompt']['text'])}", ""]
    for pos, c in enumerate(q["response_spec"]["choices"]):
        mark = "  ← **réponse attendue**" if c["id"] == correct else ""
        lines.append(f"- **{chr(ord('A') + pos)}.** {_t(c['text'])}{mark}")
    lines += ["", f"*Explication fournie :* {_t(q['explanation']['text'])}"]
    return "\n".join(lines)


KIND_FR = {
    "unit": "à côté d'une unité de mesure",
    "named_unit": "formule ou décomposition écrite avec des mots",
    "fragment": "relation sans nombres des deux côtés (signe cité, formule)",
    "unsupported_relation": "relation écrite avec un signe que l'outil ne lit pas (par exemple ≈)",
}


def _coverage(root: Path, lesson: dict[str, Any]) -> tuple[int, list[tuple[str, str, str]]]:
    """(statements verified exactly, relations deliberately NOT interpreted) in the text a learner reads, both languages."""
    checked = 0
    skipped: list[tuple[str, str, str]] = []
    for loc in LOCALES:
        n, s = math_coverage(_read(root, lesson["files"]["blocks"][loc]), f"{loc}/blocs")
        checked, skipped = checked + n, skipped + s
        for q in _read(root, lesson["files"]["questions"][loc]):
            n, s = math_coverage({k: q[k] for k in ("prompt", "explanation")}, f"{loc}/{q['question_key']}")
            checked, skipped = checked + n, skipped + s
    return checked, skipped


def _sheet(root: Path, pilot: dict[str, Any], lesson: dict[str, Any]) -> str:
    ls: list[str] = []
    ls.append(f"# Leçon {lesson['position']} — {lesson['titles']['fr']}")
    ls.append(f"*Créole :* {lesson['titles']['ht']}  ")
    ls.append(f"*Identifiant stable de la leçon :* `{lesson['id']}`  ")
    ls.append(f"*Unité :* {pilot['unit']['titles']['fr']} — *classe :* {pilot['grade']} — *matière :* mathématiques")
    ls.append("")
    ls.append(
        f"> **Statut : {STATUS_FR}.** Cette feuille n'approuve rien. Aucune case n'est cochée. "
        "Le contenu n'est « approuvé » que lorsqu'un enseignant de mathématiques qualifié ET un locuteur natif de la langue concernée l'ont signé ci-dessous."
    )
    ls.append("")
    ls.append("## 1. Objectifs de la leçon")
    for loc in LOCALES:
        ls.append(f"**{LOC_NAME[loc].capitalize()}**")
        ls += [f"- {_t(o)}" for o in lesson["objectives"][loc]]
        ls.append("")
    ls.append("## 2. Lien avec les programmes officiels (à vérifier par vous)")
    for r in lesson["curriculum_refs"]:
        rel = {"direct": "correspondance directe", "partial": "correspondance PARTIELLE", "context": "contexte seulement"}[r["relation"]]
        ls.append(f"- **{r['source']}** — {rel} — {r['locator']}  \n  *Remarque :* {r['note']}")
    ls.append("")
    ls.append(
        "Registre complet des sources et de leurs limites : `docs/content-02a/01-source-register.md`. L'alignement n'est **pas** déclaré officiel : c'est à vous de le confirmer ou de le corriger."
    )
    ls.append("")

    part = 3
    for loc in LOCALES:
        blocks = _read(root, lesson["files"]["blocks"][loc])
        questions = _read(root, lesson["files"]["questions"][loc])
        extra = (
            "Vérifiez aussi : le vocabulaire mathématique, l'orthographe, le naturel des phrases, la cohérence avec le français."
            if loc == "ht"
            else "Vérifiez aussi : la justesse mathématique, la clarté pour un élève de 7e année, le niveau de langue."
        )
        ls.append(f"## {part}. Texte de la leçon — {LOC_NAME[loc]}")
        ls.append(f"*{extra}*")
        ls.append("")
        for i, b in enumerate(blocks, start=1):
            ls.append(_block_md(i, b))
            ls.append("")
        ls.append(f"### Décisions sur le texte ({LOC_NAME[loc]})")
        ls.append("")
        ls.append("| Bloc | Décision (OK / Corriger / Rejeter) | Correction proposée |")
        ls.append("|---|---|---|")
        ls += [f"| B{i} `{b['key']}` |  |  |" for i, b in enumerate(blocks, start=1)]
        ls.append("")
        part += 1
        ls.append(f"## {part}. Exercices et clé de réponses — {LOC_NAME[loc]}")
        ls.append(
            "Pour chaque exercice : la réponse attendue est marquée. Les calculs ont été **recalculés automatiquement** par l'outil de validation, "
            "mais seul un enseignant peut juger si la question est juste, claire et adaptée."
        )
        ls.append("")
        for n, q in enumerate(questions, start=1):
            ls.append(_question_md(n, q))
            ls.append("")
        ls.append(f"### Décisions sur les exercices ({LOC_NAME[loc]})")
        ls.append("")
        ls.append(
            "| Exercice | Réponse attendue correcte ? (oui / non) | Explication correcte ? (oui / non) | Question claire et de bon niveau ? (oui / non) | Correction proposée |"
        )
        ls.append("|---|---|---|---|---|")
        ls += [f"| Q{n} `{q['question_key']}` |  |  |  |  |" for n, q in enumerate(questions, start=1)]
        ls.append("")
        part += 1

    checked, skipped = _coverage(root, lesson)
    ls.append(f"## {part}. Calculs : ce que l'outil a vérifié et ce qu'il n'a PAS interprété")
    ls.append("")
    ls.append(
        f"L'outil a recalculé exactement **{checked}** égalités ou comparaisons chiffrées écrites dans les textes, énoncés et explications (français et créole). "
        "Les réponses proposées aux élèves sont contrôlées par un autre mécanisme (fiche de vérification de la leçon)."
    )
    if skipped:
        ls.append(f"**{len(skipped)}** relation(s) n'ont **pas** été interprétées par l'outil : **vérifiez-les à la main**.")
        ls.append("")
        ls += [f"- `{where}` — {KIND_FR[kind]} : « {_t(text)} »" for where, kind, text in skipped]
    else:
        ls.append("Aucune relation n'a été laissée de côté dans cette leçon.")
    ls.append("")
    part += 1

    ls.append(f"## {part}. Décision pour cette leçon")
    ls.append("")
    ls.append(
        "| Langue | Décision (Approuver / Approuver avec corrections / Rejeter) | Nom | Rôle (enseignant de mathématiques / locuteur natif) | Date | Signature |"
    )
    ls.append("|---|---|---|---|---|---|")
    for loc in LOCALES:
        for role in ("enseignant de mathématiques", "locuteur natif"):
            ls.append(f"| {LOC_NAME[loc]} |  |  | {role} |  |  |")
    ls.append("")
    ls.append(
        "Pour qu'une langue soit marquée « approuvée » dans `pilot.json`, il faut **les deux** signatures (enseignant ET locuteur natif) pour cette langue, "
        "et le champ `decision_ref` doit renvoyer à ce document signé. Tant que ce n'est pas fait, le statut reste `draft_unreviewed`."
    )
    return "\n".join(ls) + "\n"


def _answer_key(root: Path, pilot: dict[str, Any]) -> str:
    ls = [
        "# Clé de réponses — vue d'ensemble (français)",
        "",
        f"> **{STATUS_FR}.** Tableau de contrôle rapide : la lettre (position affichée : A, B, C, D) de la réponse attendue pour chaque exercice. À confirmer ou corriger par un enseignant.",
        "",
        "| Leçon | Exercice | Énoncé | Réponse attendue |",
        "|---|---|---|---|",
    ]
    for lesson in pilot["lessons"]:
        qs = _read(root, lesson["files"]["questions"]["fr"])
        for n, q in enumerate(qs, start=1):
            cid = q["answer_key"]["correct_choice_id"]
            pos, text = next((i, c["text"]) for i, c in enumerate(q["response_spec"]["choices"]) if c["id"] == cid)
            ls.append(f"| {lesson['position']} | Q{n} | {_t(q['prompt']['text'])} | **{chr(ord('A') + pos)}** — {_t(text)} |")
    return "\n".join(ls) + "\n"


def _csv(root: Path, pilot: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["lesson", "locale", "item_type", "item_id", "decision", "correction", "reviewer_name", "reviewer_role", "date"])
    for lesson in pilot["lessons"]:
        for loc in LOCALES:
            w.writerow([lesson["slug"], loc, "lesson", lesson["id"], "", "", "", "", ""])
            for b in _read(root, lesson["files"]["blocks"][loc]):
                w.writerow([lesson["slug"], loc, "block", b["key"], "", "", "", "", ""])
            for q in _read(root, lesson["files"]["questions"][loc]):
                w.writerow([lesson["slug"], loc, "question", q["question_key"], "", "", "", "", ""])
    return buf.getvalue()


GUIDE = """# Guide de relecture — pilote de mathématiques 7e AF

*(Pour un enseignant de mathématiques et un locuteur natif du créole haïtien. Aucune connaissance informatique n'est nécessaire.)*

## À quoi sert ce dossier ?

Edupreneurs prépare des leçons pour téléphones. Ce **pilote** contient **6 leçons** sur les nombres entiers naturels pour la **7e année fondamentale**,
chacune avec 5 exercices à choix multiple, en **français** et en **créole haïtien**.

**Tout est un brouillon.** Rien n'a été relu par un enseignant ni par un locuteur natif. Le choix de la 7e AF en mathématiques est lui-même
une *proposition*, pas une décision du propriétaire du projet. Ces textes ont été écrits avec l'aide d'une IA : ils peuvent contenir des erreurs,
des maladresses ou un créole peu naturel. **Votre rôle est de les juger sévèrement.**

## Ce que nous vous demandons

Pour chaque leçon (une feuille par leçon dans ce dossier) :

1. Lire le texte français, bloc par bloc, et noter pour chaque bloc **OK / Corriger / Rejeter**, avec la correction.
2. Lire les 5 exercices : la **réponse attendue** est-elle bien la seule bonne ? L'explication est-elle juste ? La question est-elle claire pour un élève de 7e année ?
3. Faire la même chose pour le **créole** (un locuteur natif ; idéalement aussi un enseignant).
4. Donner une décision par langue : **Approuver**, **Approuver avec corrections** ou **Rejeter**, et signer (nom, rôle, date).

Vous pouvez écrire sur la feuille imprimée, dans le fichier, ou remplir `decisions.template.csv` (un tableau avec une ligne par leçon, bloc et exercice, que
vous pouvez ouvrir dans un tableur).

## Ce que « approuvé » veut dire

Une langue d'une leçon n'est « approuvée » que si **deux personnes** l'ont signée : un **enseignant de mathématiques qualifié** et un **locuteur natif de cette langue**.
Aucune leçon n'a ce statut aujourd'hui. Les accords de principe, les « ça a l'air bien » ou la signature d'une seule personne ne suffisent pas.

## Les questions de programme (à ne pas ignorer)

Le dossier `docs/content-02a/01-source-register.md` explique ce qui a pu être vérifié sur les programmes officiels du MENFP et ce qui reste **incertain** :
deux documents officiels existent (un programme de 2024 et un programme à compétences minimales de 2019) et ils ne placent pas tous les sujets dans la même année.
Les leçons ne reprennent que ce que les deux documents ont en commun. **Dites-nous** si, selon vous, un sujet est mal placé en 7e année ou manque.

## Ce que les outils ont déjà contrôlé (et ce qu'ils ne peuvent pas contrôler)

Déjà contrôlé automatiquement : format des fichiers ; les égalités et comparaisons chiffrées écrites avec les symboles + − × ÷ = ≠ < > ≤ ≥ dans les textes, les énoncés
et les explications (calcul exact, sens des opérations respecté) ; chaque réponse attendue (recalculée) ; une seule bonne réponse par exercice ;
mêmes nombres en français et en créole ; absence de caractères parasites et de balisage ; tailles.

**Ce que l'outil n'interprète pas, volontairement** : les calculs avec des unités de mesure (`8 km = 8 000 m`), les décompositions en unités nommées
(`3 480 = 3 milliers + 4 centaines …`), les formules écrites avec des lettres, et toute notation qu'il ne sait pas lire (fraction écrite `1/2`, virgule décimale, puissance,
signe moins du clavier). Une notation non lisible dans une relation fait **échouer** la validation ; une relation laissée de côté est **listée** dans la feuille de la leçon
(rubrique « Calculs ») : c'est à vous de la vérifier. Aucun message de l'outil ne doit être lu comme « tous les calculs sont justes ».

**Non contrôlable par une machine** : la qualité pédagogique, la justesse du vocabulaire, le naturel du créole, l'adéquation au programme, la clarté pour un élève.
C'est précisément votre travail.

## Que faire de vos décisions ?

Renvoyez les feuilles (ou le CSV) à l'équipe Edupreneurs. Elle corrigera les textes, puis enregistrera les approbations (nom, rôle, date, référence du document signé)
dans le descripteur du pilote. Voir `docs/content-02a/06-path-to-content-02b.md`.

## Contenu du dossier

- `lesson-01-…` à `lesson-06-…` : une feuille de relecture par leçon (texte, exercices, tableaux de décision).
- `answer-key-overview.md` : toutes les réponses attendues sur une page.
- `decisions.template.csv` : tableau de décisions vide.
"""


def build_review_pack(root: Path, repo_root: Path | None = None) -> dict[str, str]:
    """The review package, generated only from content that passes the SAME validation as `validate`.

    A reviewer must never receive a traceback instead of the question to fix, so the child documents are validated
    first and the first problems are reported with lesson, file, question and field.
    """
    if repo_root is None:
        try:
            repo_root = find_repo_root(Path(root).resolve())
        except FileNotFoundError:
            repo_root = find_repo_root(TOOL_DIR)
    errors = [f for f in validate(root, repo_root=repo_root) if f.severity == "error"]
    if errors:
        shown = "; ".join(f"{f.code} @ {f.where}: {f.message}" for f in errors[:5])
        more = f" (and {len(errors) - 5} more)" if len(errors) > 5 else ""
        raise ContentFileError("review_input_invalid", f"the review package cannot be built from invalid content: {shown}{more}")
    pilot = load_descriptor(root)
    files = {"00-guide-de-relecture.md": GUIDE, "answer-key-overview.md": _answer_key(root, pilot), "decisions.template.csv": _csv(root, pilot)}
    for lesson in pilot["lessons"]:
        files[f"lesson-{lesson['position']:02d}-{lesson['slug']}.md"] = _sheet(root, pilot, lesson)
    return files
