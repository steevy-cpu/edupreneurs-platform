# 6. Cost comparison

`evaluate.py cost` → `benchmarks/jude-02a/results/cost.md`. Change the inputs
in `benchmarks/jude-02a/config/` and re-run; formulas are in
`jude_eval/costmodel.py` and are unit-tested at their limits.

## Three kinds of number — never mix them

| Basis | What | Where |
|---|---|---|
| **Published** | OpenRouter per-token prices and its 5.5% credit-purchase fee; Runpod hourly GPU and storage prices | `config/published_prices.json`, each with its source URL, read 2026-11-26 |
| **Assumption** | Requests per day, tokens per request, hours of use, peak factor, retry overhead; **every GPU performance figure** | `config/cost_scenarios.json` |
| **Measured** | — | **Nothing.** No model and no GPU was run |

## Inputs

**Workloads (assumptions)** — 1,800 input and 250 output tokens per request
(Jude-01's conservative estimator averages about 1,550 in and 135 out on the
benchmark), 5% extra calls for retries:

| Scenario | Requests/day | Over | Peak factor |
|---|---:|---|---:|
| Pilot — 200 learners × 5 questions | 1,000 | 10 h | ×3 |
| Growth — 5,000 × 4 | 20,000 | 12 h | ×3 |
| Scale — 30,000 × 3 | 90,000 | 14 h | ×4 |

**GPU performance (assumptions, three guesses to show sensitivity)** — for one A40 48 GB:

| | Time to first token | Tokens/s per stream | Concurrent streams | Cold start |
|---|---:|---:|---:|---:|
| Pessimistic | 1.0 s | 15 | 4 | 180 s |
| Middle | 0.5 s | 30 | 12 | 90 s |
| Optimistic | 0.3 s | 50 | 32 | 40 s |

**Published prices used:** A40 at 0.59 USD/h dedicated (Secure Cloud) and
1.22 USD/h serverless; four OpenRouter models from 0.075/0.20 to 0.75/4.50 USD
per million input/output tokens.

## Results — monthly USD

| Option | Pilot | Growth | Scale |
|---|---:|---:|---:|
| OpenRouter · Mistral Small 3.2 | 6 | 123 | 553 |
| OpenRouter · Claude Haiku 5.5 | 10 | 203 | 912 |
| OpenRouter · Gemma 4 31B | 15 | 306 | 1,376 |
| OpenRouter · GPT-5.4 mini | 82 | 1,645 | 7,403 |
| Runpod serverless, scale to zero — pessimistic / middle / optimistic | 317 / 278 / 220 | 1,287 / 443 / 440 | 5,777 / 966 / 517 |
| Runpod serverless, 1 always-on worker | 883 / 883 / 883 | 1,726 / 883 / 883 | 6,143 / 1,332 / 883 |
| Runpod dedicated, 24 h — pessimistic / middle / optimistic | 431 / 431 / 431 (1 GPU) | 2,980 (7) / 856 (2) / 431 (1) | 13,600 (32) / 2,555 (6) / 856 (2) |
| Runpod dedicated, school hours + 2 h | 218 / 218 / 218 | 1,741 / 502 / 254 | 9,068 / 1,705 / 572 |

(Numbers of GPUs in brackets. Full table with cost per request, utilisation and
cold-start share in `results/cost.md`.)

**Break-even — daily requests above which one always-on A40 costs less than paying per token:**

| OpenRouter model | Pessimistic | Middle | Optimistic |
|---|---:|---:|---:|
| Mistral Small 3.2 | never on one GPU | never on one GPU | 69,096 |
| Claude Haiku 5.5 | never | never | 41,910 |
| Gemma 4 31B | never | never | 27,788 |
| GPT-5.4 mini | never | 5,165 | 5,165 |

"Never on one GPU" means the GPU would be saturated at peak before reaching the
volume at which it pays for itself.

## What this supports

1. **OpenRouter for the pilot is the right call on cost, by a wide margin.**
   6–82 USD a month against at least 218 USD for any GPU. The difference between
   the cheapest and dearest per-token model at pilot size is 76 USD a month —
   so **choose the pilot model on quality, not price.**
2. **At pilot traffic a GPU would sit 98–99% idle** (utilisation 1–2% under the
   middle assumption). The cost is the idle time, not the inference.
3. **Serverless does not rescue low traffic.** With questions minutes apart, the
   model predicts 86–88% of requests would wait for a cold start, and removing
   them with an always-on worker (883 USD) costs twice a dedicated pod (431 USD),
   because the serverless hourly price is about double.
4. **Self-hosting can win at scale — if the GPU performs.** At 90,000 requests a
   day the answer swings from 517 USD (optimistic) to 13,600 USD (pessimistic)
   for the same hardware price. **The decision depends almost entirely on
   numbers nobody has measured**, which is the case for running the experiment
   in [05](05-runpod-experiment.md) before any commitment.
5. **Cost is not the only reason to self-host.** Keeping children's text off
   third-party APIs, or serving a model adapted to Haitian Creole, could justify
   a GPU that costs more. Those are owner decisions this model does not price.

## What the model leaves out or gets wrong

- **Queueing approximations.** Poisson arrivals, a fixed service time, perfect
  spreading over the day apart from one peak factor. Real school traffic is
  burstier (a class starts an exercise together).
- **Serverless packing** is a single assumed efficiency (70%); scaling delay,
  queue delay and per-worker idle tails at multi-worker load are not modelled.
- **No always-on discount** is applied, because Runpod does not publish one.
- **One GPU type.** Other cards change both price and performance.
- **Not priced:** engineering and on-call time to run a GPU service (the largest
  real cost of self-hosting), the Render backend, monitoring, a second GPU for
  redundancy, data egress, the safety classifier if it is a second model.
- **OpenRouter prices change**, differ by upstream provider, and the
  no-data-retention routes Jude would require may cost more than the listed
  price or not exist for a given model. Check per model.
- **Token counts are assumed.** A model that writes longer answers, or needs
  more retries, costs proportionally more; output tokens dominate for some models.
- **Caching discounts** (prompt caching on some providers, prefix caching on
  vLLM) are ignored; they would lower both sides.
