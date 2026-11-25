# Independent review — lane NATIVE (`overnight/native-experience` @ 779657f, base `mobile-02` 54fec1c)

Reviewer: independent, read-only source review. Nothing was modified, staged, committed, built or
run (no Jest, no emulator). Every statement below comes from reading the diff, the files at
779657f, the brief, and the three backend lane documents. Paths are relative to
`apps/student-native/` unless they start with `docs/`.

## Verdict: APPROVE WITH FIXES

The work is careful: migrations are additive and transactional, everything new is per account,
queries are parameterised, server responses are validated before storage and again on read, Gold is
never computed on the phone, the leaderboard route has no data source, and no existing test,
dependency, backend file, contract or generated type was touched. With every flag unset the new
code is unreachable.

It is safe to merge **with all flags off**. Before a flag is switched on:

- `dailyWord`: fix H1 (and decide M1/M2).
- `onboardingSync`: fix M3 and M4.
- `rewards`: fix M5.

## Findings

### HIGH

**H1 — Yesterday's word stays labelled "Mot du jour" while Accueil remains mounted**
`src/ui/experience/DailyWordCard.tsx:40-57` and `:61`; `src/core/experience/dailyWord.ts:68`.
The freshness (`today` / `last_downloaded`) is computed once, inside the mount effect, and stored
in React state. The effect depends on `[account, remote, locale]` only; it is a plain `useEffect`,
not a focus effect, and nothing listens to the app returning to the foreground.
Failing scenario: a learner opens Accueil at 20:00, the card says "Mot du jour". The phone is put
down with the app in the background (or the learner opens a lesson pushed on top of Accueil) and
is picked up the next morning. Accueil is still mounted, the effect does not run again, the state
still says `today`: yesterday's word is shown under "Mot du jour" with the highlighted card, with
or without network, until the learner changes tab. The foreground sync re-renders Accueil but the
card only re-renders its frozen state. This breaks the slice's central rule ("never present
yesterday's word as today's") in the most ordinary usage pattern.
Smallest fix: keep `fetchedAt` / `validUntil` in the view and call `freshnessOf(..., now())` at
render time; re-run the read + refresh on focus and on `AppState` `active` (or schedule one
re-render at `validUntil`).
Missing test: render Accueil once, move the clock past `valid_until`, re-render the **same**
instance (and simulate a foreground event) and assert the label. The existing boundary test
(`tests/components/daily_word.test.tsx:144-161`) mounts a new `<Home />` for each instant, so it
cannot see this.

### MEDIUM

**M1 — A phone clock set behind real time shows yesterday's word as today's, online, for up to 6 h**
`src/core/experience/dailyWord.ts:37-42` (label uses the absolute device clock), `:33` and `:96-99`
(6-hour revalidation). The author documents the offline half of this as a known limit; the online
half is a consequence of the 6-hour choice.
Scenario: device clock 5 hours slow (manual time, no network time — common on old phones). After
the real Haiti midnight the device still believes `now < valid_until`, so the word is `today`, and
because it is `today` the next request is not due for 6 hours after the last attempt. The learner
is online and still sees yesterday's word as "Mot du jour" for hours. Offline it lasts as long as
the clock is wrong (a clock reset to a past year: indefinitely).
Smallest fix: stop trusting the absolute clock. At download, compute the remaining lifetime from
the server (`valid_until` minus the response `Date` header) and call the word today's only while
`0 <= now - fetchedAt < lifetime`; cap the lifetime at about 25 h. Elapsed time is right even
when the absolute time is wrong. Also see M2 for the revalidation rhythm.

**M2 — Withdrawn or switched-off content can stay on screen for up to 6 hours**
`src/core/experience/dailyWord.ts:98` and `:124-133`; `DailyWordCard.tsx:51`.
The server sends `Cache-Control: private, no-cache` and the vocab contract (rule 4) asks for a
conditional request "at most once per app start / return to foreground". The app asks at most
every 6 hours, and (H1) never on return to foreground.
Scenario A: an editor withdraws today's word for a rights or content reason at 09:00. A learner
who fetched at 08:00 keeps seeing it as "Mot du jour" until 14:00 on a connected phone.
Scenario B: the server feature is switched off (`404 not_found`). The outcome is `unavailable`,
the cached word is kept and still displayed as today's; the contract (rule 6) says to hide the
card and keep the cache.
A 304 costs a few hundred bytes. Smallest fix: one conditional request per app start and per
return to foreground (an in-memory marker, no timer), keeping the 10-minute spacing for failures;
hide the card while the last outcome is `unavailable`. If 6 hours is kept, it should be an explicit
owner decision, since the app serves minors and withdrawal is the content-safety lever.

