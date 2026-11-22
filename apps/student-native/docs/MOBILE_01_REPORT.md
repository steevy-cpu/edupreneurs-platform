# Mobile-01 — report

**Overall status: PARTIAL.** The app is written, type-checks, bundles for Android
and iOS, and its storage + synchronisation logic passes 52 automated tests
against the real local backend — including the full "save lesson → airplane
mode → five answers → force-quit → reopen → reconnect" scenario.
**The app has not been launched on any simulator, emulator or phone**, so the
definition of success is proven for the logic underneath the screens, not for
the screens themselves.

Every claim below is tagged:

| Tag | Meaning |
|---|---|
| **[TESTED]** | Executed by an automated test in this repository, on 2026-11-22, with a real SQLite engine and the real local API + Supabase Auth |
| **[BUILT]** | Code exists, passes the TypeScript compiler and is included in the Metro bundles — but was **not executed** |
| **[SIMULATED]** | Measured or exercised in Node on the development Mac, standing in for a phone |
| **[NOT DONE]** | Not performed |

## 1. Screens and workflows

| # | Screen (route) | What it does | Status |
|---|---|---|---|
| 1 | Sign-in (`/sign-in`) | E-mail + password against Supabase Auth; distinct messages for wrong password vs unreachable server; language switch; "sign in again" mode when the session expired | **[BUILT]** — the sign-in, refresh and error paths underneath are **[TESTED]** |
| 2 | Home (`/home`) | Greeting, navigation, sync card, language (Français / Kreyòl), sign-out with unsynced-work warning | **[BUILT]** |
| 3 | Class and subject (`/select`) | Lists grades and subjects from the cached catalog (refreshes in the background), stores the choice per account | **[BUILT]** — catalog caching **[TESTED]** |
| 4 | Lessons (`/lessons`) | Lesson list from SQLite first; saved / not saved / new version; explicit **save for offline**; open | **[BUILT]** — save, update, failure handling **[TESTED]** |
| 5 | Lesson reader (`/lesson/[id]`) | Renders the saved blocks (heading, paragraph, example, callout) from SQLite only; "start practice"; "I finished the lesson" | **[BUILT]** — reading saved content with zero network calls **[TESTED]** |
| 6 | Practice quiz (`/quiz/[id]`) | One question at a time; the answer is written to SQLite, **then** feedback + "saved on this phone" appear; result summary marked provisional | **[BUILT]** — save-before-confirm transaction **[TESTED]** |
| 7 | Progress and sync (`/progress`) | Per-lesson answered / correct / completed, waiting vs synced, items needing attention, manual sync | **[BUILT]** — every number shown comes from **[TESTED]** queries |

French and Haitian Creole: all 85 UI strings exist in both languages (a test
fails if a key is missing or empty). Lesson content is the seed 9AF mathematics
lesson in both languages.

## 2. Repository structure (new and changed)

```
apps/student-native/
  app.json, package.json, package-lock.json, tsconfig.json, jest.config.js, README.md, AGENTS.md
  src/core/        api/ auth/ db/ learning/ sync/ i18n/   (platform-free; all correctness-critical code)
  src/platform/    expoSqlite.ts, secureTokenStore.ts, config.ts, services.ts
  src/ui/          AppContext.tsx, components.tsx, SyncCard.tsx, useSession.ts
  src/app/         _layout, index, sign-in, home, select, lessons, lesson/[id], quiz/[id], progress
  tests/           unit/, integration/, perf/, support/ (Node SQLite adapter, simulated device, local-API harness)
  docs/            MOBILE_01_PLAN.md, MOBILE_01_REPORT.md
scripts/mobile_env.py, scripts/dev_login.py        (new, local only)
Makefile                                           (new targets: mobile-*, dev-login, api-lan)
.github/workflows/ci.yml                           (mobile checks + tests added)
apps/README.md                                     (updated)
```

About 4,500 lines of TypeScript. Runtime dependencies added on top of
Expo/React Native: `expo-router` (+ its required peers), `expo-sqlite`,
`expo-secure-store`, `expo-crypto`. Not added: Supabase SDK, state management,
i18n, UI kit, NetInfo, animation or media libraries.

