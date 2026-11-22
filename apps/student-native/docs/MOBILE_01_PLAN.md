# Mobile-01 — implementation plan

Written before implementation, after reading `docs/ARCHITECTURE.md`,
`docs/API_CONTRACT.md`, `docs/SECURITY.md`, `docs/NEXT_STEPS.md`,
`packages/contracts/` and `services/api/`.

## What the backend already gives us (no invention needed)

| Need | Existing contract |
|---|---|
| Sign in / refresh | Supabase Auth REST (`/auth/v1/token`), ES256 access token, 1 h expiry, rotating refresh token |
| Profile | `GET /v1/me` |
| Grade / subject / lesson list | `GET /v1/catalog?locale=` (each lesson carries `revision_id`) |
| Lesson snapshot | `GET /v1/lessons/{id}?locale=` — one response with `revision_id`, `revision`, `blocks`, all questions with answer keys |
| Upload offline work | `POST /v1/sync/push` (per-op `accepted` / `rejected` / `conflict`, `replayed`) |
| Download server state | `GET /v1/sync/pull` (gap-free versions, opaque cursor, `410` reset) |

**Decision on §5 (download):** the lesson endpoint is already a complete,
revision-aware snapshot in a single response, so **no backend change is made**.
It has no checksum or signature, so this is *not* a verified pack-distribution
system; the app validates the snapshot's structure and replaces the saved copy
atomically, and says no more than that.

## Environment constraint found during inspection

> **Correction (added during implementation).** The first inspection concluded
> that this machine had no Xcode and no Android SDK. That was wrong: the
> command-line tools were simply not pointed at Xcode. Xcode 26.3 (older than the 26.4 Expo SDK 58 requires), CocoaPods and
> iOS simulators are installed, and Android Studio was being set up at the same
> time. The real blocker turned out to be **free disk space** (under 2 GB, and at
> one point 130 MB, which crashed the local Docker VM). A native development
> build needs several GB, so none was attempted. See `MOBILE_01_REPORT.md`.

Consequences for this task:

- can do: write the app, type-check it, bundle it for Android and iOS with Metro,
  and run its storage + sync logic against a **real SQLite engine** and the
  **real local API and Auth**;
- not done: launching the app on a simulator, emulator or phone.

The design below is chosen so that as much behaviour as possible lives in code
that *can* be executed and tested without a device.

## Architecture

```
src/core/      platform-free TypeScript (no react-native / expo imports)  ← tested in Node
  api/         generated OpenAPI types, small fetch client, error model, snapshot validation
  auth/        Supabase Auth REST client, session manager (token refresh, sign-out, epochs)
  db/          SqlDatabase interface, schema migrations, ContentStore, AccountStore
  learning/    save-lesson-offline, record-answer, complete-lesson
  sync/        SyncEngine (push, pull, backoff, single-flight)
  i18n/        fr / ht strings
src/platform/  thin adapters: expo-sqlite, expo-secure-store, expo-crypto, env config
src/ui/        app context, shared components
src/app/       Expo Router screens
tests/         jest: same core code with a Node SQLite adapter, against the live local stack
```

Stack: Expo SDK 58 (React Native 0.88, Android minSdk 24 = Android 7.0, iOS 16.4+ — corrected, see MOBILE_01_REPORT §7),
Expo Router, `expo-sqlite`, `expo-secure-store`, `expo-crypto` (UUIDs). No Supabase
SDK, no state library, no i18n library, no UI kit, no NetInfo — fewer megabytes
and fewer things to break on old phones.

## Local storage

Two kinds of SQLite file:

- `content.db` — shared, **public** lesson data: saved lesson snapshots,
  questions, cached catalog.
- `account-<user id>.db` — **private**, one file per account: attempts, progress
  projection, outbox (pending operations), pull cursor, preferences.

A signed-in session opens only its own account file, so Student B's session
cannot query Student A's rows — there is no shared table to forget a `WHERE` on.
Tokens live only in SecureStore.

Key transactions:

1. *Answer a question* — attempt row + progress projection + outbox row, one
   transaction, committed **before** the UI shows confirmation.
2. *Push acknowledgement* — store the server result on the attempt/progress and
   remove the outbox row, one transaction.
3. *Pull* — apply a page of changes and advance the cursor, one transaction.
4. *Save lesson* — replace the snapshot and its questions, one transaction, only
   after the download has been fully received and validated.

## Sync engine

Single-flight (`run()` returns the in-progress run), bound to one session.
Push pending ops in batches ≤ 50 with their original `op_id`s → apply results →
pull pages until `has_more` is false. Transient failures (network, timeout, 5xx,
503) retry with bounded exponential backoff, then stop until the next trigger
(sign-in, app foreground, after an answer, manual "sync now") — no polling.
`401` → refresh the token once; if refresh is refused → state `auth_required`,
nothing local is touched. `rejected` / `conflict` → kept as "needs attention",
never retried. Every step re-checks that the session is still the active one.

## Account switch

Sign-out bumps a session epoch, aborts in-flight requests and closes the account
database; a late response cannot be written. With unsynced work, sign-out first
offers: sync now · sign out and keep the work on this phone (it syncs at that
account's next sign-in) · cancel. There is no "delete my unsynced work" button.

## Test plan

- Unit: snapshot validation, backoff, i18n completeness, session manager.
- Integration (Node SQLite file + live local API/Auth): every scenario in §8 of
  the assignment, including restart (close and reopen the database files),
  lost response after commit, two accounts on one "device", expired/revoked
  session, interrupted download, outage, storage failure mid-transaction.
- Build checks: `tsc --noEmit`, `expo-doctor`, Metro export for Android and iOS.
- **Pending (cannot be done on this machine):** running on Android/iOS
  emulators, development builds, physical low-memory devices, on-device
  performance numbers.

## Out of scope

Jude, billing, community, games, profile editing (`PATCH /v1/me` does not exist:
grade/subject choice is a local preference), background sync, media.
