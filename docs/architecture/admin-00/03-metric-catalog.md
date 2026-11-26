# 3. Metric catalog

Rule: **no metric without a definition, an event source and a calculation.** If the source does not exist, the metric is `not available`
and the tile says why. Tables are those present on `review/final-verification-2026-11-25`; column names are to be confirmed when queries
are written.

**Time.** All "day" boundaries are **Haiti local date** (the same convention the streak and Word-of-the-Day code uses).
**Privacy tiers.** T0 = platform aggregate; T1 = aggregate by grade/subject/lesson, groups < K suppressed; T2 = individual (support/admin, audited).
**Availability.** ✅ computable from existing tables · 🔧 needs new queries/aggregates only · 🆕 needs a new event or module.

| # | Metric | Definition | Source (existing) | Calculation | Tier | Avail. |
|---|---|---|---|---|---|---|
| M1 | Registered learners | Learner profiles that exist and are not erased | `app.learner_profiles` | count where not erased | T0 | ✅ |
| M2 | Enrolments over time | New profiles per Haiti day/week | `app.learner_profiles.created_at` | group by date | T0 | ✅ |
| M3 | Daily / monthly **learning-active** learners | Learners with ≥ 1 *accepted* learning operation (practice answer or lesson completion) in the period | `app.sync_receipts` / `app.practice_attempts` / `app.lesson_progress` | distinct learner per Haiti day / rolling 28 days | T0 | 🔧 |
| M4 | App opens / sessions | — | **none** (the app emits no open event) | — | — | 🆕 (do not infer from sync pulls) |
| M5 | Lesson completions | Completions accepted by the server | `app.lesson_progress` | count by date; by grade/subject via lesson→unit→course | T0/T1 | ✅ |
| M6 | Study activity | Accepted practice answers per day | `app.practice_attempts` | count by date | T0/T1 | ✅ |
| M7 | Answer accuracy | Share of server-scored answers that are correct | `app.practice_attempts` (server `is_correct`) | correct / total, per lesson/grade; **never** per learner on the dashboard | T1 | ✅ |
| M8 | Subject & grade engagement | Distinct active learners and answers per grade×subject | M3/M6 joined to catalog | group by course | T1 | 🔧 |
| M9 | Rewards activity | Gold awarded per day, achievements awarded | `rewards.ledger`, `rewards.achievement_awards` | sums/counts | T0 | ✅ if flag data exists |
| M10 | Downloaded-content statistics | Downloads started/completed per resource and day, bytes served | **none** (no client event, no CDN stats ingested) | count events / CDN log aggregation | T0 | 🆕 — needs owner decision on collection (Content-Delivery-00 doc 6 §3). Preferred: CDN request counts by object, no student id |
| M11 | Online reads | Lessons read online per day | **none** (reads are not logged; by design) | — | T0 | 🆕 only if the owner approves aggregate counters |
| M12 | Sync health — server side | Operations accepted / duplicate / rejected / conflict per day; rejection codes | `app.sync_receipts` (+ outcome) | rates by day | T0 | 🔧 |
| M13 | Sync health — device side | Oldest pending operation age, failure counts | **none** (lives on phones) | needs a client report or a "last successful push" per account | T0 | 🆕 (`app.account_sync_state` gives last server-side activity per account; evaluate) |
| M14 | Exam participation and outcomes | Sessions started/closed, score distribution | exam module | — | T1 | 🆕 (module not built) |
| M15 | Word of the Day coverage | Days in the next 14 with a published word | `vocab.daily_assignments` | count | T0 | ✅ |
| M16 | Content pipeline | Revisions by status; median time draft→published; items waiting review | `app.lesson_revisions`, `app.editorial_reviews` | counts, durations | T0 | ✅ |
| M17 | Notification delivery | Outbox → delivered/failed per kind | `notify.outbox`, `notify.deliveries` | counts (dummy adapter today) | T0 | ✅ (meaningless until a real adapter) |
| M18 | Infrastructure status | API up, DB reachable, readiness checks (no TEMP privilege, extension allow-list) | `/health` + readiness script (X-1) | boolean + timestamp | T0 | 🔧 (X-1 not built) |
| M19 | Jude AI usage, cost, errors | Tokens, cost, error rate by feature/day | **none** | — | T0 | 🆕 |
| M20 | Revenue, subscriptions, transactions | Orders, paid amount, active entitlements, refunds | `billing.orders`, `billing.entitlements`, `billing.refunds` | sums by currency/period | T0 | ✅ schema / 🆕 no real provider; **do not show a revenue tile until reconciliation exists** |
| M21 | Fraud signals (Gold) | Learners with abnormal earn rate or repeated duplicate ops | `rewards.ledger`, `rewards.processed_operations` | thresholds set by admin | T2 → admin only | 🔧 |

## Definition notes

* **Why "learning-active" and not "active":** the platform has no session or app-open event, and inventing one from token refreshes or
  sync pulls would count backgrounded phones. M3 is deliberately narrower and honest; M4 is listed so nobody fakes it.
* **Offline work counts when it is accepted by the server**, with the *server receive* date for the dashboard, and the client's
  `client_recorded_at` kept only for diagnostics. A student offline for a week therefore appears active on the sync day. This lag must be
  stated on the tile.
* **Accuracy (M7)** uses the server's score, never the phone's provisional verdict.
* **Freshness:** metrics are served from scheduled aggregate tables (hourly/daily) written by the worker — not from live scans of learner
  tables by the web request path. The worker deployment does not exist yet (platform item).
* Every tile shows `as_of` and the window; a stale tile turns amber after 2× its schedule.
