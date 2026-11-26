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
| Kill switch | `PAUSED` (static) and the ledger's `paused` flag (runtime, audited) | before anything else, inside the reservation, and before **every** provider call |
| Reservation bound framing | `INPUT_FRAMING_TOKENS_PER_MESSAGE`, `INPUT_FRAMING_TOKENS_PER_REQUEST` | sizing of every hold |
| Provider-side limit (attested) | `PROVIDER_SIDE_MONTHLY_LIMIT_MICRO` | wiring: no live provider without it |
| Reservation lifetime | `RESERVATION_TTL_S` | ledger; must exceed the longest possible request, checked at start-up |

Days and months roll over in `America/Port-au-Prince`, not UTC, so a learner's
allowance resets at their midnight.

## Reserve → authorise → call → settle

> Corrected after the independent review (J-02, J-03, J-04, J-05). The earlier
> text claimed a worst case from "one token per three bytes"; that was an
> average, not a bound. See [12](12-security-corrections.md).

1. **Size the hold from an explicit bound** (`metering.py`): input ≤ UTF-8 bytes
   of the message contents + a framing allowance per message and per call;
   output ≤ `max_tokens`; multiplied by every call the gateway may make, each at
   its own route's price. This is an **assumption** about the provider's meter.
   It is checked against every reported usage; it is not a guarantee.
2. **Reserve atomically.** The reservation succeeds only if, for the learner's
   day, the learner's month and the global month,
   `spent + reserved + estimate ≤ limit`. Money held by requests still in flight
   counts, so parallel requests cannot each see "room for one more". If it is
   refused, **no provider call happens**.
3. **Authorise, then call**, for every call: the kill switch and the hold are
   re-checked and the dispatch is counted on the hold.
4. **Settle exactly once** with the real cost: provider-reported tokens × price,
   summed over attempts and recorded per attempt. An attempt whose cost is
   unknown (timeout, connection lost, cancelled mid-call, adapter crash,
   unreadable metering) is charged at the bound. The hold is released only if
   no call that could be billed was made. A reported usage above the bound is
   recorded in full, kept as `overage_micro`, audited, and pauses the tutor.
5. **Expire.** A reservation nobody settled (crashed worker) is charged in full
   when its lifetime ends — by the learner's next request or by a sweeper job.

Invariant, for every counter, under any concurrency: **`spent + reserved ≤
limit`** — as long as no provider bills above the bound. If one does, the
ledger shows the excess instead of hiding it, and stops dispatch. **The only
hard dollar ceiling for a live provider is a limit set on the provider's
side**; a live provider cannot be wired without the owner stating it.

## Idempotency

The client generates `idempotency_key` per question. A key has at most one
*live* admission; every admission is its own row with its own reservation id,
which is never reused:

| State of that key | A repeat gets |
|---|---|
| In flight | `tutor_request_in_progress` (409) |
| Settled or expired | `tutor_duplicate_request` (409) — not charged again, no second provider call |
| Released (no billable call was made) | accepted as a **new** reservation; the released row stays as history |

Settlement is idempotent: settling or releasing twice changes nothing, and a
late call for an earlier admission of the same key cannot touch a newer one.

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
`authorize_dispatch`, `settle`, `release` is one transaction that takes row
locks in one fixed order — policy row, global month, learner month, learner
day, request row — before reading or writing. The functions require `READ COMMITTED` and refuse to run otherwise
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
- The fallback gets one call, and that call is inside the hold, at its own price.
- The fallback is authorised like any other call: none starts after a pause.
- Every attempt is recorded with its provider, model and price version.

## What a request costs (synthetic numbers only)

With the placeholder price of the mock model (0.50 USD/Mtok in, 1.50 USD/Mtok
out) a demo answer costs about 0.001 USD (≈ 1 750 input + 235 output tokens) and
holds about 0.007 USD while in flight (two permitted calls at the byte bound). These numbers illustrate the
arithmetic; they say nothing about any real model's price.
