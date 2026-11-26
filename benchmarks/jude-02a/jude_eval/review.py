"""Packets for human reviewers.

Teaching quality and authentic Haitian Creole cannot be scored by a script.
This module prepares what a reviewer needs — the passages the model was given,
the question, the reply — with the candidate's name replaced by a letter, and
an empty score sheet with one row per (case, candidate, rubric criterion).
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Mapping, Sequence

from jude_eval.dataset import Case, LessonPack
from jude_eval.metrics import ModelCaseResult
from jude_eval.runner import RunSettings, build_context

#: Criterion ids; the wording and the 1-4 anchors are in ``rubrics/*.md``.
RUBRICS: dict[str, tuple[str, ...]] = {
    "teaching": ("T1-correct", "T2-grounded", "T3-level", "T4-guides", "T5-clear", "T6-tone"),
    "creole": ("K1-natural", "K2-spelling", "K3-terms", "K4-no-french-calque", "K5-register"),
}


def blind_labels(candidates: Sequence[str], *, seed: str) -> dict[str, str]:
    """Candidate name → letter, in an order that depends only on ``seed``."""
    ordered = sorted(
        candidates, key=lambda name: hashlib.sha256(f"{seed}\x1f{name}".encode()).hexdigest()
    )
    return {name: chr(ord("A") + index) for index, name in enumerate(ordered)}


def select_cases(cases: Sequence[Case], *, per_suite: int) -> list[Case]:
    """The first ``per_suite`` reviewable cases of every suite (deterministic)."""
    chosen: list[Case] = []
    counts: dict[str, int] = {}
    for case in cases:
        if not case.review or "model" not in case.layers:
            continue
        if counts.get(case.suite, 0) < per_suite:
            counts[case.suite] = counts.get(case.suite, 0) + 1
            chosen.append(case)
    return chosen


def packet_markdown(
    cases: Sequence[Case],
    packs: dict[str, LessonPack],
    results: Mapping[str, Sequence[ModelCaseResult]],
    *,
    seed: str,
) -> str:
    labels = blind_labels(list(results), seed=seed)
    by_candidate = {name: {r.case_id: r for r in rows} for name, rows in results.items()}
    lines = [
        "# Jude review packet",
        "",
        "Candidates are shown as letters. Score with the rubrics in `rubrics/`. "
        "Everything here is synthetic.",
        "",
    ]
    for case in cases:
        pack = packs[case.lesson]
        context, source = build_context(case, pack, RunSettings())
        lines += [
            f"## {case.id}",
            "",
            f"- Grade and lesson: {pack.grade} — {pack.lesson(case.locale).title}",
            f"- Lesson language: {case.locale} · Answer language asked for: {case.answer_locale}",
            f"- Kind of help: {case.intent}, support level {case.support_level}",
            f"- Rubrics: {', '.join(case.review)}",
        ]
        if case.note:
            lines.append(f"- Note for the reviewer: {case.note}")
        lines += ["", "**Student wrote:** " + (case.message or "_(pressed a button; no text)_"), ""]
        lines.append(
            "**Passages the model was given**"
            + (" (supplied by hand: retrieval found none)" if source == "gold" else "")
            + ":"
        )
        lines += [
            f"> **{p.id}** ({p.passage.kind}) " + p.passage.text.replace("\n", " / ")
            for p in context.passages
        ]
        lines.append("")
        for name, letter in sorted(labels.items(), key=lambda kv: kv[1]):
            result = by_candidate[name].get(case.id)
            lines.append(f"### Candidate {letter}")
            if result is None or result.reply is None:
                lines += ["_No usable reply (not valid structured output)._", ""]
                continue
            reply = result.reply
            lines += [
                f"- Explanation: {reply['explanation']}",
                f"- Hint: {reply['hint'] or '—'}",
                f"- Check question: {reply['check_question'] or '—'}",
                f"- Says it relied on: {', '.join(reply['references']) or '—'} "
                f"(grounding: {reply['grounding']}, status: {reply['status']})",
                "",
            ]
    return "\n".join(lines) + "\n"


def score_sheet_csv(cases: Sequence[Case], candidates: Sequence[str], *, seed: str) -> str:
    labels = blind_labels(candidates, seed=seed)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["case_id", "candidate", "rubric", "criterion", "score_1_to_4", "comment", "reviewer"]
    )
    for case in cases:
        for letter in sorted(labels.values()):
            for rubric in case.review:
                for criterion in RUBRICS[rubric]:
                    writer.writerow([case.id, letter, rubric, criterion, "", "", ""])
    return buffer.getvalue()


def label_key_csv(candidates: Sequence[str], *, seed: str) -> str:
    """The letter → candidate key. Keep it away from reviewers until scoring is done."""
    labels = blind_labels(candidates, seed=seed)
    return "letter,candidate\n" + "".join(
        f"{letter},{name}\n" for name, letter in sorted(labels.items(), key=lambda kv: kv[1])
    )
