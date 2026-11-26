# 8. Automated test specification

**No test in this document exists yet, and none was run.** This is the list of
tests to write, with the milestone in which each must pass. It follows the
project's existing layers and tools so nothing new has to be learned:

| Layer | Tool (existing) | Location (proposed) | Runs against |
|---|---|---|---|
| Database | pgTAP via `make test-db` | `supabase/tests/1xx_social_*.sql` | Local Postgres rebuilt from migrations + seed |
| API unit | pytest | `tests/unit/social/` | No database |
| API integration | pytest | `tests/integration/social/` | Real local Postgres + Auth |
| Mobile core | jest (real SQLite) | `apps/student-native/tests/…/social_*.test.ts` | Real local API |
| Mobile UI | Maestro flows | `apps/student-native/e2e/2x_social_*.yaml` | Built app on simulator/emulator |

Rules carried over from the existing suite: synthetic data only; every test
states the threat or requirement it protects; a test that cannot fail is not a
test — for the most important invariants a **mutation check** is listed (change
the code, confirm the test goes red, change it back).

Milestone column: S1 = Social-01, S2 = Social-02, S3 = Social-03.

## A. Non-regression — the learning system is untouched

The most important group: adding the social module must not change anything
that exists.

| Id | Test | MS |
|---|---|---|
| NR-01 | The whole existing suite passes **unchanged** after the social migrations are applied: pgTAP (22 tables, 28 FKs, 17 policies in `app`), pytest, jest, Maestro. No existing test file is edited | S1 |
| NR-02 | `packages/contracts/openapi.json`: with `EDU_SOCIAL_ENABLED=false` the exported contract is byte-identical to `main` | S2 |
| NR-03 | With the social router disabled, every `/v1/social/*` path returns the ordinary `404 not_found` | S2 |
| NR-04 | Learning sync timings (`perf_cold_start`, local storage timing tests) stay within their current thresholds with the social module enabled and its cache full | S3 |
| NR-05 | Learning push/pull succeeds while every social endpoint returns 500 | S3 |
| NR-06 | Learning push/pull succeeds when the social pool is exhausted (pool size 1, one stuck query) | S2 |

## B. Boundary between `app` and `social`

| Id | Test | MS |
|---|---|---|
| DB-B01 | `edu_social`, `edu_social_mod`, `edu_social_worker` have no privilege of any kind on schema `app`, its tables, sequences or functions (`has_schema_privilege`, `has_table_privilege`, `has_function_privilege` over the catalog) | S1 |
| DB-B02 | `edu_api` has no privilege of any kind on anything in `social` | S1 |
| DB-B03 | No foreign key has one end in `app` and the other in `social` | S1 |
| DB-B04 | No function or trigger body in `social` contains the text `app.`; no function in `app` contains `social.` (catalog scan of `pg_proc.prosrc`) | S1 |
| DB-B05 | No view or materialised view exists in `social`; none in any schema references both | S1 |
| DB-B06 | The three social roles are `NOLOGIN`, not superuser, no `BYPASSRLS`, no `CREATEROLE`/`CREATEDB`/`REPLICATION`, and are members of no other role | S1 |
| API-B01 | Import rule: a static test walks `edu_api.social` and fails on any import of `edu_api.sync`, `edu_api.identity`, `edu_api.routers`; and fails if any non-social module imports `edu_api.social` | S2 |
| API-B02 | The social pools' `current_user` is `edu_social_login` / `edu_social_mod_login`; running `SELECT 1 FROM app.lesson_progress` on them fails with `42501` | S2 |
| API-B03 | `social` is not reachable through the Supabase Data API, with the publishable key **and** with the secret service key (same shape as the existing test for `app`) | S2 |
| API-B04 | No social response model contains a field named like a learning concept (`score`, `progress`, `attempt`, `lesson_id`) — schema scan of the generated OpenAPI | S2 |

## C. Database structure and integrity

