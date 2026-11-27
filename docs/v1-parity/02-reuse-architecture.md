# Reuse versus rebuild: integration architecture

**Status:** proposal for owner decision. No legacy system was contacted beyond read-only source inspection; no data was read or moved.

## The decision that has to be made first (OD-1)

Two recorded directions conflict:

| Source | Direction |
|---|---|
| Mobile-rebuild report (Nov 2026) | "Rebuild the student client, not every service": narrow API over the existing Supabase data if a data and permissions audit passes; keep ids, entitlements and history; no forced re-registration |
| Fable Task 01 and Blueprint ADR-008 | Clean start: fresh database; "do not connect to, scrape, alter, or migrate" the Lovable site; invite users to re-register |
| **This mission** | 61 students must keep identity and learning history |

The rebuild followed the second direction, so today **there is no path for an existing student to reach their account from mobile.** The v1 directive reopens the question. My recommendation follows.

## Recommendation: new platform is the single source of truth; legacy is a one-way, audited import source

Not a live adapter over the legacy database. Reasons, from the source inspection:

* **The legacy trust model is client-side.** Exam scores, Gold amounts and timers are supplied by the browser to RPCs; answer keys are selectable by any signed-in client; grade gating and the paywall are client-only. A mobile API layered on top would inherit records that cannot be trusted and policies that cannot be made safe without changing the live site.
* **~35 `USING (true)` policies** appear across migrations and **~70 of ~85 edge functions run with JWT verification off**. The final effective policy set is unknown without a database audit. Exposing more clients to it increases risk for 61 minors.
* **Two writers to one database** (live web + new API) means two authorities for progress and rewards: the opposite of one source of truth.
* The rebuild already has what the legacy lacks: RLS throughout, server scoring, exactly-once sync, an editorial approval chain.

So: **import, do not proxy.** The web prototype keeps running unchanged during the transition; the new platform takes over feature by feature.

| Legacy capability | Verdict | How |
|---|---|---|
| **Auth users (email/password, Google)** | **Reuse the identities, not the project** *(preferred, needs OD-1)* | See "Identity" below |
| Lesson rows (HTML) | **Reuse as import source** | Deterministic import, then human review (`03-…`) |
| Exam rows, exercises, PDFs | **Reuse as import source** | Same pipeline; PDFs only with rights |
| `lesson_completions`, study sessions | **Reuse as import source** | Map by lesson id after content import |
| Gold balances, exam scores | **Do not trust as records** | Client-supplied. Carry over only as a one-time goodwill grant if the owner wants (OD-6) |
| Social posts, messages, follows | **Do not migrate by default** | Private communications of minors; needs consent and legal basis (OD-4, OD-5) |
| Edge functions (AI tutors, generation, payments) | **Replace** | No auth, no cost caps, keys in gateway scope; rebuild equivalents exist or are planned |
| Storage buckets (lesson images, audio, exam PDFs) | **Copy with integrity manifest** | Assets re-hosted under the new platform's rules; public buckets are not referenced directly |
| Custom auth flows (6-digit verification, device trust, reset tokens) | **Replace** | Partly browser-driven; use the identity provider's own flows |
| Payments (MonCash/Bazik, Stripe) | **Leave on web** (v2) | Honour remaining paid time via entitlements if needed (OD-7) |

## Identity: three options

| Option | What the student experiences | Risk | Verdict |
|---|---|---|---|
| **A. Link-on-first-login** *(recommended)* | Signs in on mobile with the **existing** email and password (or Google). The new platform recognises the legacy identity and attaches the imported history | Requires either the new platform trusting the legacy project's tokens for a transition period, or an Auth user import that preserves password hashes | Best continuity; no credential handling by us |
| B. Re-register with verified claim | Creates a new account; proves ownership of the old email; history is attached | Friction; 61 families to guide; duplicate-account risk | Fallback if A is blocked legally or technically |
| C. Re-register, no history | Clean start | Violates the v1 directive | Not acceptable under this mission |

**Option A, concretely** (to be proven on synthetic fixtures before any real account is touched):

1. **Identity mapping table** in the new platform: `legacy_subject` (legacy auth user id) ↔ `account_id`, unique both ways, with `linked_at`, `method`, `import_batch`. Idempotent: re-running a link is a no-op.
2. **Auth continuity** by one of:
   * *A1 – Auth user import:* a Supabase-supported export/import of auth users (password hashes preserved) into the new project. Students keep their password; Google identities need the new project's OAuth client configured for the same Google app. **No password ever passes through our code.**
   * *A2 – Transitional token trust:* the API accepts tokens from both issuers (legacy and new JWKS) and maps the legacy subject. Faster, but keeps the legacy project in the trust chain; time-boxed only.
3. **History attach** runs only after the content import has produced a `legacy lesson slug → lesson id` map. Unmapped rows go to an exceptions table that staff can see; nothing is dropped silently.
4. **Consent and notice:** a migration notice in French and Creole; for minors, whatever basis counsel confirms (OD-5).
5. **Rollback:** the mapping and imported rows carry an `import_batch`; a batch can be detached without touching the legacy data, which is never written to.

**What must be tested with synthetic fixtures first:** duplicate emails, changed emails, Google-only accounts, accounts with no profile row, legacy grade aliases (7e, S1, Rheto, Philo), lesson slugs that no longer exist, partial imports, re-runs, and detach.

## Integration contracts (who is authoritative, what the contract is)

| Area | Authority | Contract | Legacy input |
|---|---|---|---|
| Curriculum delivery | New platform: `app.lessons`, revisions, packs | `GET /v1/catalog`, `GET /v1/lessons/{id}` (merged); pack manifests (#7) | One-way import with `legacy_id` on course, lesson and asset rows |
| ExamHub | New platform: `app.exams…` | `/v1/exams…` (first slice implemented; see backlog) | One-way import; keys never leave the server before submission |
| Jude | New platform: `tutor` schema (#28/#43) | `POST /v1/jude/requests`, `GET` status | None. Legacy function is replaced |
| Community | New platform (Social-01+) | Draft `social-v1` OpenAPI (#1), to be revised after OD-4 | None by default |
| Notifications | New platform outbox (#6) | Preferences + device token registration (to be added) | Legacy preferences optionally imported |
| Profiles and progress | New platform: `learner_profiles`, `lesson_progress` | `GET/PATCH /v1/me` (#5), sync push/pull (merged) | Profile basics and completions imported through the identity map |

## Secrets and boundaries (non-negotiable)

* The native app holds **only** the publishable Supabase key and the API base URL. No service-role key, no AI provider key, no storage write key.
* AI provider credentials live only in the API's server environment; calls go through the gateway with caps (Jude plan).
* The legacy **service-role key is needed only by the import job**, run by an operator in an isolated shell, never by the API or the app, and rotated after the import.
* The source inspection found the anon key and founder UUIDs hardcoded in the legacy client. They are not secrets, but founder checks by hardcoded UUID are not a model to carry over.

## Sequence

1. OD-1 decided; database audit of the legacy project by the owner (counts, effective RLS, auth user export feasibility).
2. Synthetic-fixture migration rehearsal in CI (identity map, content map, history attach, detach).
3. Content import to *draft* status; review workflow.
4. Read-only pilot: a few consenting students link accounts on a staging build.
5. Cut-over per feature; web prototype stays live until parity is accepted.
