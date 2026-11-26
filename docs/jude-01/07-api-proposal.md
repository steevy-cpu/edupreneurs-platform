# 7. API proposal

**Status: proposal.** The router exists (`edu_api.tutor.router.build_tutor_router`)
and is tested on a throwaway application, but `main.py` does not include it and
`packages/contracts/openapi.json` does not mention it. Registering it is a
Jude-02 change that needs the approvals in [10](10-open-decisions.md).

Path prefix `/v1/jude` follows Platform-00 §7. All routes need
`Authorization: Bearer <Supabase access token>`; the learner is the token subject.

## `POST /v1/jude/requests`

Ask Jude about one published lesson. Schema:
`packages/contracts/tutor/tutor-request.schema.json`.

| Field | Type | Notes |
|---|---|---|
| `idempotency_key` | uuid, required | Client-generated per question. Never charged twice. |
| `lesson_id` | uuid, required | |
| `lesson_revision_id` | uuid, optional | The revision on screen. If set, Jude answers only from exactly it. |
| `locale` | `fr` \| `ht`, required | Language of the lesson content being read. |
| `response_locale` | `fr` \| `ht`, optional | Language of the answer; defaults to `locale`. |
| `intent` | enum, required | `explain_concept`, `ask_question`, `hint`, `explain_answer`, `another_example`, `simplify` |
| `message` | string ≤ 600, optional | The student's words. Never stored or logged. |
| `focus_block_key` | string, optional | Block the learner is looking at. |
| `question_key` | string, optional | Practice question concerned. |
| `selected_choice_id` | string, optional | The learner's answer; required for `explain_answer`. |
| `support_level` | 1–4, default 1 | How much help was already given; kept by the client. |

Unknown fields are rejected (there is deliberately no learner field).

```json
{
  "idempotency_key": "0b6f5d0e-3f0a-4c58-9a57-6a2f3d1c9e10",
  "lesson_id": "b0000000-0000-4000-8000-000000000005",
  "lesson_revision_id": "c0000000-0000-4000-8000-000000000001",
  "locale": "fr",
  "response_locale": "ht",
  "intent": "ask_question",
  "message": "Pourquoi on soustrait 5 des deux côtés ?",
  "focus_block_key": "exemple-1"
}
```

### `200` — `tutor-response.schema.json`

| Field | Notes |
|---|---|
| `request_id` | Echo of `idempotency_key` |
| `status` | `answered` · `insufficient_context` · `declined` · `safety_support` |
| `source` | `model` (validated model text) or `fixed_template` (fixed text shipped with the server, **not professionally reviewed**; no model was called or its text was discarded) |
| `grounding` | `lesson` · `general` · `none` |
| `language` | `fr` \| `ht` |
| `explanation`, `hint`, `check_question` | Student-facing text |
| `references[]` | `{lesson_id, lesson_revision_id, locale, kind: block\|question, key}` — created by the server only |
| `next_action` | `none`, `reread_passage`, `review_example`, `try_practice_question`, `ask_follow_up`, `rephrase_question`, `talk_to_trusted_adult` |
| `answer_was_correct` | For `explain_answer`: decided by the server from the reviewed key |
| `notices[]` | e.g. `general_knowledge_beyond_lesson`, `personal_info_removed`, `question_not_found_in_lesson`, `safety_concern` |
| `lesson_revision_id`, `prompt_version` | Traceability |

All four statuses are `200`: they are answers the app shows. The app should
render `source: fixed_template` plainly (not as "Jude says") and must show
the `general_knowledge_beyond_lesson` notice when present.

### Errors

The API's existing shape — `{"error": {"code", "message", "request_id"}}` — with
these stable codes (`packages/contracts/tutor/error-codes.json`):

| HTTP | `code` | Meaning for the app |
|---:|---|---|
| 401 | `unauthenticated` | Sign in again |
| 403 | `tutor_consent_required` | Show the consent path; do not retry |
| 403 | `tutor_not_entitled` | Hide Jude for this account |
| 404 | `tutor_lesson_unavailable` | Lesson not published in this language |
| 409 | `tutor_lesson_revision_not_current` | Refresh the lesson, then ask again |
| 409 | `tutor_duplicate_request` | Already answered; show the answer you kept |
| 409 | `tutor_request_in_progress` | Wait for the first response |
| 422 | `validation_error` / `tutor_invalid_request` | Client bug |
| 429 | `tutor_daily_limit_reached` | "You have used today's questions" |
| 429 | `tutor_monthly_limit_reached` | "You have used this month's allowance" |
| 429 | `tutor_too_many_requests` | One question at a time |
| 502 | `tutor_invalid_model_output` | "Jude could not answer reliably; try again" (new key) |
| 503 | `tutor_disabled`, `tutor_paused`, `tutor_busy`, `tutor_budget_exhausted`, `tutor_provider_unavailable`, `tutor_unavailable` | Hide or grey out Jude; lessons unaffected |
| 504 | `tutor_provider_timeout` | Try again (new key) |

`Retry-After` is sent where waiting helps. Messages are fixed English strings
for developers; the app localises by `code`.

## `GET /v1/jude/status`

A cheap probe so the app can show or hide the Jude button without spending
anything. Always `200`:

```json
{"available": true, "reason": null, "daily_requests_used": 3, "daily_requests_limit": 20}
```

`reason` is one of the codes above when `available` is false. It reports only
the caller's own usage.

## Client rules (for the mobile work, not built here)

1. Never block a lesson, quiz, download or sync on Jude. Any error or timeout
   → hide the panel, keep the lesson.
2. Offline: do not call. Show the lesson's own reviewed explanation and worked
   examples, labelled as lesson content, never as a Jude answer.
3. One `idempotency_key` per question; reuse it only when retrying the *same*
   question after a network failure. Use a new key after `502`/`504`.
4. Keep the answer on the device if it should survive navigation; the server
   cannot replay it.
5. Increase `support_level` when the learner asks again about the same thing.
6. Send `lesson_revision_id` of the revision on screen.

## Not in this proposal

Streaming, multi-turn threads, voice, staff endpoints (kill switch, budgets,
usage dashboards for Admin-00 section F / metric M19). The ledger already holds
what M19 needs; the staff API waits for the staff boundary (#4).
