# 5. Mobile component handoff (for Claude #2)

**A specification only.** Nothing here is implemented on the Mobile-03 branch, and no file under `apps/student-native/src` other than the generated API types was changed by this PR.

## Components

`LessonVideoSection` → `VideoCard` (list) → `VideoPlayerSheet` (one at a time).

### Data

* Fetch `GET /v1/lessons/{id}/videos?locale=` **after** the lesson text has rendered, only when online. 404 → render nothing (feature off). Error or timeout → render nothing; never block the lesson.
* Do not store the response in the lesson's offline pack. A short in-memory cache for the session is fine.

### `VideoCard` (thumbnail-first)

* Thumbnail from `thumbnail_url`, displayed **unaltered** (no filters or edits), at least **120 × 70** (RMF) and in practice 160 × 90 dp or full width. A play badge on the thumbnail is fine (the overlay ban applies to the player itself).
* **Title** (`title`, unchanged, up to 2 lines, ellipsis), **channel** (`channel_title`, always shown), duration (`mm:ss`), and the word "YouTube" as the source (DP III.F.2.a). Channel name may link to `channel_url` via `Linking.openURL`.
* Thumbnails are **not** loaded when the learner has "Économiser les données" on, or the connection is reported as metered/2G: show a text card instead.
* Use the platform image cache only; never write thumbnails into the offline store.
* **Accessibility:** card is one button. Label (fr) "Regarder la vidéo « {title} », chaîne {channel}, durée {minutes} minutes, sur YouTube"; (ht) "Gade videyo « {title} », chèn {channel}, {minutes} minit, sou YouTube". Hint: "Ouvre le lecteur YouTube. Nécessite Internet." / "Ouvri lektè YouTube la. Bezwen entènèt." Thumbnail `accessibilityElementsHidden` / `importantForAccessibility="no"`.

### `VideoPlayerSheet` (tap-to-load)

* **Mounted only after the tap.** One player at a time; opening another closes the first.
* `react-native-webview` (Expo SDK–supported; the only standard way to host the official embed on both platforms; no extra native video library). Justification for the dependency: required by YouTube's own guidance ("use a WebView instance of the embedded player").
* Load a small local HTML page containing the IFrame player:
  * `source={{ html, baseUrl: 'https://<application id>' }}` where the application id is the store id (`ht.edupreneur.student`, dev builds `ht.edupreneur.student.dev`). This sets the **Referer** (RMF "Set the Referer"). Do not set `noreferrer` or a Referrer-Policy that suppresses it.
  * Player parameters: `playsinline=1`, `rel=0`, `hl=fr|ht` (UI language), `enablejsapi=1`, `origin=https://<application id>`, `widget_referrer=https://<application id>`, `start={start_seconds}`. **Not** `autoplay`, **not** `controls=0`, **not** `modestbranding` (deprecated), **not** `fs=0`.
  * WebView props: `allowsInlineMediaPlayback`, `mediaPlaybackRequiresUserAction={true}` (no autoplay), `allowsFullscreenVideo`, `javaScriptEnabled`, `originWhitelist` limited to `https://*`; `setSupportMultipleWindows={false}`; `onShouldStartLoadWithRequest`: let the player load whatever it needs inside its frame (**never filter its requests, which would block ads or features**, DP III.I.5–6); only a **top-level navigation away from the local page** (for example the YouTube logo or title link toward `youtube.com/watch` or a channel) is cancelled and handed to `Linking.openURL` (YouTube app or browser).
  * No `injectedJavaScript` that changes the player; no views positioned over the WebView.
* **Size (verified RMF rule: viewport ≥ 200 × 200 px):** `width = min(screenWidth − 2 × gutter, 480)`, `height = max(200, round(width × 9 / 16))`. On a 320 dp phone with a 16 dp gutter: **288 × 200** (letterboxed), not 288 × 162. Never place the player in a container smaller than 200 × 200 at any font scale.
* **Lifecycle:** pause by destroying the WebView when the sheet closes, the screen blurs, or `AppState` leaves `active` (no background playback, DP III.I.9).
* **Errors** (IFrame `onError`): 2 invalid id, 5 HTML5 error, 100 removed/private, 101/150 owner disallows embedding, 153 missing Referer → show "Cette vidéo ne peut pas être lue ici." with **"Ouvrir dans YouTube"** (`watch_url`). Report the code (without learner data) to the API log later for staff, so the refresh can mark the video.
* **Timeout:** if the player is not ready in 15 s on a slow link, show the same fallback.

### Low-RAM, weak network, metered data

* Never more than one WebView alive; release it on close (Android Go devices ≈ 1 GB RAM).
* No preloading of the player or the IFrame API script before the tap.
* Before the first play on a metered connection, show a one-time notice: "La vidéo utilise des données mobiles (environ 5 Mo par minute)." / "Videyo a ap itilize done mobil (anviwon 5 Mo pa minit)." *(estimate to verify on device)*.
* Respect the app's existing connectivity indicator; offline → offline card.

### Large fonts and 320 dp

* Title wraps to 2 lines then ellipsis; channel and duration on their own line at font scale ≥ 1.3; the play button label never breaks mid-word (reuse the Mobile-02 `roomy` rule).
* The player box size does not depend on font scale; it always meets 200 × 200.

## UI copy (Creole is draft, needs native-speaker review)

| Key | Français | Kreyòl (draft) |
|---|---|---|
| `video.sectionTitle` | Vidéos pour aller plus loin | Videyo pou ale pi lwen |
| `video.watch` | Regarder | Gade |
| `video.source` | sur YouTube | sou YouTube |
| `video.offline` | Vidéo disponible avec une connexion Internet. La leçon fonctionne sans. | Videyo a disponib avèk entènèt. Leson an mache san li. |
| `video.unavailable` | Cette vidéo ne peut pas être lue ici. | Videyo sa a pa ka jwe isit la. |
| `video.openInYouTube` | Ouvrir dans YouTube | Louvri nan YouTube |
| `video.dataNotice` | La vidéo utilise des données mobiles. | Videyo a ap itilize done mobil. |
| `video.dataSaverOn` | Vidéos masquées (économie de données). | Videyo kache (ekonomi done). |
| `video.loading` | Chargement du lecteur… | Lektè a ap chaje… |
| `video.close` | Fermer la vidéo | Fèmen videyo a |
| `settings.showVideos` | Afficher les vidéos dans les leçons | Montre videyo nan leson yo |
| `settings.dataSaver` | Économiser les données | Ekonomize done |

## Things the app must not do

Autoplay; show any overlay on the player; hide or restyle controls; block or skip ads; play in the background or audio-only; download or cache video; store thumbnails offline; award Gold, streaks or completion for watching; add likes, comments, subscriptions or sharing (no write actions, DP III.J); run analytics or tracking SDKs on screens that show a video (required for Made-for-Kids videos, DP III.E.4.j; simplest to apply to all).

## Device tests to run (see `06-test-plan.md` §B)

Error 153 absent on Android and iOS release builds; 320 dp layout at font 1.0 / 1.3 / 2.0; one-player limit; background stop; offline card; low-RAM Android (API 24, 1 GB); slow 3G timeout fallback.
