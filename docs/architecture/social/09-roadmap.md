# 9. Phased implementation roadmap

Five milestones. Each has **deliverables**, **dependencies**, **safety
prerequisites** (things that must be true before the milestone may *start
exposing anything to learners*) and an **acceptance gate** (what must be
demonstrated, with evidence, before the next one begins).

No dates are given: the order and the gates matter, and several gates depend on
answers from outside the team (legal advice, a partner school).

```
 Social-00  design                      ← this pull request
     │  gate: decisions D-01…D-06 made, legal questions sent
 Social-01  database, local only        no API, no app, no learner
     │  gate: all database tests green, learning suite unchanged
 Social-02  API + moderation console    switched off by default, synthetic data only
     │  gate: full test suite, safety prerequisites P-1…P-9 closed
 Social-03  mobile + closed pilot       one school, a few class groups, real learners
     │  gate: pilot review against agreed measures
 Social-04  measured expansion          each addition gated separately
```

## Prerequisites outside the social module

These are existing gaps (from `docs/SECURITY.md` and `docs/NEXT_STEPS.md`) that
the social module depends on. They are listed here so they are not discovered late.

| Id | Prerequisite | Needed before | Why |
|---|---|---|---|
| P-1 | A hosted staging environment exists and is reachable only by the team | Social-02 gate | Nothing social can be tried with a real phone otherwise |
| P-2 | General rate limiting at the gateway (per IP and per account) | Social-02 gate | `docs/SECURITY.md` item 1; the in-database limits cover social writes only |
| P-3 | Transaction-mode pooler tested with three pools and `EDU_DB_DISABLE_STATEMENT_CACHE=true` | Social-02 gate | `docs/SECURITY.md` item 5 |
| P-4 | Staff authentication with a second factor; staff accounts separate from learner accounts | Social-02 gate | Moderators read unpublished children's text |
| P-5 | Account provisioning process for learners and teachers (public sign-up stays off) | Social-03 start | Enrolment needs real accounts tied to a school |
| P-6 | Account deletion procedure for the **learning** side (the social half is `erase_user`) | Social-03 start | Required by both app stores and by data-protection principles; `docs/SECURITY.md` item 9 |
| P-7 | Backups and a tested restore | Social-03 start | Moderation evidence and audit records must not be lost |
| P-8 | Privacy notice and terms that cover the community, in French and Haitian Creole | Social-03 start | Store requirement; legal |
| P-9 | Answers to legal questions L-1 … L-6 (doc 11) | Social-03 start | Consent model, reporting duties, retention periods |

## Social-00 — Design (this branch)

| | |
|---|---|
| **Deliverables** | The documents in this folder: decision record, ERD and dictionary, proposed SQL (parsed, not run), OpenAPI draft, permission matrix, moderation workflow and threat model, bandwidth strategy, test specification, this roadmap, risks |
| **Dependencies** | None |
| **Changes to running code** | None |
| **Acceptance gate** | (1) The founder has read docs README, 10, 01, 06 and recorded a decision on D-01 to D-06. (2) Legal questions L-1 to L-6 have been sent to counsel. (3) A second technical reviewer has read the SQL and doc 05. (4) This pull request stays a draft until then; it is merged only as documentation |

## Social-01 — Database, local only

| | |
|---|---|
| **Goal** | Prove the data model and the boundary on a disposable local database |
| **Deliverables** | The six migrations adopted into `supabase/migrations/` (after review fixes); the specified admin functions needed for fixtures; pgTAP files for groups B–F of doc 08; synthetic seed (2 communities, 6 learners, 1 teacher, 3 staff); `scripts/local_stack.py` creates the three login roles; the two static CI checks |
| **Dependencies** | Social-00 gate. Mobile-02 is independent and unaffected: no file under `apps/` changes |
| **Safety prerequisites** | None — no learner can reach anything |
| **Acceptance gate** | (1) NR-01: the existing suite passes with **no existing test file edited**. (2) Every S1 test in doc 08 passes twice in a row from a fresh `make db-reset`. (3) The mutation checks turn the named tests red. (4) DB-C11 (ordering under concurrency) and DB-C12 (counter consistency) pass 50 consecutive runs. (5) A `TEST_REPORT`-style page records commands and observed output. (6) Still no `/v1/social` route exists |
| **Explicitly not in scope** | Any API route, any mobile code, any hosted database |

