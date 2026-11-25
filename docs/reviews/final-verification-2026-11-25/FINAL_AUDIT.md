# Edupreneurs 2.0 — Independent final verification of the overnight mission

**Date:** 2026-11-25 · **Lead:** Claude Opus 5.5 · **Scope:** draft PRs #4–#13 (overnight lanes), #11
(integration), the relationship of #8 to Mobile-02 (#3), plus the corrections this verification made
(#14–#20).
**Nothing was merged, deployed, or run against real data or the owner's shared database.**

## 0. How independent this is — read first

The lead of this verification ran in the same Claude Code session that had directed the overnight
work, so the lead's own context contained the overnight director's conclusions. To compensate:

- every code-level verdict below comes from a **fresh reviewer agent** that was given the code, the
  specifications and the earlier reviewers' original findings — never the director's assessments —
  and was told to treat every "fixed" claim as unverified;
- every correction was implemented by a **separate Sonnet agent** and reviewed by someone else (a
  fresh reviewer for the privacy-critical leaderboard fix, the lead for small diffs);
- the lead personally re-ran every gate whose numbers appear here and reproduced the most serious new
  finding (NF-1) before recording it.

Reviewer reports (public versions, no exploit steps) are in this folder; private versions with
reproductions are kept off GitHub in `/Volumes/EdupreneursDev/logs/final-verification-2026-11-25/reviews/`.

## 1. Executive summary

- **The overnight backend is substantially sound where it matters most.** Reviewers could not:
  - get duplicate Gold from any retried, replayed or concurrent offline operation;
  - change a published Word of the Day after its Haiti date opened;
  - reach any new schema through the Supabase Data API;
  - find any change to the verified `app` RLS rules.

  All 9 backend lanes pass their gates and the corrected integration candidate is green: pgTAP
  3,101/3,101 on both runs; pytest 1,792 with flags off and 1,792 with rewards on; mypy strict, lint
  and the contracts clean.
- **Two HIGH security issues remain open, and neither is a defect of the overnight code alone.**
  - **H1 — temporary-schema type shadowing.** It lets a session with arbitrary SQL on an API login
    run code as the database owner. **It is still open on `main`.** It is closed on the corrected
    branches by one database privilege revoke, and minimal draft PR #20 brings that revoke to `main`.
  - **NF-1 — the local Supabase `supautils` extension wrapper.** It lets every service login create,
    drop or move privileged extensions in any schema, including the private `app` schema.
    Reproduced by the lead. No migration can fix it; it needs hosted-project verification and the
    Supabase vendor.

  Both require arbitrary SQL on a service login, which the API never gives (bound parameters only).
- **One HIGH privacy issue is blocked on an owner decision.** After an account erasure, a
  still-valid token re-creates the learner's profile through the API. The fix needs a decision
  on how Auth accounts are deleted (PO-04).
- **The leaderboard was not safe as built.** In small cohorts a child could infer another
  child's exact Gold and consent decision. It is fixed (minimum cohort size, snapshot-only reads) and
  re-verified. Two low findings must be fixed before any leaderboard flag is turned on.
- **The test environment hazard is closed on the corrected branches but still present on `main`
  and Mobile-02.** This is the hazard that truncated the owner's shared database overnight.
  - The owner's shared database was **not modified** during this verification: its fingerprint
    is identical before and after, and only its own health checks and three read-only queries ran.
  - One stray, rejected sign-in attempt reached it from an emulator build left installed overnight
    (§6).
- **The onboarding fixes work on Android API 24 at 320 dp in French and Creole, at font scales 1.0,
  1.3 and 2.0:** 23 of 24 emulator checks pass. Not tested on a physical device.
- **Merge readiness:** no PR is ready to merge into `main` today. #4 + #17 (staff foundation) and the
  `main` hardening branch are the closest; most features are ready as **dormant, flag-off** code once
  their corrections are applied; enabling any learner-facing flag needs owner decisions (§8).

## 2. Security findings, ranked

| # | Sev | Finding | Where | Status |
|---|---|---|---|---|
| S1 | HIGH | **H1:** temp-schema type shadowing in SECURITY DEFINER functions; with arbitrary SQL on `edu_api_login`, `edu_staff_login` or `edu_worker_login`, code runs as `postgres` | baseline `app` functions on `main`; new functions | **Open on `main`** (reproduced). **Closed** on #4 / candidate by `REVOKE TEMPORARY … FROM PUBLIC`, verified for all three logins. That revoke is the *only* barrier: with TEMP re-granted, even functions pinned to `pg_catalog, pg_temp` were exploitable through `app.current_actor_id()`. Minimal `main` fix: #20 |
| S2 | HIGH | **NF-1:** `supautils` runs privileged-extension DDL (create, drop, move — including `dblink`, `http`, `pg_net`, `pg_cron`, `postgres_fdw`) for every service login, in any schema incl. `app` and `pg_catalog`; enables outbound HTTP and job scheduling from the database | local Supabase platform (also `main`) | **Open, not fixable by migration** (an owner-owned event trigger does not fire). Reproduced by the lead in a rolled-back transaction. Hosted behaviour NOT_VERIFIED. Action: verify on the hosted project, raise with Supabase, add a readiness check that refuses to start if unexpected extensions exist |
| S3 | HIGH (conditional) | **M-3 / H-1-via-API:** after `account.erase_learner`, a still-valid token can call `/v1/me`, file requests and sync; the API re-creates the profile on every authenticated request, and the learner id reappears in 8 tables | `identity.py` (profile on first contact), lifecycle design | **BLOCKED on owner** (Auth deletion order, PO-04). Database-level H-1 fix PASSES. Lifecycle flag is off |
| S4 | MEDIUM | Mobile test harness hard-codes the shared container: truncates learning tables, pauses the shared gateway, pattern-kills APIs (caused incident I-01) | `apps/student-native/tests/support/*`, `scripts/e2e-run.sh` on `main`, `mobile-02`, #8 | **Fixed** in #15 (derivation from `config.toml`, refusal of the shared stack, per-checkout ports and PID files; refusal proven live; CI override for the disposable runner). **Open on `mobile-02`**; fixed for `main` in #20 |
| S5 | MEDIUM | **LB-1:** leaderboard rank and size revealed another child's exact Gold and opt-in/out in small cohorts | #13 | **Fixed** in #19, re-verified (PASS at K=5). Residuals LB-R1/LB-R2 below |
| S6 | MEDIUM | **QA5-C1:** content body gate accepts media links and non-string values nested inside blocks; the nested asset escapes the rights check | #7, `20261124030200` | **Open.** Reachable only through raw SQL on the staff login; no v2 content or activation path exists |
| S7 | MEDIUM | **M-B2-1:** an admin could rewrite another editor's draft and approve it (unreviewed content under an editor's name) | #4 | **Fixed** (33aa2e2), re-verified PASS |
| S8 | MEDIUM | **notify M-1:** behind a proxy, clients could choose their own rate-limit key | #6 | **Fixed** in #14, reviewed PASS |
| S9 | LOW | **LB-R1:** a refresh at REPEATABLE READ / SERIALIZABLE can resurrect a withdrawn learner into a frozen week | #19 | Open — fix before enabling |
| S10 | LOW | **LB-R2:** K can be set to 1 by the owner, which restores LB-1 | #19 | Open — needs a hard lower bound |
| S11 | LOW | **QA5-V1:** any service login holding the day's advisory key blanks today's word (404) | #9 | Open (availability only; never a changed word) |
| S12 | LOW | **QA5-C3:** invisible-character rule is a hand list; several Cf characters pass | #7 | Open |
| S13 | LOW | **L-B2-4:** last-admin check ignores banned/deleted accounts (zero usable admins reproduced) | #4 | Open |
| S14 | LOW | **notify L-4:** expired-token learners behind a shared carrier NAT get 429 instead of 401 | #6 | Open — limiter must stay off |
| S15 | LOW | **NF-2, NF-3, CRLF:** asset attach by non-author; NUL in `source_uri` → 500; CR refused (breaks Windows clients) | #7, #4 | **Fixed** in #18, #17 (reviewed PASS) |
| S16 | LOW | **QA5-R1/R2:** any non-rewards lock costs a push 5 s; rule-switch race loses awards | #12 | **Fixed** in #16 (0.27 s under foreign locks), reviewed PASS |
| S17 | NOTE | Lesson text accepts bidi overrides, zero-width-only text, U+2028, BOM | staff, content | Owner/editorial decision (recorded in lane docs) |

