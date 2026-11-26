# Jude-01 — grounded AI tutoring engine

Jude is the study helper for Edupreneurs 2.0. Jude-01 builds the backend engine
and proves it end to end **on a deterministic mock model**. It is not connected
to the application, to any AI provider, or to any learner.

| | |
|---|---|
| Branch | `feature/jude-01-grounded-tutor` |
| Code | `services/api/src/edu_api/tutor/` |
| Tests | `tests/unit/tutor/`, `tests/tutor_pg/`, `tests/integration/test_tutor_lesson_source.py` |
| Contracts | `packages/contracts/tutor/` |
| Try it | `uv run python -m edu_api.tutor.demo` |

## What Jude-01 does not do

- It registers **no route**. `main.py`, `config.py`, `deps.py`, the mobile app,
  the admin app and `supabase/migrations` are untouched; two tests fail if that changes.
- It makes **no call to an AI provider**. The only adapter that could is refused
  by the factory unless the owner sets an explicit authorisation flag.
- It adds **nothing to the database**. The usage-ledger SQL is a proposal that
  only tests apply, to databases they create and drop.
- It is **disabled by default**, and its production defaults deny everyone
  (unknown consent is not consent; unknown entitlement is no entitlement).

## Built versus designed

| Capability | State | Where |
|---|---|---|
| Tutor request/response contract, stable error codes | **Built, tested** | `types.py`, `errors.py`, `packages/contracts/tutor` |
| Reading approved lessons under the learner's RLS | **Built, tested** — on a double locally, and against the real stack and policies in CI | `content.py` |
| Lesson-scoped lexical retrieval with stable references | **Built, tested, measured** | `retrieval.py`, `evaluation.py` |
| Semantic (embedding) retrieval | **Designed only** — seam exists (`Ranker`), no model evaluated | [03](03-retrieval.md) |
| Versioned prompts, trusted/untrusted separation | **Built, tested** | `prompts.py` |
| Provider interface, timeouts, retries, explicit fallback, metering, cancellation | **Built, tested** | `providers/base.py`, `gateway.py` |
| Deterministic mock provider | **Built, tested** | `providers/mock.py` |
| OpenRouter / OpenAI-compatible adapter | **Built, tested against an in-memory transport only; never run against a real API** | `providers/openai_compatible.py` |
| Output validation and citation mapping | **Built, tested** | `validation.py` |
| Safeguarding screen and fixed messages | **Built as a deterministic baseline, tested. Not reviewed by a safeguarding professional or native speakers**; a student-facing route cannot be built until that is recorded | `safety.py` |
| Budget: reserve / settle / expire, limits, kill switch, idempotency | **Built, tested** in memory and **on real PostgreSQL** (throwaway databases; 16 locally, 17 in CI) | `budget.py`, `pg_store.py`, `sql/tutor_schema.sql` |
| Usage-ledger schema as a migration | **Designed only** — SQL is implementation-ready but not a migration | [08](08-database-proposal.md) |
| Consent, entitlement, erasure, retention, audit | **Interfaces built, deny-by-default**; real implementations blocked on unmerged work | `governance.py` |
| FastAPI router | **Built, tested on a throwaway app; not registered** | `router.py` |
| Multi-turn conversation, streaming, voice | **Not designed in detail** — deliberately out of scope | [11](11-jude-02-roadmap.md) |
| Quality of real model answers, real injection resistance | **Unverified** — needs live evaluation, which is not authorised yet | [09](09-test-evidence.md) |
| Mobile UI | **Not started** (other agents own the mobile app) | — |

## Documents

1. [System architecture](01-architecture.md)
2. [Request flow](02-request-flow.md)
3. [Retrieval design and measurements](03-retrieval.md)
4. [Prompt specification](04-prompts.md)
5. [Safety and privacy](05-safety-and-privacy.md)
6. [Cost and budget model](06-cost-and-budget.md)
7. [API proposal](07-api-proposal.md)
8. [Database proposal](08-database-proposal.md) · [`sql/tutor_schema.sql`](sql/tutor_schema.sql)
9. [Test evidence](09-test-evidence.md)
10. [Open decisions](10-open-decisions.md)
11. [Jude-02 roadmap](11-jude-02-roadmap.md)
12. [Security corrections after the independent review (J-01 … J-09)](12-security-corrections.md)

## Audit of the repository this was built on

Checked on 2026-11-26 against `main` at `6ad3fdb` (after #20, #2, #23).

- `main` has identity, the published catalogue and lessons, and offline sync.
  It has **no** staff boundary, entitlements, consent records, account
  lifecycle or worker — those live in unmerged drafts (#4, #5, #10, #21, #25).
- Lessons are immutable revisions (`app.lesson_revisions`, one per locale) made
  of typed blocks with stable `key`s; practice questions carry a reviewed
  explanation. Row-level security shows the API role only **approved** revisions
  in a **current pack** of a **published** course. Jude reuses exactly that.
- Platform-00 (§7, PO-11) asks for: lesson-scoped help only, no stored
  conversations, a request log without text, per-learner and global budgets, a
  kill switch, consent first. Jude-01 follows those recommendations; where they
  are still owner decisions the code denies by default.
- Platform-00 proposed `POST /v1/jude/requests`; the router uses that path.
