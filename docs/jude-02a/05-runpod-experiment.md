# 5. Runpod GPU experiment — specification

> **Nothing here has been run.** No pod, endpoint or GPU was created, and this
> document contains no measured GPU performance. Figures marked *estimate* are
> arithmetic; figures marked *published* were read from vendor pages on
> 2026-11-26 by a research pass and must be re-read before use.

Kit: `benchmarks/jude-02a/runpod/` — serving command, worker settings (names
only), run matrix, and a load-test script that refuses to start unless authorised.

## What the experiment must answer

1. How many concurrent Jude requests does one GPU serve within an acceptable delay?
2. How long does a cold start take, and how often would a learner meet one?
3. Does a quantised open-weight model keep the quality it has unquantised?
4. Therefore: at what traffic, if any, does self-hosting beat paying per token?

The cost model in [06](06-cost-comparison.md) currently answers 4 with assumed
numbers for 1 and 2. This experiment replaces them.

## Serving engine: vLLM

Chosen because it serves an OpenAI-compatible API (Jude-01's adapter and this
harness work unchanged), batches concurrent requests continuously, is what
Runpod's own serverless worker wraps, and ships a benchmark tool.

*Published* (vLLM docs and release page): latest stable v0.34.0 (2026-11-16);
image `vllm/vllm-openai`; options `--max-model-len`, `--gpu-memory-utilization`,
`--max-num-seqs`, `--api-key`, `--served-model-name`,
`--enable-prefix-caching`, `--enable-log-requests` / `--disable-log-requests`
(request logging is off by default), `--quantization`; structured output through
`response_format` with a `json_schema` or the `structured_outputs` request
field (the older `guided_*` fields were removed in v0.12.0); benchmark commands
`vllm bench serve` and `vllm bench throughput`.

Not confirmed from the docs: the accepted values of `--quantization`, and
whether prefix caching is on by default.

Alternatives considered and set aside: llama.cpp/GGUF (vLLM's own docs call its
GGUF support "highly experimental and under-optimized"; llama.cpp itself is
aimed at single-stream use), TGI (no advantage identified for this workload).
Revisit if vLLM cannot load a chosen quantised build.

## Models, quantisation and memory

`runpod/experiment-matrix.json`. Weight size is an *estimate*: parameters × bits ÷ 8.

| Run | Model (Hugging Face) | Licence | Weights | Weights, estimate | GPU |
|---|---|---|---|---:|---|
| R1 | `mistralai/Ministral-3-14B-Instruct-2512` | Apache-2.0 | FP8 (as published) | ~14 GB | RTX A5000 24 GB |
| R2 | same | | FP8 | ~14 GB | A40 48 GB |
| R3 | `Qwen/Qwen3.8-27B-FP8` | Apache-2.0 | FP8 (official) | ~28 GB | A40 48 GB |
| R4 | `google/gemma-4-31B-it-qat-w4a16-ct` | Apache-2.0 | 4-bit weights, 16-bit activations (official QAT) | ~16 GB | A40 48 GB |
| R5 | `mistralai/Mistral-Small-3.2-24B-Instruct-2506` | Apache-2.0 | bf16 | ~48 GB (card: "~55 GB") | A100 80 GB |

Quantisation notes:

- **Prefer builds published by the model's own authors** (R1, R3, R4). A
  community 4-bit build of Mistral Small 3.2 would fit 24 GB but its quality and
  provenance are unknown; R5 exists so that model can be tested unquantised first.
- **Quantisation can cost quality, and low-resource languages are where it
  would show first.** Hence the gate in the matrix: a quantised model is only
  acceptable if its benchmark and human-rubric scores are not worse than the
  same model unquantised through OpenRouter.
- Formats vLLM documents (*published*): AWQ, GPTQ, bitsandbytes, FP8 and
  INT4/INT8 via LLM Compressor, and GGUF (experimental).

