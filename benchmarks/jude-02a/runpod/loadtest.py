#!/usr/bin/env python3
"""Load-test a self-hosted vLLM endpoint with real Jude prompts. See jude_eval/loadtest.py.

    export JUDE_GPU_ENDPOINT_URL=https://<your endpoint>/v1      # never commit this
    export JUDE_GPU_ENDPOINT_KEY=<endpoint key>                  # never commit this
    uv run python benchmarks/jude-02a/runpod/loadtest.py \\
        --model jude-candidate --label a40-ministral14b-fp8 \\
        --gpu "A40 48GB" --quantization FP8 \\
        --concurrency 1,2,4,8,16,32 --requests-per-level 64 --max-minutes 20 \\
        --i-am-authorized-to-use-this-gpu

Without the last flag, the two variables and a time limit it refuses to start.
Results go to results/gpu/<label>.json, marked as MEASURED with what was measured on.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jude_eval import RESULTS_DIR, loadtest
from jude_eval.dataset import build_cases, load_packs

from edu_api.tutor.providers.openai_compatible import OpenAICompatibleProvider


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--model", help="served model name (vLLM --served-model-name)")
    parser.add_argument("--label", default="unnamed", help="file name for the results")
    parser.add_argument("--gpu", default="unspecified", help="GPU type, recorded with the results")
    parser.add_argument("--quantization", default="unspecified", help="recorded with the results")
    parser.add_argument("--concurrency", default="1,2,4,8,16")
    parser.add_argument("--requests-per-level", type=int, default=48)
    parser.add_argument("--max-minutes", type=float)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument(loadtest.AUTHORIZATION_FLAG, dest="authorized", action="store_true")
    args = parser.parse_args(argv)
    try:
        url, key = loadtest.check_authorization(
            authorized=args.authorized, model=args.model, max_minutes=args.max_minutes
        )
    except loadtest.LoadTestRefused as refused:
        sys.stderr.write(f"{refused}\n")
        return 2
    packs = load_packs()
    prompts = loadtest.jude_prompts(build_cases(packs), packs, model=args.model)
    levels = [int(x) for x in args.concurrency.split(",")]

    async def run() -> list[loadtest.LevelResult]:
        async with httpx.AsyncClient(
            base_url=url, headers={"Authorization": f"Bearer {key}"}, timeout=args.timeout_s
        ) as client:
            return await loadtest.run_load_test(
                OpenAICompatibleProvider(client, name="self-hosted"),
                prompts,
                levels=levels,
                requests_per_level=args.requests_per_level,
                max_seconds=args.max_minutes * 60,
            )

    results = asyncio.run(run())
    document = {
        "basis": "measured",
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": args.model,
        "gpu": args.gpu,
        "quantization": args.quantization,
        "prompts": len(prompts),
        "requests_per_level": args.requests_per_level,
        "levels": [r.to_json() for r in results],
    }
    out = RESULTS_DIR / "gpu"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    for r in results:
        sys.stdout.write(
            f"c={r.concurrency:<3} ok={r.completed:<4} failed={sum(r.failed.values()):<3} "
            f"p50={r.latency_s_p50}s p95={r.latency_s_p95}s "
            f"agg={r.aggregate_output_tokens_per_s} tok/s\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