## Social-02 — API and moderation, switched off by default

| | |
|---|---|
| **Goal** | A complete, tested server — usable only by the team, with synthetic data |
| **Deliverables** | `edu_api.social` package: member routes, moderation routes, admin routes; pools B and C; the local text screen with French and Creole word lists; cursors, `ETag`s, response compression; the remaining specified functions (admin, escalation close, reporter reveal); a minimal moderation console (one item at a time; no bulk actions); retention job runnable by hand; OpenAPI regenerated; `docs/API_CONTRACT.md` and `docs/SECURITY.md` updated |
| **Dependencies** | Social-01 gate; P-1 to P-4 |
| **Safety prerequisites (must be closed before the gate, not before the start)** | Community rules written in French and Haitian Creole and reviewed by an educator · reason-code texts written · moderator handbook and incident runbook written · a named safety lead and backup · word lists reviewed by a Creole-fluent person · decision D-06 confirmed (no third-party AI) |
| **Acceptance gate** | (1) All S2 tests pass; NR-02 and NR-03 show nothing changes while the setting is off. (2) SEC-01 and SEC-02 pass. (3) PERF-01 to PERF-06 measured and recorded (thresholds confirmed or revised with reasons). (4) A scripted end-to-end run: enrol → join → post → approve → comment → report → auto-hide → remove → sanction → appeal → erase, with the audit trail printed. (5) A **tabletop exercise**: the team walks through one bullying case and one child-safety case using the console and the runbook, and writes down what was unclear. (6) `EDU_SOCIAL_ENABLED` is still false in every environment a learner can reach |
| **Explicitly not in scope** | Mobile screens; real learners; guardianship routes; media; messaging |

## Social-03 — Mobile integration and closed pilot

| | |
|---|---|
| **Goal** | Real learners, in a setting small enough to watch closely |
| **Deliverables** | React Native screens (see below); social cache and social outbox; all failure states; French and Creole strings; scheduled retention job; open-hours switch; queue alerts; `GET /moderation/metrics`; social erasure wired into account deletion; store listings updated (age rating answers, child-safety declarations, privacy details) |
| **Pilot shape** | One partner school with a written agreement · 3–5 **class groups** led by their own teacher (no subject forums yet) · about 150 learners · NS1–NS4 first unless D-02 says otherwise · a fixed 6–8 week period · consent recorded per learner |
| **Dependencies** | Social-02 gate; Mobile-02 merged (the screens use its design components); P-5 to P-9 |
| **Safety prerequisites** | Two trained moderators on a written rota · safety lead reachable during open hours · school contact named · families informed in writing · published contact address for safety concerns live · help resources for self-harm/abuse confirmed locally (D-11) · internal testers used the app for two weeks first · kill switch tested in staging |
| **Acceptance gate** | (1) All mobile tests in doc 08 pass on Android and iOS, including NR-04/05. (2) Measured data use within doc 07's budgets on a real low-end Android phone on mobile data. (3) Pilot measures, agreed **before** the pilot starts: median review time ≤ 4 h and no item over 24 h in open hours · every severe report reviewed within 4 h · zero items published without an approval record (checked by query) · weekly sampling of approvals finds ≤ 2 % that the safety lead would have rejected · no learning-sync regression. (4) A written pilot review with teachers and a sample of learners and parents: did it help learning, what worried anyone. (5) An explicit decision to continue, change, or stop |
| **Stop conditions during the pilot** | Any confirmed child-safety incident that the process handled badly · the queue older than 24 h on two days in a week · moderators unavailable · the school asks → freeze immediately (one setting), review, then decide |

## Social-04 — Measured expansion

Not one release: a menu. Each item ships alone, behind its own switch, after
its own gate. Order is a recommendation.