## 3. Review of each workstream

| Lane | PR | Verdict of this verification |
|---|---|---|
| **Staff boundary, editorial, roles, worker** | #4 (+#17) | **Security fix verified** for all three logins. Editorial rules hold through the API: reviewer ≠ author, frozen after submit, pack and release rules, and concurrent release/rollback leave exactly one current release. **Open:** no takedown route for live content (L-B2-3), last-admin check (S13), MFA design only, NF-1 |
| **Identity / onboarding / erasure** | #5 | Database fixes PASS: actor ≠ target, worker only through an open deletion request, hook discovery, deadlock order. Containment of the trigger-disabling window PASSES under errors, timeouts, cancels and savepoints. Cross-lane erasure leaves no id; all 8 schemas with learner rows are registered. **Blocked:** S3, hosted support for `session_replication_role` (NOT_VERIFIED), consent/retention choices (§8) |
| **Gold / rewards** | #12 (+#16) | **PASS** on every duplicate scenario (9), server-only amounts, 72 parallel pushes racing reconcile, rebuild and erase (0 violations in 456 balance checks), flag-off identity, Haiti midnight and DST streaks. Fixes verified. Note: `FOR KEY SHARE` would be cheaper than `FOR SHARE` under load |
| **Leaderboard** | #13 (+#19) | First review: not ready (LB-1 to LB-7). After #19, re-verified acceptable **as a draft**; fix LB-R1 and LB-R2 before enabling. Residual inference at K ≥ 5 judged acceptable by the reviewer, subject to batched refreshes (owner policy). Not built: cohort page, opt-in routes, staff routes, scheduler |
| **Word of the Day** | #9 | **PASS:** published day immutable (owner TRUNCATE refused, commit-after-midnight refused, no changed word observable), editorial approval over HTTP, staff routes. Residual S11. Staff vocab routes are not behind `daily_word_enabled` (they need the staff side to be configured) |
| **Content format v2** | #7 (+#18) | H1 and M1–M3 PASS. **H2 and M4 only partly fixed** (S6, S12). `/v1/catalog` and `/v1/lessons` unchanged. Not shippable: 3 of the 6 preconditions for v2 content are missing (activation gate, format-aware endpoint, `app` question-kind migration) |
| **Entitlements** | #10 | M1 PASS; L1–L4 open and low. **No paywall:** catalogue, lesson, push and pull are identical with the flag on and with billing unreachable. The simulated provider is unreachable outside local/test |
| **Notify, limiter, logs** | #6 (+#14) | Defaults identical to `main`. Outbox privileges, free-text refusal and claim concurrency PASS. Review fixes in #14 PASS. Limiter must stay off (S14) |
| **Native** | #8 (+#15) | Onboarding fixes verified on the emulator. Harness hazard fixed. Open items in §6 |
| **Integration** | #11 | Superseded by the corrected candidate `review/final-verification-2026-11-25` (#11's tree plus #14, #16, #17, #18, #19). Do not merge #11 as-is |