## 3. SQLite schema and persistence design

Two kinds of database file. Tokens are in neither.

**`content.db` — public lesson content, shared by all accounts on the phone**

| Table | Key | Purpose |
|---|---|---|
| `saved_lessons` | `(lesson_id, locale)` | One saved snapshot per lesson and language: `revision_id`, `revision`, title, blocks JSON, saved time |
| `saved_questions` | `question_id` | Questions of the saved revision: prompt, choices, answer key, explanation (JSON) |
| `catalog_cache` | `locale` | Last catalog response, so lists render without the network |

**`account-<user id>.db` — private, one file per account**

| Table | Key | Purpose |
|---|---|---|
| `attempts` | `op_id` | Every practice answer known on this phone: made here (`origin = local`) or pulled from another device (`remote`); local provisional verdict; server verdict, score, attempt id, change version; `sync_state` |
| `question_progress` | `question_revision_id` | Projection: latest answer per question, attempt count, sync state. Rebuilt from `attempts` inside the same transaction as any change |
| `lesson_progress` | `lesson_id` | Completion: local intent (revision, time, op id) and server confirmation (revision, time, version) |
| `outbox` | `seq` (autoincrement), unique `op_id` | Operations not yet confirmed by the server, in the order they happened; `state` = `pending` or `needs_attention`; problem code; send attempts |
| `meta` | `key` | Owning account id, pull cursor, last sync time, cursor-reset flag, preferences (locale, grade, subject) |

Settings: WAL journal, `synchronous = FULL`, schema versioned with
`PRAGMA user_version`. All writes go through a mutex, so a transaction never
interleaves with another write on the same connection.

The four transactions that carry the guarantees (all **[TESTED]**, including
with injected storage failures at each statement):

1. **Answer** — attempt + progress projection + outbox row. The UI awaits this before confirming.
2. **Push acknowledgement** — server result written onto the attempt / progress row, *then* the outbox row removed, per operation, one transaction per batch.
3. **Pull** — a page of changes applied and the cursor advanced together.
4. **Save lesson** — old snapshot and questions replaced by the new ones together, only after the download was fully received and validated.

Why per-account files rather than an `account_id` column: a session can only
open its own file, so there is no query in which a forgotten `WHERE` could
expose another student's rows. The file refuses to open for a different account id.

## 4. Synchronisation

`SyncEngine.run()`:

1. **Push** pending operations in `seq` order, ≤ 50 per request, each with the
   `op_id` it was given when the action happened. The id is stored in SQLite and
   never regenerated, so a retry after a lost response is recognised by the server.
2. Apply each per-operation result: `accepted` (new or `replayed`) → confirmed;
   `rejected` / `conflict` → `needs_attention`, never sent again.
3. **Pull** pages from the stored cursor until `has_more` is false; each page and
   its cursor are committed together. A change carrying one of this phone's own
   `op_id`s also confirms that operation (heals a lost push response).
4. Record the last successful sync time.

| Requirement | How | Evidence |
|---|---|---|
| Unique operation ids, preserved across retries and restarts | UUID v4 at action time, stored in `outbox` | offline-flow and lost-response tests; mutation A below |
| Only the signed-in account's operations are sent | The engine holds one account's database and one session's token provider | two-accounts test |
| Bounded exponential backoff for transient failures | 4 attempts per step by default: waits of 1 s, 2 s, 4 s (cap 30 s, 50–100 % jitter), then stop until the next trigger | outage test asserts exactly 3 waits of 1000/2000/4000 ms and 4 requests |
| Permanently rejected operations are not retried forever | Flagged once; later runs send nothing | rejected-operations test (push count unchanged over 3 more runs) |
| A request-level refusal (413 / 422) cannot block the queue | Batch is halved until the offending operation is alone, then it is set aside | request-level-refusal test |
| Acknowledgement persisted before removal | Same transaction, in that order | storage-failure-during-ack test |
| Pull applied atomically with the cursor | One transaction | storage-failure-during-pull test |
| Never shown as synced before the server confirms | `sync_state` changes only in the two confirm paths | lost-response test asserts `pending` while the server already holds the rows |
| No overlapping runs | `run()` returns the in-flight promise | single-flight test (one HTTP push for three calls) |
| Expired session does not lose work | Refresh once on 401 / near expiry; if Auth refuses → `auth_required`, credentials cleared, database untouched, further offline work still possible | revoked-session test |
| Progress reconciled across devices | Remote attempts merged by `op_id`; "latest answer" follows the server's change version; lesson completion takes the server's record | two-devices test |
| Unusable cursor (410) | Cursor dropped, server-derived rows rebuilt from the first page, outbox untouched | cursor-reset test |

