# Lane NATIVE — onboarding, tour, Word of the Day, Gold, leaderboard review screen

Branch `overnight/native-experience`, based on `mobile-02` (54fec1c). Nothing here was run on an
emulator, a simulator or a phone: every statement about behaviour comes from Jest (real SQLite files,
real screen components rendered with stand-ins for `react-native` and `expo-router`). **Layout,
colours, touch targets and large-text behaviour are unverified.**
(Later addition: section 12 records one emulator pass at 320 dp; everything else above still holds.)

## 1. What exists

| Slice | Commit | Route / place | Client flag (build-time, default **off**) |
|---|---|---|---|
| 1 First-run onboarding | b3d11c8 | `/onboarding`; Accueil redirects to it | `EXPO_PUBLIC_FF_ONBOARDING` |
| 1 Server sync of onboarding + grade/locale | b3d11c8 | background only | `EXPO_PUBLIC_FF_ONBOARDING_SYNC` (network) |
| 2 Product tour | 1e0d71d | `/tour`; card on Accueil, row in Profil | `EXPO_PUBLIC_FF_TOUR` |
| 3 Word of the Day | 9390202 | card on Accueil | `EXPO_PUBLIC_FF_DAILY_WORD` (network) |
| 4 Gold, streak | aa176bb | card in Profil, row on Accueil | `EXPO_PUBLIC_FF_REWARDS` (network) |
| 4 Leaderboard review screen | aa176bb | `/leaderboard` from Profil; `/design/leaderboard` preview | `EXPO_PUBLIC_FF_LEADERBOARD_REVIEW` |
| Contract alignment | e3aec2b | adapters | — |

A flag is on only for the value `1` or `true`. With none set the app is Mobile-02: the 157 baseline
tests pass unedited, no new screen is reachable, no new request is made. The additive local schema is
applied regardless of flags.

## 2. Decisions taken without the owner (reversible)

1. **Local onboarding and the tour are also behind flags, default off.** The brief only required this
   for network features. Reason: the existing component tests and the Maestro journey assume
   sign-in → Accueil, and existing tests may not be edited. Switching the default is a one-line
   change in `src/core/experience/flags.ts` plus an update of the e2e flows.
2. **The onboarding gate sits on Accueil only.** Lesson, exercises, Apprendre, Réviser and Profil are
   never gated, so a saved lesson opened directly is never blocked. The introduction can be skipped
   in one tap from its first step.
3. **Returning learners are never sent through onboarding.** Three ways to be "returning": the account
   database existed before this schema (upgrade); the account already has a grade preference on this
   phone; or (sync flag on) the server says `ready`.
4. **A learner who declines the tour is not offered later tour versions on Accueil** (Profil keeps
   "Revoir la visite guidée"). A learner who finished version 1 would be offered version 2.
5. **Word and Gold caches are per account**, as the brief asked. Cost on a shared phone: a second
   student offline does not see a word the first one downloaded.
6. **Today's cached word is revalidated once per app start and per return to the foreground**, at
   least 5 minutes apart (ETag, 304 without body) — the rule agreed with the vocab lane after review;
   it replaced an earlier 6-hour interval. A withdrawn word is deleted from the cache; when the
   feature is off on the server the card is hidden and the cache kept.
7. **A negative Gold balance is refused** (nothing is shown) although the rewards lane allows staff
   adjustments of either sign.
8. **Audio**: when metadata exists the card shows the text "Audio : bientôt disponible". Nothing is
   downloaded or played; no audio dependency was added. Playback is a follow-up.

## 3. Local schema (per-account database `account-<user id>`)

| Version | Added | Notes |
|---|---|---|
| 2 | `onboarding_state` (single row), `tour_state` (single row) | plus one `INSERT … WHERE EXISTS (account_id)` marking a pre-existing account as `returning` |
| 3 | `daily_word_cache` (one row per interface language) | |
| 4 | `rewards_summary_cache` (single row) | display copy of the server summary |

Additive only: no statement alters, drops or deletes from a version-1 table. Defined in
`src/core/experience/schema.ts`, appended to the existing migration list in `accountStore.ts`
(the only change to that file besides a read-only `experience` accessor).

