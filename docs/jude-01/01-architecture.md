# 1. System architecture

## Shape

Jude is one Python package, `edu_api.tutor`, with no import from the rest of the
API except three stable things: `Database.transaction` (to read lessons as the
learner), `CurrentPrincipal` (the verified caller) and `ApiError` (the error
shape). Nothing in the rest of the API imports the tutor.

```
                         ┌──────────────────────── edu_api.tutor ─────────────────────────┐
 mobile app (later)      │                                                                │
        │                │  router.py ── NOT registered in main.py                        │
        ▼                │      │                                                         │
 POST /v1/jude/requests ─┼─▶ service.py  (the pipeline, the failure boundary)             │
                         │      │                                                         │
                         │      ├─ safety.py        screen message · fixed messages       │
                         │      ├─ governance.py    consent · entitlement  (deny default) │
                         │      ├─ content.py       approved lesson, as the learner (RLS) │
                         │      ├─ retrieval.py     rank blocks · bounded context         │
                         │      ├─ prompts.py       versioned template · trust boundary   │
                         │      ├─ budget.py        reserve ▸ settle ▸ expire             │
                         │      │     └─ pg_store.py ─▶ tutor.* SQL functions (proposal)  │
                         │      ├─ gateway.py       timeout · retries · fallback · meter  │
                         │      │     └─ providers/  base · mock · openai_compatible      │
                         │      └─ validation.py    shape · language · citations · safety │
                         │                                                                │
                         │  config.py (EDU_TUTOR_*)   factory.py (wiring, refuses unsafe) │
                         └────────────────────────────────────────────────────────────────┘
```

## Module responsibilities

| Module | Responsibility | Depends on |
|---|---|---|
| `types.py` | The public contract: `TutorRequest`, `TutorResponse`, enums | pydantic |
| `errors.py` | Typed failures with stable codes and HTTP statuses | — |
| `content.py` | `LessonSource` protocol; `SqlLessonSource` (RLS); in-memory double | `db.session` |
| `text.py` | Normalisation, tokenisation | — |
| `metering.py` | The token bound a hold is sized with, and the check of reported usage against it | `providers` |
| `retrieval.py` | `Ranker` protocol, BM25, char-trigram, fusion, `LessonRetriever` | `content`, `text` |
| `evaluation.py` | Repeatable ranker comparison on synthetic questions | `retrieval` |
| `prompts.py` | Versioned `PromptTemplate`, fingerprint, DATA envelope | `retrieval` |
| `safety.py` | Message screen, removal of contact details and self-introductions, output checks, fixed messages (unreviewed) | `text` |
| `validation.py` | Model output → validated answer with real references | `safety`, `retrieval` |
| `providers/` | `ModelProvider` protocol and adapters | httpx (adapter only) |
| `gateway.py` | One place that calls a provider: bounded, metered | `providers`, `budget` |
| `budget.py` | Prices, policy, `UsageStore` protocol, in-memory store | — |
| `pg_store.py` | `UsageStore` over the `tutor` schema functions | `db.session` |
| `governance.py` | Consent, entitlement, erasure, retention, audit interfaces | — |
| `config.py` | `TutorSettings`, safe defaults | pydantic-settings |
| `factory.py` | Builds a service; refuses unsafe configuration | all of the above |
| `service.py` | Orchestration; never logs or stores text | all of the above |
| `router.py` | FastAPI router factory, unregistered | `service`, `deps`, `errors` |
| `contracts.py` | Generates `packages/contracts/tutor` from the models | `types`, `validation` |
| `demo.py`, `demo_content.py` | Mock demonstration and synthetic lessons | — |

## Design decisions

**Stateless, single-turn.** A request carries everything; the server keeps no
conversation. Progressive hints work through `support_level`, a counter the
client holds. This is what makes "no stored transcripts" true rather than a
policy promise, and it removes a whole class of cross-learner leaks.

**The learner is never a parameter.** The learner is `principal.user_id` from
the verified token. The request model has no learner field and forbids unknown
fields. Lesson reads run in `Database.transaction(learner_id)`; budget functions
read `app.current_actor_id()`.

**Interfaces at every external edge.** Lessons (`LessonSource`), ranking
(`Ranker`), the model (`ModelProvider`), the ledger (`UsageStore`), consent and
entitlement gates. Each has a deterministic double, so the full pipeline runs
in a unit test with no database and no network.

**One failure boundary.** `TutorService.answer` raises only `TutorError`
subclasses. Anything unexpected becomes `tutor_unavailable` and is logged by
exception *type* only. See [Reliability](#reliability).

**The model is treated as untrusted in both directions.** What goes in is
separated into trusted instructions and untrusted data; what comes out is
parsed, checked and re-mapped before a student sees it.

## Reliability

Jude cannot block learning:

- Nothing on the lesson, download, quiz or sync paths imports or calls the tutor.
- No database connection is held while a provider is awaited. A request uses
  three short transactions: read lesson, reserve, settle.
- Provider calls are bounded by the per-learner and global concurrency limits,
  a per-call timeout and a fixed maximum number of calls.
- Reading `EDU_TUTOR_*` settings cannot stop the API from starting: the settings
  class is separate from `edu_api.config` and is only read when a tutor service
  is built.

| Situation | Result |
|---|---|
| Provider times out | Retried within the bound, then `tutor_provider_timeout` (504) |
| Provider down / rate limited | `tutor_provider_unavailable` (503) |
| Model returns invalid data | Retried once within the bound, then `tutor_invalid_model_output` (502) |
| Lesson unavailable | `tutor_lesson_unavailable` (404) |
| Budget exhausted | `tutor_daily_limit_reached` / `tutor_monthly_limit_reached` (429), `tutor_budget_exhausted` (503) |
| Kill switch on | `tutor_paused` (503, `Retry-After`) |
| Consent unknown or denied | `tutor_consent_required` (403) |
| Device offline | No request is made. The app shows the reviewed explanations and worked examples already in the downloaded lesson, labelled as lesson content — never as a Jude answer. This is a client rule for the mobile work; the server never sees an offline learner. |

## What can change without changing the contract

Retrieval strategy, ranker, prompt version, provider, model, prices, limits and
the ledger backend are all behind interfaces or configuration. `TutorRequest`
and `TutorResponse` do not mention any of them except `prompt_version`, which is
reported for traceability.
