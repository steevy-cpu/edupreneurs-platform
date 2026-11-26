# Jude-02A — model evaluation and GPU readiness

Jude-02A builds the instrument for choosing Jude's first model on evidence. It
does **not** choose one: no real model was run, no GPU was rented and no money
was spent. Stacked on Jude-01 (PR #28, `b11b780`).

| | |
|---|---|
| Branch | `feature/jude-02a-model-evaluation` |
| Harness and data | `benchmarks/jude-02a/` |
| Tests | `tests/unit/jude_eval/` (115) |
| Run everything offline | `uv run python benchmarks/jude-02a/evaluate.py all` |
| Generated results | `benchmarks/jude-02a/results/` |

## What was found (offline, on synthetic data)

1. **Jude-01's retrieval is weaker than its own small test suggested.** On seven
   lessons instead of one, the baseline puts a block that answers the question
   into the prompt for 68–75% of same-language questions, 11% across languages,
   and **5% when the student adds one ordinary sentence before the question**.
2. **Three deterministic changes fix most of it, with no model and no vector
   database:** treat a matched heading as its section, rank against the lesson's
   other-language revision and map hits by block key, and accept a passage that
   matches two solid terms. Together: 86% in every language direction, 70% with
   the extra sentence, and none of 336 unrelated questions matched.
   → [03](03-cross-language-retrieval.md)
3. **At pilot size, paying per token is roughly 3 to 35 times cheaper than the cheapest GPU arrangement.**
   With published prices and assumed traffic of 1,000 questions a day, OpenRouter
   costs 6–82 USD a month depending on the model; the cheapest GPU arrangement
   costs about 218 USD. A single always-on GPU only undercuts the cheaper
   per-token models above roughly 28,000–69,000 questions a day, and only if it
   performs at the optimistic end of numbers nobody has measured yet.
   → [06](06-cost-comparison.md)
4. **The harness tells good behaviour from bad.** Six scripted profiles each lose
   on the metric built for their defect and not on the others.
   → [02](02-harness-and-metrics.md)
5. **Five gaps in Jude-01 surfaced along the way**, listed in
   [08](08-limitations-and-educator-checklist.md#findings-about-jude-01).

## Built versus not done

| Item | State |
|---|---|
| Bilingual benchmark: 7 lessons (7AF–NS4), 215 cases, 13 suites | **Built.** Synthetic; Creole written by an AI model and unreviewed |
| Two-layer runner on Jude-01's prompt, validator and service | **Built, tested** |
| Nine automatic measurements with denominators | **Built, tested** |
| Human rubrics, blind review packet, score sheet | **Built.** No human has scored anything |
| Four deterministic retrieval improvements, benchmarked | **Built, measured** — in the benchmark only; **not** wired into the Jude service |
| Cost model, three hosting options | **Built.** Published prices + assumptions; nothing measured |
| Live evaluation against OpenRouter | **Built, gated, never run** |
| Runpod serving spec, experiment matrix, load-test instrument | **Built, gated, never run** |
| Any real model's quality, latency or cost | **Unknown** |
| Any GPU performance figure | **Unknown** — every one in this work is a labelled assumption |

## Documents

1. [Benchmark dataset](01-benchmark-dataset.md)
2. [Harness, metrics and offline results](02-harness-and-metrics.md)
3. [Cross-language retrieval](03-cross-language-retrieval.md)
4. [Provider comparison methodology](04-provider-comparison-methodology.md)
5. [Runpod experiment specification](05-runpod-experiment.md)
6. [Cost comparison](06-cost-comparison.md)
7. [Human review](07-human-review.md)
8. [Limitations and educator checklist](08-limitations-and-educator-checklist.md)

## Commands

```bash
uv run python benchmarks/jude-02a/evaluate.py dataset     # expand cases → dataset/cases.jsonl
uv run python benchmarks/jude-02a/evaluate.py retrieval   # → results/retrieval.md
uv run python benchmarks/jude-02a/evaluate.py offline     # → results/offline.md, offline.json
uv run python benchmarks/jude-02a/evaluate.py cost        # → results/cost.md
uv run python benchmarks/jude-02a/evaluate.py review      # → results/review-sample/
uv run python benchmarks/jude-02a/evaluate.py all --check # fail if any committed result is stale
uv run pytest tests/unit/jude_eval
```

All of these are deterministic and need no network. `evaluate.py live` and
`runpod/loadtest.py` are the only commands that would contact anything, and
both refuse to start by default.

## What changed outside `benchmarks/` and `docs/`

One additive change to Jude-01's code:
`OpenAICompatibleProvider` accepts an optional `extra_body` merged into each
request (used to ask OpenRouter for providers that keep no data). It cannot
override `model`, `messages`, `max_tokens` or `stream`. Nothing else in the API,
the mobile app, the admin app or the migrations was touched; `openapi.json` is
unchanged and no route is registered.
