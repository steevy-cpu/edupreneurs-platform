# Platform-00 — Prototype feature and architecture gap audit

**Status: analysis and planning only.** No migration was run, no feature was
implemented, nothing was deployed, and no production data was read or changed.
Every file added by this branch is under `docs/architecture/platform-00/`.

Date: 2026-11-24 · Branch: `platform-00` (from `main`).

## What this is

A map of what the original Edupreneurs prototype (the Lovable web app) contains,
compared with what Edupreneurs 2.0 actually has today, and a prioritised plan
for the missing capabilities that does not weaken the offline-first foundation.

| # | Document | Answers |
|---|---|---|
| 1 | [01-feature-inventory.md](01-feature-inventory.md) | What did the prototype do, domain by domain, and what would each feature need in v2? |
| 2 | [02-gap-matrix.md](02-gap-matrix.md) | One table: prototype status vs v2 status, priority, launch or later |
| 3 | [03-domain-boundaries.md](03-domain-boundaries.md) | Which modules exist, who may talk to whom, where data lives |
| 4 | [04-shared-data-and-dependencies.md](04-shared-data-and-dependencies.md) | The entities several modules need (profile, entitlement, lesson identity, events, notifications) and who owns each |
| 5 | [05-database-migration-sequence.md](05-database-migration-sequence.md) | In what order to add schema, and why that order |
| 6 | [06-backend-roadmap.md](06-backend-roadmap.md) | Milestones with gates |
| 7 | [07-product-owner-decisions.md](07-product-owner-decisions.md) | The choices only the owners can make |
| 8 | [08-launch-readiness-checklist.md](08-launch-readiness-checklist.md) | What must be true before real learners use v2 |
| 9 | [09-risks-of-delay.md](09-risks-of-delay.md) | What it costs to postpone each high-priority architectural decision |

Suggested first read: this page → 07 (decisions) → 02 (matrix) → 09 (risks).

## How the evidence was gathered — and its limits

**Prototype.** Read-only inspection of the project's source: its own
`ARCHITECTURE.md` and `DATABASE.md` (read in full), the routing file, and
targeted reading of migrations, edge functions and frontend code across five
domain groups. About 490 file reads and searches in total.

- The prototype was **not run**, its live site was **not exercised**, and its
  live database was **not queried**. It has real users, many of them minors.
- Therefore **nothing about the prototype is reported as "tested"**. The
  strongest statement made is "present in source and wired end to end".
- The migration files show how the database was *built*; the live database may
  have been changed by hand since. Scheduled jobs in particular were created
  outside the migrations and cannot be confirmed from source.
- The prototype has one automated test file (for the career-orientation
  matching logic) and no continuous-integration configuration.
- Coverage is deep on the questions that drive architecture (who decides a
  score, where paid access is enforced, how a lesson is identified) and
  shallower on screens. Files that were not opened are named in the inventory
  as open questions rather than guessed at.

**Edupreneurs 2.0.** Read from `main` of this repository, with its test
reports. "Tested" below means covered by the automated suites that run in CI
on `main` (209 database tests, 144 API tests, 52 mobile tests) or by the
recorded emulator/simulator validation runs.

**Work in progress elsewhere, not on `main`:** Mobile-02 (redesigned student
screens) and Social-00 (community architecture design, draft pull request #1).
Neither branch was modified. They are referenced, not re-audited.

## Status vocabulary used in every document

| Label | Meaning |
|---|---|
| **Existing and tested** | Implemented, and covered by automated tests or a recorded validation run. *Only v2 items can have this label.* |
| **In source, unverified** | Code for the whole path (screen, server logic, storage) is present; behaviour was not observed |
| **Partially implemented** | Some of the path is present; the missing part is named |
| **Planned but missing** | Named in documentation, a schema, or a roadmap, but no working implementation was found |
| **Deliberately deferred** | A recorded decision not to build it yet |
| **Not present** | No trace found |

## Headline findings

1. **The prototype is broad and thin.** It has roughly 96 tables, 87 server
   functions and 15 storage buckets across 18 feature areas. Edupreneurs 2.0
   has 22 tables and 6 endpoints covering one area deeply: offline lessons,
   practice and sync. The gap is real, but most of it should not be closed by
   copying.

2. **The prototype trusts the browser; v2 trusts nothing from the device.**
   In the prototype the browser decides scores, awards points, declares game
   results and holds the paywall. v2's core rule is the opposite: the server
   computes the score and is the only writer of learning records. Every
   prototype feature that depends on a number the device reports — points,
   streaks, leaderboards, battle results, exam scores, paid access — has to be
   **redesigned**, not ported.

3. **The prototype's paywall is switched off, and was never enforced on the
   server.** One plan exists (30 days). Paid access is checked only in the
   web page. v2 has no billing at all. Entitlement is therefore the largest
   missing cross-cutting capability, and it interacts directly with offline
   downloads (see 04 and 09).

4. **Prototype lesson content cannot be imported as data.** Lessons are HTML
   with presentation classes, mathematics is detected by guesswork at display
   time, quizzes exist in three formats and are usually regenerated by AI for
   each student, and progress is keyed by a text slug. v2 uses reviewed,
   versioned, per-language blocks with independent questions. Moving content
   across is an **editorial conversion and review project**, and v2's block
   format must first grow (mathematics, images, lists, tables, audio).

5. **The prototype is not offline-capable in any strong sense.** It caches the
   last lessons viewed and shows an "offline" page otherwise. There is no
   lesson download, no offline answers, and no native app (only a wrapper
   configuration). v2 is ahead here, and that advantage is the thing to protect.

6. **Several prototype features are heavier on risk than on value for a first
   release** — open direct messages between minors, an unmoderated public feed,
   real-time multiplayer, AI endpoints with no spending limit. The
   recommendation is to defer or redesign them (Social-00 already does this
   for the community).

7. **Three capabilities block everything else in v2** and should be built
   before any new learner-facing feature: a staff content pipeline (today
   content enters only through seed files), a hosted staging environment with
   the privacy basics (consent, deletion, retention), and the entitlement model.

8. **Weaknesses in the live prototype were observed while reading its source.**
   This repository is public, so they are described here only as *classes of
   requirement* for v2. The specifics were given to the owners privately and
   are not in this pull request.
