#!/usr/bin/env python3
"""Jude-02A evaluation — command line.

    uv run python benchmarks/jude-02a/evaluate.py dataset     # write dataset/cases.jsonl
    uv run python benchmarks/jude-02a/evaluate.py retrieval   # retrieval strategies
    uv run python benchmarks/jude-02a/evaluate.py offline     # mock + simulated candidates
    uv run python benchmarks/jude-02a/evaluate.py cost        # hosting cost comparison
    uv run python benchmarks/jude-02a/evaluate.py review      # blind human-review packet
    uv run python benchmarks/jude-02a/evaluate.py all         # everything above
    uv run python benchmarks/jude-02a/evaluate.py live ...    # REFUSED unless fully authorised

Add ``--check`` to fail instead of writing when a committed result is out of date.
Everything except ``live`` runs offline, deterministically, without a network.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jude_eval import DATASET_DIR, RESULTS_DIR, costmodel, live, retrieval_bench, review
from jude_eval.candidates import Candidate, offline_candidates
from jude_eval.dataset import build_cases, cases_jsonl, load_packs, suite_counts
from jude_eval.report import CandidateReport, results_json, results_markdown
from jude_eval.runner import (
    RunSettings,
    RunStopped,
    run_model_layer,
    run_pipeline_layer,
    wall_clock,
)

REVIEW_SEED = "jude-02a-review-1"


def _emit(path: Path, text: str, *, check: bool, stale: list[str]) -> None:
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            stale.append(str(path.relative_to(Path(__file__).resolve().parent)))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _header(cases: int, kind: str) -> dict[str, object]:
    return {
        "Benchmark": "jude-02a",
        "Kind of run": kind,
        "Cases": cases,
        "Prompt": RunSettings().prompt_version,
        "Retrieval": retrieval_bench.RECOMMENDED,
        "Output limit (tokens)": RunSettings().max_output_tokens,
    }


_REPORTS: list[CandidateReport] = []


def _offline_reports() -> list[CandidateReport]:
    """Run every offline candidate once per process (two commands share the result)."""
    if _REPORTS:
        return _REPORTS

    async def run() -> None:
        packs = load_packs()
        cases = build_cases(packs)
        for candidate in offline_candidates():
            _REPORTS.append(
                CandidateReport(
                    candidate,
                    await run_model_layer(candidate, cases, packs),
                    await run_pipeline_layer(candidate, cases, packs),
                )
            )

    with retrieval_bench.memoised_tokenizer():
        asyncio.run(run())
    return _REPORTS


def cmd_dataset(check: bool, stale: list[str]) -> None:
    cases = build_cases()
    _emit(DATASET_DIR / "cases.jsonl", cases_jsonl(cases), check=check, stale=stale)
    if not check:
        for suite, count in suite_counts(cases).items():
            sys.stdout.write(f"{count:4d}  {suite}\n")
        sys.stdout.write(f"{len(cases):4d}  total\n")


def cmd_retrieval(check: bool, stale: list[str]) -> None:
    text = (
        "# Jude-02A retrieval benchmark\n\nSynthetic lessons and questions; see "
        "docs/jude-02a/03-cross-language-retrieval.md.\n\n"
    )
    _emit(
        RESULTS_DIR / "retrieval.md",
        text + retrieval_bench.report() + "\n",
        check=check,
        stale=stale,
    )


def cmd_offline(check: bool, stale: list[str]) -> None:
    reports = _offline_reports()
    header = _header(len(build_cases()), "offline — mock and simulated candidates only")
    _emit(
        RESULTS_DIR / "offline.md",
        results_markdown(reports, header=header),
        check=check,
        stale=stale,
    )
    _emit(
        RESULTS_DIR / "offline.json", results_json(reports, header=header), check=check, stale=stale
    )


def cmd_cost(check: bool, stale: list[str]) -> None:
    _emit(RESULTS_DIR / "cost.md", costmodel.report(), check=check, stale=stale)


def cmd_review(check: bool, stale: list[str]) -> None:
    packs = load_packs()
    cases = build_cases(packs)
    chosen = review.select_cases(cases, per_suite=2)
    reports = _offline_reports()
    shown = {
        r.candidate.name: r.model
        for r in reports
        if r.candidate.name in ("mock (Jude-01)", "sim: leaky-tutor")
    }
    out = RESULTS_DIR / "review-sample"
    _emit(
        out / "packet.md",
        review.packet_markdown(chosen, packs, shown, seed=REVIEW_SEED),
        check=check,
        stale=stale,
    )
    _emit(
        out / "score-sheet.csv",
        review.score_sheet_csv(chosen, list(shown), seed=REVIEW_SEED),
        check=check,
        stale=stale,
    )
    _emit(
        out / "label-key.csv",
        review.label_key_csv(list(shown), seed=REVIEW_SEED),
        check=check,
        stale=stale,
    )


def cmd_live(args: argparse.Namespace) -> int:
    try:
        authorization = live.authorize_live_run(
            live_flag=args.live,
            model=args.model,
            max_spend_usd=args.max_spend_usd,
            authorized_by=args.authorized_by,
        )
    except live.LiveRunRefused as refused:
        sys.stderr.write(f"{refused}\n")
        return 2
    packs = load_packs()
    cases = [c for c in build_cases(packs) if "model" in c.layers][: args.max_cases]
    guard = live.SpendGuard(authorization.cap_micro)
    provider = live.build_live_provider(authorization, guard)
    candidate = Candidate(
        name=authorization.model,
        kind="live",
        model=authorization.model,
        price=authorization.price,
        make_provider=lambda clock: provider,
        note="live run",
    )
    stopped = ""
    try:
        results = asyncio.run(
            run_model_layer(candidate, cases, packs, clock=wall_clock, provider=provider)
        )
    except RunStopped as stop:
        results, stopped = [], str(stop)
    header = (
        _header(len(cases), "LIVE")
        | authorization.manifest()
        | {
            "spent_usd": guard.spent_micro / 1e6,
            "calls": guard.calls,
            "stopped_early": stopped or "no",
        }
    )
    name = authorization.model.replace("/", "__")
    report = CandidateReport(candidate, results, [])
    out = RESULTS_DIR / "live"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.md").write_text(results_markdown([report], header=header), encoding="utf-8")
    (out / f"{name}.json").write_text(results_json([report], header=header), encoding="utf-8")
    sys.stdout.write(f"spent {guard.spent_micro / 1e6:.4f} USD in {guard.calls} calls\n")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "command", choices=["dataset", "retrieval", "offline", "cost", "review", "all", "live"]
    )
    parser.add_argument("--check", action="store_true", help="fail if committed outputs are stale")
    parser.add_argument("--live", action="store_true", help="live only: confirm a paid run")
    parser.add_argument("--model", help="live only: exact OpenRouter model slug")
    parser.add_argument("--max-spend-usd", type=float, help="live only: hard spending cap")
    parser.add_argument("--authorized-by", help="live only: who authorised the spend")
    parser.add_argument("--max-cases", type=int, default=40, help="live only: cases to run")
    args = parser.parse_args(argv)
    if args.command == "live":
        return cmd_live(args)
    stale: list[str] = []
    commands = {
        "dataset": cmd_dataset,
        "retrieval": cmd_retrieval,
        "offline": cmd_offline,
        "cost": cmd_cost,
        "review": cmd_review,
    }
    for name in commands if args.command == "all" else [args.command]:
        commands[name](args.check, stale)
    if stale:
        sys.stderr.write("stale: " + ", ".join(stale) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