## 4. Original defects and fix-verification evidence

Each row: original defect · affected commit · reproduction now · verdict. Details, commands and
residual paths are in the per-area reports in this folder.

| ID | Defect (short) | Fixed in | Reproduction now | Verdict |
|---|---|---|---|---|
| B1-H1 | temp-schema shadowing | 16f4ee1 (staff) | refused for all 3 logins; control with TEMP re-granted still exploitable | PASS (candidate) · FAIL on `main` |
| B1-M1/M2/L1–L5 | denial bound, audit validator, actor kinds | 16f4ee1 | 400 refusals → 1 audit row | PASS |
| M-B2-1 | admin edits and approves another editor's draft | 33aa2e2 | admin gets 403 on edit/attach/detach/submit | PASS |
| L-B2-1 | control character → 500 | 33aa2e2 + #17 | `source_uri` NUL → 422; CRLF normalised | PASS (after #17) |
| L-B2-2 | two revisions of one lesson in a pack | 33aa2e2 | 422 in both orders | PASS |
| L-B2-3 / L-B2-4 | no takedown route / last admin | — | reproduced | OPEN |
| ID H-1 | onboarding/export racing an erasure | d6560ce | 42501 in the database; reappears via API (M-3) | BLOCKED |
| ID M-1 / M-2 / L-1 / L-2 / L-4 | erasure hardening | d6560ce | refused / blocks / no deadlock | PASS |
| ID M-3 | profile re-created after erasure | — | reproduced | BLOCKED (owner) |
| RW-M1 | push stall on a held lock | 909e495 + #16 | 220 ms rewards lock; 0.27 s foreign lock | PASS |
| RW-M2 / L1 / L2 / L3 | evidence rule, caps, erase undone, cursor | 3e0860c, 4146267 | behave as documented | PASS |
| RW-INT-L3 / QA5-R2 | `no_active_rule` final; switch race | 3e0860c + #16 | heals; race closed | PASS |
| VOC-F1 / F2 / F3 | late reschedule; TRUNCATE; tests | 0d607ec | 404 never a changed word; refused; tests exist | PASS (residual S11) |
| CT-H1 / M1 / M2 / M3 | verifier format, math markup/depth, totals | 660a87b–d53d0a1 | refused | PASS (C2 residual) |
| CT-H2 / M4 | body gate, invisible characters | 0212050, d53d0a1 | nested values and Cf characters pass | FAIL (partial) |
| ENT-M1 | idempotency key namespace | 50a6b52 | 422 / 22023 | PASS |
| NOT-M1 / L1 / L2 / L3 | XFF, log leak, lease, flag 404 | #14 | regression tests fail before, pass after | PASS |
| LB-1 … LB-7 | privacy, race, speed, flag, tests | #19 | original attacks rerun | PASS (LB-2 at READ COMMITTED only) |
| NAT-H1, M1–M5 | stale word label, clock, sync loop, grade, streak | 49ffcb3 … 2921ecb | source review only | NOT_VERIFIED (not re-reviewed) |
| NAT-grade, connectivity, welcome | emulator defects | #15 | emulator, fr and ht, font scales 1.0/1.3/2.0 | PASS |