Upgrade path test (`tests/experience/local_schema.test.ts`): a version-1 file is built from a frozen
copy of the Mobile-02 schema (`tests/support/legacySchema.ts`) with synced, pending and refused
answers, completions, outbox rows and preferences; after opening it with today's code every row of
the five old tables is identical, the app's own queries return the same work, the learner is
`returning`, reopening changes nothing, and an upgrade interrupted half-way (simulated storage
failure) leaves version 1 intact and succeeds at the next start. Account-switch isolation is tested
at store level and on rendered screens for each slice.

## 4. API shapes assumed (`src/core/experience/remote.ts`)

`schema.d.ts` was not regenerated or edited (those routes are not on this branch). Each response is
validated before it is stored and again when read back. Checked against the lanes' in-progress
models on 2026-11-24 around 23:10; they may still move.

- `GET /v1/me/onboarding` → `{state: new|profile_selected|downloads_informed|ready,
  onboarding_version, tour_version_seen, tour_dismissed}` (other fields ignored).
- `PUT /v1/me/onboarding` ← `{state?, onboarding_version (>=1), tour_version_seen?, tour_dismissed?}`,
  nothing else (the endpoint is strict). Forward-only on both sides.
- `PATCH /v1/me` ← `{grade_code?, preferred_locale?}` only; response ignored.
- `GET /v1/daily-word?locale=` → `{haiti_date, locale, requested_locale, is_fallback_locale,
  valid_until, word:{word_id, revision_id, term, pronunciation, part_of_speech (code), definition,
  example, gloss}, audio: null|{mime_type, byte_size, duration_ms}}`, `ETag`, 304 on
  `If-None-Match`, 404 `daily_word_not_available`. Flat word fields are also accepted.
- `GET /v1/rewards/summary` → `{balance, streak:{current_days, longest_days}, achievements:[{code}],
  up_to_date, rules_status}`; `streak.current/longest` and flat `current_streak/longest_streak`
  also accepted. `recent`, `lifetime_earned`, achievement titles are not used.

Not sent anywhere: a user id, a Gold amount, a device clock.

## 5. Honesty rules implemented

- **Word of the Day** is called "Mot du jour" only while `0 <= now - fetchedAt < lifetime`, where the
  lifetime is `valid_until` minus the response `Date` header (server clock), capped at 25 h, and the
  label is decided at every render. Otherwise "Dernier mot téléchargé · <date>". Only elapsed phone
  time is used, so a wrong phone date (behind, ahead, reset) does not mislabel the word. Remaining
  limit: if the `Date` header is unreadable the lifetime falls back to the phone clock at download.
- **Streak**: "Série en cours" only while the server copy is under a day old; an older copy says
  "Série au <date>" or nothing.
- **Gold**: the confirmed number is the server's balance, with the time received. Unsynced work is
  "En attente", counted in actions, never given a Gold value, never added. No summary → no number.
  The server's `rules_status: provisional` and `up_to_date: false` are shown as text.
- **Leaderboard: this screen is not wired to real learners.** There is no ranking request, query or
  name in any production path; `/leaderboard` passes an empty list and shows "Pas encore de
  classement". The podium and list are drawn only from `src/design/preview/leaderboardFixture.ts`
  (eight `…-TEST` pseudonyms, round Gold values), in tests and in the design preview. A production
  Android export (`expo export`, flags unset) was checked: 0 occurrences of the fixture names and of
  the preview identifiers.
- No consent, age or legal question is asked. The grade step asks the school class only.

## 6. Tests

Command (the mobile Jest harness needs the shim, see §8):
`/Volumes/EdupreneursDev/logs/overnight-2026-11-24/tmp/native/native-gate.sh`
= `npx tsc --noEmit && npx tsc --noEmit -p tests && npx jest` in `apps/student-native`.

| | Suites | Tests |
|---|---|---|
| Baseline on 54fec1c | 10 | 157 passed |
| After e3aec2b | 22 | 319 passed, 0 failed |
| After the review fixes (section 11) | 22 | 337 passed, 0 failed |

Also run: `npm run check:api` (generated types fresh: pass). Bundle, flags unset, Android `.hbc`:
2,885,744 bytes (Mobile-02 report: 2,778,788), gzip 1,245,855.

