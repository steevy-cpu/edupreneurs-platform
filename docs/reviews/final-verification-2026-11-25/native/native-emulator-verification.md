# Native onboarding fixes: Android emulator verification (2026-11-25)

**This was run on an Android emulator, not a physical device.** The AVD is `edu_api24`: Android 7.0 (API 24), arm64,
480×800 px at 240 dpi (320×533 dp), run headless.
Code under test: branch `review/fix-native-harness-and-onboarding` at `202c12f`, which contains `4189f4e` (onboarding layout and
connectivity notice) and `202c12f` (Profil "Serveur injoignable"). The JS came from Metro started in this worktree
(`EXPO_PUBLIC_FF_ONBOARDING=1 EXPO_PUBLIC_FF_TOUR=1`, other flags off). The native shell was the debug APK
`/Volumes/EdupreneursDev/artifacts/edupreneurs-debug-arm64.apk`. The local API ran on 127.0.0.1:8095 and Auth on this worktree's
own stack (57821). The account was seeded `student_a`, with app data cleared before onboarding.

Original defects (from `docs/overnight-2026-11-24/screenshots/native/`):
- `fr-03-grade-top.png`: no class chip visible without scrolling. The hyphenated title "En quelle classe es-/tu ?" broke
  across lines. "Pas encore de connexion" showed while the API was up. Two buttons were pinned.
- `fr-01-welcome.png`: only 1 of the 3 points was visible, and two pinned buttons covered the content.

## Verdicts

