# Jude-02A cost comparison

Prices: **published**, read 2026-11-26 (`config/published_prices.json`). Workloads and every GPU performance figure: **assumptions** (`config/cost_scenarios.json`). **Nothing here is measured.**

GPU used for the self-hosted rows: A40 (48 GB) — dedicated 0.59 USD/h (Secure Cloud), serverless 1.22 USD/h.

## Pilot — 200 learners, 5 questions a day

1,000 requests/day over 10 h, peak x3, 1,800 input + 250 output tokens, 5% retries — all assumptions.

| Option | GPU performance assumed | Monthly USD | USD / request | GPUs | Utilisation | Requests that wait for a cold start |
|---|---|---:|---:|---:|---:|---:|
| OpenRouter · mistralai/mistral-small-3.2-24b-instruct | n/a | 6.15 | 0.00020 | — | — | — |
| OpenRouter · anthropic/claude-haiku-5.5 | n/a | 10.14 | 0.00034 | — | — | — |
| OpenRouter · google/gemma-4-31b-it | n/a | 15.29 | 0.00051 | — | — | — |
| OpenRouter · openai/gpt-5.4-mini | n/a | 82.25 | 0.00274 | — | — | — |
| Runpod serverless · A40 (idle timeout 5 s) | pessimistic | 316.98 | 0.01057 | — | 12% | 87% |
| Runpod serverless · A40 · 1 always-on (idle timeout 5 s) | pessimistic | 882.60 | 0.02942 | — | 12% | 0% |
| Runpod dedicated · 1x A40 (24 h/day provisioned) | pessimistic | 430.80 | 0.01436 | 1 | 5% | — |
| Runpod dedicated · 1x A40 (12 h/day provisioned) | pessimistic | 218.40 | 0.00728 | 1 | 10% | — |
| Runpod serverless · A40 (idle timeout 5 s) | middle | 277.97 | 0.00927 | — | 2% | 88% |
| Runpod serverless · A40 · 1 always-on (idle timeout 5 s) | middle | 882.60 | 0.02942 | — | 2% | 0% |
| Runpod dedicated · 1x A40 (24 h/day provisioned) | middle | 430.80 | 0.01436 | 1 | 1% | — |
| Runpod dedicated · 1x A40 (12 h/day provisioned) | middle | 218.40 | 0.00728 | 1 | 2% | — |
| Runpod serverless · A40 (idle timeout 5 s) | optimistic | 220.34 | 0.00734 | — | 0% | 86% |
| Runpod serverless · A40 · 1 always-on (idle timeout 5 s) | optimistic | 882.60 | 0.02942 | — | 0% | 0% |
| Runpod dedicated · 1x A40 (24 h/day provisioned) | optimistic | 430.80 | 0.01436 | 1 | 0% | — |
| Runpod dedicated · 1x A40 (12 h/day provisioned) | optimistic | 218.40 | 0.00728 | 1 | 0% | — |

## Growth — 5,000 learners, 4 questions a day

20,000 requests/day over 12 h, peak x3, 1,800 input + 250 output tokens, 5% retries — all assumptions.

| Option | GPU performance assumed | Monthly USD | USD / request | GPUs | Utilisation | Requests that wait for a cold start |
|---|---|---:|---:|---:|---:|---:|
| OpenRouter · mistralai/mistral-small-3.2-24b-instruct | n/a | 122.96 | 0.00020 | — | — | — |
| OpenRouter · anthropic/claude-haiku-5.5 | n/a | 202.72 | 0.00034 | — | — | — |
| OpenRouter · google/gemma-4-31b-it | n/a | 305.74 | 0.00051 | — | — | — |
| OpenRouter · openai/gpt-5.4-mini | n/a | 1,645.01 | 0.00274 | — | — | — |
| Runpod serverless · A40 (idle timeout 5 s) | pessimistic | 1,287.14 | 0.00215 | — | 68% | 0% |
| Runpod serverless · A40 · 1 always-on (idle timeout 5 s) | pessimistic | 1,726.34 | 0.00288 | — | 68% | 0% |
| Runpod dedicated · 7x A40 (24 h/day provisioned) | pessimistic | 2,979.60 | 0.00497 | 7 | 15% | — |
| Runpod dedicated · 7x A40 (14 h/day provisioned) | pessimistic | 1,740.60 | 0.00290 | 7 | 25% | — |
| Runpod serverless · A40 (idle timeout 5 s) | middle | 442.72 | 0.00074 | — | 34% | 7% |
| Runpod serverless · A40 · 1 always-on (idle timeout 5 s) | middle | 882.60 | 0.00147 | — | 34% | 0% |
| Runpod dedicated · 2x A40 (24 h/day provisioned) | middle | 855.60 | 0.00143 | 2 | 9% | — |
| Runpod dedicated · 2x A40 (14 h/day provisioned) | middle | 501.60 | 0.00084 | 2 | 15% | — |
| Runpod serverless · A40 (idle timeout 5 s) | optimistic | 440.18 | 0.00073 | — | 8% | 14% |
| Runpod serverless · A40 · 1 always-on (idle timeout 5 s) | optimistic | 882.60 | 0.00147 | — | 8% | 0% |
| Runpod dedicated · 1x A40 (24 h/day provisioned) | optimistic | 430.80 | 0.00072 | 1 | 4% | — |
| Runpod dedicated · 1x A40 (14 h/day provisioned) | optimistic | 253.80 | 0.00042 | 1 | 7% | — |