**M3 — Onboarding sync retries on every Accueil focus with no back-off and no terminal state**
`src/app/home.tsx:69-71`; `src/core/experience/onboardingSync.ts:80-98`; `src/app/onboarding.tsx:128-132`.
Unlike the word and the Gold summary (10-minute spacing), `syncOnboarding` runs whenever something
is owed and Accueil gains focus or the sync summary changes. Any failure leaves the flags set.
Scenario A: the identity lane has three server flags; `EDU_ONBOARDING_ENABLED` on and
`EDU_PROFILE_EDIT_ENABLED` off is a legal server state, the app has one client flag. `PATCH /v1/me`
answers 404, `profileNeedsPush` stays set, and every visit to Accueil sends a `GET` and a `PATCH`
for ever.
Scenario B: the grade chosen offline from the built-in list is not active on the server
(`422 grade_not_available`). Same endless retry; it can never succeed.
Scenario C: finishing onboarding fires a sync and immediately navigates to Accueil, whose focus
effect fires a second one: duplicate `GET`/`PUT`/`PATCH` (harmless on the server, paid for by the
learner).
Smallest fix: store the last attempt time and space attempts like `RETRY_AFTER_MS`; treat a 4xx
other than 401 on `PATCH` as final (clear `profileNeedsPush`); keep one in-flight promise per
account.

**M4 — A learner the server already knows is carried past the grade step on a new phone with no grade on the phone**
`src/core/experience/onboarding.ts:57-61` and `:233-241`.
Identity's returning-learner rule reports `profile_selected` for any learner who has a grade. On a
new phone the merge moves `step` to `downloads`; the adapter never reads the server profile, so
the local grade preference stays empty.
Scenario: the learner is reading the welcome step, the background sync returns, the screen jumps
to step 4, the last step says "Classe : à choisir dans Apprendre", and Apprendre shows no courses
until a grade is picked there — although the server knows the grade.
Smallest fix: when the local grade preference is empty, raise `furthestStep` only and never move
`step` beyond `grade`; or read `grade.code` from `GET /v1/me` and prefill. Do not move the visible
step while the learner is on it except to finish the flow.

**M5 — A cached streak is presented as "current" however old the copy is**
`src/ui/experience/Rewards.tsx:69`; `src/core/experience/remote.ts:203-206`.
The parser drops `today`, `streak.last_active_day` and `streak.active_today`.
Scenario: the summary cached on the 1st says 5 days. The phone is offline until the 12th. Profil
shows "Série en cours : 5 jours"; the true current streak is 0. The "Confirmé par le serveur ·
date" caption is there, but the sentence itself asserts a present fact the phone cannot know.
Smallest fix: keep `today` and `last_active_day`; when the copy is older than a day show the
streak as of its date ("Série au 1er novembre : 5 jours") or omit it.

### LOW

**L1 — A phone clock set ahead re-downloads the full word every 10 minutes**
`src/core/experience/dailyWord.ts:98`. With the clock past `valid_until` (for example 5 h fast,
from 19:00 real time), each successful download is immediately `last_downloaded`, so the 10-minute
rule applies instead of the 6-hour one and every remount of Accueil after 10 minutes downloads the
whole body again until real midnight. Fix: after an `updated` outcome whose word is not `today` on
arrival, wait the long interval. (The fix proposed in M1 removes the cause.)

**L2 — Migrations rely on atomicity alone; they are not idempotent statement by statement**
`src/core/experience/schema.ts:28, 43, 57, 73, 94` (`CREATE TABLE` without `IF NOT EXISTS`, plain
`INSERT`). `migrate()` wraps each version and its `user_version` bump in one transaction, which is
correct and tested. But a migration that fails for any reason makes `AccountStore.open` throw
(`src/core/db/accountStore.ts`, `open`), and then the account's saved work cannot be opened at
all — with every flag off. Belt and braces: `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE`.
Note also that these migrations run in a flags-off build: the local schema moves to version 4 on
first start. I checked that a Mobile-02 build still opens a version-4 file (`migrate` skips
versions it does not know), so a rollback of the app is safe.

