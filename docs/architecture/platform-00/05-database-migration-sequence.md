# 5. Suggested database migration sequence

**Nothing here was written as SQL or executed.** This is the proposed *order*
of future schema changes and the reasoning for it. Each step becomes its own
reviewed design and its own milestone (doc 06) before any migration exists.

It is a sequence for the **new** database. The prototype's database is not
copied, migrated or connected at any step (blueprint ADR-008).

## Principles

1. **Additive only.** The four existing migrations and their 209 tests are not
   edited. New steps add tables, columns with defaults, functions and grants.
2. **The sync contract never breaks.** New kinds of learner action are added
   as new operation kinds in the existing push/pull contract. Installed apps
   that do not know a kind keep working.
3. **Content format changes are versioned.** Old packs stay readable; a phone
   declares which format versions it understands.
4. **One trust boundary per schema** (doc 03). A new schema arrives with its
   role, its policies, its erase function and its isolation tests in the same step.
5. **Decide before you build:** steps marked ◆ are blocked on a product-owner
   decision (doc 07).

## The sequence

| Step | Adds | Schema | Blocked on | Why here |
|---|---|---|---|---|
| **M-01** | Profile editing: column-level update rights for grade, language, display name; a `profile_updated` operation so it works offline | `app` | — | Smallest useful change; needed by onboarding and by Mobile-02's Profil tab |
| **M-02** | Privacy basics: consent records (what, which version, who gave it), age band, deletion requests, export requests, retention settings; the erasure orchestrator and the learning module's erase function | `app` | ◆ PO-04, legal | Nothing with real learner data may precede this. It also removes the "accounts cannot be deleted" limitation |
| **M-03** | Audit writes: server code starts writing `audit_events` for sync conflicts, staff actions and access changes | `app` | — | The table exists and is empty. Every later step relies on it |
| **M-04** | Staff boundary: a staff database role with exactly the rights the editorial workflow needs; staff-role grant process; worker role and job leasing (claim, lease, retry, dead-letter) on `background_jobs` | `app` | — | Unlocks content at scale, packs, and every background task |
| **M-05** | Content format v2: new block types (mathematics, image, list, table, audio reference, video link); question kinds `true_false`, `numeric`, `short_text`, matching — each with a versioned scoring rule; `content_assets` (object key, size, hash, rights) | `app` | ◆ PO-08 | Must precede bulk authoring: every lesson written before it would need rewriting |
| **M-06** | Real packs: complete pack tables (true hashes, sizes, asset lists), release pointer rules, format version per pack | `app` | — | Depends on M-04 (worker) and M-05 (assets) |
| **M-07** | Bac series/tracks on courses | `app` | — | Small; needed before upper-secondary content and exams |
| **M-08** | Entitlements: `billing` schema — plans, orders, provider events, entitlements, refunds; the "is entitled" function; entitlement-aware catalogue and pack download; the offline lease | `billing` (+ one read function used by `app`) | ◆ PO-01, PO-05, PO-06, PO-07 | The largest cross-cutting step. Placed after packs because it changes how packs are fetched, and before payments, Jude and paid exams, which all read it |
| **M-09** | Payments: provider integrations write `billing` only through the event pipeline; staff grant and refund actions | `billing` | ◆ PO-01, PO-06 | Separate from M-08 so the model can be tested with staff-issued grants before any money moves |
| **M-10** | Rewards: reward ledger, streak state, achievement definitions and awards; the sync write function calls the award rules | `app` | ◆ PO-09 | Independent of billing; can move earlier if wanted. Kept after M-05 so new question kinds have point rules from the start |
| **M-11** | Learning extras: reading position, notes and goals as operation kinds; progress snapshot and feed compaction | `app` | — | Cheap; the snapshot becomes necessary as operation kinds multiply |
| **M-12** | Notifications: `notify` schema — outbox, deliveries, push tokens, preferences | `notify` | ◆ PO-10 | After the worker; before anything that wants reminders or receipts by push |
| **M-13** | Exams: exam papers as publishable content built from question revisions; exam-session operations; marking guides for open-ended questions | `app` | ◆ PO-02, rights | Needs format v2, packs and the staff pipeline. Earlier if exam candidates are the launch audience |
| **M-14** | Library and enrichment: books and career-orientation content as pack assets; reading position reuse | `app` | rights | Reuses M-05/M-06 |
| **M-15** | Tutor: `tutor` schema — usage, budgets, kill switch, optional threads | `tutor` | ◆ PO-11, legal | After entitlements and privacy |
| **M-16** | Community: the six files proposed by Social-00 | `social` | Social-00's own decisions | Independent of M-05…M-15; ordered last only because the product does not depend on it |
| **M-17** | Games: asynchronous challenges (in `app`); a `games` schema only if real-time play is approved | `app` / `games` | ◆ PO-12 | A leaf |

## Dependency view

