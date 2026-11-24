# 1. Architecture decision record — social module

Each decision says **what** was chosen, **why**, **what was rejected**, and
**what it costs**. Status of all of them: *proposed* (Social-00), to be
confirmed in review. Open questions are in
[10-risks-and-open-decisions.md](10-risks-and-open-decisions.md).

## Context

What exists today (branch `main`):

- One FastAPI service (`services/api/src/edu_api`) with routers `health`, `me`,
  `catalog`, `sync`. It verifies Supabase Auth tokens (ES256, public key only)
  and opens one database transaction per request, in which it sets the verified
  user id (`set_config('edu.actor_id', …, true)`).
- One PostgreSQL database. Schema `app` has 22 tables, row-level security on all
  of them, and one API role (`edu_api`) that can read a little and write
  nothing: learning data is written only by the function `app.sync_apply_operation()`.
- A React Native (Expo) student app with an offline outbox for lesson progress
  and practice answers, and four destinations: Accueil · Apprendre · Réviser · Profil.
- No hosted environment. Supabase Realtime, Storage and public sign-up are
  disabled in `supabase/config.toml`.
- Known gaps recorded in `docs/SECURITY.md`: no rate limiting, no token
  revocation check, no audit trail written yet, no retention or deletion, no staff API.

What the old Lovable prototype had, and what this design does with it:

| Prototype feature | In this design |
|---|---|
| Feed, posts, comments | Yes — text only, pre-moderated, inside closed communities |
| Likes | Replaced by three positive reactions; only a total is shown |
| Replies | One level of replies |
| Follows | **No.** No follower graph, no follower counts |
| Images, video, media sharing | **Not in the initial schema.** Images drafted separately (`migrations/future/F002_media.sql`); video out of scope |
| Direct and group messaging | **Not in the initial schema.** Drafted separately (`F001_direct_messaging.sql`); needs its own approval |
| Realtime, presence | **No** always-on connections. Presence is never built (it tells others when a child is online) |
| Notifications | Pull-based events, ids only; push later, content-free |
| Reporting, limited moderation | Full workflow: queue, deadlines, sanctions, audit, escalation |
| Jude AI as a participant | **No.** Sending minors' conversations to an AI provider needs a privacy review first |

Nothing is copied or migrated from the prototype, and it was not accessed for this work.

## Component view

```
 Phone (untrusted)
   │  Authorization: Bearer <Supabase access token>
   ▼
 FastAPI service — ONE deployable, three separate database identities
 ┌─────────────────────────┬───────────────────────────────┬──────────────────────────────┐
 │ learning module         │ social module  /v1/social/*   │ social moderation + admin    │
 │ /v1/me /v1/catalog      │ edu_api.social                │ /v1/social/moderation/*      │
 │ /v1/lessons /v1/sync    │ local text screen (no AI)     │ /v1/social/admin/*  (MFA)    │
 │ pool A → edu_api_login  │ pool B → edu_social_login     │ pool C → edu_social_mod_login│
 └───────────┬─────────────┴───────────────┬───────────────┴──────────────┬───────────────┘
             ▼                             ▼                              ▼
 PostgreSQL ─ schema app (unchanged)   schema social (new, private)
              22 tables                 23 tables, RLS on all, writes only through functions
              ▲                                                           ▲
              └────────── no grant, no foreign key, no function ──────────┘
                          crosses this line in either direction

 Scheduled job (later): edu_social_worker_login → social.run_retention() only
```

## Decisions

### S-01 · A module inside the existing API, not a new service

**Decision.** Add a Python package `edu_api.social`, mounted at `/v1/social`.
Same process, same deploy, same token verification, same error shape.

**Why.** A team this size cannot operate two services well. The valuable
separation is *data access*, and that is enforced in the database (S-02, S-03)
— stronger than a network hop between two services that would share a database anyway.