Not run: Maestro flows, any emulator/simulator/device, iOS export, screen readers.

## 7. What needs eyes on an emulator (in order)

1. `/onboarding` grade step at 320 dp and at 200 % text: seven full-width chips with long labels, two
   pinned buttons.
2. `/onboarding` offline explainer: four rows with two-line subtitles.
3. Leaderboard podium (`monedupreneur://design/leaderboard?width=320`, also `state=podium`, and at
   large text where it stacks).
4. Accueil with every flag on: order and length (Continue card, pending row, Gold row, word card,
   review, downloads, tour card).
5. Word card with a long definition/example and the two-pill header at large text.
6. Profil with Gold card, tour row and leaderboard row.
7. `/tour` step pages.

## 8. Test-harness hazard and the shim

`tests/support/device.ts` `resetServerLearningState()` hard-codes
`docker exec supabase_db_mon-edupreneur … TRUNCATE` (the shared stack's container). Run from a lane
worktree it truncates the shared stack's learning tables instead of the lane's — this happened once
during the baseline run (incident I-01). Environment-only workaround used since:
`/Volumes/EdupreneursDev/logs/overnight-2026-11-24/tmp/native/bin/docker`, a wrapper that rewrites
that one container name to `supabase_db_edu-on-native` and passes everything else to the real docker.
**Recommended permanent fix** (not done: it edits existing test support): derive the container name
from `project_id` in `supabase/config.toml`.

## 9. Known gaps

- Grade or language changed later in Apprendre/Profil is not pushed to the server (only choices made
  in onboarding are). The server profile is not pulled to prefill a new phone.
- An account created while the onboarding flag was off, that never chose a grade, will see the flow
  once when the flag is turned on.
- The onboarding sync runs from Accueil and the onboarding screen only, not from the sync engine.
- Maestro flows are not updated for flags-on builds.
- Achievement titles, the ledger list and "recent" entries are not displayed.
- `BLOCKED_BY_OWNER`: PO-09 (reward amounts — the app only relays the server's numbers and its
  "provisional" marker), leaderboard visibility/pseudonyms/consent, PO-04, Creole wording.

## 10. Haitian Creole strings for native-speaker review (all DRAFT)

103 catalogue strings in `src/core/i18n/strings.ts`, listed below. Also outside the catalogue:
grade labels in `src/core/experience/grades.ts` (`7èm/8èm/9èm ane fondamantal`, `Nouvo Segondè 1–4`)
and month names in `src/core/experience/dailyWord.ts` (`janvye, fevriye, mas, avril, me, jen, jiyè,
out, septanm, oktòb, novanm, desanm`).

### Slice 1 — onboarding (37)

| Key | Français | Kreyòl (draft) |
|---|---|---|
| `onbStepWelcome` | Bienvenue | Byenveni |
| `onbStepLanguage` | Langue | Lang |
| `onbStepGrade` | Classe | Klas |
| `onbStepOffline` | Hors ligne | San entènèt |
| `onbStepReady` | Prêt | Pare |
| `onbWelcomeTitle` | Bienvenue sur Edupreneurs | Byenveni sou Edupreneurs |
| `onbWelcomeBody` | Lis tes leçons et fais tes exercices sur ce téléphone, même sans internet. | Li leson ou yo epi fè egzèsis ou yo sou telefòn sa a, menm san entènèt. |
| `onbWelcomePoint1` | Des leçons courtes, classe par classe | Leson kout, klas pa klas |
| `onbWelcomePoint2` | Des exercices avec la correction expliquée | Egzèsis ak eksplikasyon koreksyon an |
| `onbWelcomePoint3` | Ton travail reste enregistré sur ce téléphone | Travay ou rete anrejistre sou telefòn sa a |
| `onbStart` | Commencer | Kòmanse |
| `onbSkipAll` | Passer l’introduction | Sote entwodiksyon an |
| `onbContinue` | Continuer | Kontinye |
| `onbLanguageTitle` | Choisis ta langue | Chwazi lang ou |
| `onbLanguageBody` | Tu pourras la changer à tout moment dans Profil. | Ou ka chanje l nenpòt lè nan Pwofil. |
| `onbGradeTitle` | En quelle classe es-tu ? | Nan ki klas ou ye? |
| `onbGradeBody` | L’application te montre d’abord les leçons de ta classe. Tu pourras changer dans Apprendre. | Aplikasyon an ap montre ou leson klas ou anvan. Ou ka chanje sa nan Aprann. |
| `onbGradeOfflineList` | Pas encore de connexion : voici la liste des classes. Les cours se chargeront plus tard. | Poko gen koneksyon: men lis klas yo. Kou yo ap chaje pita. |
| `onbGradeLater` | Je choisirai plus tard | M ap chwazi pita |
| `onbOfflineTitle` | Comment ça marche sans internet | Kijan sa mache san entènèt |
| `onbOffline1Title` | Télécharge tes leçons | Telechaje leson ou yo |
| `onbOffline1Body` | Avec une connexion, appuie sur « Télécharger ». La leçon reste sur ce téléphone. | Lè ou gen koneksyon, peze « Telechaje ». Leson an rete sou telefòn sa a. |
| `onbOffline2Title` | Étudie sans internet | Etidye san entènèt |
| `onbOffline2Body` | Une leçon téléchargée s’ouvre partout. « Hors ligne » s’affiche quand le serveur est injoignable. | Yon leson ki telechaje ouvri nenpòt kote. « San entènèt » parèt lè nou pa ka jwenn sèvè a. |
| `onbOffline3Title` | Tes réponses sont enregistrées ici | Repons ou yo anrejistre isit la |
| `onbOffline3Body` | Chaque réponse est gardée sur ce téléphone dès que tu la valides. | Chak repons rete sou telefòn sa a depi ou valide l. |
| `onbOffline4Title` | Synchronisation plus tard | Senkronizasyon pita |
| `onbOffline4Body` | Quand la connexion revient, ton travail est envoyé. En attendant, rien n’est perdu. | Lè koneksyon an retounen, travay ou ap voye. Pandan tan sa a, anyen pa pèdi. |
| `onbUnderstood` | J’ai compris | Mwen konprann |
| `onbReadyTitle` | Tout est prêt | Tout bagay pare |
| `onbReadyBody` | Télécharge ta première leçon pendant que tu as une connexion. | Telechaje premye leson ou pandan ou gen koneksyon. |
| `onbReadyLanguage` | Langue : {language} | Lang: {language} |
| `onbReadyGrade` | Classe : {grade} | Klas: {grade} |
| `onbReadyNoGrade` | Classe : à choisir dans Apprendre | Klas: pou chwazi nan Aprann |
| `onbReadyChoose` | Choisir ma première leçon | Chwazi premye leson mwen |
| `onbReadyHome` | Aller à l’accueil | Ale nan akèy |
| `onbSaveFailed` | Ce choix n’a pas pu être enregistré. Réessaie. | Chwa sa a pa t ka anrejistre. Eseye ankò. |

### Slice 2 — tour (20)

| Key | Français | Kreyòl (draft) |
|---|---|---|
| `tourTitle` | Visite guidée | Vizit gide |
| `tourInviteTitle` | Découvre l’application | Dekouvri aplikasyon an |
| `tourInviteBody` | Une visite en {count} étapes. Elle fonctionne sans internet. | Yon vizit an {count} etap. Li mache san entènèt. |
| `tourInviteStart` | Commencer la visite | Kòmanse vizit la |
| `tourInviteResume` | Continuer la visite | Kontinye vizit la |
| `tourInviteDecline` | Non merci | Non mèsi |
| `tourNext` | Suivant | Pwochen |
| `tourFinish` | Terminer la visite | Fini vizit la |
| `tourClose` | Fermer la visite | Fèmen vizit la |
| `tourWhere` | Où : onglet {tab} | Ki kote: onglè {tab} |
| `tourHomeTitle` | Reprends où tu t’es arrêté | Kontinye kote ou te rete a |
| `tourHomeBody` | Accueil te propose la leçon à continuer et te dit si du travail attend d’être envoyé. | Akèy montre ou leson pou kontinye a, epi li di ou si gen travay k ap tann pou voye. |
| `tourLearnTitle` | Choisis et télécharge tes leçons | Chwazi epi telechaje leson ou yo |
| `tourLearnBody` | Dans Apprendre, choisis ta classe et ta matière, puis télécharge une leçon pour l’étudier sans internet. | Nan Aprann, chwazi klas ou ak matyè ou, epi telechaje yon leson pou etidye l san entènèt. |
| `tourReviewTitle` | Refais tes exercices | Refè egzèsis ou yo |
| `tourReviewBody` | Réviser rassemble les exercices de tes leçons enregistrées et les questions à revoir. | Revize rasanble egzèsis leson ou anrejistre yo ak kesyon pou revize yo. |
| `tourProfileTitle` | Ta progression et tes réglages | Pwogrè ou ak reglaj ou yo |
| `tourProfileBody` | Profil montre ta progression, l’état de la synchronisation et la langue. Tu peux revoir cette visite ici. | Pwofil montre pwogrè ou, eta senkronizasyon an ak lang lan. Ou ka revwè vizit sa a la. |
| `tourReplay` | Revoir la visite guidée | Revwè vizit gide a |
| `tourReplayHint` | {count} étapes · sans internet | {count} etap · san entènèt |

### Slice 3 — Word of the Day (10)

| Key | Français | Kreyòl (draft) |
|---|---|---|
| `wordToday` | Mot du jour | Mo jodi a |
| `wordLastDownloaded` | Dernier mot téléchargé · {date} | Dènye mo ki telechaje · {date} |
| `wordStaleOffline` | Le mot d’aujourd’hui se chargera à la prochaine connexion. | Mo jodi a ap chaje lè ou gen koneksyon ankò. |
| `wordNoneToday` | Pas de nouveau mot pour aujourd’hui. | Pa gen nouvo mo pou jodi a. |
| `wordPronunciation` | Prononciation : {text} | Pwononsyasyon: {text} |
| `wordExample` | Exemple | Egzanp |
| `wordGlossHt` | En créole : {gloss} | An kreyòl: {gloss} |
| `wordGlossFr` | En français : {gloss} | An fransè: {gloss} |
| `wordFallbackLocale` | Ce mot n’est pas encore disponible en créole. Il est affiché en français. | Mo sa a poko disponib an kreyòl. Nou montre l an fransè. |
| `wordAudioSoon` | Audio : bientôt disponible | Odyo: l ap disponib talè |

### Slice 4 — Gold and leaderboard review (23)

| Key | Français | Kreyòl (draft) |
|---|---|---|
| `rewardsTitle` | Gold et série | Gold ak seri |
| `rewardsConfirmed` | Gold confirmé | Gold konfime |
| `rewardsConfirmedAt` | Confirmé par le serveur · {when} | Sèvè a konfime l · {when} |
| `rewardsNone` | Ton Gold s’affichera ici après ta prochaine synchronisation. | Gold ou ap parèt la a apre pwochen senkronizasyon ou. |
| `rewardsPendingPill` | En attente | Ap tann |
| `rewardsPending` | {count} action(s) en attente : leur Gold sera calculé par le serveur après la synchronisation. | {count} aksyon ap tann: sèvè a ap kalkile Gold yo apre senkronizasyon an. |
| `rewardsPendingShort` | Le Gold du travail en attente n’est pas encore compté. | Gold travay k ap tann lan poko konte. |
| `rewardsStreak` | Série en cours : {days} jour(s) | Seri k ap kontinye: {days} jou |
| `rewardsStreakBest` | Meilleure série : {days} jour(s) | Pi bon seri: {days} jou |
| `rewardsAchievements` | {count} réussite(s) obtenue(s) | {count} reyisit ou genyen |
| `rewardsHomeRow` | Gold confirmé : {gold} | Gold konfime: {gold} |
| `lbTitle` | Classement | Klasman |
| `lbProfileEntry` | Classement (aperçu) | Klasman (apèsi) |
| `lbProfileEntryHint` | Écran en cours de revue, sans vrais élèves | Ekran k ap revize, san vrè elèv |
| `lbNotAvailableTitle` | Pas encore de classement | Poko gen klasman |
| `lbNotAvailableBody` | Cet écran est un aperçu. Aucun classement réel n’est calculé pour l’instant. | Ekran sa a se yon apèsi. Poko gen okenn klasman reyèl ki kalkile. |
| `lbSyntheticNotice` | Données fictives pour la démonstration. Ce ne sont pas de vrais élèves. | Done sa yo pa reyèl, se pou demonstrasyon. Se pa vrè elèv. |
| `lbPodium` | Podium | Podyòm |
| `lbOthers` | Suite du classement | Rès klasman an |
| `lbEntryLabel` | Rang {rank}. {name}. {gold} Gold | Ran {rank}. {name}. {gold} Gold |
| `lbGold` | {gold} Gold | {gold} Gold |
| `lbYou` | Toi | Ou menm |
| `lbOpenPreview` | Voir l’aperçu avec des données fictives | Gade apèsi a ak done ki pa reyèl |

### Contract alignment — part of speech, Gold caveats (12)

| Key | Français | Kreyòl (draft) |
|---|---|---|
| `wordPosNoun` | nom | non |
| `wordPosVerb` | verbe | vèb |
| `wordPosAdjective` | adjectif | adjektif |
| `wordPosAdverb` | adverbe | advèb |
| `wordPosPronoun` | pronom | pwonon |
| `wordPosPreposition` | préposition | prepozisyon |
| `wordPosConjunction` | conjonction | konjonksyon |
| `wordPosInterjection` | interjection | entèjeksyon |
| `wordPosDeterminer` | déterminant | detèminan |
| `wordPosExpression` | expression | ekspresyon |
| `rewardsProvisional` | Valeurs provisoires | Valè pwovizwa |
| `rewardsCatchingUp` | Le serveur compte encore tes dernières actions. | Sèvè a ap konte dènye aksyon ou yo toujou. |

## 11. Independent review of 779657f — what was fixed and what is open

Report: `/Volumes/EdupreneursDev/logs/overnight-2026-11-24/reviews/native-review-FULL.md`.

| Finding | Status | Commit |
|---|---|---|
| H1 word label frozen at mount | fixed, tested on one mounted instance | 49ffcb3 |
| M1 phone clock behind (and L1 clock ahead) | fixed: lifetime from the server clock, elapsed time only | ac0a2a0 |
| M2 revalidation rhythm; hide on feature-off | fixed (per app start / foreground, 5 min apart) | ac0a2a0 |
| M3 onboarding sync retries | fixed: single flight, 10 min spacing, refused PATCH is final | see `git log` (M3+M4 commit) |
| M4 step jump on a new phone | fixed: step never moved; grade prefilled from `GET /v1/me` | same commit |
| L4 flag cleared for an unsent change | fixed | same commit |
| M5 stale streak | fixed | M5 commit |
| L2 idempotent migration statements | fixed | L2+L3 commit |
| L3 direct open of `/onboarding` | fixed | L2+L3 commit |

**Open (not done):**
- L5 leaderboard review component: screen-reader order in the three-column podium is 2-1-3; raw
  sizes instead of tokens; two-line truncation of pseudonyms. Review screen only, flag off.
- L6 month names, grade labels and language names live outside `strings.ts`; `toLocaleString('fr-HT')`
  for the Gold confirmation time; "(s)" plurals; the Creole wordings the reviewer listed; "Dènye mo
  ki telechaje" versus the vocab lane's "Dènye mo telechaje".
- L7 validators are looser than the contracts (text limits, 8000-byte cap, `duration_ms`,
  `tour_version_seen` upper bound, control characters). `valid_until` far in the future is now
  harmless for the label (25 h cap) but is still stored.
- L8 `rewardsPending` wording suggests waiting work will earn Gold.
- Notes: the cache stores a normalised copy, not the verbatim body; `Retry-After` is not read; one
  client flag covers identity's separate server flags (a refused PATCH is now simply final).
- Missing tests still missing: the real `useRemote` hook; a Mobile-02 snapshot comparison with
  flags off; validator upper bounds.
- The onboarding-sync spacing and the "checked since foreground" marker are in memory (per app
  start), not persisted.
- With the `onboardingSync` flag on, a learner whose server state is `ready` but who has no grade
  anywhere still chooses it in Apprendre.

### Review fix M5 (1)

| Key | Français | Kreyòl (draft) |
|---|---|---|
| `rewardsStreakAsOf` | Série au {date} : {days} jour(s) | Seri jiska {date}: {days} jou |

## 12. Emulator pass (2026-11-25, 04:46–04:50 local)

This supersedes the "nothing was run on an emulator" statement at the top for the screens listed
here only. Large text (200 %), screen readers, real phones and Maestro remain unverified.

**Provenance, stated plainly.** The 14 PNGs in `docs/overnight-2026-11-24/screenshots/native/` were
captured on the Android emulator by the first emulator session of this lane, which was cut off before
it could write anything down. A second session selected them from that session's scratch folder,
opened every one of them, and wrote this section; **it did not boot the emulator again**. What is
known about the run comes from the logs it left (`emulator.log`, `metro.log`, `api.log`, `seed.sql`
in the lane's scratch folder):

- AVD `edu_api24`, Android 7.0 (API 24), 480 x 800 px at 240 dpi = **320 x 533 dp**, default font
  scale. Every screenshot is therefore already the narrow-width case; no `wm size` override was used.
- Metro served the JavaScript from this worktree's `apps/student-native` (1391 modules); the lane's
  API ran on port 8010 against the lane's own backend stack and answered 404 to
  `/v1/me/onboarding`, `/v1/rewards/summary` and `/v1/daily-word` (these routes are not on this branch).
- Signed in as the synthetic account `student_a`.
- Not recorded anywhere: which debug APK was installed and the exact flag values (onboarding, tour,
  word, Gold and leaderboard-review are visibly on).

**Three kinds of screenshot:**
- *real flow* — the signed-in app as it behaves on this branch.
- *seeded cache* — real screens of the signed-in app, but the Word of the Day and Gold values were
  inserted by hand into the on-device cache tables (`daily_word_cache`, `rewards_summary_cache`) with
  the `seed.sql` left in the scratch folder. The word "persévérance / pèseverans", the balance 120,
  the streak 3/7 and "Valeurs provisoires" are invented. No server produced them.
- *design preview* — the `/design/leaderboard` route with the eight `…-TEST` fixture names.

From 04:49 on, the header shows the "Hors ligne / San entènèt" pill (the API had been stopped or was
unreachable by then; the logs do not say which). All four Creole onboarding screenshots are in that
state, so they also show how the pill sits in the onboarding header.

| File | Shows | Locale | Width | Kind |
|---|---|---|---|---|
| `fr-01-welcome.png` | Onboarding 1/5, welcome | fr | 320 dp | real flow |
| `fr-03-grade-top.png` | Onboarding 3/5, grade step as it opens (nothing selected) | fr | 320 dp | real flow |
| `fr-04-offline-scrolled.png` | Onboarding 4/5, offline explainer, scrolled to the end | fr | 320 dp | real flow |
| `fr-05-ready.png` | Onboarding 5/5, ready (9AF chosen) | fr | 320 dp | real flow |
| `fr-07-home-tour-invite.png` | Accueil after onboarding, scrolled to the tour card | fr | 320 dp | real flow |
| `fr-08-tour-1.png` | Tour, step 1/4 | fr | 320 dp | real flow |
| `fr-09-profile-bottom.png` | Profil, bottom: tour row and leaderboard row | fr | 320 dp | real flow |
| `fr-11-leaderboard-preview-top.png` | Leaderboard review screen, podium | fr | 320 dp | design preview |
| `fr-12-home-seeded-word.png` | Accueil with Gold row and Word of the Day card | fr | 320 dp | seeded cache |
| `fr-13-profile-gold.png` | Profil with the Gold card populated | fr | 320 dp | seeded cache |
| `ht-01-welcome.png` | Onboarding 1/5, welcome, offline pill | ht | 320 dp | real flow |
| `ht-02-language.png` | Onboarding 2/5, language (Kreyòl selected) | ht | 320 dp | real flow |
| `ht-03-grade-selected.png` | Onboarding 3/5, grade list scrolled, NS2 selected | ht | 320 dp | real flow |
| `ht-04-offline.png` | Onboarding 4/5, offline explainer, scrolled to the end | ht | 320 dp | real flow |

Also seen in the scratch folder but not committed (to stay under the file limit): French language
step, French grade step with a selection, ready step in Creole, tour step 4/4, Accueil top, Profil
top and middle (Gold empty state "Ton Gold s’affichera ici après ta prochaine synchronisation."),
the production `/leaderboard` empty state ("Pas encore de classement"), the leaderboard list with
the "Toi" row, and the Creole Accueil/Profil with seeded values. They show nothing that contradicts
the list below.

### Defects and doubts visible in the screenshots (reported, not fixed)

1. **Grade step, 320 dp: no class is visible when the step opens** (`fr-03-grade-top.png`). The
   title (two lines), the body (three lines) and the "Pas encore de connexion" notice fill the
   space above the two pinned buttons; the notice's lower edge is cut by the footer and the first
   chip is below the fold. In Creole the first chip is half visible. A learner must guess that the
   list scrolls. "Continuer" is greyed out at that moment, which makes the screen look blocked.
2. **Grade step: the two pinned buttons take about a quarter of the screen height** (roughly 200 of
   800 px). With the back-button row that leaves about 4.5 chips of scrolling area for 7 classes
   (`ht-03-grade-selected.png`).
3. **Grade step shows "Pas encore de connexion : voici la liste des classes" at 04:46 while the API
   was running and had just answered a sync request.** No catalogue request reached the API before
   that screen. Either the step does not fetch the catalogue or it shows the notice before the
   answer arrives. To check; a learner with a connection is told there is none.
4. **French grade title breaks inside the hyphenated verb**: "En quelle classe es-" / "tu ?".
5. **Welcome step: one of the three points is visible** above the pinned buttons in French; in
   Creole the second one is cut through the middle by the footer.
6. **Offline explainer: the progress bar, the title and the first row are scrolled away in the only
   captures there are** (French and Creole). The top of that step ("Comment ça marche sans internet",
   "Télécharge tes leçons") has not been seen. The step needs a scroll to reach its last row at 320 dp.
7. **Header with the offline pill** (`ht-*`): in the tour, the pill pushes the title "Vizit gide"
   off-centre to the left (in French without the pill it is centred). In onboarding the pill sits
   alone on the right of the back button, which reads oddly on screens that explain offline use.
8. **Podium, 320 dp**: "Flamboyant-TEST" wraps onto two lines ("Flamboyant-" / "TEST") while the
   other two names take one line, so the three name/Gold labels sit at three different heights
   above the columns. Longer pseudonyms will wrap worse. The order on screen is 2-1-3 (already
   noted as L5 for screen readers).
9. **Untranslated/French formatting in Creole**: the Gold card reads
   "Sèvè a konfime l · 25/11/2026 à 04:48:51" (French "à"; already L6). The language chip
   "Français" stays in French in the Creole interface (may be intended as the language's own name).
10. **"(s)" plurals are visible**: "Série en cours : 3 jour(s)", "Meilleure série : 7 jour(s)" (L6).
11. **Icons look like placeholders**: the Gold row on Accueil and the "Synchronisation plus tard" row
    use a small dot / small ring in a pale circle; the offline pill uses the same ring. They read as
    missing icons rather than as symbols.
12. **Profil**: "Choisir ma classe et ma matière" wraps onto two lines inside its button, and
    "Dernière synchronisation : 25/11/2026 à 04:46:16" wraps with the time alone on the second line
    (seen in the uncommitted Profil captures). Nothing is clipped.
13. **Accueil greets "Bonjour student.a"** — the part of the e-mail address before the @, not a name.
14. **Profil shows "Mathématiques · 9AF" right after onboarding** although the learner only chose a
    class; the subject was not chosen by the learner in this run. To check whether it is a default.

No clipped or overlapping text, no cut-off button and no raw string key was seen in any of the
captures. Not captured at all: the lower part of the Word of the Day card (example, gloss, audio
line), the stale-word label "Dernier mot téléchargé", the Gold "En attente" state, tour steps 2 and
3, the podium `state=podium` variant, anything at large text, and any width other than 320 dp.