## 5. Automated tests — counts and commands

Backend gate, run by the lead on isolated stacks:

```sh
export UV_CACHE_DIR=/Volumes/EdupreneursDev/caches/uv
make lint && make typecheck && uv run python scripts/export_openapi.py --check
make db-reset && make test-db && uv run pytest -q && EDU_REWARDS_ENABLED=true uv run pytest -q && make test-db
```

| Tree | pgTAP | pytest (flags off / rewards on) | lint · mypy · OpenAPI |
|---|---|---|---|
| `origin/main` dd2aa19 (overnight baseline) | 209 assertions PASS | 144 / — | clean |
| #11 integration 34a2e6d | 3,025 PASS ×2 | 1,754 / 1,754 | clean |
| **Corrected candidate** `review/final-verification-2026-11-25` | **3,101 PASS ×2** | **1,792 / 1,792** | clean |
| #14 notify fix 9175743 (lead re-run) | 889 PASS ×2 | 492 | clean |

Mobile, at #15's head (202c12f), on an isolated stack, run by the lead:

```sh
cd apps/student-native && npx tsc --noEmit && npx tsc --noEmit -p tests && EDU_TEST_DEBUG=1 npx jest
```

- Result: tsc clean ×2; **Jest 369/369 in 24 suites**.
- Harness target line: `stack edu-fv-native-verify: db container supabase_db_edu-fv-native-verify, db port 57822`.
- Live refusal check: the harness refuses the owner's checkout configuration.

Mobile contract on the candidate: `npm run check:api` and both `tsc` checks are clean.

Other checks on the candidate:
- **Baseline files byte-identical to `main`:** the 4 migrations, seed, `0xx` tests, conftest, helpers and the v1 content schemas.
- **All 10 server flags default `False`.**
- **Verified `app` permissions unchanged:**
  - 17 policies;
  - `edu_api`: SELECT ×16 plus INSERT(user_id) on profiles, and EXECUTE on exactly 2 functions;
  - 16 app triggers;
  - no API role has BYPASSRLS or membership in `pg_read_all_data` / `pg_write_all_data`.
- **Definer functions:** 0 SECURITY DEFINER functions in project schemas without a pinned `search_path`.
- **TEMP** is held only by `postgres`, `supabase_admin` and `dashboard_user`.

