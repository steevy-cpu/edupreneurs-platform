# Lane NATIVE — onboarding, tour, Word of the Day, Gold, leaderboard review screen

Branch `overnight/native-experience`, based on `mobile-02` (54fec1c). Nothing here was run on an
emulator, a simulator or a phone: every statement about behaviour comes from Jest (real SQLite files,
real screen components rendered with stand-ins for `react-native` and `expo-router`). **Layout,
colours, touch targets and large-text behaviour are unverified.**

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
6. **Today's cached word is revalidated at most every 6 hours** (ETag, 304 without body). The vocab
   lane serves `Cache-Control: private, no-cache` because a word can be withdrawn during the day;
   strict HTTP semantics would revalidate on every display. 6 h is a data-cost compromise — to be
   arbitrated with the vocab lane. A withdrawn word is deleted from the cache.
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

- **Word of the Day** is called "Mot du jour" only while `fetchedAt <= now < valid_until` (the
  server's Haiti-midnight instant). Otherwise "Dernier mot téléchargé · <date>". The phone never
  computes the Haitian date. Known limit: a phone clock set *behind* real time keeps a word "today's"
  for longer; any successful request corrects it.
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

102 catalogue strings in `src/core/i18n/strings.ts`, listed below. Also outside the catalogue:
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