| Id | Test | MS |
|---|---|---|
| DB-S01 | Exactly 23 tables in `social`, with the expected names; every one has a primary key and row-level security enabled | S1 |
| DB-S02 | 46 foreign keys; none to `auth.users` cascades a delete | S1 |
| DB-S03 | 31 policies; every policy targets exactly `edu_social` or `edu_social_mod`; none allows INSERT, UPDATE or DELETE | S1 |
| DB-S04 | No social function is executable by PUBLIC, `anon`, `authenticated` or `service_role`; every `SECURITY DEFINER` function has `search_path = ''` | S1 |
| DB-S05 | No role other than the owner holds INSERT/UPDATE/DELETE/TRUNCATE on any social table | S1 |
| DB-S06 | `config` and `visibility_clock` contain exactly one row and reject a second | S1 |
| DB-S07 | Every foreign-key column has a supporting index (catalog query, same as the reasoning of change C12) | S1 |
| DB-C01 | A post/comment inserted with any status other than `pending_review`, or with a `publish_seq`, is refused — as owner, not just as the API role | S1 |
| DB-C02 | The text of a published post cannot be updated; `body_sha256`, `community_id`, `client_op_id`, `submitted_at`, `publish_seq` cannot change | S1 |
| DB-C03 | **Publishing without an approval action fails** (owner-level `UPDATE … SET status='published'`) | S1 |
| DB-C04 | Publishing fails when the approval's digest differs from the row's digest | S1 |
| DB-C05 | Publishing fails when the approver is the author | S1 |
| DB-C06 | Every illegal transition is refused (table-driven: all 30 pairs of different states, 9 allowed) | S1 |
| DB-C07 | Text can be set to NULL only in `rejected`, `removed`, `deleted` | S1 |
| DB-C08 | A reply to a reply is refused; a reply whose parent belongs to another post is refused (composite FK) | S1 |
| DB-C09 | A comment cannot reference a post of another community (composite FK) | S1 |
| DB-C10 | `author_id` can become NULL and nothing else | S1 |
| DB-C11 | `publish_seq` values are unique and strictly increasing in commit order under 20 concurrent approvals (no reader ever observes N+1 before N) | S1 |
| DB-C12 | Counter consistency: after a randomised sequence of approve / hide / restore / remove / delete / react / unreact, `comment_count` and `reaction_count` equal recomputed counts | S1 |
| DB-M01 | Active membership requires `verified_by`, `verified_at`, `verification_method`; `verified_by = user_id` is refused | S1 |
| DB-M02 | Active membership refused when the enrolment is not `active` | S1 |
| DB-M03 | A learner of band `7AF-9AF` cannot be active in an `NS1-NS4` or `staff_only` community | S1 |
| DB-M04 | A learner account cannot hold the `teacher` role | S1 |
| DB-M05 | The member limit holds under concurrent approvals | S1 |
| DB-E01 | Enrolment constraints: `active` needs a known age band and consent; `not_required` only for `18_plus`; `granted` needs method, recorder, time; nobody enrols or records consent for themselves | S1 |
| DB-A01 | `moderation_actions` and `audit_events`: UPDATE refused; DELETE refused before the retention period, allowed after | S1 |
| DB-A02 | Every state-changing moderation function writes exactly one action row per decision (two for restore + dismiss) | S1 |
| DB-A03 | A denied sanction or join decision writes an audit row with `outcome = 'denied'` | S1 |
| DB-A04 | `social.staff_roles` cannot be written by any API role or function | S1 |

Mutation checks: remove the approval check from `content_update_guard` →
DB-C03/04/05 must fail. Change `IS DISTINCT FROM NEW.author_id` to `IS NOT
NULL` → DB-C05 must fail.

## D. Row-level security (what each person can see)

Fixtures: two communities X (7AF–9AF) and Y (NS1–NS4); learners A, B (in X), C
(in Y), D (enrolled, no community), E (not enrolled); teacher T (X); moderator
M; safety lead L; admin N.