| # | Check | Screenshot(s) | Locale | Font scale | Expected | Seen | Verdict |
|---|---|---|---|---|---|---|---|
| 1a | Class step on open | `screenshots/fr-1.0-03-grade-top.png` | fr | 1.0 | ≥3–4 chips visible, only "Continuer" pinned, title "Quelle est ta classe ?" unbroken | Title on one line; 5 chips fully visible (7AF to NS2); only "Continuer" pinned | PASS |
| 1b | Class step end of scroll | `screenshots/fr-1.0-04-grade-bottom.png` | fr | 1.0 | status notice under list, then "Je choisirai plus tard" in the scroll | NS4, then the notice, the explanation and "Je choisirai plus tard" (scrolls), with "Continuer" pinned | PASS |
| 1c | Class step on open | `screenshots/ht-1.0-03-grade-top.png` | ht | 1.0 | as 1a | "Nan ki klas ou ye?"; 5 chips visible; only "Kontinye" pinned | PASS |
| 1d | Class step end | `screenshots/ht-1.0-04-grade-bottom.png` | ht | 1.0 | as 1b | notice "Kou yo poko telechaje…", explanation, "M ap chwazi pita" in scroll | PASS |
| 1e | Class step on open | `screenshots/fr-1.3-03-grade-top.png` | fr | 1.3 | ≥3–4 chips visible | title on one line; 4 chips fully visible (labels wrap to 2 lines) + part of a 5th; only "Continuer" pinned | PASS |
| 1f | Class step end | `screenshots/fr-1.3-04-grade-bottom.png` | fr | 1.3 | as 1b | notice, explanation, "Je choisirai plus tard" in scroll; "Continuer" pinned | PASS |
| 1g | Class step on open / end | `screenshots/ht-1.3-03-grade-top.png`, `screenshots/ht-1.3-04-grade-bottom.png` | ht | 1.3 | as 1a/1b | 5 chips visible (1 line each); notice + "M ap chwazi pita" in scroll; "Kontinye" pinned | PASS |
| 1h | Class step on open | `screenshots/fr-2.0-03-grade-top.png` | fr | 2.0 | chips reachable, title unbroken | Title wraps at a word boundary ("Quelle est ta / classe ?"); 2 full chips + part of a 3rd; at 2.0 nothing is pinned (by design: `roomy=false`). **The 2-line chip labels touch and overlap the rounded border of the chip (see D1)** | PASS (with defect D1) |
| 1i | Class step end | `screenshots/fr-2.0-04-grade-bottom.png` | fr | 2.0 | actions reachable | "Continuer" then "Je choisirai plus tard" at the end of the scroll | PASS |
| 1j | Class step on open / end | `screenshots/ht-2.0-03b-grade-top.png`, `screenshots/ht-2.0-04-grade-bottom.png` | ht | 2.0 | as 1h/1i | as 1h; same chip-border overlap (D1) | PASS (with defect D1) |
| 1k | Step change at large text | `screenshots/ht-2.0-03a-grade-on-open-after-scrolled-language-step.png` | ht | 2.0 | new step opens at its top | after scrolling the language step to reach "Kontinye", the class step opened still scrolled: step label and most of the title hidden (D2) | FAIL (new, D2) |
| 2a | Welcome on open / scrolled | `screenshots/fr-1.0-01-welcome-top.png`, `screenshots/fr-1.0-02-welcome-scrolled.png` | fr | 1.0 | 3 points visible, nothing hidden behind footer, only "Commencer" pinned | all 3 points fully visible on open; body text and "Passer l’introduction" in the scroll; only "Commencer" pinned | PASS |
| 2b | Welcome | `screenshots/ht-1.0-01-welcome-top.png`, `screenshots/ht-1.0-02-welcome-scrolled.png` | ht | 1.0 | as 2a | 3 points visible on open; "Sote entwodiksyon an" in scroll; only "Kòmanse" pinned | PASS |
| 2c | Welcome | `screenshots/fr-1.3-01-welcome-top.png`, `screenshots/fr-1.3-02-welcome-scrolled.png` | fr | 1.3 | 3 points visible or clearly scrollable | 2 points visible, the 2nd card cut by the footer edge, which shows there is more below; 3rd point, body and "Passer l’introduction" after scrolling; only "Commencer" pinned | PASS |
| 2d | Welcome | `screenshots/ht-1.3-01-welcome-top.png`, `screenshots/ht-1.3-02-welcome-scrolled.png` | ht | 1.3 | as 2c | same as 2c | PASS |
| 2e | Welcome | `screenshots/fr-2.0-01-welcome-top.png`, `screenshots/fr-2.0-02-welcome-bottom.png` | fr | 2.0 | content reachable | 1 point + top of the 2nd on open; everything (incl. both buttons) scrolls; nothing pinned | PASS |
| 2f | Welcome | `screenshots/ht-2.0-01-welcome-top.png`, `screenshots/ht-2.0-01b-welcome-mid.png`, `screenshots/ht-2.0-02-welcome-bottom.png` | ht | 2.0 | as 2e | as 2e; all 3 points seen while scrolling | PASS |
| 3a | API up, no catalogue cached | `screenshots/fr-1.0-04-grade-bottom.png`, `screenshots/ht-1.0-04-grade-bottom.png` | fr, ht | 1.0 | "not yet downloaded" notice, no "Hors ligne" pill | "Les cours ne sont pas encore téléchargés. Voici la liste habituelle des classes." / "Kou yo poko telechaje…"; no pill (API log: `GET /v1/sync/pull` 200) | PASS |
| 3b | API stopped, sync attempted (app background → foreground) | `screenshots/fr-1.0-05-grade-api-down.png` | fr | 1.0 | offline notice + pill | "Pas de connexion pour le moment. Voici la liste habituelle des classes." and a "Hors ligne" pill in the header | PASS |
| 3c | API restarted, sync again | `screenshots/fr-1.0-06-grade-api-back.png` | fr | 1.0 | back to "not downloaded", no pill | notice back to "pas encore téléchargés", pill gone | PASS |
| 3d | Profil / Accueil, API up | `screenshots/fr-1.0-10-accueil-api-up.png`, `screenshots/fr-1.0-11-profil-api-up.png`, `screenshots/fr-1.0-12-profil-api-up-scrolled.png` | fr | 1.0 | no pill, no "Serveur injoignable" | none shown; "Tout est synchronisé", last sync 08:55:14 | PASS |
| 3e | Profil / Accueil, API stopped, "Synchroniser maintenant" | `screenshots/fr-1.0-13-profil-api-down.png`, `screenshots/fr-1.0-14-accueil-api-down.png` | fr | 1.0 | "Serveur injoignable" + pill | Profil: "Serveur injoignable. Ton travail reste enregistré ; réessaie plus tard." + "Hors ligne" pill; Accueil: "Hors ligne" pill | PASS |
| 3f | API up but answering 503 (API started with an unreachable DB port; `/v1/sync/pull` → 503 JSON `dependency unavailable`) | `screenshots/fr-1.0-15-profil-api-5xx.png`, `screenshots/fr-1.0-16-accueil-api-5xx.png` | fr | 1.0 | no "Hors ligne", no "Serveur injoignable" (server answered) | neither shown on Profil or Accueil (API log: 5 × 503 on `/v1/sync/pull`) | PASS |
| 4 | Header pill regression on Accueil / Profil | 3d–3f screenshots | fr | 1.0 | pill only when unreachable | matches; no regression seen | PASS |

