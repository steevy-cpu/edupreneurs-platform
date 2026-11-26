# 4. Shared data and dependency matrix

The brief asked for special attention to the things several modules need at
once. These are where a database redesign later would hurt most, so each one
gets: what the prototype did, what v2 has, a recommended shape, and who owns it.

## Cross-cutting entities

### 4.1 User profile

| | |
|---|---|
| **Prototype** | One table with about 45 columns holding identity, personal details, subscription state, points, streaks, exam statistics, e-mail bookkeeping and onboarding flags — all in a row its owner may update |
| **v2 today** | `app.learner_profiles`: user id, grade, language, optional display name. Owner can read; nothing can edit yet |
| **Recommendation** | Keep it small, and **split by purpose** so each fact has one owner and one protection level |

| Concern | Lives in | Owner module | Visible to |
|---|---|---|---|
| Who the person is (credentials, e-mail) | `auth.users` | Supabase Auth | Auth only |
| Study settings: grade, language, display name | `app.learner_profiles` | learning | The learner |
| Consent, age band | `app.consent_records` (new) | privacy | The learner; staff with reason |
| Entitlement | `billing.entitlements` (new) | billing | The learner (own status) |
| Points, streak | `app.reward_ledger`, `app.streak_state` (new) | learning | The learner |
| Public name and avatar | `social.profiles` (Social-00) | social | Members of the same group |
| Notification settings, push tokens | `notify.*` (new) | notify | The learner |
| Staff role | `app.staff_roles`, `social.staff_roles` | staff / social | Staff administration |

Risk if not split: the prototype's situation — a change to one concern (say,
letting learners edit a nickname) silently opens another (their own access state).

### 4.2 Entitlement status

| | |
|---|---|
| **Prototype** | Three profile columns and several special cases (trial, promo with a fixed end date, legacy accounts, founders); evaluated in the browser; currently bypassed by a global "free access" setting |
| **v2 today** | Nothing. "Published" is the only gate |
| **Recommendation** | A **grant** model in its own schema |

```
billing.plans          what can be bought (data, not code): duration, price per currency, scope
billing.orders         an attempt to pay: plan, amount expected, provider, state
billing.provider_events every message from a provider, stored raw, unique by provider id → applied once
billing.entitlements   one row per grant: learner, scope, starts, ends, source, source reference
                       source ∈ purchase | gift | promo | school_licence | trial | staff_grant | migration
billing.refunds
```

- "Is this learner entitled to scope X now?" is a single read-only function.
  Scope is `all`, a grade, or a course — decision PO-05.
- Several grants can overlap; access = any active grant. Extending = adding a
  grant, never editing a date. History is therefore automatic.
- **Offline lease.** The phone cannot ask the server while offline, so the
  server issues a signed statement — "learner L holds scope X until date D,
  issued at T" — refreshed at each sync. The app honours it until
  `min(D, T + lease length)`. Lease length is decision PO-07 (suggested 30
  days). When it lapses, downloaded lessons stay on the phone but paid ones
  lock, with a clear message; free ones never lock.
- Consumers: catalogue (what to show as locked), pack download (who may fetch
  paid packs), tutor (usage allowance), notify (expiry reminders).

### 4.3 Grade access

| | |
|---|---|
| **Prototype** | Free-text grade on the profile; a browser-side rule decides which grades a learner may open; fixed ids bypass it |
| **v2 today** | `grade_id` on the profile referencing a real `grades` table; the catalogue returns everything published |
| **Recommendation** | Grade is a **preference that filters**, not a permission. A learner sees their grade by default and may browse others (revision of earlier years is normal). What *restricts* is entitlement scope (4.2). Keeping the two separate avoids the prototype's tangle of "grade lock" exceptions |

### 4.4 Lesson identity

| | |
|---|---|
| **Prototype** | Three identities in use at once: internal id (AI assets), subject slug + lesson slug (addresses, cache), slug + free-text subject (progress). Renaming a slug orphans audio files and progress |
| **v2 today** | `lessons.id` is the stable identity; `lesson_revisions.id` is the exact text a learner saw, per language; questions belong to one revision; attempts reference the exact question revision. **Existing and tested** |
| **Recommendation** | Keep it, and make every new module use it: |

| New feature | References |
|---|---|
| Reading position, notes | `lesson_id` (+ `block_key` inside a revision) |
| Exams | An exam paper is content with its own id and revisions, built from `question_revisions` |
| Rewards | The learning event (attempt or completion) that earned them |
| Jude | `lesson_revision_id` as the cited source |
| Community (later "ask about this lesson") | The public `lesson_id` only, no link in the database (Social-00 rule) |
| Packs, audio, images | `lesson_revision_id` + content hash, never a slug |
| Prototype content being converted | A mapping table kept by the conversion tooling, **outside** the product schema |

### 4.5 Event records

| | |
|---|---|
| **Prototype** | No event history. Progress is a row per completed lesson; points are a total; there are no stored attempts for lesson quizzes |
| **v2 today** | Three event-like records, all server-written: `practice_attempts` (every answer), `sync_receipts` (every operation and its result), `account_change_feed` (ordered per learner). `audit_events` exists but nothing writes it |
| **Recommendation** | Treat **accepted sync operations as the product's event log** |

- Everything a learner *does* enters as an operation with an id made on the
  phone: answer, completion, reading position, note, goal, exam session,
  reward claim (if any). One pipe, one de-duplication rule, one ordering.