Triggers: after sign-in / session restore, when the app returns to the
foreground, after each saved answer or completion, and the manual button.
There is no timer and no background task.

A defect found by these tests and fixed during the work: two phones on one
account disagreed about which answer was the "latest" (one ordered by its own
clock, the other by server time). Ordering now follows the server's change version.

**Account isolation.** Sign-out marks the session inactive, aborts its in-flight
requests, clears SecureStore and closes the account database. The engine checks
"is my session still active?" before every local write, so a response arriving
after an account switch is dropped. With unsynced work, sign-out shows a dialog:
*sync first* / *sign out and keep my work* / *cancel*. There is deliberately no
option that deletes unsynced work; kept work is uploaded at that account's next sign-in.

## 5. Backend changes

**None to the API, database or contract.** `GET /v1/lessons/{id}?locale=` already
returns a complete, revision-aware snapshot in one response, so it is used as is.

It carries no checksum or signature. The app therefore validates structure and
identity (right lesson, right language, revision present, non-empty body,
well-formed questions, answer key among the choices) and replaces the saved
copy atomically — and **makes no claim of verified pack distribution**. Checksum,
signature and activation guarantees remain future work (see §9).

Repository-level additions that are not API changes: `scripts/mobile_env.py`,
`scripts/dev_login.py`, Makefile targets, and mobile steps in the CI workflow.

## 6. Automated test results

All commands were run on 2026-11-22 on the development Mac against the local stack.

| Command | Result |
|---|---|
| `make mobile-test` (`npx jest`) | **52 passed, 0 failed, 0 skipped** — 6 files |
| `make mobile-check` | generated API types up to date; `tsc --noEmit` clean for the app and for the tests |
| `npx expo-doctor` | 20/20 checks passed |
| `npx expo export --platform android --platform ios` | both bundles built (see §8) |
| `make test-db` | **209 passed** (unchanged) |
| `uv run pytest` | **144 passed** (unchanged) — backend total still 353 |
| `make lint`, `make typecheck` | clean |

Mobile tests by file: `unit/core` 17 · `integration/offline_flow` 2 ·
`integration/sync_resilience` 11 · `integration/accounts_and_auth` 12 ·
`integration/downloads_and_storage` 9 · `perf/local_storage_timing` 1.

**What these tests are.** They run the app's real `src/core` code in Node. The
"phone" is a temp directory of real SQLite files (Node's built-in SQLite 3.50
behind the same `SqlDatabase` interface the device adapter implements), an
in-memory stand-in for SecureStore, and real HTTP to the local API and Supabase
Auth with switchable failure modes. A "force-quit" closes the files and builds
every object again from disk. **They do not render React Native screens and do
not execute `expo-sqlite` or `expo-secure-store`.**

Coverage of the required scenarios:

| Required scenario | Test | Level |
|---|---|---|
| Download and reopen a saved lesson | offline flow; Creole copy | **[TESTED]** core |
| Complete all five questions offline | offline flow | **[TESTED]** core |
| Restart with unsynced answers; restore progress | offline flow (kill + boot, twice) | **[TESTED]** core |
| Reconnect and synchronise | offline flow | **[TESTED]** core |
| Server commits, response lost | lost-response (two tests) | **[TESTED]** core |
| No duplicate attempts | offline flow, lost-response, single-flight, storage-failure-during-ack | **[TESTED]** core + server feed |
| Switching between two accounts | two-accounts; in-flight response after switch; wrong-account; foreign database file | **[TESTED]** core |
| Expired authentication | expired token; pre-expiry refresh; single refresh; revoked session; refresh while offline | **[TESTED]** core |
| Interrupted content downloads | first download interrupted; eight failure modes on update | **[TESTED]** core |
| Invalid or changed lesson revisions | changed revision; wrong lesson; 13 validation cases; unknown revision rejected by server | **[TESTED]** core |
| API outage / unreachable server | outage with backoff; 503 recovery; Auth unreachable at sign-in | **[TESTED]** core |
| Local storage errors | failure at each statement of the answer transaction; during ack; during pull; during lesson replace | **[TESTED]** core (failures injected in the Node adapter) |

**Do the tests detect bugs?** Two deliberate defects were introduced and reverted:

| Mutation | Result |
|---|---|
| A — generate a new `op_id` when sending instead of reusing the stored one | 17 of 34 integration tests failed |
| B — write the outbox row in a separate transaction from the attempt | 1 failed (the storage-failure atomicity test) |

## 7. Android and iOS testing evidence

| Check | Android | iOS |
|---|---|---|
| Metro production bundle (Hermes bytecode) builds | **done** — 2.7 MB | **done** — 2.7 MB |
| Minimum OS of the chosen SDK | Android 7.0 (API 24), from React Native 0.88's `minSdk = 24` | **iOS 16.4** — every Expo module in the app (`Expo`, `ExpoModulesCore`, `ExpoRouter`, `ExpoSecureStore`) declares `:ios => '16.4'` in its podspec, matching Expo's SDK 58 table |
| Required build tool | compileSdk 37, build-tools 37.0.0, NDK 27.1 (React Native 0.88 `libs.versions.toml`) | **Xcode 26.4+** (Expo SDK 58 table) |
| Native development build (`expo run:*`) | **[NOT DONE]** | **[NOT DONE]** |
| Launched on emulator / simulator | **[NOT DONE]** | **[NOT DONE]** |
| Manual acceptance scenario on screen | **[NOT DONE]** | **[NOT DONE]** |
| Physical device, including older low-memory Android | **[NOT DONE]** — no device available | **[NOT DONE]** |

Why no native build: this Mac had under 2 GB of free disk during the work (at
one point 130 MB, which crashed the local Docker VM). Xcode 26.3, CocoaPods and
iOS simulators are installed; Android Studio was being installed at the same
time and had no virtual device yet. A first native build needs several GB, so
attempting one risked another disk-full failure. Nothing was deleted to make room.

> **Correction (2026-11-22, after review).** An earlier version of this report
> said "iOS 15.1+" and treated the installed Xcode 26.3 as usable. Both were
> wrong. 15.1 is React Native's own floor; the app's effective minimum is
> **iOS 16.4** because Expo's modules require it, and Expo SDK 58 requires
> **Xcode 26.4 or newer**. The installed Xcode (26.3, iOS SDK 26.2) is therefore
> too old to build this app and must be updated first. The deployment target has
> not been, and will not be, lowered below what Expo supports. Practical
> consequence: iPhones that cannot run iOS 16.4 (iPhone 7 and older) are not
> supported by this SDK.

Consequently these are **unverified on a real runtime**: the `expo-sqlite`
adapter (notably `withExclusiveTransactionAsync`), the SecureStore adapter,
Expo Router navigation and redirects, the sign-out dialog, keyboard and layout
behaviour, app-foreground sync trigger, and cleartext-HTTP access to the local
API from an emulator.

## 8. Performance

