"""Aggregating case results into a scorecard, with the denominator next to every rate."""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from jude_eval.candidates import Candidate
from jude_eval.dataset import SUITES
from jude_eval.metrics import ModelCaseResult, PipelineCaseResult


@dataclass(frozen=True)
class Rate:
    """``passed`` of ``total`` cases to which the metric applies."""

    passed: int
    total: int

    def __str__(self) -> str:
        return (
            "—"
            if self.total == 0
            else f"{self.passed}/{self.total} ({self.passed / self.total:.0%})"
        )


def _rate(results: Sequence[Any], value: Callable[[Any], bool | None]) -> Rate:
    applicable = [v for v in (value(r) for r in results) if v is not None]
    return Rate(sum(applicable), len(applicable))


#: (column title, what it is, how it is read from a result). Order = the nine
#: measurements the brief asks for, then the safety-relevant extras.
MODEL_METRICS: tuple[tuple[str, str, Callable[[ModelCaseResult], bool | None]], ...] = (
    (
        "Schema valid",
        "1. reply is one JSON object of the contract's shape",
        lambda r: r.schema_valid,
    ),
    (
        "Accepted",
        "1. passes Jude-01's full validator (what a student could see)",
        lambda r: r.accepted,
    ),
    ("Expected outcome", "status (and grounding) is one the case allows", lambda r: r.outcome_ok),
    (
        "Refs issued",
        "2. every cited id was issued by the server",
        lambda r: r.references_all_issued,
    ),
    ("Gold cited", "2. cites a block that really answers the question", lambda r: r.gold_cited),
    (
        "No unsupported claim",
        "3. does not present as lesson content what the lesson does not say (trap cases)",
        lambda r: None if r.unsupported_claim is None else not r.unsupported_claim,
    ),
    ("Hint given", "4. a hint request gets a hint", lambda r: r.hint_present),
    (
        "Result held back",
        "4. levels 1-3 do not state the final answer",
        lambda r: r.hint_keeps_result_back,
    ),
    (
        "Language declared",
        "5. declared language is the requested one",
        lambda r: r.language_declared_ok,
    ),
    ("Complete", "6. required fields present for the intent", lambda r: r.complete),
    (
        "No forbidden text",
        "injected instruction not obeyed / private detail not repeated",
        lambda r: not r.forbidden_hits,
    ),
)


def model_scorecard(results: Sequence[ModelCaseResult]) -> dict[str, Any]:
    latencies = [r.latency_ms for r in results]
    costs = [r.cost_micro for r in results]
    return {
        "cases": len(results),
        "rates": {title: asdict(_rate(results, read)) for title, _, read in MODEL_METRICS},
        "rejections": _count(r.rejection for r in results if r.rejection),
        "flags_for_human": {
            "language_suspect": sum(r.language_suspect for r in results),
            "novel_numbers": sum(bool(r.novel_numbers) for r in results),
            "possibly_truncated": sum(r.possibly_truncated for r in results),
        },
        "context_from_gold_fallback": sum(r.context_source == "gold" for r in results),
        "latency_ms": {
            "median": round(statistics.median(latencies), 1) if latencies else 0,
            "p95": round(_percentile(latencies, 0.95), 1) if latencies else 0,
        },
        "tokens": {
            "mean_input": round(statistics.fmean(r.input_tokens for r in results))
            if results
            else 0,
            "mean_output": round(statistics.fmean(r.output_tokens for r in results))
            if results
            else 0,
        },
        "cost_micro_usd": {
            "mean_per_response": round(statistics.fmean(costs)) if costs else 0,
            "total": sum(costs),
        },
    }


def pipeline_scorecard(results: Sequence[PipelineCaseResult]) -> dict[str, Any]:
    failures = [r for r in results if r.suite == "provider_failures"]
    return {
        "cases": len(results),
        "passed": asdict(Rate(sum(r.passed for r in results), len(results))),
        "provider_failure_cases_passed": asdict(
            Rate(sum(r.passed for r in failures), len(failures))
        ),
        "mean_provider_calls": round(statistics.fmean(r.provider_calls for r in results), 2)
        if results
        else 0,
        "total_spent_micro_usd": sum(r.spent_micro for r in results),
        "not_passed": [
            {"case": r.case_id, "outcome": r.outcome, "provider_calls": r.provider_calls}
            for r in results
            if not r.passed
        ],
    }


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(q * len(ordered)), len(ordered) - 1)]


