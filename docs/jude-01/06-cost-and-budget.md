# 6. Cost and budget model

> Every price and limit in the code is a **synthetic placeholder** so the
> accounting can be tested. Real prices, limits and the provider are owner decisions.

## Units

- Money: integer **micro-USD** (1 USD = 1 000 000). No floating point anywhere.
- Price: micro-USD per million tokens, separately for input and output.
- Cost of a call: `ceil(input × price_in / 1e6) + ceil(output × price_out / 1e6)`
  — rounded up per direction, so a real cost is never recorded as zero.

## Prices are configurable and versioned

`ModelPrice(price_version, model, input_micro_per_mtok, output_micro_per_mtok)`.
A price change is a **new `price_version`**, never an edit: the SQL table is
append-only (a trigger refuses `UPDATE` and `DELETE`, tested), and every ledger
row records the `price_version` it was costed with, so past spend can always be
re-derived. Configuration refuses to start with a model that has no price, or
two active prices for one model. No model name appears in business logic; the
only literal is the mock's own id.

## Controls

| Control | Setting (`EDU_TUTOR_…`) | Enforced where |
|---|---|---|
| Per-request output limit | `MAX_OUTPUT_TOKENS` | sent to the provider on every call |
| Per-request input bound | message ≤ 600 chars; `MAX_CONTEXT_CHARS` | request contract; retrieval |
| Calls per request | `MAX_ATTEMPTS` (+1 if a fallback is configured) | gateway |
| Per-learner daily number of answers | `LEARNER_DAILY_REQUESTS` | ledger, at reservation |
| Per-learner daily cost | `LEARNER_DAILY_MICRO` | ledger, at reservation |
| Per-learner monthly cost | `LEARNER_MONTHLY_MICRO` | ledger, at reservation |
| Global monthly ceiling | `GLOBAL_MONTHLY_MICRO` | ledger, at reservation |
| Concurrency per learner / overall | `MAX_CONCURRENT_PER_LEARNER`, `MAX_CONCURRENT_GLOBAL` | ledger, at reservation |
| Kill switch | `PAUSED` (static) and the ledger's `paused` flag (runtime, audited) | before anything else and again inside the reservation |
| Reservation lifetime | `RESERVATION_TTL_S` | ledger; must exceed the longest possible request, checked at start-up |

Days and months roll over in `America/Port-au-Prince`, not UTC, so a learner's
allowance resets at their midnight.

## Reserve → call → settle

1. **Estimate the worst case.** Input tokens are over-estimated (one token per
   three UTF-8 bytes), output is the cap, and both are multiplied by every call
   the gateway may make, at each route's price.
2. **Reserve atomically.** The reservation succeeds only if, for the learner's
   day, the learner's month and the global month,
   `spent + reserved + estimate ≤ limit`. Money held by requests still in flight
   counts, so parallel requests cannot each see "room for one more". If it is
   refused, **no provider call happens**.
3. **Call** the provider (bounded).
4. **Settle exactly once** with the real cost: provider-reported tokens × price,
   summed over attempts. An attempt whose cost is unknown (timeout, connection
   lost, cancelled mid-call, adapter crash) is charged at its worst case. If
   provably nothing was spent, the hold is released.
5. **Expire.** A reservation nobody settled (crashed worker) is charged in full
   when its lifetime ends — by the learner's next request or by a sweeper job.

Invariant, for every counter, at all times: **`spent + reserved ≤ limit`**, and
recorded spend ≥ real spend.

## Idempotency

The client generates `idempotency_key` per question. `(learner, key)` is unique
in the ledger:

| State of that key | A repeat gets |
|---|---|
| In flight | `tutor_request_in_progress` (409) |
| Settled or expired | `tutor_duplicate_request` (409) — not charged again, no second provider call |
| Released (nothing was spent) | accepted as a fresh attempt |

Settlement is idempotent: settling or releasing twice changes nothing.

## Atomicity: what is and is not proven

| Claim | Evidence |
|---|---|
| The accounting rules are right | `tests/unit/tutor/test_budget.py` on the in-memory store. **Single process; proves the rules, not database atomicity.** |
| The global ceiling holds under real concurrent transactions | `tests/tutor_pg`: 60 learners reserve simultaneously against a ceiling that fits 11 → exactly 11 admitted, 49 refused, `reserved = 11 × estimate`. Passed on PostgreSQL 16 locally and on the project's PostgreSQL 17 in CI. |
| Books stay exact under interleaved reserve/settle | 120 concurrent workers over 15 learners: global spent = sum of ledger rows; every learner counter equals its rows; nothing left reserved |
| One request sent 25 times at once is admitted once | 1 reserved, 24 `in_progress` |
| Per-learner concurrency under a burst | 20 simultaneous → exactly the limit admitted |
| Through the whole service, with a slow provider | 30 learners: provider calls = admitted; refused requests never reach the provider; final spend ≤ ceiling |

How PostgreSQL provides it (`sql/tutor_schema.sql`): each of `reserve`,
`settle`, `release` is one transaction that takes row locks on the counters in
one fixed order — global month, learner month, learner day — before reading or
writing. The functions require `READ COMMITTED` and refuse to run otherwise
(tested), because the check relies on seeing what the previous lock holder
committed.

**Not proven:** behaviour at production scale. Every reservation briefly locks
the single global counter row, which serialises reservations. That is a
deliberate trade for a simple, obviously correct ceiling at this project's
scale (a reservation is a few milliseconds); sharding the global counter is a
later optimisation if measurement asks for it. No load test was run.

## No silent expensive switch

- A fallback route exists only if `FALLBACK_MODEL` is set.
- A fallback that costs more than the primary is refused at wiring time unless
  `ALLOW_COSTLIER_FALLBACK=true` — a named, explicit decision.
- The fallback gets one call, and that call is inside the reserved worst case.
- Every attempt is recorded with its provider, model and price version.

## What a request costs (synthetic numbers only)

With the placeholder price of the mock model (0.50 USD/Mtok in, 1.50 USD/Mtok
out) a demo answer costs about 0.001 USD (≈ 1 500 input + 150 output tokens) and
reserves about 0.003 USD while in flight. These numbers illustrate the
arithmetic; they say nothing about any real model's price.