**Rejected.** (a) A separate microservice: double the deploy, monitoring and
on-call for no extra isolation. (b) Supabase's auto-generated table API straight
from the phone: the rules here ("approve by someone else", "hide after two
reports") involve several rows at once and cannot be written as per-row permissions.

**Cost.** A social bug can take down the shared process. Mitigations: separate
connection pools with their own limits and timeouts (a slow feed query cannot
use up the learning pool); the module is behind a setting and can be unmounted.

Proposed layout (to be created in Social-02, nothing exists yet):

```
services/api/src/edu_api/social/
  router.py        mounts the sub-routers; only imported when EDU_SOCIAL_ENABLED=true
  deps.py          social_db (pool B), mod_db (pool C), require_staff_session (aal2)
  schemas.py       request/response models, unknown fields rejected
  cursors.py       opaque cursors (same style as edu_api.sync.cursor)
  screening/       normalise.py, rules.py, wordlists/fr.txt, wordlists/ht.txt
  service/         me, communities, feed, posts, comments, reactions, safety, notifications
  moderation/      router.py, service.py
  admin/           router.py, service.py
```

Import rule, enforced by a test: `edu_api.social` may import only
`edu_api.auth`, `edu_api.errors`, `edu_api.config`, `edu_api.middleware`, the
`Database` class and `get_principal`. It must not import `edu_api.sync`,
`edu_api.identity` or `edu_api.routers`, and no learning module may import `edu_api.social`.

### S-02 · Same database, separate `social` schema, no SQL bridge

**Decision.** All social tables live in a new private schema `social` in the
same managed PostgreSQL instance. **No** foreign key, view, trigger or function
crosses between `app` and `social`. The social migrations never name the `app` schema.

**Why.** "Do not grant social components access to private academic progress"
is easiest to guarantee, and to *test*, when there is simply no path. The two
modules share exactly two things: `auth.users` (who the person is) and the
transaction setting `edu.actor_id` (who is calling right now).

**Rejected.** (a) Social tables inside `app`: one wrong `GRANT` exposes scores.
(b) A second database: more cost and backups, and no real gain while both are
reached by the same API. (c) A "bridge" function that reads the learner's grade
from `app.learner_profiles`: convenient, but it is exactly the kind of small
exception that grows. Instead, the grade *band* is recorded in the social
enrolment by the adult who enrols the learner (S-04).

**Cost.** If a feature ever needs both (for example "ask the class about this
lesson"), the API layer must make two separate queries on two pools and combine
them in Python; it cannot `JOIN`. That friction is intended.

### S-03 · Three database roles, three connection pools

**Decision.**

| Role (NOLOGIN group) | Login role (created out of band) | Used by |
|---|---|---|
| `edu_social` | `edu_social_login` | `/v1/social/*` member endpoints |
| `edu_social_mod` | `edu_social_mod_login` | `/v1/social/moderation/*`, `/v1/social/admin/*` |
| `edu_social_worker` | `edu_social_worker_login` | scheduled retention job |

None has `BYPASSRLS` or any admin attribute. None has any privilege on `app`.
`edu_api` has none on `social`.

**Why.** A role is a hard ceiling. If a student endpoint is tricked into
running a moderation query, it fails with "permission denied" because that pool
physically cannot execute moderation functions. And each moderation function
*also* checks that the verified caller holds an active staff role — two
independent locks.

**Cost.** More connections: with pools of 5 (learning), 4 (social), 2
(moderation) the service uses up to 11 + overflow. On a small managed instance
this needs the transaction-mode pooler, which `docs/SECURITY.md` lists as
untested. That test becomes a prerequisite (see roadmap).

### S-04 · Identity comes from Auth; eligibility is owned by the social module

**Decision.** A person exists in `auth.users`. To take part they additionally
need: a `social.profiles` row (the limited public profile), a
`social.enrollments` row (private: age band, consent, status) created **by an
authorised adult, never by themselves**, and at least one verified membership.
The social module never reads `app.learner_profiles`; the "learner on first
contact" behaviour of the learning API does not apply here.

**Why.** Being able to study must not automatically mean being able to talk to
other children. Enrolment is the single place where age band and consent are
checked. We store an age **band** (`under_13`, `13_15`, `16_17`, `18_plus`),
not a date of birth: enough to apply rules, much less to leak.

Grade is not age. Learners in a given grade can be considerably older than the
nominal age (to be confirmed with partner schools), so the grade band controls
*which communities* are possible and the age band controls *which rules* apply.

**Cost.** Enrolment is manual work for staff or schools. For a pilot that is a
feature (it caps growth to what moderation can handle); at scale it needs the
admin tools in Social-02 and the guardian flows in Social-04.

### S-05 · Writes only through database functions; refusals are answers, not errors

**Decision.** `edu_social` has no `INSERT`, `UPDATE` or `DELETE` on any table.
Each write is one `SECURITY DEFINER` function (`submit_post`, `file_report`, …)
that takes no "caller id" parameter. Expected refusals — "muted", "limit
reached" — are *returned* as `{"result": "<code>"}` and the transaction commits.

**Why.** Same reasoning as `app.sync_apply_operation()`: everything that must
be true together happens in one place, and a bug in Python cannot skip a step.
Returning refusals (instead of raising) lets the rate counter and the audit row
survive; a raised error would roll them back and make limits useless.

**Cost.** Business logic in PL/pgSQL is harder to unit-test than Python and
needs pgTAP. These functions are owned by `postgres`, which can bypass RLS — the
same limitation as item 4 of `docs/SECURITY.md`, with the same mitigations
(empty `search_path`, no dynamic SQL, typed arguments, narrow `EXECUTE`).

### S-06 · Everything users write is approved before anyone else sees it

**Decision.** Posts, comments **and display names** start as `pending_review`.
They become visible only after a moderator approves them. Enforced three times:

1. the API returns `202` and never puts pending content in a feed;
2. the row-level-security policy shows others only `status = 'published'`;
3. a database trigger refuses any change to `published` unless a
   `moderation_actions` row of type `approve` exists for **that exact text
   (same SHA-256 digest)** by **someone who is not the author**.

Only one moderation mode exists (`pre_moderated`); the column's `CHECK` allows
nothing else, so loosening it requires a reviewed migration.

**Why.** The requirement is explicit: content must not become visible before
safety checks and approval. Layer 3 means the rule holds even for a person
typing SQL in a console, and mirrors the existing rule that a lesson's reviewer
cannot be its author.

**Cost.** Conversation is slow: a reply appears hours later, not seconds. That
is a deliberate product trade for this age group and this team size, and it is
the main thing to evaluate in the pilot. It also means the moderation queue is
the capacity limit of the whole feature (see doc 06 for the arithmetic).

### S-07 · Initial scope is text in closed communities — nothing else

**Decision.** Out of the initial schema: media, direct/group messages, follows,
public or searchable profiles, member directories for learners, hashtags,
search across communities, sharing links, presence, typing indicators.

**Why.** Each of these multiplies either safety risk (private contact between
strangers and minors, images of children) or data use. The two largest —
messaging and media — have draft tables in `migrations/future/` so the initial
design does not paint them into a corner, but they are not approved.

### S-08 · Local rule-based screening only; no third-party AI; no Jude

**Decision.** Before storing a submission, the API runs a small deterministic
screen in its own process: Unicode normalisation, removal of control and
invisible characters, length limits, and pattern rules for phone numbers,
e-mail addresses, links, social-media handles, plus French and Haitian Creole
word lists. Outcome: *refuse now* (contact details, links) with a helpful
message, or *accept and flag* for the moderator. **The screen never approves anything.**

No user-generated content is sent to any external service. Jude does not read
or write in communities.

**Why.** The requirement forbids third-party AI moderation without a privacy
and permission review. A rule-based screen is weak against determined evasion —
which is why the human approval in S-06 is the real control and the screen only
helps the human prioritise.

**Cost.** Word lists need a Creole-fluent maintainer and will produce false
positives. Any future use of an AI vendor is decision D-06.

### S-09 · Verified membership, grade bands, no public communities

**Decision.** A community is `invite_only` or `listed_to_eligible` (its name is
visible to learners of the same grade band). Joining by code creates a
*request*; a teacher of that group or staff approves. Invite codes are stored
as a digest only, always expire, and guesses are limited to 5 per hour per
account. A trigger refuses an active membership whose learner is in a different
grade band, is not actively enrolled, or would exceed the member limit.

### S-10 · Pull, not push: no always-on connections

**Decision.** No WebSocket, no Supabase Realtime, no long-polling. Feeds are
paginated reads. One small call, `GET /v1/social/updates`, tells the phone what
changed. Publication order comes from a single counter row
(`social.visibility_clock`) locked for each visibility change, so sequence
numbers become visible in commit order and a cursor never skips an item — the
same idea as `app.account_sync_state`.

**Cost.** One global lock limits visibility changes to roughly hundreds per
second — orders of magnitude above what human moderators produce. If that ever
changes, the clock can be split per community.

### S-11 · Safe retries through natural keys, with no idempotency table

**Decision.** Posts and comments carry a phone-generated `client_op_id`;
`(author_id, client_op_id)` is unique. Same id + same text → the first answer
again (`replayed: true`). Same id + different text → `409 idempotency_conflict`.
Reactions are `PUT`/`DELETE` (naturally repeatable). Reports are unique per
reporter and subject. Blocks and joins are unique by key.

**Why.** The learning sync keeps receipts forever because an offline phone may
retry weeks later. The same is true here, and the content row itself is the
receipt — no separate table to grow or expire.

### S-12 · Rate limits stored in PostgreSQL

**Decision.** Per-account fixed-window counters in `social.rate_counters`,
checked inside the write functions; limits are data in `social.config`.
Defaults: 5 posts and 30 comments a day, 3 posts / 10 comments waiting for
review at once, 200 reactions and 20 reports a day, 5 join attempts an hour.

**Why.** It works across several API processes without adding Redis, and the
limits double as moderation capacity planning. **This does not replace the
general per-IP / per-account limiter that `docs/SECURITY.md` item 1 still
requires** before any exposure to the internet.

### S-13 · No editing

**Decision.** Published text never changes. To correct something, the author
deletes it and writes a new one (which is reviewed again). A rejected post can
be corrected and resubmitted as a new post from the phone's local copy.

**Why.** "What was approved" and "what is shown" stay identical forever, with
no revision tables, no "edited" abuse (approve something harmless, then change it).

### S-14 · Positive reactions, totals only

**Decision.** Three reactions (`helpful`, `thanks`, `encourage`); no downvote;
members see a total, never who reacted; no notification per reaction.

**Why.** Fewer mechanisms for exclusion and popularity pressure, nothing extra
to moderate, fewer bytes.

### S-15 · On the phone: a separate social cache and a separate social outbox

**Decision.** Social data uses its own SQLite tables (`social_*`) and its own
outbox and drain loop. It never writes to the learning outbox, and the learning
sync engine never waits for it. Details in doc 07.

### S-16 · Keep safety records, erase text

**Decision.** Deleting or rejecting content erases the *text* (immediately or
after a short, configured period). What remains is a row with ids, timestamps
and a digest. Moderation actions and audit events are append-only and kept
longer, but contain no text. An evidence hold suspends erasure for a specific item.

### S-17 · Ships switched off

**Decision.** Three independent switches, all "off" by default: the API setting
`EDU_SOCIAL_ENABLED` (routes not mounted), `social.config.submissions_open`
(global read-only), and each community's `status` (`draft`/`frozen`).

### S-18 · Staff sign-in is stronger than learner sign-in

**Decision.** Moderation and admin routes require a multi-factor session
(`aal2` claim), check the staff role in the database on every request (so
removing a role takes effect at once, despite the token living up to an hour),
and run on the moderation pool.

## How the module meets the stated requirements

| Requirement | Where it is met |
|---|---|
| Modular social domain inside FastAPI | S-01 |
| Same PostgreSQL, separate `social` schema, explicit boundaries | S-02, S-03; doc 05 |
| Preserve `app` and all learning migrations | No statement touches `app`; doc 03 "What does not change" |
| No access to private academic progress | S-02, S-04; tests DB-B01…B06 in doc 08 |
| Not visible before safety checks and approval | S-06 |
| No open DMs or arbitrary uploads | S-07; `migrations/future/` |
| No third-party AI moderation without review | S-08; decision D-06 |
| Text-first, paginated, no always-on realtime | S-10; doc 07 |
| Separate from the offline learning outbox | S-15; doc 07 |
| Four-tab navigation unchanged | doc 09 "Mobile integration" |