**L3 — Opening the onboarding route directly bypasses the "returning learner" rule**
`src/core/experience/onboarding.ts:99-121` versus `:72-79`. `beginOrResumeOnboarding` creates an
`in_progress` row for any account without one, including an account that already chose a grade
while the flag was off (which `onboardingGate` would have recorded as returning). After that,
Accueil sends that learner into the flow. Fix: call `onboardingGate` first in the screen and
redirect when it answers `done`.

**L4 — `profileNeedsPush` can be cleared for a change that was not sent**
`src/core/experience/onboardingSync.ts:79-91`. The flag is read, the request is sent, then the flag
is cleared unconditionally. A language tapped during the request (it sets the flag again) is
cleared without being pushed. The flag is also cleared when the patch is empty. Fix: clear only if
`updatedAt` is unchanged since the read.

**L5 — Leaderboard review component: reading order, raw sizes, truncation**
`src/ui/experience/LeaderboardReview.tsx`. In the three-column layout the elements are rendered
2nd, 1st, 3rd (`:36`, `:49`), so a screen reader announces rank 2 first; the comment says the
reading order stays 1-2-3, which is only true when stacked. Raw numbers instead of Design-00
tokens at `:37` (96/72/56), `:62` (44), `:120` (40/40/20) and the thresholds 1.2 / 1.3. Pseudonyms
are cut at two lines in column mode (`:51`). Review screen only, flag off.

**L6 — Text outside the i18n catalogue, and engine-dependent date formatting**
- Month names: `src/core/experience/dailyWord.ts:160-163`. Grade labels:
  `src/core/experience/grades.ts:18-26`. Language names: `src/app/onboarding.tsx:36-39`. These are
  translated in both languages but live outside `strings.ts`, so the catalogue checks and the
  native-review list do not cover them (the lane document should list the Creole months and grade
  labels for review).
- `src/ui/experience/Rewards.tsx:67` formats the confirmation time with
  `toLocaleString('fr-HT')`: French month and day names inside the Creole interface, and it
  depends on the engine's locale data, which the author deliberately avoided for the word card.
  (The same call already exists in `profile.tsx:88` on Mobile-02.)
- French plurals written as "action(s)", "jour(s)", "réussite(s)".
- Creole wording to put in front of a native speaker (not rewritten here): `tourNext` "Pwochen",
  `tourWhere` "onglè", `tourReplay` "Revwè", `onbSkipAll` "Sote entwodiksyon an",
  `onbReadyHome` "Ale nan akèy", `rewardsAchievements` "reyisit", `rewardsProvisional`
  "Valè pwovizwa", `lbProfileEntry` "apèsi", `wordPosDeterminer` "detèminan",
  `wordAudioSoon` "talè". The vocab lane's draft label is "Dènye mo telechaje"; the app says
  "Dènye mo ki telechaje" — settle one.

**L7 — Validation is looser than the contracts**
`src/core/experience/remote.ts`. Text limits 200 / 2000 / 2000 / 500 and 8000 bytes (`:152`,
`:157-158`, `:187-188`) against the contract's 60 / 300 / 240 / 80 and 1536 bytes: a malformed
answer could put two 2000-character paragraphs on Accueil above the review section. `valid_until`
is accepted however far in the future (`:160`): one bad value makes a word "today's" for as long
(cap at about now + 25 h). Control characters and line breaks are not removed from single-line
fields. `duration_ms` is not range-checked (`:171`). `tour_version_seen` accepts any non-negative
integer (`:132`; contract maximum 10000): one bad value silences the tour offer for good on that
account, because the merge takes the maximum (`onboardingSync.ts:37`).

**L8 — Rewards wording suggests waiting work will earn Gold**
`strings.ts` `rewardsPending` ("leur Gold sera calculé par le serveur") and `rewardsPendingShort`.
Most actions earn nothing under the rewards rules (first correct answer only, daily caps). No
number is invented, but the expectation is. Suggest "le serveur décidera s'il donne du Gold".