## Defects

- **D1 (LOW, new at large text, not caused by these commits as far as seen)**: at font scale 1.3 and especially 2.0, the class chips'
  two-line labels are left-aligned at the chip's inner edge. The strongly rounded (pill) border then runs through the first
  and last characters ("7AF", "fondamantal/fondamentale", "NS1"). Seen in `fr-2.0-03-grade-top.png`, `ht-2.0-03b-grade-top.png`,
  and slightly in `fr-1.3-03-grade-top.png`. Smallest fix: a smaller corner radius or more horizontal padding on `Chip` when the label
  wraps (or when `textScale` ≥ 1.3).
- **D2 (LOW/MEDIUM, large text)**: at font scale 2.0 nothing is pinned, so the learner has to scroll down to "Kontinye/Continuer".
  The next onboarding step then opens with the same scroll offset: the step label "3/5" and the title are off screen
  (`ht-2.0-03a-grade-on-open-after-scrolled-language-step.png`). Smallest fix: reset the onboarding ScrollView to the top
  (`scrollTo({y:0})`, or a `key={record.step}`) whenever the step changes.
- **NOTE N1**: in Profil while the server is unreachable, the card shows "Tout est synchronisé" with a green check next to
  "Serveur injoignable" (`fr-1.0-13-profil-api-down.png`). Both are literally true (nothing is pending), but they read as
  contradictory. On a 503 the learner gets no feedback at all after tapping "Synchroniser maintenant". This is acceptable
  under the commit's intent and is noted only.
- **NOTE N2 (dev build only)**: changing the system font scale recreates the activity, and the debug build then shows a LogBox
  *error* toast "Looks like you have configured linking in multiple places…". It was dismissed before the screenshots and
  does not appear in release builds, but it suggests a duplicated linking configuration worth a look.
- **NOTE N3 (wording, needs a native speaker)**: the Haitian Creole status lines end in "Men lis klas yo abitye." That
  reads oddly ("here are the classes' list [they are] used to"). A native speaker should confirm or rephrase it, for example
  "Men lis klas yo jan l ye abityèlman."
- **NOTE N4 (outside the scope of these commits)**: the onboarding chose class 7AF, yet afterwards Accueil and Profil still say "Choisis
  d’abord ta classe et ta matière" (only a subject is missing). This could confuse learners. Not investigated.

## Not verified

- The `loading` notice ("Chargement des cours…") was not captured: it is transient and the sync finished before a capture.
- The Haitian Creole offline notice ("Pa gen koneksyon pou kounye a…") was not captured on device. Only the French offline notice was.
- Profil and Accueil at font scale 1.3 and 2.0, and in Haitian Creole.
- The case where the class list comes from a downloaded catalogue (`none` notice): this stack has no catalogue the app downloaded during onboarding.
- No physical device was used.

## Environment incident (reported to the audit lead)

The AVD already had a different build of `ht.edupreneur.student.dev` installed (installed 2026-11-24 18:35; 32 MB; it has an
**embedded** `index.android.bundle` and so ignores Metro). Its baked-in Auth URL was `10.0.2.2:54321`, the owner's
**shared stack**. The first launch ran that build. One login attempt (student_a's e-mail and a random password valid only on
this worktree's stack) went to port 54321 and was rejected ("E-mail ou mot de passe incorrect"). It was detected
with `adb shell netstat` (an ESTABLISHED connection to 10.0.2.2:54321). The app was force-stopped at once. That build was
then replaced (`adb install -r`) by the debug artifact APK, which loads JS from Metro, so every later request went only to
8081/8095/57821, as `netstat` confirmed. Metro was moved to port 8081 because the debug app on a stock emulator asks
10.0.2.2:8081. No data was written to the shared stack beyond that one failed sign-in request. Its containers were not touched
and their logs were not read. The AVD now has the debug APK installed instead of the embedded-bundle build.

## Shutdown

Font scale reset to 1.0. `adb emu kill`, then Metro (`expo start --port 8081`) and the API stopped by PID. `adb devices` shows an empty list.
`ps` shows no qemu/emulator/expo/uvicorn process, and ports 8081 and 8095 are free. No adb server was running before this session, so it
was stopped with `adb kill-server`. The git-ignored `apps/student-native/.env.local` in this worktree points at API port 8095.