| Target | Measurement | Status |
|---|---|---|
| Cached home usable within 3 s on the low-memory baseline | — | **[NOT DONE]** (needs a device) |
| Cached lesson opens within 1 s | — | **[NOT DONE]** on a device |
| Storage path for reopening a saved lesson | Open both databases, restore the session and read the lesson + progress: **median 1.4 ms, max 2.7 ms** over 15 cold opens | **[SIMULATED]** Node on an Apple-Silicon Mac — not comparable to a phone |
| Durable answer write (3-table transaction, fsync) | **median 0.4 ms, max 2.6 ms** over 50 writes | **[SIMULATED]** same caveat |
| No network needed to reopen a saved lesson | Zero HTTP calls while reading saved content (asserted) | **[TESTED]** core |
| Text-first, system fonts | No custom fonts, images (beyond the app icon), animation or media libraries; stack transitions disabled | **[BUILT]** |
| No background polling or media download | No timers or background tasks in the code; sync runs only on the four triggers listed in §4 | **[BUILT]** |
| JavaScript bundle size | 2.7 MB Hermes bytecode per platform | measured |

The simulated numbers only show that the SQL is cheap. On a low-end Android
phone, process start, Hermes start-up and flash storage will dominate; none of
the three device targets may be reported as met until measured there.

## 9. Outstanding defects and security risks

**Not verified (highest priority)**

1. The app has never run on a device or emulator (see §7). Treat every screen as untested.
2. No UI/component tests. The Expo Jest preset conflicted with the SDK's React version, so only platform-free code is under test.
3. Linux/CI: the workflow was extended but has never run on a runner.

**Functional gaps**

4. A second sign-in on the same phone as a *different* account requires the first account to sign out; there is no account picker.
5. Grade and subject are a local preference only: the API has no profile-update endpoint, so `GET /v1/me` is not used and the choice does not follow the student to another phone.
6. "Needs attention" items are listed with their code but there is no action to dismiss or redo them.
7. Lesson completion is a manual button in the reader; finishing the quiz does not mark the lesson complete.
8. Saved lessons are never removed and old revisions' questions are dropped when a lesson is updated (attempts keep their own data, so history is intact, but the old question text is no longer shown).
9. No connectivity listener: after an outage the app retries on foreground, on the next answer, or on the manual button — not automatically when the network returns.
10. After a cursor reset, attempts made on this phone keep their previous server fields until the feed replays them.

**Security and privacy**

11. **No integrity check on downloaded lessons.** A snapshot is validated for shape only; there is no checksum or signature, so a tampered response over plain HTTP would be accepted. Requires HTTPS in any hosted environment and a signed manifest for real pack distribution.
12. **Local databases are not encrypted.** A signed-out account's `account-<id>.db` stays on the phone (that is what makes "keep my work" safe). It is unreachable through the app, but readable on a rooted/jailbroken device or from a device backup. Options later: SQLCipher, or an explicit "remove this account from this phone" action once work is synced.
13. An expired session (`auth_required`) keeps the previous student's data visible until someone signs out. On a shared phone that is a deliberate trade-off in favour of not losing work; an inactivity lock is a possible follow-up.
14. Answer keys are stored on the phone (by design for offline practice). Local "correct / incorrect" is provisional and the server re-scores; scores are not proof of knowledge.
15. Local development uses plain HTTP: iOS allows it only for local networking (`NSAllowsLocalNetworking`); Android allows it in debug builds. Release builds must use HTTPS and must not ship these exceptions.
16. `make api-lan` exposes the development API to the local network without TLS. Development only.
17. The e-mail address is shown on the home screen and kept in SecureStore; the display name from the profile is not used.
18. Babel's TypeScript preset used by the tests is resolved through Expo's own dependencies rather than declared explicitly; the lockfile pins it, but it should be made an explicit dev dependency.

## 10. Commands

```bash
# automated checks (no phone needed)
make start                 # backend stack
make mobile-install        # once
make mobile-check          # API types fresh + TypeScript
make mobile-test           # 52 tests against the local stack
make check                 # the 353 backend tests, lint, types

# run the app (needs ~10 GB free disk for the first native build)
make api                                  # terminal 1
make dev-login ACCOUNT=student_a          # terminal 2: prints e-mail + password
make mobile-env TARGET=ios-sim            # or android-emu / lan
make mobile-ios                           # or make mobile-android
```

The manual acceptance script (the definition of success, on a device) is in
`apps/student-native/README.md`.