### NOTE

- **Flags-off equivalence is behavioural, not byte-level.** The author's own figure: the Android
  bundle with flags unset is 2,885,744 bytes against 2,778,788 on Mobile-02 (+107 KB). `FLAGS` is
  computed at run time (`flags.ts:29-40`), so nothing is removed from the bundle; three routes
  (`/onboarding`, `/tour`, `/leaderboard`) are always registered (`_layout.tsx`) and redirect when
  their flag is off; the local schema is migrated. No extra query runs on Accueil or Profil with
  flags off (checked: `home.tsx:53, 60, 69`, `profile.tsx`).
- **Leaderboard fixtures and `/design`.** The production route passes `entries={[]}` and imports no
  fixture; the fixture and the preview route are under the two folders that `metro.config.js`
  blocks in production. The pseudonym strings do not occur in production source. I did not build a
  bundle to confirm the exclusion.
- **The cache stores a normalised copy, not the body "verbatim"** as the vocab contract suggests:
  `audio.asset_id` and `sha256` are dropped (`remote.ts:166-173`). A future playback feature will
  have to download the word again.
- **Negative balance.** `remote.ts:202` refuses a negative balance; the refusal is classed as
  "unreachable" and the previous balance stays on screen as confirmed. The rewards lane states a
  balance can never go below zero (staff adjustments are bounded), so this is consistent today.
  Adjustments of either sign change the balance between two summaries without any pending work on
  the phone: nothing in the app assumes the balance only grows (checked).
- **401 handling.** A 401 forces one token refresh per call (`remote.ts:309-312`), the same rule as
  the existing client; concurrent refreshes share one request (`core/auth/session.ts:150-154`). A
  new endpoint that wrongly answered 401 would cost a refresh on every attempt.
- `Retry-After` on 503 is not read; the fixed spacings make this acceptable.
- The author's test counts (22 suites, 319 tests) are for e3aec2b. 779657f differs from it by the
  lane document only (checked with `git diff --stat e3aec2b 779657f`). I did not run anything.
- The lane document reports that the mobile test harness once truncated the shared stack's
  learning tables (incident I-01) and now relies on a wrapper script. Outside this review's scope;
  the director should confirm it is tracked.

## Verified sound

- **Data safety.** v2–v4 only create new tables and insert into them; no statement touches
  `attempts`, `question_progress`, `lesson_progress`, `outbox` or `meta` (schema.ts, whole file).
  Each version and its `user_version` bump share one transaction (`db/driver.ts:49-60`). The
  upgrade row marks an existing account as returning. Onboarding writes only the grade and subject
  preferences Apprendre already writes. Sign-out, account switch and cache replacement delete
  nothing from learning tables. `ExperienceStore` contains no statement on a learning table.
- **Per account.** Onboarding, tour, word cache, Gold copy and the language preference are all in
  the account's own database file; nothing new is device-global; nothing new goes to secure
  storage; no token, e-mail or name is written to SQLite by the new code.
- **SQL.** All values are bound parameters. The only interpolation is of compile-time constants
  (`schema.ts:20-23`).
- **Offline.** Every new screen draws from SQLite before any request. No request is awaited before
  a screen is shown (`home.tsx:67-71`, `onboarding.tsx:69-76`, the two cards). Requests have a
  15-second timeout and are cancelled at sign-out. Nothing new is in the path of opening a lesson
  or saving an answer. No request is started during render.
- **Honesty of Gold.** The balance is displayed exactly as received, with the time received;
  pending work is a count of actions, never added, never valued; no summary means no number.
- **Leaderboard.** No ranking request, query or learner name exists in any production path.
- **Minors and privacy.** No age, consent or legal question. Sent to the server: onboarding state,
  flow version, two tour fields, grade code, interface language — exactly the documented fields. No
  analytics, no logging added.
- **Rules.** `package.json` and the lockfile are unchanged; no backend, `packages/contracts` or
  `schema.d.ts` edit; four tabs; no existing test or test-support file modified (all 15 test files
  are additions).
- **Accessibility as far as source shows.** New touchables are Design-00 `Button`, `Chip`
  (radio role, selected state, label) and `ListRow`; headings carry the header role; grade choices
  are one per line; pills wrap; the podium stacks at large text or narrow width.