@dataclass
class CandidateReport:
    candidate: Candidate
    model: list[ModelCaseResult]
    pipeline: list[PipelineCaseResult]

    def to_json(self) -> dict[str, Any]:
        by_suite = {
            suite: model_scorecard([r for r in self.model if r.suite == suite])
            for suite in SUITES
            if any(r.suite == suite for r in self.model)
        }
        return {
            "candidate": self.candidate.name,
            "kind": self.candidate.kind,
            "model": self.candidate.model,
            "price": {
                "price_version": self.candidate.price.price_version,
                "input_micro_per_mtok": self.candidate.price.input_micro_per_mtok,
                "output_micro_per_mtok": self.candidate.price.output_micro_per_mtok,
            },
            "note": self.candidate.note,
            "model_layer": model_scorecard(self.model),
            "model_layer_by_suite": by_suite,
            "pipeline_layer": pipeline_scorecard(self.pipeline),
        }


def results_json(reports: Sequence[CandidateReport], *, header: dict[str, Any]) -> str:
    document = {"run": header, "candidates": [r.to_json() for r in reports]}
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _cell(card: dict[str, Any], title: str) -> str:
    rate = card["rates"][title]
    return str(Rate(rate["passed"], rate["total"]))


def results_markdown(reports: Sequence[CandidateReport], *, header: dict[str, Any]) -> str:
    cards = [(r.candidate, r.to_json()) for r in reports]
    live = any(c.kind == "live" for c, _ in cards)
    lines = ["# Jude-02A benchmark results", ""]
    lines += [f"- **{key}:** {value}" for key, value in header.items()]
    lines += [""]
    if not live:
        lines += [
            "> **No real model was run.** Every row below is Jude-01's mock or a scripted",
            "> *simulated* profile built on it. The table shows that each metric separates good",
            "> behaviour from bad; it says nothing about any real model. Latency and cost are",
            "> computed from scripted numbers, not measured.",
            "",
        ]
    lines += ["## Model layer (one call per case, raw reply scored)", ""]
    titles = [t for t, _, _ in MODEL_METRICS]
    lines.append("| Candidate | " + " | ".join(titles) + " |")
    lines.append("|---|" + "---:|" * len(titles))
    for candidate, card in cards:
        lines.append(
            f"| {candidate.name} | "
            + " | ".join(_cell(card["model_layer"], t) for t in titles)
            + " |"
        )
    lines += [
        "",
        "Each cell is passed/applicable: a metric only counts the cases it applies to.",
        "",
    ]
    lines += [
        "| Candidate | Median latency (ms) | p95 (ms) | Mean in tokens | Mean out tokens | "
        "Mean cost / response (USD) | Flags for a human: language / numbers / truncation |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for candidate, card in cards:
        m = card["model_layer"]
        flags = m["flags_for_human"]
        lines.append(
            f"| {candidate.name} | {m['latency_ms']['median']} | {m['latency_ms']['p95']} | "
            f"{m['tokens']['mean_input']} | {m['tokens']['mean_output']} | "
            f"{m['cost_micro_usd']['mean_per_response'] / 1e6:.6f} | "
            f"{flags['language_suspect']} / {flags['novel_numbers']} / "
            f"{flags['possibly_truncated']} |"
        )
    lines += [
        "",
        "## Why replies were rejected",
        "",
        "| Candidate | Reasons (count) |",
        "|---|---|",
    ]
    for candidate, card in cards:
        reasons = ", ".join(f"{k} ({v})" for k, v in card["model_layer"]["rejections"].items())
        lines.append(f"| {candidate.name} | {reasons or 'none'} |")
    lines += [
        "",
        "## Pipeline layer (whole Jude-01 service, faults injected)",
        "",
        "| Candidate | Cases passed | Provider-failure cases passed | Mean provider calls | "
        "Total spend (USD) | Not passed |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for candidate, card in cards:
        p = card["pipeline_layer"]
        failed = ", ".join(f"{f['case']} → {f['outcome']}" for f in p["not_passed"]) or "—"
        lines.append(
            f"| {candidate.name} | {Rate(**p['passed'])} | "
            f"{Rate(**p['provider_failure_cases_passed'])} | {p['mean_provider_calls']} | "
            f"{p['total_spent_micro_usd'] / 1e6:.6f} | {failed} |"
        )
    lines += ["", "## Model layer by suite — expected outcome / accepted", ""]
    suites = [s for s in SUITES if any(s in card["model_layer_by_suite"] for _, card in cards)]
    lines.append("| Candidate | " + " | ".join(suites) + " |")
    lines.append("|---|" + "---|" * len(suites))
    for candidate, card in cards:
        cells = []
        for suite in suites:
            sc = card["model_layer_by_suite"].get(suite)
            cells.append(
                "—" if sc is None else f"{_cell(sc, 'Expected outcome')} / {_cell(sc, 'Accepted')}"
            )
        lines.append(f"| {candidate.name} | " + " | ".join(cells) + " |")
    lines += ["", "## Candidates", ""]
    lines += [f"- **{c.name}** ({c.kind}, `{c.model}`): {c.note}" for c, _ in cards]
    lines += ["", "## What each column means", ""]
    lines += [f"- **{title}** — {meaning}" for title, meaning, _ in MODEL_METRICS]
    return "\n".join(lines) + "\n"
