# 12. Security corrections (J-01 … J-09)

Corrections to Jude-01 after the independent security review in
[PR #30](https://github.com/steevy-cpu/edupreneurs-platform/pull/30)
(`docs/reviews/jude-01/SECURITY_QA.md` on `qa/jude-01-security`, commit `ddd51db`).

| | |
|---|---|
| Corrected implementation | PR #28 at `b11b780fff7820dccabb75bacfac383505a1fe1c` |
| Correction branch | `fix/jude-01-security-corrections`, stacked on #28 |
| Independent tests | The three `test_independent_*` files from PR #30, **byte-identical** (`git diff origin/qa/jude-01-security -- <the three files>` is empty) |
| Not changed | `main.py`, `config.py`, `deps.py`, mobile, admin-web, `supabase/migrations`, secrets, PR #28's branch, PR #30's branch, PR #35's branch |

Jude is still unregistered, disabled by default, on the mock provider,
deny-by-default on consent and entitlement, with no production migration and
no live learner. No model, no OpenRouter traffic, no Runpod, no spend.

## Results

| Suite | Before (`b11b780`) | After |
|---|---:|---:|
| Independent unit / privacy / provider cases (11) | 1 passed, 10 failed | **11 passed** |
| Independent PostgreSQL accounting cases (6) | 3 passed, 3 failed | **6 passed** |
| Independent signed-session and withdrawal cases (2, need the Auth stack) | 2 passed | see CI results below |
| Existing Jude-01 unit + PostgreSQL tests | 415 passed | 415 kept; 4 rewritten because they asserted the defect (listed below) |
| New security regressions, unit (`test_security_corrections.py`) | — | 192 passed, 12 expected failures that pin documented limits |
| New security regressions, real PostgreSQL (`test_security_corrections_postgres.py`) | — | 33 passed |
| `ruff check`, `ruff format --check`, `mypy` (strict), OpenAPI and contract freshness | clean | clean |

"Before" was reproduced locally on the pinned commit with the reviewer's files
added and nothing else changed: 13 failed, 4 passed, the same 13 the review lists.

The four existing tests that changed meaning, and why:

| Test | Was asserting | Now asserts |
|---|---|---|
| `test_budget_postgres.py::test_released_request_costs_nothing_and_may_retry_with_the_same_key` | `again.id == reservation.id` — the J-04 defect itself | a new id, and the released row kept |
| `test_service.py::test_a_request_that_failed_before_spending_may_be_retried_with_the_same_key` | one ledger record after a retry | two: the released admission and the settled one |
| `test_privacy.py::test_the_ledger_has_no_field_that_could_hold_conversation_text` | a fixed field list | the list plus the new counters, and the per-call record's fields |
| `test_budget_postgres.py::test_no_column_can_hold_conversation_text` | five tables | six, and that every text column of the new table and `pause_reason` refuses free text |

## Root causes and corrections

### J-01 · HIGH · learner requests retained in memory

**Root cause.** `DeterministicMockProvider.calls` was a list that every
`complete()` appended the whole `ModelRequest` to. The class was written as a
test spy and then also made the provider the factory builds by default, so a
long-lived service kept every prompt (student text and lesson context) for the
life of the process.

**Correction.**
- The mock keeps one integer, `call_count`. `calls` is now `range(call_count)`:
  `len(provider.calls)` still works, and there is nothing in it but indices.
- Request recording moved out of the application package into an explicit test
  spy, `tests/unit/tutor/spies.py::RecordingMockProvider`. The test harness
  injects it; nothing in `services/` can construct it.
- `TutorService.answer` re-raised its generic error inside the `except` block,
  so the error handed to the caller still referenced the original exception and,
  through its traceback, frames holding the prompt. It is now raised after the
  handler, with no chained exception.
- The gateway drops a crashed validator's exception instead of propagating it
  (its message can quote the model's answer).

**Reviewed and found clean:** the retriever, prompt template, gateway and usage
stores keep no per-request state; the attempt list is owned by the request and
holds codes, counts and prices; nothing is cached by message text.

**Evidence.** `test_factory_mock_drops_completed_request` (independent).
`test_no_request_outlives_its_call_whatever_the_outcome` holds only weak
references to each request and each message and shows they are dead after
garbage collection for seven outcomes: an answer, rejected output, provider outage, rate
limit, auth error, timeout, leaked-prompt output. A second test covers a
validator crash and a client cancellation.

### J-02 · HIGH · the hold could be smaller than the bill

**Root cause.** The hold was sized with `estimate_tokens` = UTF-8 bytes ÷ 3 per
message. That is an *average* for French prose, not an upper bound, and it
ignored chat framing. The mock billed with the same function, so no test could
see a hold that was too small. The reviewer's mock billed one extra token:
1,736 micro-USD settled against a ceiling of 1,735.

**Correction — an explicit bound, and what it is not.**

`edu_api/tutor/metering.py` states the contract:

```
input tokens  ≤  UTF-8 bytes of every message's content
                 + tokens_per_message × number of messages   (default 16)
                 + tokens_per_request                        (default 64)
output tokens ≤  the max_tokens sent with the request
hold          =  Σ over every permitted call (each primary attempt, plus the
                 fallback) of  price_of_that_route(input bound, output bound)
```

One token per byte holds for tokenizers in which every token covers at least
one byte of text (byte-level BPE; SentencePiece with or without byte fallback),
so the content term does not depend on which model is used. The two framing
allowances are configuration and must cover the chat template of every
configured model. For the standard test question the hold went from 3,236 to
6,800 micro-USD at the placeholder price; the same request then settles at
1,226.

**This is an assumption about someone else's meter, not a proof**, and the code
and docs no longer say otherwise. A provider can add text of its own, count
differently, or bill above `max_tokens`. So:

1. **Every reported usage is checked against the bound.** A call that reports
   more is a *bound violation*.
2. **The real figure is recorded, never capped.** `spent_micro` is what the
   provider reported × price, even above the hold; the difference is kept in
   `overage_micro`.
3. **Dispatch stops.** No retry and no fallback follow such a call; settlement
   turns the kill switch on with `pause_reason = 'cost_bound_exceeded'`, so no
   request anywhere is dispatched until staff unpause.
4. **An audit row is written** (`tutor.cost_bound.exceeded`) with amounts, model
   and price version — no learner id, no text.
5. **A live provider cannot be wired without a provider-side limit.** The
   factory refuses any live-capable provider unless
   `EDU_TUTOR_PROVIDER_SIDE_MONTHLY_LIMIT_MICRO` is set: the owner's statement
   that a spending limit exists on the provider's side for that key. That limit
   is the only hard dollar ceiling for live use. The server cannot verify it.

So the honest wording of the guarantee is: *the ledger admits no request whose
assumed worst case does not fit, under any concurrency; if a provider bills
above the assumption, the ledger says so, in full, and stops.* It is an
admission control, not a cap on a third party's invoice.

**Unknown usage.** A call that was dispatched and returned no usable figures
(timeout, connection lost, cancellation, adapter crash, malformed metering,
unexpected 2xx) is charged at the bound for that call and counted in
`unmetered_attempts`. This is the documented conservative policy; it can
over-charge the learner's allowance and cannot under-record.

**Per-call ledger.** New table `tutor.usage_attempts`: one row per call that
may have been billed, with its own model, price version, tokens, cost and
whether it was metered. A request that used two differently priced routes can
be re-costed (the review noted the request row alone could not).

**Evidence (PostgreSQL).** The independent
`test_normal_provider_framing_fits_the_admitted_ceiling` (admitted 5,300 at the
reviewer's tariff; the framed invoice is 1,747). New: framing of 0/1/7/40/90
tokens against a ceiling of exactly one hold; prompts of four lengths in
multi-byte text; a provider billing far above the bound (recorded in full,
`overage_micro` set, paused, audited, next learner refused); 24 simultaneous
learners against a ceiling that fits four (exactly four held while all are in
flight, four provider calls, final spend ≤ ceiling); one learner sending twelve
requests at once against a per-learner ceiling of two holds; unknown usage;
re-costing two price versions. Unit: rounding boundaries, bound arithmetic,
exact-limit and one-below-limit admission, costlier fallback refused.

### J-03 · HIGH · a completed provider call recorded as free

**Root cause.** The gateway appended an attempt to the caller's list only
*after* the caller's parser returned. A parser exception other than
`OutputRejected` skipped the append, so the service saw "no attempt, nothing
spent", released the hold, and the same key could buy a second call.

**Correction.** One call is now five separate steps, each written to the
attempt record as it happens: the attempt exists before permission is asked;
*dispatched*; *completed* (usage recorded **before** the text is looked at);
*validated*; and settlement, which reads the list. Consequences:

- A fault in local validation leaves a completed, metered attempt. It is
  settled at its reported usage, the request ends (calling the provider again
  cannot repair a local fault), and the key is used up.
- A hold is released only when **no** attempt could have been billed: nothing
  was dispatched, or every dispatched call was refused by the provider before
  doing work (429, 401/403, 400, a redirect).
- The decision is no longer "spent == 0". A completed call at a zero price is
  settled, not released.
- **Cross-check in the database.** `authorize_dispatch` counts each permitted
  call on the hold. `release` must state how many dispatched calls the provider
  refused; if that differs from the count, a call is unaccounted for, nothing
  is released (`dispatch_mismatch`, audited) and the hold expires at its full
  amount. A regression to the original bug would now be refused by the ledger.
- A request cancelled *while being admitted* no longer leaves an orphan hold to
  expire at full price: the admission is completed in the background and
  released.

**Evidence.** `test_completed_provider_call_remains_chargeable_if_local_validation_fails`
(independent); the same on PostgreSQL with three attempts and a fallback
configured (one call, settled, per-call row `validation_failed`, retry of the
key refused); `test_every_outcome_is_finalised_exactly_once` counts finalizer
calls for six outcomes; cancellation mid-call and mid-admission; the
independent cancellation-during-settlement case.

### J-04 · HIGH · a reservation id reused by a later attempt

**Root cause.** `tutor.usage_requests` had `UNIQUE (learner_id, request_key)`,
and re-admitting a released key *updated that row in place*. The row id — which
is the reservation id — therefore identified both the old and the new attempt,
and a late settlement for the old one would have landed on the new one.

**Correction.** Three identities are now distinct:

| Identity | What it is |
|---|---|
| `request_key` | The client's logical idempotency key |
| reservation `id` | One **admission**. Always a new row, never reused |
| status of that row | `reserved → settled / released / expired`, one way only |

The unique constraint became a partial unique index: at most one row per key
that is not `released`. Released rows stay as history. `settle`, `release` and
`authorize_dispatch` name the row id and the calling learner, so a stale call
for an old admission finds a finished row and changes nothing
(`already_finished`). A stale claim of a charge against a released admission is
kept as an audit row. The Python store now returns the SQL outcome to the
service instead of discarding it.

One deliberate exception to "finished rows never change": a late settlement
for an **expired** admission whose real amount is *higher* than the full hold
already charged adds the difference (`late_overage`, paused, audited). A lower
late amount leaves the conservative charge in place.

**Evidence (PostgreSQL).** `test_each_admitted_attempt_has_a_fresh_lease`
(independent); late settlement, late release and late authorisation against a
newer admission of the same key; 15 rounds of stale finalizers racing the new
admission concurrently; 30 simultaneous duplicates (one admitted, 29
`in_progress`, and a direct second live row refused by the index); expiry
followed by settlement; cancellation; **account erasure during outstanding
work** (the retry is not dispatched, no row or counter is recreated, the hold
stays as anonymous spend, the unattributed late figure is audited); a forged
reservation from another learner.

### J-05 · MEDIUM · the kill switch during retry backoff

**Root cause.** The pause was read once, in `reserve`. Retries and the fallback
ran without looking again. `reserve` also read the policy row without a lock,
before taking its counter locks, so a queued admission could act on an older
snapshot.

**The boundary, exactly.** `tutor.set_paused` updates the single policy row.
`tutor.reserve` and the new `tutor.authorize_dispatch` read that row
`FOR SHARE`, and `authorize_dispatch` runs before **every** provider call
(first call, each retry, the fallback). Therefore each admission and each
dispatch authorisation is strictly before or strictly after a pause:

- none is granted by a transaction that reads the policy after the pause
  committed;
- one that began reading while a pause was in progress waits, then is refused;
- a pause waits for authorisations already reading the row.

What the boundary does **not** cover: a call authorised just before the pause
may still reach the provider a moment after it. It is not recalled; it is
settled normally. The static `EDU_TUTOR_PAUSED` setting is read at start-up
only.

**Evidence (PostgreSQL).** `test_pause_stops_new_provider_attempts_during_backoff`
(independent). A pause held open in an uncommitted transaction: the
authorisation and a new admission both block, then both are refused when it
commits, and `dispatches` stays 0; rolled back instead, the authorisation is
granted. Forty holds authorised around a pause: everything after the commit is
refused and the granted count equals the dispatches recorded. The same
mechanism for a limit change (the review's source observation). A call
dispatched before the pause still settles; a pause during backoff with a
fallback configured starts no fallback and settles the first call.

### J-06 · MEDIUM · provider authorisation and destination

**Root cause.** The live-authorisation check lived in `build_provider`, which
is skipped when a provider is injected. The https check looked at the
configured URL string, not at the client actually used. The adapter treated
any status below 400 as success.

**Correction.**
- One gate, `require_live_authorization`, applied to the configured provider
  and to every injected provider, primary and fallback. A provider that can
  leave the machine declares `live_capable = True` (the adapter does); it is
  refused without the owner's authorisation flag, a stated provider-side limit
  (J-02), and an origin equal to the approved `provider_base_url`.
- The adapter is bound at construction to one https origin (scheme, host,
  port; no credentials in the URL). An injected client pointing elsewhere, over
  http, on another port, or with `follow_redirects` on is refused. The request
  URL is built from that origin; the completion path cannot leave it.
- Redirects are never followed. 3xx is `ProviderRedirectError` (not billed, not
  retried). Only **200** is a completion; any other 2xx is "unexpected status,
  cost unknown". A response that did not come from the approved origin is refused.
- The live provider stays disabled by default.

**Limit, stated plainly.** `live_capable` is a declaration. An arbitrary object
that opens connections without declaring it is not detected by the factory;
wiring is trusted, reviewed code, and both test suites refuse every socket.

### J-07 · MEDIUM · token usage validation

**Root cause.** `int(usage["prompt_tokens"])` turns `True` into 1 and `1.5` into 1.

**Correction.** `parse_token_count` accepts only a real `int` between 0 and
10,000,000. Booleans, fractions (including `2.0`), strings, `null`, lists,
negatives and absurd values are refused, in the adapter and in `TokenUsage`
itself, so no provider can construct a malformed usage. Malformed or missing
metering on a served call is `ProviderMeteringError`: charged at the bound as
unknown usage (J-02), and **not retried** — a provider whose meter cannot be
read is not called again inside the request.

### J-08 · MEDIUM · identifying free text

**Root cause.** Only e-mail addresses, links and phone numbers were removed.
The privacy text read as if no identifying information could leave.

**Correction.** `minimise_personal_details` also removes a name given after an
explicit self-introduction ("je m'appelle …", "mon nom est …", "moi c'est …",
"mwen rele …", "non mwen se …", "my name is …") and a home place after
"j'habite à …" / "mwen rete …". Ambiguous phrases ("je suis …", "mwen rele …",
"mwen se …") count only before a capitalised word, so "je suis perdu" and
"mwen rele pwofesè a" are untouched. The response carries the existing
`personal_info_removed` notice. Nineteen ordinary French, Creole and
mathematics sentences (named points, `f(x)`, word problems with first names,
"Comment s'appelle ce théorème ?") are tested to pass byte for byte.

**Limits — this is pattern matching, not name recognition.** It does not
remove: a name mentioned any other way; a nickname; a school, class or
teacher's name; a relative's name; an address in other wording; or a
description that identifies the child without naming them. Four such cases are
pinned as expected failures. The privacy claim in
[05](05-safety-and-privacy.md) is narrowed to exactly this. A first name inside
a pasted word problem is deliberately kept.

### J-09 · MEDIUM · safeguarding claims and accuracy

**Root cause.** Two different things were called "reviewed": lesson content,
which really passes editorial review, and the safety phrase lists and fixed
replies, which were written by the implementer and reviewed by nobody. The API
emitted `source: "reviewed_template"`.

**Correction.**
- `ResponseSource.REVIEWED_TEMPLATE` (`"reviewed_template"`) is now
  `FIXED_TEMPLATE` (`"fixed_template"`); the published contract was regenerated.
  **This is a contract change** for any client of the (unregistered) route.
- `safety.TEMPLATES_REVIEW_STATUS = "unreviewed"`, and the module, service,
  types and documents say so wherever they said "reviewed" about a fixed message.
- New setting `EDU_TUTOR_SAFEGUARDING_REVIEW_COMPLETED` (default false) and
  `build_student_facing_router`, the only entry point a production application
  may use to mount Jude: it raises until the owner records the review.
  `build_tutor_router` remains for tests on a private application.
- Screen accuracy: a narrow exemption for a quotation attributed to a text
  ("Dans le roman, le narrateur dit « … »") — quotation marks **and** an explicit
  literary attribution, and no flagged phrase outside the quotation. Quotation
  marks alone exempt nothing. Patterns were added for indirect first-person
  statements in French, Creole and English (not safe at home, afraid of a
  parent, not being fed, sleeping in the street); sixteen phrasings are tested.
- No helpline, number or organisation is named, and a test fails if a digit
  appears in the support message. No verified Haitian contact has been supplied.

**Not claimed.** The phrase list is short. Six realistic indirect disclosures
it still misses are pinned as expected failures, so nobody can read the suite
as coverage. One sentence of the model-facing system prompt still says "the app
shows a reviewed message"; it is addressed to the model, shown to nobody, and
changing it means a new prompt version, which is left to the next prompt revision.

### Also corrected while in the same code

- **Lock order in `tutor.reserve`.** When charging a learner's stale holds,
  `reserve` locked the request row before the counters of that hold's period,
  the reverse of `settle`. With a stale hold from an earlier day this could
  deadlock against a late settlement (PostgreSQL would abort one of the two).
  It now takes counters first, like every other function. Not reported by the
  review; found while rewriting the function.

## Findings carried from Jude-02A (PR #35)

| 02A finding | Security relevance | Here |
|---|---|---|
| F1 A sentence before the question → "not in this lesson" | Availability, not confidentiality. But it also meant distress written in ordinary prose fell through to that canned reply (F4) | Not fixed (retrieval milestone). It affected this branch's own tests: a question with a suffix retrieved nothing |
| F2/F6 Heading-only matches; retrieval figures did not generalise | None directly | Not fixed (retrieval milestone) |
| F3 "Explain more simply" with a typed remark fails | None directly | Not fixed (retrieval milestone) |
| F4 Indirect distress got "not in this lesson" | **Safeguarding boundary** | The 02A sentence and fifteen similar ones now get the fixed support reply with no model call (`test_the_jude_02a_indirect_case_no_longer_falls_through_to_not_in_lesson`). The general problem remains (J-09 limits) |
| F5 Validator accepts a reply quoting injected lesson text, and a hint that gives the answer | **Output boundary** | Not fixed. Pinned as two strict expected failures |
| Live benchmark runner may under-estimate billable tokens | **Spend boundary** | Requirements below. Nothing was run |

### Required safeguards for the future live evaluation runner

The runner in PR #35 was written against the old estimator. Before any live
run it must, in addition to the gates it already has:

1. size its spend guard with `metering.InputBound` (bytes + framing), not a
   characters-per-token estimate, and count every retry;
2. stop on the first usage report above the bound, and record that report in full;
3. parse usage with `parse_token_count`; treat unreadable metering as the bound;
4. use the origin-bound adapter from this branch (no redirects, 200 only);
5. run on a provider key that has its own spending limit set on the provider's
   side, no larger than the run's cap, and state that limit in the run record;
6. keep its own credential, separate from `EDU_TUTOR_PROVIDER_API_KEY`;
7. use only the synthetic benchmark — no learner text;
8. remain off by default and require the named authorisation it already requires.

No live evaluation is authorised by this branch, and none was run.

## Privacy verification

| Claim | How it was checked |
|---|---|
| The default provider keeps no request | Weak references to requests and messages are dead after nine kinds of outcome |
| The service keeps nothing between requests | `service._background` empty; marker text absent from ledger records and audit log after five requests |
| The error returned for an unexpected failure does not carry the prompt | No `__context__`/`__cause__`; marker absent |
| No ledger or per-call column can hold text | Field allow-lists (unit); `CHECK` violations for free text in every text column of `usage_requests`, `usage_attempts` and `policy.pause_reason` (PostgreSQL) |
| Audit rows for overages, mismatches and orphan settlements name no learner and hold no text | Asserted on PostgreSQL after an over-bound call and after an erasure |
| Logs carry codes and counts only | Existing log tests still pass; the new log lines are `result=<code> bound_violations=<n>` |
| No transcript is persisted | Unchanged: there is nowhere to put one |

## Remaining limitations

- **No dollar guarantee against a provider.** The hold is an assumption; the
  hard ceiling for live use is the provider-side limit, which this server
  cannot verify. An overage is detected after it happened: at most the calls
  already authorised when it is detected.
- **Framing allowances are unmeasured.** 16 per message and 64 per request are
  placeholders. They must be set from the chat template of the chosen model,
  and a model whose tokenizer can emit more tokens than bytes would break the
  content term.
- **Conservative charging can over-count.** Unknown usage and expired holds
  are charged at the bound; a learner can lose allowance to a timeout.
- **Erasure is not a lasting fence.** After `erase_learner`, outstanding holds
  authorise nothing more, but a *new* request from a still-valid session would
  be admitted. Token revocation at erasure is upstream of this module.
- **A dispatch whose authorisation could not be confirmed** (database error
  after commit) leaves a hold that expires at full price rather than being released.
- **The pause does not recall a call already authorised.**
- **PII minimisation and the safety screen are narrow** (J-08, J-09 limits).
- **Retrieval and output-validation gaps** from Jude-02A are open (table above).
- **Not load-tested.** Each admission and authorisation share-locks one policy
  row; the global counter row still serialises admissions.
- **`live_capable` is a declaration**, not detection.
- The in-memory store proves the rules, not database atomicity; the PostgreSQL
  evidence is on throwaway PostgreSQL 16 locally and 17 in CI, not under load.

## Decisions still open (safety and legal)

| # | Decision | Who |
|---|---|---|
| S-1 | Review of the safety phrase lists and fixed replies by a child-safeguarding professional, and of the French and Haitian Creole wording by native speakers. Blocks any student-facing route | Owner + professional |
| S-2 | Which verified Haitian support contacts, if any, the support message may name | Owner + professional |
| S-3 | What must happen when a child discloses (escalation duty, who is told, what is logged). Today nothing is logged or escalated, by design | Owner + legal |
| S-4 | Whether free text that may identify a minor may be sent to a third-party model at all, and under what consent and data-processing terms | Owner + legal |
| S-5 | The provider-side spending limit, and who may raise it | Owner |
| S-6 | Whether a learner's allowance should be credited back after a conservative charge | Owner |
| S-7 | Who may unpause after `cost_bound_exceeded`, and the reconciliation steps first | Owner |
| S-8 | Retention of `usage_attempts` and of released rows (now kept as history) | Owner + legal |
| S-9 | The existing open decisions in [10](10-open-decisions.md) are unchanged | — |

## Dependencies for Jude-02B

1. **Rebase PR #35 onto this branch under a separate integration review.** It
   was not rebased or force-pushed here. Known contact points:
   `providers/openai_compatible.py` (rewritten here; `extra_body` is included so
   #35's addition is preserved, but the constructor now requires an https base
   URL and refuses redirect-following clients); `DeterministicMockProvider.calls`
   (now indices — the harness needs the recording spy or `call_count`);
   `gateway.run` (new `authorize` and `bound` arguments); `UsageStore`
   (`authorize_dispatch`, results returned from `settle`/`release`);
   `ResponseSource.FIXED_TEMPLATE`; `text.estimate_tokens` (removed); and any
   wrapper around the live adapter (such as #35's spend guard) must itself
   declare `live_capable` and expose the adapter's `origin`, or the factory
   will not see what it wraps.
2. The live runner safeguards above.
3. Retrieval improvements measured in #35 (sections, sibling keys, two-term
   rule) and the simplify/hint retrieval rule — unchanged scope.
4. Output validation for hints against the answer key and for quoted injected
   text (the two pinned gaps).
5. Measured framing allowances for each candidate model.
6. A model-based safety classifier and its evaluation — after S-1 to S-3.
7. Turning the SQL proposal into a migration still needs the staff/worker
   roles, the erasure orchestrator and token revocation at erasure.

## Request for independent re-review (Codex #1)

Please re-run the review against the correction commit named in the pull
request, with your own tests unchanged. In particular:

- **J-02**: is the stated contract (assumption + detection + provider-side
  limit) acceptable in place of a guarantee, and are the default framing
  allowances defensible? Try a provider that bills between the mock's count and
  the bound, and one above it.
- **J-03/J-04**: try to make a finalizer for one admission affect another, or
  to release a hold after a dispatch, including with your own fault injection
  in `authorize_dispatch` and around settlement.
- **J-05**: is "before or after the policy-row lock" the boundary you want?
- **J-06**: any way to reach an unapproved destination through an injected
  object that does not declare `live_capable`.
- **J-08/J-09**: the expected-failure lists are the claimed limits; say if a
  limit that matters is missing from them.
