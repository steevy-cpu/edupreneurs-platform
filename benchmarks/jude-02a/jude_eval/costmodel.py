"""A configurable cost comparison of three ways to serve Jude.

    OpenRouter (pay per token)  ·  Runpod serverless  ·  Runpod dedicated GPU

EVERY INPUT CARRIES ITS BASIS
-----------------------------
``published``   read from a vendor page (config/published_prices.json).
``assumption``  a number somebody chose. All GPU performance figures are
                assumptions until the Runpod experiment in ``runpod/`` is run.
``measured``    observed in a benchmark. Nothing in Jude-02A is measured.

The formulas are simple queueing approximations, written out below so they can
be argued with. They are for choosing which experiment to run next, not for a
budget commitment.

Definitions (per day unless stated)
    R   requests            H   hours over which they arrive (the school day)
    λ   = R / (H·3600)      arrival rate in requests per second
    S   = ttft + output_tokens / tokens_per_second     seconds a request occupies a stream
    a   = λ·S               streams busy on average;   a_peak = a · peak_factor
    c   concurrent streams one GPU sustains

OpenRouter   cost = R · (1+retry) · (in·price_in + out·price_out) · (1+credit_fee)
Dedicated    GPUs = ceil(a_peak / c);  cost = GPUs · hourly · hours_provisioned + storage
Serverless   a worker is billed while it cold-starts, while it has work, and during
             its idle timeout T after the last request. Treat one worker as
             alternating between DOWN (until the next arrival, 1/λ on average)
             and UP. With Poisson arrivals an up period lasts on average
                 E[up] = cold + (e^(λ(S+T)) - 1) / λ
             so   up fraction = E[up] / (E[up] + 1/λ)          (never above 1)
                  cold starts = H·3600 / (E[up] + 1/λ)
                  waiting requests ≈ cold starts · (1 + λ·cold)   (those arriving mid-start too)
             When the load needs more than one worker, billed worker-time is
             a / (c · packing), where packing < 1 admits that requests do not
             fill workers perfectly.
                 billed seconds = H·3600 · max(up fraction, a / (c·packing))
             Always-on ("active") workers are billed 24 h and remove cold starts
             for the load they cover. Their discount is not published, so none
             is assumed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jude_eval import CONFIG_DIR

Basis = Literal["published", "assumption", "measured"]
DAYS_PER_MONTH = 30


@dataclass(frozen=True)
class Workload:
    name: str
    requests_per_day: float
    input_tokens: float
    output_tokens: float
    active_hours_per_day: float
    peak_factor: float
    #: Extra provider calls from retries and rejected outputs, as a fraction.
    retry_overhead: float = 0.05

    @property
    def arrival_rate(self) -> float:
        return self.requests_per_day / (self.active_hours_per_day * 3600)


@dataclass(frozen=True)
class GpuPerformance:
    """UNMEASURED until the Runpod experiment runs. Every field is an assumption."""

    label: str
    time_to_first_token_s: float
    output_tokens_per_s: float
    concurrent_streams: int
    cold_start_s: float

    def service_time(self, output_tokens: float) -> float:
        return self.time_to_first_token_s + output_tokens / self.output_tokens_per_s


@dataclass(frozen=True)
class CostLine:
    option: str
    monthly_usd: float
    usd_per_request: float
    gpus: int | None = None
    utilization: float | None = None
    cold_start_share: float | None = None
    detail: str = ""


def openrouter_cost(
    workload: Workload,
    *,
    model: str,
    input_usd_per_mtok: float,
    output_usd_per_mtok: float,
    credit_fee_pct: float,
) -> CostLine:
    calls = workload.requests_per_day * (1 + workload.retry_overhead) * DAYS_PER_MONTH
    per_call = (
        workload.input_tokens * input_usd_per_mtok + workload.output_tokens * output_usd_per_mtok
    ) / 1e6
    monthly = calls * per_call * (1 + credit_fee_pct / 100)
    return CostLine(
        f"OpenRouter · {model}",
        monthly,
        monthly / (workload.requests_per_day * DAYS_PER_MONTH),
        detail="pay per token; no idle cost",
    )


def dedicated_cost(
    workload: Workload,
    perf: GpuPerformance,
    *,
    gpu: str,
    usd_per_hour: float,
    hours_per_day: float = 24.0,
    storage_gb: float = 60.0,
    storage_usd_per_gb_month: float = 0.10,
) -> CostLine:
    service = perf.service_time(workload.output_tokens)
    busy = workload.arrival_rate * service
    gpus = max(1, math.ceil(busy * workload.peak_factor / perf.concurrent_streams))
    monthly = (
        gpus * usd_per_hour * hours_per_day * DAYS_PER_MONTH + storage_gb * storage_usd_per_gb_month
    )
    used_stream_hours = busy * workload.active_hours_per_day
    utilization = used_stream_hours / (gpus * perf.concurrent_streams * hours_per_day)
    return CostLine(
        f"Runpod dedicated · {gpus}x {gpu}",
        monthly,
        monthly / (workload.requests_per_day * DAYS_PER_MONTH),
        gpus=gpus,
        utilization=utilization,
        detail=f"{hours_per_day:g} h/day provisioned",
    )


def serverless_cost(
    workload: Workload,
    perf: GpuPerformance,
    *,
    gpu: str,
    usd_per_hour: float,
    idle_timeout_s: float = 5.0,
    active_workers: int = 0,
    packing_efficiency: float = 0.7,
    storage_gb: float = 60.0,
    storage_usd_per_gb_month: float = 0.07,
) -> CostLine:
    rate = workload.arrival_rate
    service = perf.service_time(workload.output_tokens)
    busy = rate * service
    window = workload.active_hours_per_day * 3600
    per_second = usd_per_hour / 3600
    workers_for_load = busy / (perf.concurrent_streams * packing_efficiency)
    if active_workers > 0:
        # Warm workers absorb load up to their capacity; flex workers take the rest.
        flex_seconds = window * max(0.0, workers_for_load - active_workers)
        billed_seconds = active_workers * 24 * 3600 + flex_seconds
        waiting_share = 0.0
    else:
        linger = service + idle_timeout_s
        # exp() overflows for heavy load; there the worker simply never goes down.
        exponent = min(rate * linger, 50.0)
        up_period = perf.cold_start_s + (math.exp(exponent) - 1) / rate
        cycle = up_period + 1 / rate
        billed_seconds = window * max(up_period / cycle, workers_for_load)
        cold_starts = window / cycle
        waiting = cold_starts * (1 + rate * perf.cold_start_s)
        waiting_share = min(1.0, waiting / workload.requests_per_day)
    monthly = billed_seconds * per_second * DAYS_PER_MONTH + storage_gb * storage_usd_per_gb_month
    return CostLine(
        f"Runpod serverless · {gpu}" + (f" · {active_workers} always-on" if active_workers else ""),
        monthly,
        monthly / (workload.requests_per_day * DAYS_PER_MONTH),
        utilization=min(
            1.0, busy / (perf.concurrent_streams * max(1.0, math.ceil(workers_for_load)))
        ),
        cold_start_share=waiting_share,
        detail=f"idle timeout {idle_timeout_s:g} s",
    )


def break_even_requests_per_day(
    workload: Workload,
    perf: GpuPerformance,
    *,
    openrouter: dict[str, float],
    dedicated_usd_per_hour: float,
    credit_fee_pct: float,
) -> float | None:
    """Daily requests above which ONE dedicated GPU is cheaper than paying per token.

    ``None`` when a single GPU cannot carry that many requests at peak, so the
    crossover does not exist for one GPU.
    """
    per_request = (
        (workload.input_tokens * openrouter["in"] + workload.output_tokens * openrouter["out"])
        / 1e6
        * (1 + workload.retry_overhead)
        * (1 + credit_fee_pct / 100)
    )
    if per_request <= 0:
        return None
    needed = dedicated_usd_per_hour * 24 / per_request
    capacity = (
        perf.concurrent_streams
        / perf.service_time(workload.output_tokens)
        * workload.active_hours_per_day
        * 3600
        / workload.peak_factor
    )
    return needed if needed <= capacity else None


def load_scenarios(path: Path | None = None) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        (path or CONFIG_DIR / "cost_scenarios.json").read_text(encoding="utf-8")
    )
    return document


def load_prices(path: Path | None = None) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        (path or CONFIG_DIR / "published_prices.json").read_text(encoding="utf-8")
    )
    return document


def _usd(value: float) -> str:
    return f"{value:,.2f}" if value >= 1 else f"{value:.4f}"


def report(scenarios: dict[str, Any] | None = None, prices: dict[str, Any] | None = None) -> str:
    scenarios = scenarios or load_scenarios()
    prices = prices or load_prices()
    fee = prices["openrouter"]["fees"]["credit_purchase_fee_pct"]
    models = {m["slug"]: m for m in prices["openrouter"]["models"]}
    gpus = {g["name"]: g for g in prices["runpod"]["gpus"]}
    perfs = [GpuPerformance(**p) for p in scenarios["gpu_performance_assumptions"]]
    chosen_models = scenarios["openrouter_models"]
    gpu = gpus[scenarios["gpu"]]
    lines = [
        "# Jude-02A cost comparison",
        "",
        f"Prices: **published**, read {prices['retrieved_on']} "
        "(`config/published_prices.json`). Workloads and every GPU performance figure: "
        "**assumptions** (`config/cost_scenarios.json`). **Nothing here is measured.**",
        "",
        f"GPU used for the self-hosted rows: {gpu['name']} ({gpu['vram_gb']} GB) — "
        f"dedicated {gpu['pod_secure_usd_per_hour']} USD/h (Secure Cloud), "
        f"serverless {gpu['serverless_usd_per_hour']} USD/h.",
        "",
    ]
    for raw in scenarios["workloads"]:
        workload = Workload(**raw)
        lines += [
            f"## {workload.name}",
            "",
            f"{workload.requests_per_day:,.0f} requests/day over "
            f"{workload.active_hours_per_day:g} h, "
            f"peak x{workload.peak_factor:g}, {workload.input_tokens:,.0f} input + "
            f"{workload.output_tokens:,.0f} output tokens, {workload.retry_overhead:.0%} retries "
            "— all assumptions.",
            "",
            "| Option | GPU performance assumed | Monthly USD | USD / request | GPUs | "
            "Utilisation | Requests that wait for a cold start |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for slug in chosen_models:
            model = models[slug]
            line = openrouter_cost(
                workload,
                model=slug,
                input_usd_per_mtok=model["input_usd_per_mtok"],
                output_usd_per_mtok=model["output_usd_per_mtok"],
                credit_fee_pct=fee,
            )
            lines.append(
                f"| {line.option} | n/a | {_usd(line.monthly_usd)} | "
                f"{line.usd_per_request:.5f} | — | — | — |"
            )
        for perf in perfs:
            rows = [
                serverless_cost(
                    workload,
                    perf,
                    gpu=gpu["name"],
                    usd_per_hour=gpu["serverless_usd_per_hour"],
                    idle_timeout_s=scenarios["serverless_idle_timeout_s"],
                    packing_efficiency=scenarios["serverless_packing_efficiency"],
                ),
                serverless_cost(
                    workload,
                    perf,
                    gpu=gpu["name"],
                    usd_per_hour=gpu["serverless_usd_per_hour"],
                    idle_timeout_s=scenarios["serverless_idle_timeout_s"],
                    active_workers=1,
                    packing_efficiency=scenarios["serverless_packing_efficiency"],
                ),
                dedicated_cost(
                    workload,
                    perf,
                    gpu=gpu["name"],
                    usd_per_hour=gpu["pod_secure_usd_per_hour"],
                ),
                dedicated_cost(
                    workload,
                    perf,
                    gpu=gpu["name"],
                    usd_per_hour=gpu["pod_secure_usd_per_hour"],
                    hours_per_day=workload.active_hours_per_day + 2,
                ),
            ]
            for line in rows:
                cold = "—" if line.cold_start_share is None else f"{line.cold_start_share:.0%}"
                util = "—" if line.utilization is None else f"{line.utilization:.0%}"
                lines.append(
                    f"| {line.option} ({line.detail}) | {perf.label} | {_usd(line.monthly_usd)} | "
                    f"{line.usd_per_request:.5f} | {line.gpus or '—'} | {util} | {cold} |"
                )
        lines.append("")
    lines += [
        "## Break-even: one dedicated GPU (24 h) versus paying per token",
        "",
        "Daily requests above which one always-on GPU costs less than OpenRouter, using the "
        "token sizes of the first workload. A dash means one GPU cannot carry that many at "
        "peak under that performance assumption.",
        "",
        "| OpenRouter model | " + " | ".join(p.label for p in perfs) + " |",
        "|---|" + "---:|" * len(perfs),
    ]
    reference = Workload(**scenarios["workloads"][0])
    for slug in chosen_models:
        model = models[slug]
        cells = []
        for perf in perfs:
            point = break_even_requests_per_day(
                reference,
                perf,
                openrouter={"in": model["input_usd_per_mtok"], "out": model["output_usd_per_mtok"]},
                dedicated_usd_per_hour=gpu["pod_secure_usd_per_hour"],
                credit_fee_pct=fee,
            )
            cells.append("—" if point is None else f"{point:,.0f}")
        lines.append(f"| {slug} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Performance assumptions used (unmeasured)",
        "",
        "| Label | Time to first token (s) | Output tokens/s per stream | Concurrent streams | "
        "Cold start (s) |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {p.label} | {p.time_to_first_token_s:g} | {p.output_tokens_per_s:g} | "
        f"{p.concurrent_streams} | {p.cold_start_s:g} |"
        for p in perfs
    ]
    return "\n".join(lines) + "\n"
