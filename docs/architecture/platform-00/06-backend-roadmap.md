# 6. Proposed backend implementation roadmap

Milestones in order, each with what it delivers, what it depends on, and an
**acceptance gate** — evidence required before the next one starts. No dates:
several gates depend on decisions and on people outside engineering.

This roadmap is for the backend and platform. Mobile-02 (screens) and
Social-00 (community design) run on their own tracks and are shown only where
they connect.

## Overview

```
 NOW ── Platform-00  this audit ───────────────────────────── gate: decisions PO-01…PO-08

 TRACK A  foundations (no learner-visible change)
   Platform-01  profile edit, audit writes, privacy basics
   Platform-02  staging environment, rate limiting, backups, staff sign-in
   Platform-03  staff role + worker + job leasing
   Platform-04  content format v2 + assets
   Platform-05  pack builder + object storage + integrity on device

 TRACK B  content (people, not code)
   Content-01   minimal staff authoring and review tool
   Content-02   first reviewed course(s) in French and Creole
                                              ══► LAUNCH GATE (free pilot)

 TRACK C  access and money
   Platform-06  entitlement model + offline lease (staff-granted only)
   Platform-07  payments: mobile money first
                                              ══► PAID LAUNCH GATE

 TRACK D  engagement and depth (order adjustable)
   Platform-08  rewards ledger and streaks
   Platform-09  learning extras: reading position, notes, snapshot
   Platform-10  notifications: outbox and push
   Platform-11  exams
   Platform-12  library and career orientation
   Platform-13  Jude
   Social-01…   per Social-00
   Platform-14  games (asynchronous first)
```

Tracks A and B run in parallel after Platform-03. Track C can start as soon as
its decisions are made; it does not block a free pilot.

## Track A — Foundations

### Platform-01 · Profile, audit, privacy basics
| | |
|---|---|
| Delivers | `PATCH /v1/me` (grade, language, display name) and the matching offline operation; server writes audit events; consent records, age band, deletion and export requests; erasure for the learning module; retention job design |
| Migrations | M-01, M-02, M-03 |
| Depends on | Decision PO-04; first answers from legal counsel |
| Connects to | Mobile-02 Profil tab (needs the edit endpoint) |
| Gate | Existing 405 tests unchanged and green · a learner account with learning data can be fully erased, proven by test · every new table has isolation tests · consent cannot be skipped by calling the API directly |

