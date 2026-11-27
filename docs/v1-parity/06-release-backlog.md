# Dependency-ordered v1 release backlog

Small, independently reviewable PRs. Everything behind default-off flags until its gate passes. "Blocked by" names an owner decision (OD, see `README.md`) or another item.

## Track 0: unblock (owner actions, no engineering)

| # | Item | Unblocks |
|---|---|---|
| OD-1 | Identity continuity: link existing accounts (recommended) vs re-register | All migration work |
| OD-2 | Status of legacy content on import: draft until human review (recommended) | Curriculum volume and schedule |
| OD-3 | Name reviewers: subject teachers and a native Creole speaker | Any approved content; Jude |
| OD-4 | Community model (see `05-…`) | All social engineering |
| OD-5 | Legal: minors' consent, data migration basis, third-party AI processing | Identity, Jude, social |
| Gate 0 | Jude: provider, data terms, limits, safeguarding path | Live Jude |
| Counts | Run the aggregate inventory queries on the legacy database | Sizing of curriculum, exams, social |
| Infra | Approve hosted staging (accounts, budget) | Device pilot, provider secrets |
| Repo | Make `content-pilot / verify` and `platform-staging-00` required checks; protect `main` | Trustworthy merges |

## Track 1: consolidate what is already built (review and merge debt)

39 draft PRs are open; several stacks are far behind `main`. This is the biggest schedule risk after the owner decisions.

| # | Item | PRs | Blocked by |
|---|---|---|---|
| 1.1 | Content validator stack | #31 → #37 → #41 | Independent retest of `d33edb6` |
| 1.2 | Staging stack | #33 → #39 → #42 → #46 | Independent review of `1e42eaf` |
| 1.3 | Staff boundary, roles, worker (base of the overnight stack; 60 commits behind `main`) | #4 (+#17), then re-cut #5, #6, #7, #10, #12, #13 onto `main` one lane at a time | Rebase and re-verify; #21's corrected candidate is the reference |
| 1.4 | Jude engine | #28 + #43, then #35 rebased | Re-review of #43 |
| 1.5 | Mobile-03 polish | #32 | Device validation (Claude #2) |

## Track 2: shared foundations (engineering, in dependency order)

| # | Item | Depends on | Notes |
|---|---|---|---|
| **S-1** | **ExamHub first workflow: catalog → attempt → answers → server scoring → explanation → history** | `main` only | **Implemented now as the first slice** (separate draft PR). Chosen because it is the largest P0 gap with no owner-decision blocker, it replaces a client-trusted legacy flow with a server-authoritative one, and its attempt/answer/scoring contracts are reused by lesson practice history and Jude's exam-review context |
| S-2 | Lesson format v2: maths, images, tables, audio | #7/#18 (1.3) | Prerequisite for importing real lessons |
| S-3 | Legacy id columns and import batches on content tables | S-2 | `legacy_id`, `import_batch`, deterministic ids |
| S-4 | Content import pipeline (export manifest → normalise → validate → load as draft → report) | S-2, S-3, counts | Synthetic fixtures first; then a real dry-run report with no publication |
| S-5 | Identity map and account link (synthetic rehearsal: link, re-run, detach) | OD-1, OD-5, #5 | No real account until rehearsal passes and the owner authorises |
| S-6 | History attach (legacy completions → `lesson_progress`) | S-4, S-5 | Exceptions visible to staff |
| S-7 | Account functions: sign-up, password recovery, profile edit, deletion | #5 (1.3) | Store requirement |
| S-8 | Notifications: device token registration, push adapter, in-app inbox, account emails | #6 (1.3), provider choice | |
| S-9 | Review workflow at volume: reviewer queue in Admin, connected to the staff API | #4, Admin-01 | Without this, OD-3 reviewers have no tool |

## Track 3: feature completion

| # | Item | Depends on |
|---|---|---|
| E-1 | Exam import (legacy exams and exercises as drafts; key completeness report) | S-1, S-3, S-4, counts |
| E-2 | Exam screens in the native app (catalog, attempt, review, history; fr + ht) | S-1; coordinate with Mobile-03 owner |
| E-3 | Timed mode hardening (resume, server expiry, single active attempt), PDFs with rights | S-1, rights |
| E-4 | Open-ended answers: self-review now; AI grading only after Jude gates (OD-9) | S-1, J-track |
| C-1 | Curriculum import dry-run per grade, exceptions report | S-4 |
| C-2 | Review and approval, subject by subject; packs | OD-3, S-9 |
| J-1…J-8 | Jude path (`04-jude-live-plan.md`) | Gate 0, 1.4, approved content |
| So-1 | Social-01/02 build for the chosen model | OD-4, OD-5, #4, S-8 |
| G-1 | Gold ledger, streaks, private rank on `main` | 1.3, OD-6 |
| L-1 | Creole UI string review | OD-3 |

## Track 4: release gates

Physical low-RAM Android pass · hosted staging acceptance (TLS, restore drill) · security re-reviews closed · privacy notice and terms in fr/ht · consented pilot group · rollback rehearsed · web prototype kept live until parity is accepted.

## Critical path

`OD-1/OD-2/OD-3 + counts` → `1.3 (staff stack)` → `S-2 → S-3 → S-4 → C-1 → C-2 (review)` → packs → pilot.

**Review capacity (C-2), not engineering, is the long pole** for "complete curriculum 7AF–NS4". Exams (S-1 → E-1 → E-2) and identity (S-5 → S-6) can proceed in parallel once their decisions are made.