GitHub CI (the repository's workflow): pass on every open PR, #3–#19. #15's pass also shows that the
harness's disposable-runner override works in CI.

## 6. Native testing results

- **Emulator:** Android API 24, AVD `edu_api24`, 320 × 533 dp. This is an emulator; **no physical-device claim.** Full report and 33 screenshots: [`native/native-emulator-verification.md`](native/native-emulator-verification.md).
- **PASS:**
  - grade step shows 5 classes on open, with only "Continuer" pinned, in fr and ht at 1.0 and 1.3;
  - welcome step fits;
  - the notice distinguishes not-downloaded from offline;
  - the "Hors ligne" pill and "Serveur injoignable" appear only when the server is unreachable, and not on a 503;
  - no regression of the header pill.
- **FAIL D2 (low/medium):** at font scale 2.0 the next onboarding step opens still scrolled, with its title off screen.
- **D1 (low):** at large font sizes, chip labels touch the chip border.
- **Notes:**
  - offline, Profil shows "Tout est synchronisé" next to "Serveur injoignable", which contradicts itself;
  - no feedback after a manual sync that gets a 503;
  - "Men lis klas yo abitye." needs a native speaker;
  - after choosing 7AF in onboarding, Accueil and Profil still ask the learner to choose a class — **needs investigation** (possibly the grade stays local while `EXPO_PUBLIC_FF_ONBOARDING_SYNC` is off).
- **Not re-verified here:** the overnight native source-review fixes (stale word label, clock handling, sync spacing, grade prefill, stale streak); account switching on device; Word of the Day freshness and Gold on a live backend; Creole at large text on Accueil/Profil.
- **Feature-flag defaults:** all six client flags default off; with none set the app behaves as Mobile-02. Checked by source and by the overnight production-bundle inspection; not rebuilt here.
- **Environment incident:** the emulator still had an older build from 2026-11-24, which pointed at the shared stack (port 54321). Its first launch made one sign-in attempt, rejected by Auth; nothing was written (fingerprint identical, last Auth audit entry from 2026-11-24). That build was replaced on the emulator by the debug APK from `/Volumes/EdupreneursDev/artifacts`; reinstall it from its source if it is still needed.

## 7. Confirmed architectural risks

1. **One privilege as the only barrier.** The TEMP revoke alone stops S1; baseline `app` functions keep `search_path = ''`. Add a deploy-time assertion that no API role holds TEMP, and move `app` functions to `pg_catalog, pg_temp` when the baseline is unfrozen.
2. **Platform trust (NF-1, erasure).** Supabase's `supautils` both enables NF-1 and is what allows the erasure function to disable triggers. Both are unverified on a hosted project. Decide the hosting target and test it before relying on either.
3. **Erasure is an orchestration contract.** 20 foreign keys from new schemas into `app` (all `RESTRICT`) mean a profile cannot be deleted until every lane's hook runs. The registry fails closed, which is correct, but every future schema must register. Text/JSON columns are not swept by the postcondition.
4. **Nothing runs on a schedule.** There is no worker process or scheduler, so reconcile, Word of the Day fill, leaderboard refresh and notification delivery are library functions exercised only by tests.
5. **Staff surface without MFA or takedown.** Staff routes must stay unconfigured in any reachable environment until MFA (designed only) and a content takedown path exist.
6. **Per-process rate limiting.** A gateway limiter is still needed for any hosted deployment.
7. **Merge hotspot.** Every lane appends to `config.py` and `main.py`. "Keep both" resolutions produced duplicate router registrations three times (overnight twice, and once in this verification); each was caught by the lead. A router registry, or a test asserting unique route registration, would remove the class.
8. **Isolation-level assumptions.** The leaderboard locking (LB-R1) and the Word of the Day read guarantee assume READ COMMITTED. Nothing enforces that.

## 8. Legal and product decisions still required (not decided by any agent)

| Decision | Blocks |
|---|---|
| **PO-04 + legal:** personal data, consent for minors, age band; Auth account deletion order and deadline; retention of de-identified audit rows, the erasure record, billing records and exports; cooling-off period | erasure (S3), lifecycle flag, notifications for minors |
| **Erasure mechanism** (trigger disabling inside a definer function) on the hosting target | identity lane |
| **PO-09:** Gold amounts and caps; the "one scored answer before completion Gold" placeholder; forfeiting Gold past a cap | rewards flag, leaderboard |
| **Leaderboard:** who may consent for a minor; whether real children ever see a rank; minimum cohort size K (5 is a placeholder) and its floor; pseudonym policy; refresh schedule | leaderboard flags |
| **PO-01 / 05 / 06 / 07:** free or paid, scope, checkout, offline lease | entitlements |
| **PO-08:** content format v2 contents and maths rendering; the format-character (bidi, zero-width) policy | content v2 |
| **PO-10:** notification policy and quiet hours | notify |
| **Rights:** who clears sources; behaviour when rights on today's word are withdrawn (today: no word, never a different one) | Word of the Day, content |
| **Staff MFA** factor types and reset procedure | staff surface |
| **Haitian Creole wording** (≈106 draft strings, demo vocabulary) | every learner-facing flag |
| **Hosting:** hosted Supabase project and its `supautils` configuration | S1 assertion, S2, erasure portability |

## 9. Branches and draft PRs

Overnight (all drafts, none merged): #4 staff · #5 identity · #6 notify · #7 content · #8 native (on
`mobile-02`) · #9 Word of the Day · #10 entitlements · #11 integration · #12 rewards · #13 leaderboard.