- **Strings.** Every new key exists in both dictionaries.

## Missing tests

1. H1: the card kept mounted across `valid_until`, and across a background/foreground cycle.
2. M1: device clock behind real time, online and offline; clock ahead (L1) request count.
3. M3: `PATCH` answering 404 and 422 — number of requests over several Accueil visits; two
   overlapping sync runs.
4. M4: new phone, server at `profile_selected`, no local grade — which step is shown and what
   Apprendre shows afterwards.
5. M5: a summary cached days ago — what the streak line says.
6. The real `useRemote` hook is mocked in every component test; its "no session or no network flag
   means no adapter" rule has no test.
7. Flags-off equivalence is asserted item by item, not against a Mobile-02 snapshot of Accueil and
   Profil; nothing checks the production bundle for the fixture or the `/design` route.
8. L3: opening `/onboarding` directly for an account that already has a grade.
9. Upper bounds of the validators (L7), `valid_until` far in the future.

## Contract mismatches (adapters versus the backend lane documents)

Identity (`lanes/identity.md`):
- Three server flags (`EDU_PROFILE_EDIT_ENABLED`, `EDU_ONBOARDING_ENABLED`, lifecycle) against one
  client flag `onboardingSync` covering `PATCH /v1/me` and the onboarding routes (see M3).
- `422 grade_not_available`, `422 empty_patch`, `422 validation_error`: no specific handling; all
  are "failed, retry" (M3).
- Returning-learner rule (`profile_selected` when a grade exists, `ready` when work was accepted):
  `ready` is handled; `profile_selected` produces M4. The contract's "`ready` with `grade: null` —
  show the grade picker" is satisfied only through Apprendre.
- `tour_version_seen` and `onboarding_version` have a maximum of 10000 on the server; the client
  accepts any non-negative integer on read (L7).
- Response fields `completed_at`, `updated_at` are ignored (harmless). `PATCH` returns the profile;
  the client discards it (it could prefill the grade, M4).
- Request bodies match: `onboarding_version` always sent and at least 1, no unknown field.

Vocab (`lanes/vocab.md`):
- Revalidation: contract "once per app start / return to foreground"; client "every 6 hours, on
  mount only" (H1, M2).
- `404 not_found`: contract "hide the card, keep the cache"; client keeps showing the card (M2).
- "Store the last 200 body verbatim": client stores a normalised subset; `word.revision`,
  `audio.asset_id`, `audio.sha256` are dropped.
- Field limits: client far looser than the server (L7).
- Field names, nesting, `is_fallback_locale`, the ten part-of-speech codes, `daily_word_not_available`,
  the ETag header and the 304 path all match.

Rewards (`lanes/rewards.md`, provisional):
- `streak.current_days` / `longest_days`: read correctly. `last_active_day`, `active_today`,
  `today`, `lifetime_earned`, `recent` are ignored (M5 for the first three).
- `achievements`: the client keeps a count of entries that have a `code`; titles are not shown.
- Ledger `adjustment` kind: the client never calls `/v1/rewards/ledger` and ignores `recent`, so
  the new kind has no effect on it. A negative balance is refused by the client and impossible on
  the server per the lane document; if the owners later allow it, `remote.ts:202` must change.
- `404 not_found` (flag off), 401, 503: handled as documented.

## Not examined

- Nothing was executed: no Jest, type-check, bundle, emulator, screen reader or device. Layout at
  320 dp and 200 % text is judged from source only.
- The test files were read for what they cover (names, structure, the boundary cases cited), not
  line by line; `tests/support/experienceHarness.tsx` and `legacySchema.ts` were not audited.
- Existing Mobile-02 code was read only where the new code depends on it (migration driver, account
  store open, session token refresh, HTTP helper, app context, Apprendre's grade handling, Pill /
  Chip / StepStrip). The device SQLite adapter (`platform/expoSqlite.ts`) was not read: the claim
  that a `PRAGMA user_version` inside its transaction is atomic on the phone rests on SQLite's
  documented behaviour and on Mobile-02's own tests.
- The backend lanes' code was not read, only their lane documents.
- The Creole strings were scanned for obvious problems only; a native speaker must review them.
- The lane document's Creole list (section 10) was not compared entry by entry with `strings.ts`.

