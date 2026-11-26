"""Concurrency load test for a self-hosted, OpenAI-compatible endpoint (vLLM on Runpod).

NOT RUN in Jude-02A: no GPU has been rented. This is the instrument for the
experiment specified in docs/jude-02a/05-runpod-experiment.md.

It sends REAL Jude prompts (built from the benchmark cases with Jude-01's
template) at a series of concurrency levels and records, per level: completed
and failed requests, end-to-end latency percentiles, output tokens per second
per request, aggregate tokens per second, and the share of replies that are
valid structured output. Time to first token needs streaming, which Jude does
not use; measure it with ``vllm bench serve``.

It refuses to start unless the operator states they are authorised to use the
endpoint, and it stops at a wall-clock limit: a rented GPU bills by the second.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from edu_api.tutor.prompts import get_template
from edu_api.tutor.providers.base import ModelProvider, ModelRequest, ProviderError
from edu_api.tutor.service import TutorService
from jude_eval.dataset import Case, LessonPack
from jude_eval.metrics import parse_reply
from jude_eval.runner import RunSettings, build_context, lesson_for, tutor_request

ENDPOINT_ENV = "JUDE_GPU_ENDPOINT_URL"
KEY_ENV = "JUDE_GPU_ENDPOINT_KEY"
AUTHORIZATION_FLAG = "--i-am-authorized-to-use-this-gpu"
MAX_MINUTES = 60.0


class LoadTestRefused(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("load test refused:\n- " + "\n- ".join(reasons))
        self.reasons = reasons


def check_authorization(
    *,
    authorized: bool,
    model: str | None,
    max_minutes: float | None,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """(endpoint URL, key) or ``LoadTestRefused`` listing everything missing."""
    env = os.environ if env is None else env
    reasons: list[str] = []
    if not authorized:
        reasons.append(f"{AUTHORIZATION_FLAG} was not given")
    url, key = env.get(ENDPOINT_ENV, ""), env.get(KEY_ENV, "")
    if not url:
        reasons.append(f"no endpoint in {ENDPOINT_ENV}")
    elif not url.startswith("https://"):
        reasons.append("the endpoint must use https")
    if not key:
        reasons.append(f"no endpoint key in {KEY_ENV}")
    if not model:
        reasons.append("no served model name was given (--model)")
    if max_minutes is None or not 0 < max_minutes <= MAX_MINUTES:
        reasons.append(f"--max-minutes must be above 0 and at most {MAX_MINUTES:g}")
    if reasons:
        raise LoadTestRefused(reasons)
    return url, key


def jude_prompts(
    cases: Sequence[Case],
    packs: dict[str, LessonPack],
    *,
    model: str,
    settings: RunSettings | None = None,
) -> list[ModelRequest]:
    """The prompts Jude would really send for the model-layer cases."""
    settings = settings or RunSettings()
    template = get_template(settings.prompt_version)
    requests: list[ModelRequest] = []
    for case in cases:
        if "model" not in case.layers:
            continue
        pack = packs[case.lesson]
        lesson = lesson_for(case, pack)
        context, _ = build_context(case, pack, settings)
        turn = TutorService._student_turn(tutor_request(case, pack), lesson, case.message)
        prompt = template.render(
            language=case.answer_locale,
            lesson_title=lesson.title,
            lesson_locale=lesson.locale,
            context=context,
            student=turn,
        )
        requests.append(
            ModelRequest(prompt.messages, model, settings.max_output_tokens, settings.temperature)
        )
    return requests


@dataclass
class LevelResult:
    concurrency: int
    completed: int = 0
    failed: dict[str, int] = field(default_factory=dict)
    schema_valid: int = 0
    wall_seconds: float = 0.0
    latency_s_p50: float = 0.0
    latency_s_p95: float = 0.0
    latency_s_max: float = 0.0
    output_tokens_per_s_per_request_median: float = 0.0
    aggregate_output_tokens_per_s: float = 0.0
    mean_input_tokens: float = 0.0
    mean_output_tokens: float = 0.0
    stopped_at_time_limit: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


async def run_level(
    provider: ModelProvider,
    prompts: Sequence[ModelRequest],
    *,
    concurrency: int,
    requests: int,
    deadline: float,
    clock: Callable[[], float] = time.perf_counter,
) -> LevelResult:
    """``requests`` prompts through ``concurrency`` parallel workers, until ``deadline``."""
    result = LevelResult(concurrency)
    latencies: list[float] = []
    speeds: list[float] = []
    tokens_in: list[int] = []
    tokens_out: list[int] = []
    queue = list(range(requests))
    started = clock()

    async def worker() -> None:
        while queue:
            if clock() >= deadline:
                result.stopped_at_time_limit = True
                return
            index = queue.pop()
            begin = clock()
            try:
                reply = await provider.complete(prompts[index % len(prompts)])
            except ProviderError as exc:
                result.failed[exc.kind] = result.failed.get(exc.kind, 0) + 1
                continue
            elapsed = max(clock() - begin, 1e-9)
            result.completed += 1
            result.schema_valid += parse_reply(reply.text) is not None
            latencies.append(elapsed)
            speeds.append(reply.usage.output_tokens / elapsed)
            tokens_in.append(reply.usage.input_tokens)
            tokens_out.append(reply.usage.output_tokens)

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    result.wall_seconds = round(max(clock() - started, 1e-9), 3)
    if latencies:
        ordered = sorted(latencies)
        result.latency_s_p50 = round(statistics.median(ordered), 3)
        result.latency_s_p95 = round(ordered[min(int(0.95 * len(ordered)), len(ordered) - 1)], 3)
        result.latency_s_max = round(ordered[-1], 3)
        result.output_tokens_per_s_per_request_median = round(statistics.median(speeds), 1)
        result.aggregate_output_tokens_per_s = round(sum(tokens_out) / result.wall_seconds, 1)
        result.mean_input_tokens = round(statistics.fmean(tokens_in), 1)
        result.mean_output_tokens = round(statistics.fmean(tokens_out), 1)
    return result


async def run_load_test(
    provider: ModelProvider,
    prompts: Sequence[ModelRequest],
    *,
    levels: Sequence[int],
    requests_per_level: int,
    max_seconds: float,
    clock: Callable[[], float] = time.perf_counter,
) -> list[LevelResult]:
    if not prompts:
        raise ValueError("no prompts to send")
    deadline = clock() + max_seconds
    results: list[LevelResult] = []
    for concurrency in levels:
        if clock() >= deadline:
            break
        results.append(
            await run_level(
                provider,
                prompts,
                concurrency=concurrency,
                requests=requests_per_level,
                deadline=deadline,
                clock=clock,
            )
        )
    return results