| Item | What | Its own gate |
|---|---|---|
| 4a · More schools and groups | Same feature, more class groups | Moderator hours available per doc 06 arithmetic; alerting proven in the pilot |
| 4b · Teacher first-line approval (D-04) | A group's teacher may approve posts of their own class; reports, removals and sanctions stay central; a teacher never approves their own post | Vetting and written agreement per teacher; sampling of teacher approvals by moderators; new tests for the scoped permission |
| 4c · Guardian tools | `adult_links` verification, the three guardianship routes, in-app consent | Legal answer on consent (L-2); a way to verify that an adult is the guardian |
| 4d · Subject forums across schools | `subject_forum` communities listed to a grade band | Only after 4a and 4b are stable: strangers from different schools meet here, so the risk is higher |
| 4e · Content-free push notifications | "Tu as du nouveau" with no text | Privacy review; opt-in; quiet hours |
| 4f · Lesson-linked questions | "Poser une question à la classe" from a lesson screen; the post stores the public lesson id only | Combined in the API with two queries on two pools; no SQL bridge; new boundary tests |
| 4g · Images (`F002_media.sql`) | One compressed image per post | D-09, D-10; store and legal review; storage enabled; human review of every image |
| 4h · Messaging (`F001_direct_messaging.sql`) | Small-group or direct messages | D-07, D-08; **recommendation: do not build for minors**; if ever, group conversations inside a class with the teacher present come first |
| 4i · Short-lived live session | Step C of doc 07 | Measured data and battery cost |
| — | Jude in the community | Not planned. Requires the privacy and permission review of D-06 first |

## Mobile integration without changing the four tabs

The tab bar stays **Accueil · Apprendre · Réviser · Profil** (recorded in
`docs/design/` on the `design-00` branch and implemented in Mobile-02). The
community is reached *from* existing destinations, never from a fifth tab.

| Entry point | Where | Shown when |
|---|---|---|
| "Ma classe" card | On **Accueil**, below the learning cards | `GET /v1/social/me` says `active`; shows the group name and an unread dot — no post text on the home screen |
| "Communauté" section | In **Profil** | Enrolled: display name and avatar, safety settings, blocked people, my messages and their status, the rules, how to report a problem |
| "Poser une question à la classe" | On a lesson screen (later, item 4f) | Enrolled and member of a class group |

Screens are **full-screen steps on the existing stack**, exactly like the
lesson and exercise screens today (back button, no tab bar):

```
src/app/community/index.tsx          my communities + join with a code
src/app/community/[id].tsx           the feed of one community
src/app/community/post/[id].tsx      a post and its comments
src/app/community/compose.tsx        write a post / comment / reply
src/app/community/mine.tsx           my messages and their status
src/app/community/rules.tsx          the rules (accept once per version)
src/app/community/report.tsx         report sheet
```

- Adding these routes means adding `Stack.Screen` entries in `_layout.tsx`;
  no existing route, tab or screen is modified.
- Code lives in a new `src/core/social/` (API client, cache store, outbox
  engine, states) and uses the Design-00 components (`ScreenFrame`, `TopBar`,
  `MessageState`, `LoadingState`, buttons, text styles). No new visual language.
- Strings go in the single string catalogue, French and Haitian Creole, as today.
- If the learner is not enrolled, nothing is rendered and nothing is called
  beyond `GET /v1/social/me` (test MOB-11). A learner outside the pilot sees
  exactly the app they have now.
- **Coordination with Mobile-02:** that branch is in progress and was not
  touched. Social-03 starts only after it is merged, so the two never edit `_layout.tsx` at the same time.

## What each milestone leaves untouched

| | Social-00 | Social-01 | Social-02 | Social-03 |
|---|---|---|---|---|
| `app` schema and its migrations | untouched | untouched | untouched | untouched |
| Existing API routes and their behaviour | untouched | untouched | untouched (new routes only, behind a setting) | untouched |
| Learning sync engine and outbox | untouched | untouched | untouched | untouched (new, separate engine) |
| Four-tab navigation | untouched | untouched | untouched | untouched (new stacked screens) |
| Production | does not exist | does not exist | setting off | on only for pilot accounts |