| Id | Test | MS |
|---|---|---|
| DB-R01 | A sees published posts of X; sees none of Y; D and E see none | S1 |
| DB-R02 | A sees own pending/rejected/removed posts; B does not see A's | S1 |
| DB-R03 | A hidden or removed post disappears for B and remains for its author | S1 |
| DB-R04 | Comments under a non-published post are invisible to members even if the comments are `published` | S1 |
| DB-R05 | After A blocks B: neither sees the other's posts, comments or profile; C is unaffected | S1 |
| DB-R06 | With no actor set, every table returns zero rows to both roles | S1 |
| DB-R07 | Nobody can read who reacted, who blocked them, or who reported: `reactions`, `blocks`, `reports` return own rows only; `reports.reporter_id` is not selectable by `edu_social_mod` | S1 |
| DB-R08 | Column grants: selecting `posts.screening_flags`, `posts.body_sha256`, `profiles.pending_display_name`, `profiles.grade_band`, `reports.content_snapshot`, `community_invites.code_sha256` fails for `edu_social` | S1 |
| DB-R09 | Profiles: visible only for people sharing an active community; D sees only their own | S1 |
| DB-R10 | Communities: A sees X; sees a listed community of the same band; does not see listed communities of the other band, drafts or archived ones | S1 |
| DB-R11 | A suspended learner sees no community content at all (own submissions remain) | S1 |
| DB-R12 | A paused enrolment (consent withdrawn) sees nothing | S1 |
| DB-R13 | Moderation role with a non-staff actor sees zero rows in every table; with moderator M sees content but not escalations, holds or audit; with L sees those too | S1 |
| DB-R14 | Admin N sees enrolments and communities but not post or comment text | S1 |
| DB-N01 | Notifications are readable only by the recipient | S1 |
| DB-N02 | Notification rows contain no text column (structure assertion) | S1 |
| DB-V01 | `visibility_changes` returns only ids of the caller's own communities, in order, capped at 200 | S1 |

## E. Member functions

| Id | Test | MS |
|---|---|---|
| DB-F01 | `submit_post`: stored as `pending_review`, one queue item created, priority 1 when flagged | S1 |
| DB-F02 | Each refusal code is reachable: not enrolled, not active, suspended, not a member, submissions closed, community frozen, rules not accepted, muted, capability off, posting restricted | S1 |
| DB-F03 | `submit_comment` on a non-published, foreign-community or blocked-author post → `content_not_found` in all three cases | S1 |
| DB-F04 | `set_reaction`: set, change, clear, repeat — totals stay exact; own content refused | S1 |
| DB-F05 | `file_report`: one report per reporter and subject; snapshot stored; own content refused | S1 |
| DB-F06 | Severe category hides at once; ordinary category hides at the 2nd distinct reporter; `change_seq` advances; an `auto_hide` action is written | S1 |
| DB-F07 | `set_block`: cannot block a teacher or staff account; cannot block a stranger; idempotent | S1 |
| DB-F08 | `join_with_invite`: valid → `pending_approval`; expired, revoked, exhausted, wrong band, frozen community → identical `invite_invalid`; removed member cannot re-join | S1 |
| DB-F09 | `decide_join_request`: teacher of X can approve for X, not for Y; nobody can approve themselves | S1 |
| DB-F10 | `delete_own_content`: text erased at once; kept when a report is open; queue item withdrawn | S1 |
| DB-F11 | `update_profile`: new name invisible to others until approved | S1 |
| DB-F12 | `update_own_settings`: when locked, switching a capability back on is refused | S1 |
| DB-F13 | No member function accepts or uses a caller-id parameter (signature scan) | S1 |

## F. Moderation, sanctions, retention, erasure

| Id | Test | MS |
|---|---|---|
| MOD-01 | `mod_claim_next` returns priority 0 before 1 before 2, oldest first; two concurrent claims never return the same item | S1 |
| MOD-02 | A moderator is never offered, and cannot decide, their own content | S1 |
| MOD-03 | An expired lease returns the item to the queue; a decision on an expired or foreign claim → `item_not_claimed` | S1 |
| MOD-04 | Approve → published + author notified + post author notified of a comment (not when blocked, not when the same person) | S1 |
| MOD-05 | Dismiss on a hidden item restores it at its original feed position; reports become `dismissed` | S1 |
| MOD-06 | Remove → gone for members, reason code visible to the author only, reports `actioned` | S1 |
| MOD-07 | Display-name approval / rejection / removal | S1 |
| MOD-08 | Role limits: moderator cannot ban, cannot suspend > 7 days, cannot sanction a teacher, cannot lift a ban, cannot escalate beyond `safety_lead`; nobody can sanction themselves | S1 |
| MOD-09 | A sanction takes effect on the very next call with the same token | S2 |
| MOD-10 | Escalation places evidence holds on the content and all its reports | S1 |
| MOD-11 | A function call on the moderation role with a learner as actor raises `42501` | S1 |
| DB-T01 | Retention: rejected text erased after the configured days and not before; removed likewise; report snapshots likewise; expired notifications deleted; running twice changes nothing | S1 |
| DB-T02 | Retention skips anything under an active evidence hold | S1 |
| DB-E02 | `erase_user`: all the person's text gone, profile and personal rows gone, authorship NULL, counters corrected, safety records remain without text | S1 |
| DB-E03 | `erase_user` is refused while an evidence hold is active | S1 |
| DB-E04 | After erasure the `auth.users` row of a **learner** can be deleted (no remaining social FK) | S1 |

