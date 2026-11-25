# Lane NATIVE — onboarding + tour, Word of the Day card, Gold, leaderboard review screen (F15 + client side of F13/F8/F14)

Worktree `/Volumes/EdupreneursDev/worktrees/overnight/native` · branch `overnight/native-experience`,
**based on `mobile-02`** (54fec1c) because the approved Design-00 interface lives there. You never
edit, check out or push `mobile-02`; your branch becomes a draft PR stacked on it.
Stack API 56821 / DB 56822 (for `npx jest`; you are the only lane allowed to run the mobile Jest
suite — its harness uses a fixed API port).

Owned paths: everything under `apps/student-native/src/**` and `apps/student-native/tests/**` that
you add; additive edits to existing screens (`src/app/home.tsx`, `profile.tsx`, `_layout.tsx`,
`index.tsx`), i18n dictionaries and the local database migrations, kept as small as possible;
`docs/overnight-2026-11-24/lanes/native.md`. Do not touch backend code, `packages/contracts`, the
generated `src/core/api/schema.d.ts`, or add any dependency (no new packages, no WebView, no
animation or audio library). Read first: `apps/student-native/AGENTS.md`,
`docs/MOBILE_02_REPORT.md`, `docs/MOBILE_02_PLAN.md`, `docs/design/EDUPRENEURS_UX_DIRECTION_v0.1.md`,
`apps/student-native/src/design/**`, `src/core/db/**`, `src/ui/**`, and the existing component tests.

## Non-negotiables
- Four tabs only (Accueil · Apprendre · Réviser · Profil). No fifth tab.
- Design-00 tokens and components only; layouts must hold at 320 dp width and with large fonts;
  accessible labels/roles; low-data rules (no remote images, no autoplay).
- Offline first: every new screen opens with no network. Nothing new may block opening a saved
  lesson or saving practice. The durable per-account SQLite/outbox design is not modified; new
  local tables are **additive**, per account, and an upgrade from the existing local schema keeps
  every saved row (test the upgrade path and account-switch isolation).
- French and Haitian Creole for every string. Creole wording is a **draft** — list every new HT
  string in your lane doc for native-speaker review.
- No invented product values in the production app: no fictional Gold amounts, ranks or names.
  Network features are behind client flags that default **off** until their backend lands.
- No consent, age or legal question is asked or implied anywhere.

## Slice 1 — first-run onboarding (highest priority)
Resumable flow: welcome → language (FR/HT) → grade (7AF…NS4; from the catalogue/grades the app
already knows, with an offline fallback list) → "how downloads and offline work" explainer
(downloaded lessons, offline status, practice saved on the phone, sync later) → ready.
State is stored locally per account with a version; killing the app mid-flow resumes at the same
step; a returning user after an app upgrade is not forced through again; switching accounts shows
each account its own state; skipping is allowed where safe. Server sync of the state and of
grade/locale goes through a thin adapter for the contract in
`/Volumes/EdupreneursDev/worktrees/overnight/integration/docs/overnight-2026-11-24/briefs/identity.md`
(`PATCH /v1/me`, `GET/PUT /v1/me/onboarding`; forward-only state) and stays flag-off until that
backend is integrated. Onboarding never deletes or resets locally saved learning work.

## Slice 2 — optional product tour
Short (3–5 steps), dismissible at any step, replayable from Profil, stored as account-scoped
version/dismissed flags, never shown over a lesson being read, works offline.

## Slice 3 — Word of the Day card on Accueil
Lightweight card: term, pronunciation text, definition, example, optional gloss; optional audio
affordance only if audio metadata exists (no autoplay; playback itself may be left as a documented
follow-up since no audio dependency may be added). Read-through local cache: no network needed to
re-read the cached word; when today's word could not be fetched, show the cached one with an
explicit "last downloaded word · <date>" label — never present yesterday's word as today's. Contract:
`briefs/vocab.md` (`GET /v1/daily-word`, `haiti_date`, `valid_until`, `is_fallback_locale`, ETag).

## Slice 4 — Gold and private progress, leaderboard review screen
Profil/Accueil: Gold balance and streak from the server summary (contract in `briefs/rewards.md`),
with unsynced offline work shown as **pending**, never as confirmed Gold. A trophy/podium + ranked
list **review screen behind a flag that defaults off**, fed only by clearly synthetic fixture data
in tests/previews (pseudonyms, no real names), reachable without adding a tab. State plainly in the
lane doc that this screen is not wired to real learners.

## Tests and evidence
Unit + component tests in the existing Jest style (real SQLite through the same interface,
react-test-renderer screens): resume after kill, upgrade path keeps saved work, account switch,
skip/replay of the tour, FR/HT rendering of every new screen, cached-word labelling across the
`valid_until` boundary, pending vs confirmed Gold, flags off = existing screens unchanged.
Gate: `(cd apps/student-native && npx tsc --noEmit && npx tsc --noEmit -p tests && npx jest)` plus
the existing mobile checks; report real counts (baseline on this branch first, then yours).
Do not start an emulator, simulator or native build — the director schedules those one at a time.