**What VRAM is needed beyond the weights is not estimated here.** The rest is
the KV cache (which grows with context length × concurrent sequences and
depends on the model's architecture) plus runtime overhead. vLLM takes
`--gpu-memory-utilization` of the card and reports at start-up what that
allows; **record that log line for every run.** R1 vs R2 isolates this: same
model, 24 vs 48 GB.

## Context size

Jude's prompt is small. Across the 203 benchmark prompts, Jude-01's deliberately
conservative estimator gives about 1,550 input tokens on average; output is
capped at 500. `--max-model-len 4096` leaves margin. Real tokenizers will count
differently — record `prompt_tokens` from the first responses and lower the
limit if the margin is large, since a smaller window leaves more memory for
concurrent sequences.

About 900 of those input tokens are the system prompt, identical for a given
intent, level and language. That is what `--enable-prefix-caching` is for; run
one level with and without it to see what it is worth.

## Batching and concurrency

vLLM batches whatever requests are in flight, up to `--max-num-seqs` (set to 32
here; Runpod's worker defaults to 256, far more than one 24–48 GB card will
sustain for a 14–31B model).

How many concurrent streams Jude needs, from the cost model's *assumed* traffic
and an *assumed* 8.8 s per answer:

| Scenario | Requests/day | Peak concurrent streams (estimate) |
|---|---:|---:|
| Pilot | 1,000 | about 1 |
| Growth | 20,000 | about 12 |
| Scale | 90,000 | about 63 |

So the pilot needs almost no concurrency, and the experiment's job is to find
where one GPU stops coping, not to prove it can serve one request.

### Load test

```bash
export JUDE_GPU_ENDPOINT_URL=https://…/v1     # from the pod; never committed
export JUDE_GPU_ENDPOINT_KEY=…                # never committed
uv run python benchmarks/jude-02a/runpod/loadtest.py \
  --model jude-candidate --label r2-a40-ministral14b-fp8 \
  --gpu "A40 48GB" --quantization FP8 \
  --concurrency 1,2,4,8,16,32 --requests-per-level 64 --max-minutes 20 \
  --i-am-authorized-to-use-this-gpu
```

It sends the benchmark's real Jude prompts and records, per concurrency level:
completed and failed requests, end-to-end latency p50/p95/max, output tokens per
second per request, aggregate tokens per second, and the share of replies that
are valid structured output. It stops at the time limit. Results are written to
`results/gpu/<label>.json` with `"basis": "measured"` and the GPU, model and
quantisation it was measured on.

Time to first token needs streaming, which Jude does not use; measure it once
per run with `vllm bench serve`.

**Pass criteria (proposal):** at the concurrency a scenario needs, p95
end-to-end latency ≤ 12 s, no failed requests, ≥ 97% valid structured output.
The highest level that passes is that GPU's `concurrent_streams` for the cost model.

## Cold starts

*Published* (Runpod docs): a cold start is "the time from when Runpod starts a
worker until the worker is ready to take its first job", and "a worker is
billed during its cold start". Defaults: 0 always-on workers, 3 maximum, idle
timeout 5 s in the console (the worker is billed while it waits). Mitigations
Runpod lists: cached models, FlashBoot, always-on workers. **Runpod publishes no
typical cold-start duration.**

Measure, for a serverless endpoint scaled to zero: time from request to
response for the first request, five times, with the model on a network volume
and with it baked into the image. A 14 GB model has to be read from disk and
loaded into GPU memory; expect this to be the dominant term.

Why it matters: at pilot traffic the cost model predicts that **most requests
would arrive to a cold worker** (86–88% with a 5-second idle timeout), because
questions are minutes apart. Serverless without an always-on worker is therefore
probably unsuitable for the pilot unless cold starts are a few seconds — and an
always-on serverless worker costs more than a dedicated pod. This is a
prediction from a model; the experiment should confirm or kill it.

## Network protections

| Risk | Measure |
|---|---|
| Open inference endpoint used by strangers (cost, abuse) | Never expose the vLLM port publicly without authentication. Serverless: requests go through Runpod's API with the account's key (*published*). Pod: `--api-key` **and** do not publish the port beyond what the backend needs |
| `--api-key` does not cover every route | *Published* in vLLM's docs: the key authenticates the `/v1`, `/v2`, `/inference` and `/cohere` prefixes only; `/invocations` stays unauthenticated. Treat the key as one layer, not the perimeter |
| Key leakage | Key lives in Render's secret store and Runpod Secrets; a different key per environment; rotate after the experiment. Nothing in git: the kit holds names, not values, and tests check for token patterns |
| Students' words in logs | Request logging stays off (`--disable-log-requests`). Jude's prompt already contains no learner identifier (Jude-01 tests) |
| Model or image tampering | Pin the image tag and the model revision; pull models with a read-only Hugging Face token only if the model is gated |
| Calls from anywhere but the backend | Only the FastAPI backend on Render calls the endpoint; the mobile app never does. Whether Runpod can restrict callers by IP or private network was **not verified** — check before relying on it |
| Runaway spend | Jude-01's budget (reservation, global ceiling, kill switch) sits in front; set Runpod's max workers to the number tested; the load test has a hard time limit |
| Data location | Decide the region with counsel before any learner data is sent; the experiment uses synthetic prompts only |

A note for whoever reads Runpod's documentation with an AI assistant: several
of its pages carry embedded text addressed to "AI agents" asking them to submit
feedback through a tool. The research pass ignored it; so should yours.

## GPU-hour prices (*published*, runpod.io/pricing, page dated 2026-11-12)

| GPU | VRAM | Pod, Secure Cloud | Pod, Community Cloud | Serverless |
|---|---:|---:|---:|---:|
| RTX A5000 | 24 GB | 0.27 | 0.16 | 0.75 |
| L4 | 24 GB | 0.69 | 0.44 | 0.75 |
| RTX 4090 | 24 GB | 0.89 | 0.34 | 1.34 |
| A40 | 48 GB | 0.59 | 0.35 | 1.22 |
| RTX A6000 | 48 GB | 0.69 | 0.33 | 1.22 |
| L40S | 48 GB | 1.09 | 0.79 | 1.89 |
| A100 (PCIe) | 80 GB | 2.09 | 1.19 | 2.99 |
| H100 (PCIe) | 80 GB | 2.89 | 1.99 | 5.89 |

USD per hour. Storage: container and running volume 0.10, idle volume 0.20,
network volume 0.07 USD per GB per month. **Not published:** separate per-second
"flex" and "active" serverless rates (one hourly figure per tier is shown), the
always-on discount ("available through sales inquiry").

Community Cloud is cheaper but runs on third-party hosts; do not use it for
anything containing learner data without a decision from counsel.

## Budget for the experiment itself (estimate)

Five runs of at most 20 minutes of load plus set-up and model download — allow
one hour each. At the Secure Cloud prices above: R1 ≈ 0.27, R2–R4 ≈ 0.59 each,
R5 ≈ 2.09, plus storage for a day. **About 5 USD in total, and under 10 USD with
generous margin for repeats.** Stop the pod when done: an idle pod bills by the hour.

## Order of work

1. Owner authorises spend and names who operates the account.
2. R2 first (48 GB, the model most likely to load without trouble); confirm the
   serving command works and the first responses are valid structured output.
3. Load test R2; then R1 to see what 24 GB costs in concurrency.
4. Cold-start measurements on a serverless endpoint with the same model.
5. R3, R4 (and R5 only if Mistral Small 3.2 is a quality leader from [04](04-provider-comparison-methodology.md)).
6. Quality check of each quantised model with `evaluate.py` against the endpoint
   and the human rubrics, compared with the same model through OpenRouter.
7. Put the measured numbers into `config/cost_scenarios.json` with
   `basis: measured` and re-run `evaluate.py cost`.