- Everything *derived* (points, streaks, mastery, study time, product metrics)
  is computed on the server from accepted operations. It can be recomputed if
  a rule changes — which is why a ledger beats a running total.
- Staff and system actions go to `audit_events`, written by the server.
- Analytics read aggregates of these; no separate tracking SDK in the app.
- Growth: receipts and feed rows accumulate. Compaction and a snapshot
  endpoint are already in the backlog and become necessary as operation kinds multiply.

### 4.6 Notifications

| | |
|---|---|
| **Prototype** | Notification rows created by the acting user's browser; push through a weakly protected endpoint; schedules created by hand outside the code |
| **v2 today** | Nothing. Social-00 designed its own pull-only event table |
| **Recommendation** | One **outbox** owned by `notify`, written only by server code |

```
notify.outbox        recipient, kind, reference ids (no free text), channel policy, created, deliver_after
notify.deliveries    attempt log per channel
notify.push_tokens   per device, per learner, removed on sign-out
notify.preferences   per learner: categories, quiet hours
```

- Producers call one function. They never hold push or e-mail credentials.
- Messages carry ids and a kind; the app renders the words in the learner's
  language. Push payloads for minors carry no content.
- Social-00 keeps its own in-app event list (its visibility rules are special)
  and may hand *delivery* of a content-free push to `notify` later.
- Account e-mails (verify, recover) stay with the auth service.

## Dependency matrix

Rows depend on columns. **●** hard dependency (cannot ship without) ·
**○** soft (works without, better with) · blank = none.

| ↓ needs → | Identity | Curriculum | Content format v2 | Staff pipeline | Packs + storage | Sync | Entitlements | Rewards | Notify | Worker | Privacy | Jude | Social |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Onboarding / profile edit | ● | ● | | | | ● | | | | | ● | | |
| Lesson content at scale | | ● | ● | ● | ● | | | | | ● | | | |
| Mathematics, images | | | ● | ● | ● | | | | | | | | |
| Audio | | | ● | ● | ● | | | | | ● | | | |
| Reading position, notes, goals | ● | ● | | | | ● | | | | | ● | | |
| Rewards (points, streaks) | ● | | | | | ● | | | ○ | | ● | | |
| Exams | ● | ● | ● | ● | ● | ● | ○ | | | | | ○ | |
| Entitlements | ● | ● | | | | | | | ○ | ● | ● | | |
| Paid content offline | ● | ● | | | ● | ● | ● | | | | | | |
| Payments (mobile money, cards) | ● | | | | | | ● | | ● | ● | ● | | |
| Gifts, promos, school licences | ● | | | ○ | | | ● | | ○ | | | | |
| Push and reminders | ● | | | | | | | | | ● | ● | | |
| Announcements | ● | ● | | ● | | | | | ● | | | | |
| Jude | ● | ● | | | | ○ | ● | | | ○ | ● | | |
| E-books | ● | ● | ○ | ● | ● | ● | ○ | | | | | | |
| Career orientation | | | ● | ● | ● | | | | | | | | |
| Solo quiz mode | | ● | | | ● | ● | | ○ | | | | | |
| Asynchronous challenges | ● | ● | | | | ● | | ○ | ○ | | | | ● |
| Community (Social-00) | ● | | | | | | | | ○ | ○ | ● | | |
| Class leaderboard | ● | | | | | | | ● | | | ● | | ● |
| Real-time games | ● | | | | | | ○ | ○ | ● | | ● | | ● |
| Staff support tools | ● | | | ● | | | ○ | | | | ● | | |
| Account deletion | ● | | | | | ● | ○ | ○ | ○ | ● | | ○ | ○ |
| Existing-user migration | ● | ● | | ● | | | ○ | | ● | | ● | | |

### What the matrix says

- **Five foundations unlock almost everything:** content format v2, the staff
  pipeline, packs with object storage, the worker, and privacy. None is a
  learner-visible feature. All are P0.
- **Entitlements sit under payments, paid offline content, Jude and exams.**
  Deciding the model is urgent even if building payments is not.
- **Rewards need only sync and privacy** — cheap once the ledger is designed,
  and independent of everything else.
- **Jude depends on entitlements and privacy, not the other way round.**
  Nothing waits for Jude.
- **Social and real-time games are leaves.** Nothing in the learning product
  depends on them, which is why deferring them is safe.

## Shared concerns that several designs already touch

Social-00 defined its own versions of some shared things on purpose (to keep
its boundary absolute). Recommendation for each, so the platform does not grow
three of everything:

| Concern | Social-00 | Recommendation |
|---|---|---|
| Staff roles | Own table (`social.staff_roles`) | **Keep separate.** A lesson editor is not a moderator |
| Audit log | Own table | **Keep separate tables, one format.** Same columns, so one staff screen can read both |
| Rate limits | In-database counters for social writes | **Keep**, plus the gateway limiter that every module needs (P0) |
| Notification events | Own pull-only table | **Keep**; hand content-free push delivery to `notify` when it exists |
| Consent and age band | Own enrolment record | **Share the question, not the table.** One consent flow in the app writes the platform consent record; social enrolment references that a consent exists. Needs a small design note before either is built |
| Account erasure | `social.erase_user` | **Shared orchestrator** calls it alongside the learning and billing ones |
| Staff sign-in with second factor | Required | **Shared** — one staff authentication for portal and moderation |
| Idempotent writes | `client_op_id` per submission | Same idea as learning's `op_id`; keep the two outboxes separate as designed |
