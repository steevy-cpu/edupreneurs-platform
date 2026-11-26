"""The GPU load-test instrument: refuses by default, measures correctly on a stand-in."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from jude_eval import BENCH_ROOT, loadtest
from jude_eval.dataset import build_cases, load_packs

from edu_api.tutor.providers.base import ModelRequest, ModelResult, ProviderUnavailableError
from edu_api.tutor.providers.mock import DeterministicMockProvider

PACKS = load_packs()
PROMPTS = loadtest.jude_prompts(build_cases(PACKS)[:40], PACKS, model="jude-candidate")
ENV = {loadtest.ENDPOINT_ENV: "https://gpu.invalid/v1", loadtest.KEY_ENV: "test-not-a-real-key"}


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_refuses_with_every_reason_when_nothing_is_set() -> None:
    with pytest.raises(loadtest.LoadTestRefused) as refused:
        loadtest.check_authorization(authorized=False, model=None, max_minutes=None, env={})
    assert len(refused.value.reasons) == 5


@pytest.mark.parametrize(
    ("kwargs", "env", "reason"),
    [
        ({"authorized": False}, ENV, "was not given"),
        ({}, {loadtest.KEY_ENV: "k"}, "no endpoint in"),
        ({}, {**ENV, loadtest.ENDPOINT_ENV: "http://gpu.invalid/v1"}, "must use https"),
        ({}, {loadtest.ENDPOINT_ENV: "https://gpu.invalid/v1"}, "no endpoint key"),
        ({"model": None}, ENV, "no served model name"),
        ({"max_minutes": 0}, ENV, "--max-minutes"),
        ({"max_minutes": 600}, ENV, "--max-minutes"),
    ],
)
def test_each_missing_condition_refuses(kwargs: dict, env: dict, reason: str) -> None:  # type: ignore[type-arg]
    options = {"authorized": True, "model": "jude-candidate", "max_minutes": 10.0} | kwargs
    with pytest.raises(loadtest.LoadTestRefused) as refused:
        loadtest.check_authorization(env=env, **options)
    assert len(refused.value.reasons) == 1 and reason in refused.value.reasons[0]
    assert loadtest.check_authorization(authorized=True, model="m", max_minutes=10, env=ENV) == (
        "https://gpu.invalid/v1",
        "test-not-a-real-key",
    )


def test_the_script_refuses_by_default() -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(BENCH_ROOT / "runpod" / "loadtest.py"), "--model", "x"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ":".join(sys.path)},
    )
    assert done.returncode == 2 and "load test refused" in done.stderr


def test_prompts_are_the_ones_jude_would_send() -> None:
    assert len(PROMPTS) == 40
    for request in PROMPTS:
        assert request.model == "jude-candidate" and request.max_output_tokens == 500
        assert [m.role for m in request.messages] == ["system", "user"]
        assert request.messages[1].content.startswith("DATA (untrusted")


async def test_levels_are_measured_and_failures_counted() -> None:
    clock = FakeClock()

    class Timed:
        name = "timed"

        def __init__(self) -> None:
            self.inner = DeterministicMockProvider()
            self.n = 0

        async def complete(self, request: ModelRequest) -> ModelResult:
            self.n += 1
            if self.n % 10 == 0:
                raise ProviderUnavailableError()
            clock.t += 2.0  # every call "takes" two seconds
            return await self.inner.complete(request)

    results = await loadtest.run_load_test(
        Timed(), PROMPTS, levels=[1, 4], requests_per_level=20, max_seconds=10_000, clock=clock
    )
    assert [r.concurrency for r in results] == [1, 4]
    for level in results:
        assert level.completed + sum(level.failed.values()) == 20
        assert level.failed == {"unavailable": 2}
        assert level.schema_valid == level.completed
        assert level.latency_s_p50 == 2.0 and level.latency_s_p95 == 2.0
        assert level.mean_input_tokens > 500 and level.mean_output_tokens > 10
        assert level.output_tokens_per_s_per_request_median > 0
        assert not level.stopped_at_time_limit
        json.dumps(level.to_json())


async def test_the_time_limit_stops_the_run() -> None:
    clock = FakeClock()

    class Slow:
        name = "slow"

        async def complete(self, request: ModelRequest) -> ModelResult:
            clock.t += 30.0
            return await DeterministicMockProvider().complete(request)

    results = await loadtest.run_load_test(
        Slow(), PROMPTS, levels=[1, 2, 4], requests_per_level=50, max_seconds=120, clock=clock
    )
    assert len(results) == 1 and results[0].stopped_at_time_limit
    assert results[0].completed == 4  # 4 x 30 s, then the limit
    with pytest.raises(ValueError):
        await loadtest.run_load_test(Slow(), [], levels=[1], requests_per_level=1, max_seconds=1)


def test_the_experiment_kit_is_complete_and_holds_no_secret() -> None:
    kit = BENCH_ROOT / "runpod"
    matrix = json.loads((kit / "experiment-matrix.json").read_text())
    assert len(matrix["runs"]) >= 4 and "Nothing here has been run" in matrix["_about"]
    assert all({"id", "model", "gpu", "weights", "why"} <= run.keys() for run in matrix["runs"])
    serve = (kit / "vllm-serve.sh").read_text()
    for flag in (
        "--api-key",
        "--max-model-len",
        "--gpu-memory-utilization",
        "--max-num-seqs",
        "--served-model-name",
        "--disable-log-requests",
    ):
        assert flag in serve, flag
    assert "NOT RUN" in serve
    example = (kit / "worker-vllm.env.example").read_text()
    assert "EXAMPLE ONLY" in example
    for line in example.splitlines():
        if line.startswith("HF_TOKEN"):
            raise AssertionError("the example must not set a token")
