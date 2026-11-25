# Lane IDENTITY — profile edit, onboarding state, account lifecycle (F0, backend of F15 · M-01, parts of M-02)

Worktree `/Volumes/EdupreneursDev/worktrees/overnight/identity` · branch `overnight/identity-onboarding`
· stack API 56221 / DB 56222 · schema `account` · migrations `2026112402xxxx_*` · pgTAP `120–139_*`.

Owned paths: `supabase/migrations/2026112402*`, `supabase/tests/12*.sql`, `supabase/tests/13*.sql`,
`services/api/src/edu_api/account/**`, `services/api/src/edu_api/routers/account*.py`,
`tests/**/test_account_*.py`, `tests/account_fixtures.py`, `docs/overnight-2026-11-24/lanes/identity.md`.
You may extend `services/api/src/edu_api/routers/me.py` and `identity.py` additively for `PATCH /v1/me`
(the existing `GET /v1/me` response and its tests must not change, other than optional new fields
being absent by default).

## Slice 1 — `PATCH /v1/me`
- Body: any of `grade_code`, `preferred_locale` (`fr`|`ht`), `display_name` (nullable). Strict
  validation: unknown fields rejected; display name trimmed, 1–80 chars, no control characters or
  line breaks; grade must exist and be active. Nothing else on the profile is editable.
- Writes go through `account.update_own_profile(...)` (definer, EXECUTE to `edu_api`): the row is
  always the actor's own; there is no user-id parameter. `edu_api` gets **no** UPDATE grant on
  `app.learner_profiles` (the baseline structure test must stay byte-identical and green).
- Each change is audited (who, which fields changed — not the values of the display name).
  Use `ops.audit_write` once the staff lane's B1 is merged (the director will message you); until
  then keep the call site isolated behind one internal function.
- Display names are private study settings, never a public name (Platform-00 doc 04 §4.1).
- Write the design for the future **offline** `profile_updated` sync operation (conflict rule,
  canonical payload, why it is not built tonight: it needs a change to the verified
  `app.sync_apply_operation`) in your lane doc. Do not modify the sync function.

## Slice 2 — onboarding state (server side of F15)
- `account.onboarding_state`: one row per learner: `state` ∈ `new` → `profile_selected` →
  `downloads_informed` → `ready`, `onboarding_version`, `tour_version_seen`, `tour_dismissed`,
  timestamps. RLS own-row read; writes only through `account.advance_onboarding(...)`.
- Semantics that make it resumable and safe for offline replay: the state only moves **forward**
  (a stale or repeated request is accepted and changes nothing), tour flags merge monotonically,
  and nothing in onboarding ever deletes or resets learning data. A returning learner after an app
  upgrade is not forced back through the flow (version rule documented and tested).
- `GET /v1/me/onboarding`, `PUT /v1/me/onboarding`. Account-switch isolation tests (A never sees B).
- **No consent is collected or inferred.** Expose nothing that looks like a consent answer. Document
  the safe behaviour for consent *unknown*: every consent-gated feature treats it as not granted.

## Slice 3 — account lifecycle mechanics on synthetic users (flag `EDU_ACCOUNT_LIFECYCLE_ENABLED`, default off)
- `account.deletion_requests` / `account.export_requests` (requested, cancelled, processed; no
  retention periods invented — store none, mark `BLOCKED_BY_OWNER` PO-04/legal).
- `account.export_own_data()` → JSON of the caller's own profile, progress, attempts, onboarding
  (bounded size; tested for isolation).
- `account.erase_learner(p_user_id)` orchestrator, executable only by `edu_worker`/staff `admin`
  (after B1): calls every existing `<schema>.erase_learner` hook and the learning-data erasure, and
  leaves a non-identifying audit record. The append-only triggers on `app.practice_attempts`,
  `app.sync_receipts`, `app.account_change_feed` block DELETE: design the least invasive way to
  erase one learner's rows **without changing any object in `app` and without weakening the
  triggers for anyone else**, write the options and the chosen one in your lane doc, and prove it:
  a synthetic learner with attempts/progress/receipts is fully erased (no row in any schema
  references the id), another learner's data is untouched, baseline tests still pass. If you cannot
  do this safely, stop at the written design plus failing-by-design test notes and say so.
  Deleting the `auth.users` row belongs to Supabase Auth and is out of scope tonight.

Order: slice 1 → slice 2 → commit and gate → slice 3. Report after slice 2 if slice 3 is going to be long.
