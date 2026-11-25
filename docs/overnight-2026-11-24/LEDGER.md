# Task ledger — overnight 2026-11-24

Status values: `PLANNED`, `IN_PROGRESS`, `BLOCKED`, `FAILED`, `TESTED_LOCAL`, `REVIEWED`, `READY_FOR_HUMAN_REVIEW`.
Worktrees are under `/Volumes/EdupreneursDev/worktrees/overnight/`. Evidence logs: `/Volumes/EdupreneursDev/logs/overnight-2026-11-24/`.
Nothing is merged into `main`; nothing is deployed.

| Task | Scope | Agent | Branch · worktree | Depends on | Status | Tests performed | Reviewer result | Open defects | PR | Blockers |
|---|---|---|---|---|---|---|---|---|---|---|
| T00 | Preflight, plan, isolation tooling, baseline | director | `overnight/integration-2026-11-24` · `integration` | — | TESTED_LOCAL | baseline pgTAP PASS ×2, pytest 144 passed (isolated stack 56022) | — | — | — | — |
| T01 | B1 platform roles, `ops.audit_write`, staff boundary | lane-staff | `overnight/staff-worker` · `staff` @ 7c3d2fb | — | TESTED_LOCAL (merged to integration 00:0x) | lane: pgTAP 354 (209+145), pytest 210 (144+66); integration after merge: same counts, log `integration-after-staff-b1.log` | security review running (qa-sec-staff-b1) | refused staff requests append unbounded audit rows (fix assigned in B2) | | |
| T02 | B2 editorial slice via API, role admin, worker leasing | lane-staff | same | T01 | IN_PROGRESS | | | | | MFA: design only |
| T03 | `PATCH /v1/me`, onboarding state | lane-identity | `overnight/identity-onboarding` · `identity` @ 70c67c8, b21f8f0 | — (audit hook: T01) | TESTED_LOCAL · turn 2 IN_PROGRESS (R-01, R-03, B1 audit wiring) | lane: pgTAP 524 (209+315), pytest 269 (144+125) incl. T04 | pending | profile edits not audited until B1 wiring | | |
| T04 | Account lifecycle mechanics (export, erasure) on synthetic users | lane-identity | same @ 712e594 | T03, T01 | TESTED_LOCAL (mechanics, synthetic) · executor wiring IN_PROGRESS | erasure proof tests 123/124 green on lane stack | pending | relies on `session_replication_role` allowed for `postgres` locally — unverified on hosted | | PO-04 / legal |
| T05 | Word of the Day: schema, schedule, learner API | lane-vocab | `overnight/word-of-the-day` · `vocab` @ db2964d, ceef319, 40ecf9f | — | TESTED_LOCAL | lane: pgTAP 562 (209+353), pytest 194 (144+50) | pending (after turn 2) | midnight reschedule race; today-tests flaky across Haiti midnight (fixes assigned) | | |
| T06 | Word of the Day: staff editorial + scheduling API | lane-vocab | same | T01 | IN_PROGRESS | | | | | |
| T07 | Gold ledger, streaks, achievements, sync hook | lane-rewards | `overnight/rewards-gold` · `rewards` @ 53ec9aa | — | TESTED_LOCAL | lane report: 273 new pgTAP, 92 new pytest, baseline green flag off and on (to be confirmed by reviewers) | security (qa-sec-rewards) and integration (qa-int-rewards) reviews running on stacks qa1/qa2 | R-03 search_path template pending | | PO-09 values |
| T08 | Leaderboard: private rank, opt-in synthetic cohort | lane-leaderboard | `overnight/leaderboard` · `leaderboard` | T07 reviewed | PLANNED | | | | | visibility/consent for minors |
| T09 | Native onboarding + tour | lane-native | `overnight/native-experience` · `native` (base `mobile-02`) | — | IN_PROGRESS | | | | | HT wording review |
| T10 | Native Word of the Day card, Gold, leaderboard review screen (flags off) | lane-native | same | T09; contracts T05/T07/T08 | PLANNED | | | | | |
| T11 | Content format v2 validators, vectors, assets, pack manifest | lane-content | `overnight/content-format-v2` · `content` | T01 for staff writes | IN_PROGRESS | | | | | PO-08 |
| T12 | Entitlement grants, read API, mock provider | lane-entitlements | `overnight/entitlements` · `entitlements` @ 6e97d4c, cfd2b37 | T01 for staff grants | TESTED_LOCAL · staff routes IN_PROGRESS | lane: pgTAP 568 (209+359), pytest 249 (144+105) | pending | `is_entitled` course-existence probe (fix assigned) | | PO-01/05/06/07 |
| T13 | Notify outbox + dummy adapter; rate limiting, logging, restore drill | lane-notify | `overnight/notify-security` · `notify` @ 1fecfca, 2fb4cd6 | T02 for worker delivery | TESTED_LOCAL · turn 2 IN_PROGRESS | lane: pgTAP 445 (209+236), pytest 224 (144+80); restore drill performed and timed | pending | limiter fails open at key capacity (fix assigned) | | PO-10 |
| T14 | Integration branch: merge reviewed lanes, full suites | director | `overnight/integration-2026-11-24` | all reviewed lanes | PLANNED | | | | | |
| T15 | Morning report, pushes, draft PRs | director | same | T14 | PLANNED | | | | | |