## G. API — authentication, authorisation, validation

| Id | Test | MS |
|---|---|---|
| API-A01 | Every `/v1/social/*` route without a token, with an expired token, with a project key → `401`, no database work | S2 |
| API-A02 | Each `403` code in doc 04 is produced by the matching situation, with the standard error shape and `request_id` | S2 |
| API-A03 | Uniform not-found: unknown id, pending post, removed post, other community, blocked author → identical status and body | S2 |
| API-A04 | Requests containing `user_id`, `author_id`, `status`, `published`, `comment_count` → `422`; none is ever honoured | S2 |
| API-A05 | Identity isolation on one pooled connection: A → nobody → B, after an SQL error, after an exception (same design as the existing pool test), for pools B and C | S2 |
| API-A06 | Suspension, consent withdrawal and staff-role removal apply on the next request with a still-valid token | S2 |
| API-M01 | A learner token on any moderation or admin route → `403`; the request never reaches pool C functions | S2 |
| API-M02 | A staff token **without** the second-factor claim → `403` | S2 |
| API-M03 | A staff token whose role was deactivated a second ago → `403` | S2 |
| API-M04 | Moderation responses never contain a reporter's identity; the safety-lead reveal writes an audit row | S2 |
| API-V01 | Text limits: 2000 / 1000 / 500 / 40 characters; empty after cleanup → `content_not_allowed` | S2 |
| API-V02 | Unknown fields, wrong types, non-UUID ids → `422` without echoing input | S2 |
| API-V03 | Markup and script-like text is stored and returned byte-for-byte as text, with JSON content type | S2 |
| API-V04 | Submission returns `202` with `pending_review`; the post is absent from every feed for every other account | S2 |
| API-V05 | Body-size and gzip-bomb limits apply to social routes | S2 |
| API-L01 | Logs captured during a run of the suite contain no submitted text and no token | S2 |
| SEC-01 | "Arbitrary SQL as the member role": a list of statements that must **all** fail with `42501` — insert a published post, update a status, insert an approval, delete a report, read `staff_roles`, read `audit_events`, read `app.practice_attempts`, call `mod_decide`, call `erase_user`, call `run_retention`, read `auth.users` | S2 |
| SEC-02 | The same list for the moderation role, minus what it may do, plus: update or delete a `moderation_actions` row, insert into `staff_roles`, read `app.*` | S2 |

## H. API — retries, limits, pagination

| Id | Test | MS |
|---|---|---|
| API-I01 | Same `client_op_id` twice → one row, second answer `replayed: true` | S2 |
| API-I02 | Twenty concurrent identical submissions → one row, one queue item | S2 |
| API-I03 | Same `client_op_id`, different text → `409`, nothing written | S2 |
| API-I04 | The commit succeeds but the answer is lost (injected failure after commit) → the retry returns the original | S2 |
| API-I05 | A retry of an accepted submission after the author was muted still returns the original answer | S2 |
| API-O03 | A submission made "offline" and sent after a suspension is refused with `social_suspended` | S2 |
| API-R01 | 6th post in a day → `429` with `Retry-After`; counters survive because the refusal is committed | S2 |
| API-R02 | 4th post while 3 wait for review → `429 pending_limit_reached` | S2 |
| API-R03 | A refused request commits its counter (mutation check: make the API roll back on refusal → this test fails) | S2 |
| API-R04 | 6th join attempt in an hour → `429`, including when all five were wrong codes | S2 |
| API-R05 | Global switch off → all writes `403 submissions_closed`, all reads still work; frozen community likewise | S2 |
| API-P01 | Feed pagination returns every published post exactly once while posts are approved and removed between pages | S2 |
| API-P02 | Page size is capped at 20 (feeds) / 50 (lists) | S2 |
| API-P03 | `If-None-Match` → `304` when nothing changed; `200` after any visibility change; never a `304` for another account's `ETag` | S2 |
| API-P04 | Cursor of another account, garbage, oversized → `410`; a hand-edited cursor never returns a row the caller cannot see | S2 |
| API-P05 | `updates`: a removed post appears with `visible: false`; more than 200 changes → `cache_reset: true` | S2 |
| API-C04 | Invite codes: digest stored, clear code returned once, never present in any later response or log | S2 |
| API-C05 | All invite failures are indistinguishable (status, body) | S2 |
| API-C06 | A revoked or expired code stops working immediately | S2 |
| API-S06 | Reporting: answer is identical whether or not the content was hidden | S2 |
| API-S07 | No endpoint reveals whether the caller is blocked by someone | S2 |

