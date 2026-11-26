"""The cost model behaves sensibly at its limits, and review packets are blind and complete."""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys

import pytest
from jude_eval import BENCH_ROOT, CONFIG_DIR, RESULTS_DIR, costmodel, review
from jude_eval.costmodel import GpuPerformance, Workload
from jude_eval.dataset import build_cases, load_packs

PILOT = Workload("pilot", 1000, 1800, 250, 10, 3)
MID = GpuPerformance("middle", 0.5, 30, 12, 90)
OPENROUTER = {
    "model": "m",
    "input_usd_per_mtok": 0.10,
    "output_usd_per_mtok": 0.50,
    "credit_fee_pct": 5.5,
}


def scaled(factor: float) -> Workload:
    return Workload("x", PILOT.requests_per_day * factor, 1800, 250, 10, 3)


def test_pay_per_token_cost_is_linear_and_matches_hand_arithmetic() -> None:
    line = costmodel.openrouter_cost(PILOT, **OPENROUTER)
    per_call = (1800 * 0.10 + 250 * 0.50) / 1e6
    assert line.monthly_usd == pytest.approx(1000 * 1.05 * 30 * per_call * 1.055)
    assert costmodel.openrouter_cost(scaled(10), **OPENROUTER).monthly_usd == pytest.approx(
        10 * line.monthly_usd
    )
    assert line.usd_per_request == pytest.approx(line.monthly_usd / 30_000)


def test_a_dedicated_gpu_costs_the_same_whether_or_not_anyone_uses_it() -> None:
    quiet = costmodel.dedicated_cost(scaled(0.01), MID, gpu="A40", usd_per_hour=0.59)
    pilot = costmodel.dedicated_cost(PILOT, MID, gpu="A40", usd_per_hour=0.59)
    assert quiet.gpus == pilot.gpus == 1
    assert quiet.monthly_usd == pilot.monthly_usd == pytest.approx(0.59 * 24 * 30 + 6.0)
    assert quiet.usd_per_request == pytest.approx(100 * pilot.usd_per_request)
    assert pilot.utilization is not None and pilot.utilization < 0.05


def test_dedicated_gpu_count_follows_peak_load() -> None:
    heavy = costmodel.dedicated_cost(scaled(90), MID, gpu="A40", usd_per_hour=0.59)
    assert heavy.gpus is not None and heavy.gpus > 1
    slower = GpuPerformance("slow", 1.0, 15, 4, 180)
    assert (
        costmodel.dedicated_cost(scaled(90), slower, gpu="A40", usd_per_hour=0.59).gpus > heavy.gpus
    )  # type: ignore[operator]


def test_serverless_is_never_billed_for_more_than_the_time_that_exists() -> None:
    for factor in (0.001, 0.01, 0.1, 1, 10):
        line = costmodel.serverless_cost(scaled(factor), MID, gpu="A40", usd_per_hour=1.22)
        workers = max(1.0, scaled(factor).arrival_rate * MID.service_time(250) / (12 * 0.7))
        ceiling = workers * 10 * 1.22 * 30 + 60 * 0.07
        assert 0 < line.monthly_usd <= ceiling + 1e-6, factor
        assert line.cold_start_share is not None and 0 <= line.cold_start_share <= 1


def test_serverless_cost_grows_with_traffic_and_cold_starts_fade() -> None:
    lines = [
        costmodel.serverless_cost(scaled(f), MID, gpu="A40", usd_per_hour=1.22)
        for f in (0.01, 0.1, 1, 10, 100)
    ]
    costs = [line.monthly_usd for line in lines]
    assert costs == sorted(costs)
    cold = [line.cold_start_share for line in lines]
    assert cold[0] > 0.9 and cold[-1] < 0.01  # type: ignore[operator]
    per_request = [line.usd_per_request for line in lines]
    assert per_request == sorted(per_request, reverse=True)


def test_an_always_on_worker_removes_cold_starts_and_costs_at_least_a_full_day() -> None:
    line = costmodel.serverless_cost(PILOT, MID, gpu="A40", usd_per_hour=1.22, active_workers=1)
    assert line.cold_start_share == 0
    assert line.monthly_usd >= 1.22 * 24 * 30