### Platform-02 · A real environment
| | |
|---|---|
| Delivers | An Edupreneurs-owned staging project (never the prototype's); migrations applied by CI; API role provisioned out of band; rate limiting at the gateway; structured logs without personal data; backups and one restore drill; staff accounts with a second factor |
| Migrations | none |
| Depends on | Hosting decisions already recorded in the blueprint |
| Gate | The whole suite passes against staging in an explicit staging mode · the pooler works with transaction-scoped identity (open item in `docs/SECURITY.md`) · a restore from backup has been performed and timed · the app on a **physical low-end Android phone** completes the offline workflow against staging |

### Platform-03 · Staff boundary and worker
| | |
|---|---|
| Delivers | Staff database role and `/v1/staff` skeleton; role grants by audited process; worker process with claim/lease/retry/dead-letter; schedules kept in the repository |
| Migrations | M-04 |
| Gate | The editorial rules already enforced by triggers are exercised through the API, not fixtures · a killed worker's job is retried exactly once · a learner token is refused on every staff route · the student role still cannot do anything new |

### Platform-04 · Content format v2
| | |
|---|---|
| Delivers | New block types and question kinds with versioned scoring; shared test vectors used by both server and phone; `content_assets`; offline mathematics rendering on the reference low-end phone |
| Migrations | M-05, M-07 |
| Depends on | Decision PO-08 |
| Gate | The same answer scores identically on phone and server for every vector · a lesson with mathematics, an image and a table renders on the 1 GB reference device within the existing performance thresholds · an app that only knows format v1 still opens v1 lessons |

### Platform-05 · Real packs
| | |
|---|---|
| Delivers | Pack builder job; object storage; manifest with true hashes and sizes; resumable download, integrity check and atomic activation in the app; storage budgeting |
| Migrations | M-06 |
| Gate | Interrupted download resumes · a corrupted object is rejected and the previous pack stays usable · a full disk fails cleanly · release and rollback of a pack are one audited action each · measured download size per lesson recorded |

## Track B — Content

### Content-01 · Minimal authoring and review tool
| | |
|---|---|
| Delivers | A staff web tool: create or import a lesson in blocks, preview as the phone shows it, submit, review by a second person, record sources and rights, release into a pack |
| Depends on | Platform-03 and -04 |
| Gate | Two people take one lesson from blank to a released pack without touching the database · the tool cannot publish unreviewed text (the database refuses) |

### Content-02 · First real course
| | |
|---|---|
| Delivers | At least one complete course for one grade, in French and Haitian Creole, written or converted from prototype lessons **and reviewed** |
| Depends on | Content-01; decision PO-02 (which audience first) |
| Gate | An educator has signed off every lesson and question · sources and rights recorded · a learner trial on real phones |

## Launch gate (free pilot)

All of: Platform-01 to -05, Content-01 and -02, and the checklist in doc 08.
Entitlements and payments are **not** required for a free pilot (decision PO-01).

## Track C — Access and money

### Platform-06 · Entitlements
| | |
|---|---|
| Delivers | `billing` schema; the "is entitled" function; `GET /v1/entitlements`; entitlement-aware catalogue and pack download; signed offline lease; staff grant with audit; trial as a grant |
| Migrations | M-08 |
| Depends on | Decisions PO-01, PO-05, PO-06, PO-07 |
| Gate | No client request can create or extend a grant · a phone offline keeps paid access exactly until the lease ends, then locks only paid content, and unlocks after sync · learning endpoints answer normally with the billing schema unreachable · existing free content is unaffected |

### Platform-07 · Payments
| | |
|---|---|
| Delivers | Mobile money first, cards second: checkout start, provider webhook into the raw event table, exactly-once application, reconciliation job, receipts, refunds, expiry reminders |
| Migrations | M-09 |
| Depends on | Platform-06; notify for receipts (or e-mail only at first) |
| Gate | Replayed, duplicated, out-of-order and forged provider messages change nothing they should not · amount and plan are verified on the server · a payment that completes while the phone is offline is reflected at next sync · finance can reconcile a day's orders against the provider's report |

## Track D — Engagement and depth

| Milestone | Delivers | Migrations | Depends on | Gate (summary) |
|---|---|---|---|---|
| **Platform-08** Rewards | Ledger, streaks, achievements, awarded inside the sync transaction | M-10 | PO-09 | The same accepted answer never earns twice · totals can be rebuilt from the ledger · offline work shows as provisional until confirmed |
| **Platform-09** Learning extras | Reading position, notes, goals; progress snapshot; feed compaction | M-11 | — | Two devices converge · a new device catches up from a snapshot |
| **Platform-10** Notifications | Outbox, push, preferences, quiet hours, announcements | M-12 | PO-10; worker | Only server code can create a notification · push payloads carry no content · nothing depends on delivery |
| **Platform-11** Exams | Exam papers, sessions, marking guides, exam packs | M-13 | PO-02; rights; Platform-04, -05 | Full exam practice in airplane mode · never ranked or rewarded as proof |
| **Platform-12** Library and orientation | Books and career content as packs | M-14 | rights; Platform-05 | Rights recorded per title · optional downloads with size shown |
| **Platform-13** Jude | Grounded tutor with budgets, consent, kill switch | M-15 | PO-11; legal; Platform-06 | Lessons work with Jude off · per-learner and global ceilings hold under load · no conversation stored unless policy says so |
| **Social-01…04** | Per Social-00 | M-16 | Social-00 decisions | Per Social-00 |
| **Platform-14** Games | Solo rounds from reviewed questions; asynchronous class challenges; real-time only if approved | M-17 | PO-12; Social | No device-reported result is trusted |

## Shared prerequisites, stated once

Social-00's roadmap lists nine prerequisites outside its own module. They are
the same work as milestones here:

| Social-00 prerequisite | Covered by |
|---|---|
| Hosted staging | Platform-02 |
| Gateway rate limiting | Platform-02 |
| Pooler tested with several pools | Platform-02 |
| Staff sign-in with second factor | Platform-02 |
| Account provisioning | Platform-01 + decision PO-03 |
| Account deletion (learning side) | Platform-01 |
| Backups and restore | Platform-02 |
| Privacy notice and terms | Launch checklist (doc 08) |
| Legal answers | One brief for both (doc 07) |

## What is deliberately *not* on the roadmap

Direct messages between learners, an open public feed, follows, presence,
public leaderboards, AI-published content, per-student AI-generated quizzes,
AI chess opponent, 3D avatar, study-music player, birthday e-mails, custom
device-trust and verification code. Each appears in the prototype; each is
recommended as **drop** or **redesign** in doc 02, with reasons in doc 01.