## Scale — 30,000 learners, 3 questions a day

90,000 requests/day over 14 h, peak x4, 1,800 input + 250 output tokens, 5% retries — all assumptions.

| Option | GPU performance assumed | Monthly USD | USD / request | GPUs | Utilisation | Requests that wait for a cold start |
|---|---|---:|---:|---:|---:|---:|
| OpenRouter · mistralai/mistral-small-3.2-24b-instruct | n/a | 553.32 | 0.00020 | — | — | — |
| OpenRouter · anthropic/claude-haiku-5.5 | n/a | 912.23 | 0.00034 | — | — | — |
| OpenRouter · google/gemma-4-31b-it | n/a | 1,375.83 | 0.00051 | — | — | — |
| OpenRouter · openai/gpt-5.4-mini | n/a | 7,402.54 | 0.00274 | — | — | — |
| Runpod serverless · A40 (idle timeout 5 s) | pessimistic | 5,777.41 | 0.00214 | — | 66% | 0% |
| Runpod serverless · A40 · 1 always-on (idle timeout 5 s) | pessimistic | 6,143.41 | 0.00228 | — | 66% | 0% |
| Runpod dedicated · 32x A40 (24 h/day provisioned) | pessimistic | 13,599.60 | 0.00504 | 32 | 14% | — |
| Runpod dedicated · 32x A40 (16 h/day provisioned) | pessimistic | 9,068.40 | 0.00336 | 32 | 22% | — |
| Runpod serverless · A40 (idle timeout 5 s) | middle | 966.40 | 0.00036 | — | 66% | 0% |
| Runpod serverless · A40 · 1 always-on (idle timeout 5 s) | middle | 1,332.40 | 0.00049 | — | 66% | 0% |
| Runpod dedicated · 6x A40 (24 h/day provisioned) | middle | 2,554.80 | 0.00095 | 6 | 13% | — |
| Runpod dedicated · 6x A40 (16 h/day provisioned) | middle | 1,705.20 | 0.00063 | 6 | 19% | — |
| Runpod serverless · A40 (idle timeout 5 s) | optimistic | 516.60 | 0.00019 | — | 30% | 0% |
| Runpod serverless · A40 · 1 always-on (idle timeout 5 s) | optimistic | 882.60 | 0.00033 | — | 30% | 0% |
| Runpod dedicated · 2x A40 (24 h/day provisioned) | optimistic | 855.60 | 0.00032 | 2 | 9% | — |
| Runpod dedicated · 2x A40 (16 h/day provisioned) | optimistic | 572.40 | 0.00021 | 2 | 13% | — |

## Break-even: one dedicated GPU (24 h) versus paying per token

Daily requests above which one always-on GPU costs less than OpenRouter, using the token sizes of the first workload. A dash means one GPU cannot carry that many at peak under that performance assumption.

| OpenRouter model | pessimistic | middle | optimistic |
|---|---:|---:|---:|
| mistralai/mistral-small-3.2-24b-instruct | — | — | 69,096 |
| anthropic/claude-haiku-5.5 | — | — | 41,910 |
| google/gemma-4-31b-it | — | — | 27,788 |
| openai/gpt-5.4-mini | — | 5,165 | 5,165 |

## Performance assumptions used (unmeasured)

| Label | Time to first token (s) | Output tokens/s per stream | Concurrent streams | Cold start (s) |
|---|---:|---:|---:|---:|
| pessimistic | 1 | 15 | 4 | 180 |
| middle | 0.5 | 30 | 12 | 90 |
| optimistic | 0.3 | 50 | 32 | 40 |