## I. Local text screen (unit tests, no database)

| Id | Test | MS |
|---|---|---|
| SCR-01…04 | Phone numbers in Haitian and international formats, with spaces, dots, dashes; e-mail addresses; links with and without scheme; bare domains → refused with the right rule | S2 |
| SCR-05…08 | Handles (`@name`), names of messaging apps → refused or flagged as specified; ordinary numbers in maths text ("x + 5 = 12", "en 1804", "25 000 gourdes") are **not** refused | S2 |
| SCR-09…12 | Normalisation: NFC; zero-width and direction-override characters removed; spaced-out and look-alike spellings still match the word list; whitespace collapsed | S2 |
| SCR-13 | French and Creole word lists: every entry matches itself; a list of ordinary school sentences in both languages produces zero flags (false-positive guard) | S2 |
| SCR-14 | The screen can refuse or flag; **no input produces an "approved" outcome** (type-level and property test) | S2 |
| SCR-15 | The screen makes no network call (socket use fails the test) | S2 |

## J. Performance and size

| Id | Test | Threshold (to confirm) | MS |
|---|---|---|---|
| PERF-01 | Feed page with 100 000 posts across 50 communities, caller in 10 | p95 < 60 ms in the database; query plan uses `idx_posts_feed` | S2 |
| PERF-02 | Comment page on a post with 5 000 comments | p95 < 40 ms | S2 |
| PERF-03 | 50 concurrent feed readers do not increase learning-sync latency (separate pools) | no measurable change | S2 |
| PERF-04 | Reading an entire community through the API takes the expected number of pages (no bulk path exists) | — | S2 |
| PERF-05 | Response sizes with realistic synthetic text | within the budgets of doc 07 | S2 |
| PERF-06 | `mod_claim_next` with 20 000 open items | p95 < 20 ms | S2 |

## K. Mobile (Social-03)

| Id | Test |
|---|---|
| MOB-01 | Social outbox and learning outbox are different tables; the learning engine's module graph contains no social import |
| MOB-02 | Learning sync completes when the social outbox is full, corrupt, or its endpoint fails |
| MOB-03 | Draft written offline → sent once on reconnect → `pending_review`; a lost answer does not duplicate (same `client_op_id`) |
| MOB-04 | A report made offline is sent before queued posts and hides the content locally at once |
| MOB-05 | Post text is rendered as text: markup and URLs are not interpreted or made tappable |
| MOB-06 | `visible: false` and `cache_reset` remove content from the local cache |
| MOB-07 | Sign-out deletes the social cache; the next account on the phone sees none of it |
| MOB-08 | Switching accounts: cursors of the previous account are rejected and discarded |
| MOB-09 | Every state in the failure table of doc 07 has a rendered screen with French and Creole text (snapshot per state) |
| MOB-10 | Cache older than 7 days is hidden; storage cap evicts social data before any lesson data |
| MOB-11 | With `not_enrolled`, no community entry point is rendered and no social call other than `me` is made |
| E2E-01 | Enrolled learner: open community from Accueil, read feed, open post — the four tabs are unchanged |
| E2E-02 | Write a post → "en attente de validation" → (moderator approves by script) → visible to a second account |
| E2E-03 | Offline: write a post, restart the app, reconnect → sent once |
| E2E-04 | Report and block from the item menu in two taps; content disappears |
| E2E-05 | Muted learner: composer disabled with the reason |
| E2E-06 | Reporting `self_harm` offline shows the help text immediately |
| E2E-07 | Kreyòl: all social screens in Haitian Creole |

## L. Continuous integration

- The social pgTAP and pytest files run in the existing job; no new job.
- A new static step (S1): fail if any file under `supabase/migrations/` with
  `social` in its name contains `app.`, and if any other migration contains `social.`.
- A new static step (S2): the import rule (API-B01).
- Coverage expectation: every row of the permission matrix (doc 05) and every
  threat in doc 06 names at least one test id from this document; a script
  checks that the ids referenced there exist here.