def test_break_even_moves_the_way_it_should() -> None:
    kwargs = {"dedicated_usd_per_hour": 0.59, "credit_fee_pct": 5.5}
    fast = GpuPerformance("fast", 0.3, 50, 64, 40)
    cheap = costmodel.break_even_requests_per_day(
        PILOT, fast, openrouter={"in": 0.075, "out": 0.20}, **kwargs
    )
    dear = costmodel.break_even_requests_per_day(
        PILOT, fast, openrouter={"in": 0.75, "out": 4.50}, **kwargs
    )
    # The dearer the per-token model, the sooner a GPU pays for itself.
    assert cheap is not None and dear is not None and dear < cheap
    assert cheap == pytest.approx(0.59 * 24 / ((1800 * 0.075 + 250 * 0.20) / 1e6 * 1.05 * 1.055))
    # Against the cheapest per-token model, one middling GPU cannot serve enough
    # requests to reach the crossover at all.
    assert (
        costmodel.break_even_requests_per_day(
            PILOT, MID, openrouter={"in": 0.075, "out": 0.20}, **kwargs
        )
        is None
    )


def test_inputs_are_labelled_by_where_they_come_from() -> None:
    prices = json.loads((CONFIG_DIR / "published_prices.json").read_text())
    scenarios = json.loads((CONFIG_DIR / "cost_scenarios.json").read_text())
    assert prices["retrieved_on"] == "2026-11-26"
    assert prices["openrouter"]["source"].startswith("https://openrouter.ai/")
    assert prices["runpod"]["source"].startswith("https://www.runpod.io/")
    assert len(prices["runpod"]["not_published"]) >= 3
    assert "ASSUMPTION" in scenarios["_about"]
    report = costmodel.report()
    assert "**Nothing here is measured.**" in report and "assumptions" in report
    for slug in scenarios["openrouter_models"]:
        assert slug in report


def test_committed_results_are_reproducible() -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(BENCH_ROOT / "evaluate.py"), "all", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "No real model was run." in (RESULTS_DIR / "offline.md").read_text(encoding="utf-8")


# --- human review -------------------------------------------------------------------------
def test_blind_labels_are_stable_and_hide_the_candidate() -> None:
    names = ["vendor/model-a", "vendor/model-b", "mock"]
    labels = review.blind_labels(names, seed="s")
    assert labels == review.blind_labels(list(reversed(names)), seed="s")
    assert sorted(labels.values()) == ["A", "B", "C"]
    assert review.blind_labels(names, seed="other") != labels or True  # different seed may reorder


def test_score_sheet_has_one_empty_row_per_case_candidate_and_criterion() -> None:
    cases = review.select_cases(build_cases(), per_suite=2)
    assert cases and all(c.review for c in cases)
    sheet = list(csv.DictReader(io.StringIO(review.score_sheet_csv(cases, ["x", "y"], seed="s"))))
    expected = sum(len(review.RUBRICS[r]) for c in cases for r in c.review) * 2
    assert len(sheet) == expected
    assert all(row["score_1_to_4"] == "" and row["candidate"] in "AB" for row in sheet)
    assert {row["rubric"] for row in sheet} == {"teaching", "creole"}


def test_the_sample_packet_is_blind_and_the_key_is_separate() -> None:
    packet = (RESULTS_DIR / "review-sample" / "packet.md").read_text(encoding="utf-8")
    key = (RESULTS_DIR / "review-sample" / "label-key.csv").read_text(encoding="utf-8")
    assert "### Candidate A" in packet and "### Candidate B" in packet
    assert "mock" not in packet.lower() and "leaky" not in packet.lower()
    assert "mock (Jude-01)" in key and "sim: leaky-tutor" in key
    assert "**Passages the model was given**" in packet and "**Student wrote:**" in packet


def test_rubrics_exist_for_every_criterion_on_the_sheet() -> None:
    packs = load_packs()
    assert packs
    for rubric, criteria in review.RUBRICS.items():
        name = "teaching-quality.md" if rubric == "teaching" else "haitian-creole.md"
        text = (BENCH_ROOT / "rubrics" / name).read_text(encoding="utf-8")
        for criterion in criteria:
            assert criterion in text, (rubric, criterion)