```
M-01 profile edit ─┐
M-02 privacy ──────┼─────────────────────────────────────────────► (gate: real learners)
M-03 audit ────────┤
M-04 staff+worker ─┼─► M-05 format v2 ─► M-06 packs ─► M-07 series ─► M-13 exams
                   │                        │                         M-14 library
                   │                        └─► M-08 entitlements ─► M-09 payments
                   │                                    └──────────► M-15 tutor
                   ├─► M-10 rewards        (needs only sync)
                   ├─► M-11 learning extras
                   └─► M-12 notify ───────► receipts, reminders
M-16 social   (independent; per Social-00)
M-17 games    (leaf)
```

## What each step must leave untouched

| Existing guarantee (tested today) | Steps that could threaten it | Protection |
|---|---|---|
| The student API role cannot write learning tables | M-01, M-10, M-11 | New writes go through the sync function or column-level grants; the "arbitrary SQL cannot forge state" test list grows with each step |
| A learner sees only their own rows | every step | Each new table ships with isolation tests in the same step |
| Approved content never changes; reviewer ≠ author | M-04, M-05, M-13 | Triggers apply to the staff role too; exam papers reuse the same revision rules |
| Students see only approved content in a current pack | M-06, M-08 | Entitlement is an **additional** condition in the visibility chain, never a replacement |
| Sync is exactly-once and commit-ordered | M-10, M-11, M-13 | New operation kinds are handled inside the same locked function |
| `app` is not reachable through the auto-generated data API | every new schema | Same test repeated per schema |
| Lessons work when everything else is down | M-08, M-12, M-15 | Separate pools; no external call on a learning request; chaos-style tests (billing down, notify down) |

## Database redesign risks

Places where choosing wrong now would force a painful change later.

| Risk | If we get it wrong | Avoided by |
|---|---|---|
| Putting entitlement or points on the profile row | The prototype's situation: one editable row holding money and identity; no history; every special case is a new column | Grant rows in `billing`; ledger rows in `app` (doc 04) |
| Content format frozen too early or too late | Too early: no mathematics → workarounds baked into text. Too late: hundreds of lessons to rewrite | Decide M-05 before bulk authoring; version the format |
| Slugs or titles used as identity anywhere new | Renames orphan progress, audio and notes (seen in the prototype) | Ids everywhere (doc 04, 4.4) |
| Entitlement scope too coarse or too fine | Too coarse (`all` only): cannot sell per grade or license a school later. Too fine (per lesson): catalogue and packs become complicated | A `scope` column from day one, even if the only value used at first is `all` |
| Rewards as a running total | Cannot correct a rule, cannot detect abuse, cannot explain a number to a learner | Ledger tied to the earning event |
| Exams modelled as a separate content system | Two editors, two review flows, two pack formats | Exam paper = content built from question revisions |
| A second way to get data onto the phone | Each one needs its own offline, retry and account-switch logic | Packs or the sync feed only (doc 03, rule 5) |
| Notification rows writable by clients | Spoofed messages to minors | Server-only outbox |
| Personal data collected "in case" | Legal exposure for minors; harder deletion | Add a column only with a feature and a legal basis |
| No erase function per module | Account deletion becomes impossible to complete (true of v2 today) | M-02 first; rule 7 in doc 03 |
| Time zone for "a day" left implicit | Streaks reset in the evening (seen in the prototype) | One declared product time zone, stored, tested |
| Money stored as floating numbers or without currency | Rounding disputes | Integer minor units + currency code |
| School or class tenancy bolted on later | Every table needs a new column and policy | Decide PO-13 before M-08; if schools are likely, entitlement source `school_licence` and Social-00's communities already carry most of it without a tenant column |

## On migrating data from the prototype

Recommended position, restating ADR-008 with what this audit found:

| Prototype data | Recommendation | Reason |
|---|---|---|
| Accounts and passwords | Do not copy. Invite users to create a v2 account | Custom verification and recovery flows; unknown account quality |
| Profile details | Do not copy. Ask again for grade and language only | Minimisation; consent was never recorded |
| Lesson text | **Convert through the staff pipeline**, lesson by lesson, with human review | HTML with styling classes; mathematics not marked up; no per-language versions; AI-published without review |
| Quizzes and activities | Re-author as fixed question revisions | Three formats; usually regenerated per student |
| Exam papers | Convert through the pipeline after rights are confirmed | Structured enough to be a useful starting draft |
| Progress, completions | Do not copy | Keyed by slug; device-reported |
| Gold, streaks, rankings | Do not copy as balances. Optionally grant a one-time "founding learner" badge | Device-requested totals with no history |
| Subscriptions | Honour remaining paid time as a `migration` entitlement, verified against payment records by staff | Fair to payers; small volume |
| Posts, messages, follows | Do not copy | Unmoderated content among minors |
| Payment records | Keep in the old system for accounting; do not import | Not needed by v2 |

Any conversion tooling works from **exports reviewed by a person**, never from
a live connection between the two systems.