Corrections from this verification (drafts, each implemented by a separate agent and reviewed independently):

| PR | Branch | Base | Content |
|---|---|---|---|
| [#14](https://github.com/steevy-cpu/edupreneurs-platform/pull/14) | `review/fix-notify-review-findings` | #6 | XFF, log leak, flag-off 404, lease re-check |
| [#15](https://github.com/steevy-cpu/edupreneurs-platform/pull/15) | `review/fix-native-harness-and-onboarding` | #8 | test-harness isolation + onboarding layout + truthful connectivity |
| [#16](https://github.com/steevy-cpu/edupreneurs-platform/pull/16) | `review/fix-rewards-hook-timeouts` | #12 | hook time budget, rule-switch race |
| [#17](https://github.com/steevy-cpu/edupreneurs-platform/pull/17) | `review/fix-staff-text-rules` | #4 | control characters, Windows line endings |
| [#18](https://github.com/steevy-cpu/edupreneurs-platform/pull/18) | `review/fix-content-attach-author` | #7 | asset attach/detach author-only |
| [#19](https://github.com/steevy-cpu/edupreneurs-platform/pull/19) | `review/fix-leaderboard-review-findings` | #13 | privacy floor, snapshot-only rank, locks, speed |
| [#20](https://github.com/steevy-cpu/edupreneurs-platform/pull/20) | `review/main-security-and-test-isolation` | `main` | TEMP revoke + harness isolation only (pgTAP 215, pytest 148, Jest 61) |
| this report | `review/final-verification-2026-11-25` | #11's tree | integration of #11 plus #14, #16, #17, #18, #19, the reports and the emulator evidence |

## 10. Merge-readiness verdict per PR

"Dormant" means the code may land with every flag off and the staff side unconfigured; it does
not mean the feature may be enabled.

| PR | Verdict |
|---|---|
| **#20** `main` hardening | **Recommended first**, once its CI passes: closes S1 and S4 on `main` without any feature code |
| #3 Mobile-02 | Not re-reviewed here beyond the harness. **Needs the harness fix** (from #15) before merge |
| #4 staff (+#17) | **Closest to ready** as the platform foundation. Merge only together with #17. Staff side must stay unconfigured until MFA and takedown exist. NF-1 noted |
| #5 identity | **Not ready:** blocked on S3 and PO-04. Profile/onboarding endpoints are sound, but the lifecycle flag must stay off |
| #6 notify (+#14) | Ready as **dormant** after #14. Limiter and notification flags stay off |
| #7 content (+#18) | **Not ready:** S6 open. Acceptable only as dormant contracts after S6 is fixed; v2 content needs the 3 missing preconditions |
| #8 native (+#15) | Ready as **dormant (flags off)** after #15. Before flags go on: D2, the 7AF note, Creole review, a physical-device pass |
| #9 Word of the Day | Ready as **dormant**. Enable after the rights decisions; consider S11 |
| #10 entitlements | Ready as **dormant** (no paywall exists). L1–L4 before any commercial use |
| #11 integration | **Do not merge;** use the corrected candidate instead |
| #12 rewards (+#16) | Ready as **dormant** after #16. Enabling needs PO-09 |
| #13 leaderboard (+#19) | **Draft only.** Fix LB-R1 and LB-R2, then owner decisions, before any flag |
| #14–#19 | Merge into their base PRs (not into `main` directly) |

Nothing in this verification was merged or deployed, no real payment or message was sent, and no paid
service was activated.
