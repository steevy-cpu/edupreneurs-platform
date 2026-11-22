# Next steps

## Status update — Mobile-01 (2026-11-22)

The student app now exists in `apps/student-native/` (Expo SDK 58). Its storage
and sync logic passes 52 automated tests against this backend, and it bundles
for Android and iOS. **It has not yet been run on a simulator, emulator or
phone.** No backend API change was needed. Full details, including what is and
is not verified: `apps/student-native/docs/MOBILE_01_REPORT.md`.

Native validation (same day): the app was built with Xcode 26.6 and passed the
full offline workflow on the iOS Simulator
(`apps/student-native/docs/NATIVE_VALIDATION_REPORT.md`).

Immediate next step: free about 9 GB of disk, install the Android build
components, and repeat the acceptance test on an Android emulator (including
API 24), then on a real low-memory Android phone.

## Ready for mobile integration now

The React Native app can be built against the local stack today:

| Capability | Endpoint | Notes for the mobile developer |
|---|---|---|
| Sign in | Supabase Auth (`supabase-js`), not our API | Store the session in Keychain/Keystore. Send `access_token` as a Bearer token; refresh on 401 |
| Who am I | `GET /v1/me` | First call creates the profile |
| What can I study | `GET /v1/catalog?locale=` | Compare `revision_id` with the local copy to detect updates |
| Download a lesson | `GET /v1/lessons/{id}?locale=` | Store blocks + questions in SQLite for offline use |
| Upload offline work | `POST /v1/sync/push` | Outbox pattern; retry rules in `API_CONTRACT.md` |
| Download server state | `GET /v1/sync/pull` | Apply changes and save the cursor in one SQLite transaction |

Generate a typed TypeScript client from `packages/contracts/openapi.json`
(for example with `openapi-typescript`). Content shapes are in
`packages/contracts/content/*.schema.json`.

### Suggested next engineering task: "Mobile-01 — offline outbox against the local API"

A thin Expo/React Native slice, no design polish:

1. Sign in as `student.a@edupreneur.test` against local Supabase Auth.
2. Fetch catalog + the seed lesson; store them in SQLite (`expo-sqlite`).
3. Answer the five questions **in airplane mode**: each answer writes a local
   attempt row *and* an outbox row (with a fresh UUID `op_id`) in one SQLite transaction.
4. On reconnect: push the outbox in batches ≤ 50, handle `accepted` / `replayed` /
   `rejected` / `conflict` per operation, then pull and apply.
5. Prove these with automated tests: kill the app after local save; kill it after
   the push is sent but before the response; push the same batch twice; sign in
   as student B on the same device (cursor reset, no data leak, outbox not lost).
6. UI states only: *Saved on this phone* · *Waiting to sync* · *Synced* · *Needs attention*.

Backend work that task will probably request (small): `PATCH /v1/me` for grade and
language, and `GET /v1/me/progress` as a snapshot for first sync on a new device.

## Before any cloud deployment

Blocking items, roughly in order:

1. **Decide and create an Edupreneur-owned staging Supabase project** (never the Lovable one). Apply the migrations with `supabase db push` from CI, not by hand.
2. **Provision `edu_api_login` out of band** with a managed secret; confirm the chosen pooler mode works with transaction-local identity (`SECURITY.md` → "Login model").
3. **Asymmetric signing keys** on the hosted project (ES256) so the JWKS flow matches local. Set `EDU_AUTH_ISSUER` / `EDU_AUTH_JWKS_URL` to the hosted HTTPS URLs.
4. **Rate limiting and request logging** in front of the API; structured logs without personal data.
5. **Re-run the whole test-suite against staging** (the integration tests refuse non-local hosts on purpose — add an explicit staging mode with its own fixtures, never production).
6. **Privacy decisions**: retention periods for attempts/receipts/feed, an account-deletion procedure, consent for minors. Blocks collecting real student data.
7. **Backups and a restore drill** for the database.
8. **Staff identity**: how editors/reviewers/publishers authenticate (MFA), and a separate staff API + database role for the editorial workflow that fixtures exercise today.
9. **Pack pipeline**: real pack building, object storage (R2), manifest hashing and verification before the `pack_current` pointer moves.
10. **Observability**: error tracking, `/ready` wired to the platform health check, alerts on sync failure rate.
11. **Load test** the sync path (per-learner lock contention is expected to be negligible; verify).
12. Review the open items in `SECURITY.md` → "Unresolved vulnerabilities and limitations".

## Backend backlog (not blocking mobile)

- `PATCH /v1/me` (grade, preferred locale, display name) with column-level UPDATE grants.
- `GET /v1/me/progress` snapshot endpoint; feed compaction + snapshot-based cursor reset.
- Reading-position operation (`lesson_opened` / last block) with its own merge rule.
- More question kinds (`numeric`, `short_text`) with versioned scoring rules and shared test vectors for the phone.
- Write `audit_events` for security-relevant outcomes (op_id conflicts, repeated rejections).
- ETag / `If-None-Match` on catalog and lesson responses to save mobile data.
- Dedicated owner role for SECURITY DEFINER functions (hardening).
- Concurrency tests for the editorial race guards (C08) using two database sessions.
- Dependabot/Renovate for `uv.lock` and the pinned Supabase CLI.

## Deferred to Jude and the curriculum agents

Deliberately **not** started; no tables exist for them:

- **Jude (student tutor):** read-only, allow-listed tools that call application
  services (`get_published_lesson`, `get_my_progress`, …) under the *student's own*
  identity and RLS — never raw SQL. Needs its own request budget, retention and
  consent policy first.
- **Lesson-generation agents:** write **drafts only**, through a future staff/worker
  role. The database already guarantees that nothing they produce can reach
  students without an independent human review and rights-cleared sources
  (`040_integrity_guards.sql`); model self-review does not count.
- **Workers:** `app.background_jobs` exists as the queue table; the claim/lease
  logic and the worker role are future work.
- Billing, entitlements, gamification, school tenancy, community: no schema yet, by design.
