# 1. Complete feature inventory

One section per feature domain. Each section has:

- **Prototype** — what the source shows, with the status labels from the README.
  *Nothing in the prototype was run; "in source, unverified" is the strongest claim made.*
- **Edupreneurs 2.0 today** — what is on `main`.
- **What v2 would need** — the ten points asked for in the brief, as one table.

Abbreviations: **M** mobile app · **W** public website · **S** staff portal ·
**P0** needed for launch · **P1** soon after launch · **P2** later · **P3** only if evidence supports it.

Launch here means: *real learners use the mobile app to study reviewed lessons
offline.* Whether launch is free or paid is decision PO-01 (doc 07); rows that
depend on it say so.

---

## 1. Identity, account onboarding, existing-user migration

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| E-mail + password sign-up and login | In source, unverified | Uses the hosted auth service for credentials; public sign-up is open |
| Google sign-in | In source, unverified | Through the hosting platform's OAuth wrapper |
| E-mail verification by 6-digit code | In source, unverified | Custom-built rather than the auth service's own; weaknesses withheld (README, finding 8) |
| Password reset | In source, unverified | Custom-built; same remark |
| Login lock-out after failed attempts | Partially implemented | Driven by the browser, so it can be skipped; the lock-out e-mail path looks broken in source |
| Trusted devices / new-device challenge | Partially implemented | Whole path present, but the check runs in the browser after a session already exists |
| Phone or WhatsApp verification | Planned but missing | A function exists that only builds a link; nothing calls it |
| Access method at sign-up (promo, payment, gift, 7-day trial) | In source, unverified | The browser writes the resulting access state itself |
| Onboarding quiz, guided tour, onboarding e-mails | In source, unverified | Collects full name, grade, gender, nickname, school, date of birth, "how did you hear" |
| MCP/agent access with OAuth consent page | In source, unverified | Not in the prototype's own docs |

Depends on: profile table, reset-token and login-attempt tables, two device tables, e-mail provider, hosted auth.

**Edupreneurs 2.0 today:** sign-in through Supabase Auth with public sign-up **disabled**; the API verifies tokens with the public key only (**existing and tested**, 56 token/identity tests); a learner profile row is created on first contact. No onboarding, no account provisioning flow, no migration path. ADR-008 of the original blueprint says: start from a fresh database and new accounts.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | Sign-in and token verification: yes. Everything else: no |
| New pieces | API: `PATCH /v1/me`, onboarding state. Process: how accounts are created (self sign-up vs provisioned by a school vs invited). No custom verification or reset code — use the auth service's built-in flows |
| Depends on | Privacy/consent (§18), entitlements (§13) if access is granted at sign-up |
| Surface | M (onboarding), W (account recovery page), S (provisioning) |
| Offline / low-end | First sign-in needs a connection; after that the app must open and work offline indefinitely with a stored session (already true and tested). Recovery must work on a slow connection and with a shared family phone |
| Security / privacy | Do not build custom recovery, verification or device-trust logic. Do not let the device write any account state. Decide the minimum personal data (the blueprint says: grade and language, not date of birth or school) |
| Existing users | Decision PO-03. Recommended: invite prototype users by e-mail to create a v2 account; carry over only e-mail, grade and any remaining paid time verified from payment records. Do not copy the database |
| Priority | **P0** onboarding (grade, language) and account creation path; **P1** migration invitations; **P3** device trust |
| Launch | Required: account creation, grade/language choice, recovery. Deferrable: Google sign-in, migration tooling, device trust |

---

## 2. Learner profiles and preferences

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Profile (one wide table, ~45 columns) | In source, unverified | Mixes identity, personal data, subscription state, points, streaks, e-mail bookkeeping in one row the owner can update |
| Nickname with availability check and a word filter | In source, unverified | |
| AI-generated avatar | In source, unverified | Calls an image model; 3-day cool-down |
| Theme preference | In source, unverified | |
| UI language setting | Not present | No translation framework; Creole exists only as a school subject |
| Grade selection limiting what content is shown | Partially implemented | Checked in the browser only |
| Public profile page, user search | In source, unverified | Exposes more personal data to other signed-in users than a learner would expect |
| Jude preferences (voice, 3D, speed) | Planned but missing | Table exists; no code uses it |

**Edupreneurs 2.0 today:** `app.learner_profiles` with `grade_id`, `preferred_locale` (fr/ht), optional `display_name`; readable only by its owner (**existing and tested**). No way to change any of it yet (`PATCH /v1/me` is listed in the backlog).

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | Partly: the row exists; editing does not |
| New pieces | API: profile edit (grade, language, display name). Schema: nothing large — keep the profile **small** and keep other concerns in their own tables (see doc 04) |
| Depends on | Curriculum (grades); Social-00 owns the *public* profile separately |
| Surface | M (Profil tab) |
| Offline / low-end | Language and grade must be changeable offline and synced later (a new sync operation kind), because they decide what the app shows |
| Security / privacy | No public profile in the learning module. No date of birth, school, gender or phone unless a specific feature and legal basis needs them. Avatars from a built-in set (no uploads, no AI images of children) |
| Priority | **P0** edit grade and language; **P2** avatars; **P3** theme sync |
| Launch | Required: grade and language. Everything else deferrable |

---

## 3. Grades, subjects, curriculum and content revisions

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Subjects per grade; lessons ordered within a subject | In source, unverified | Grade is free text; no units or chapters |
| Lesson identity | In source, unverified, **inconsistent** | Web address uses subject slug + lesson slug; AI assets use the id; progress uses the slug and a free-text subject |
| French and Haitian Creole versions of a lesson | Not present | One set of text per lesson |
| Version history | Partially implemented | Snapshots text sections only; no restore screen found |
| Baccalauréat series | Partially implemented | A text column; used by exams |

**Edupreneurs 2.0 today:** `grades → courses ← subjects`, `courses → units → lessons`, and `lesson_revisions` with **one revision per language**, immutable once approved; a lesson is identified everywhere by a stable id; questions belong to exactly one revision (**existing and tested**, 62 integrity assertions). Seed content: one mathematics lesson in French and Creole.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | Yes, and stronger. Missing: Bac series/tracks on courses, real content |
| New pieces | Schema: an optional `track`/series on courses (NS3–NS4). Otherwise none |
| Depends on | Staff editor (§4), pack pipeline (§6) |
| Surface | M (catalogue), S (authoring) |
| Offline / low-end | Catalogue is one compact tree, already cached on the device |
| Security / privacy | None beyond publication rules (already enforced by triggers) |
| Priority | **P0** |
| Launch | Required — but the work is content, not schema |

---

## 4. Staff content editor and AI generation pipeline

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Lesson editor | In source, unverified | Plain text areas holding HTML; the rich-text editor is used only for the blog |
| Workflow draft → in review → approved → published | Partially implemented | Screens exist, but several other screens publish directly, and nothing requires the reviewer to differ from the author |
| Scheduled publication | Planned but missing | Column only |
| AI generation as background jobs | In source, unverified | Sections generated one by one with retries; access-control remarks withheld (README, finding 8) |
| Older in-browser batch generator | In source, unverified | Still present |
| Automatic publication after generation | In source, unverified | Done by the browser after the job — i.e. AI text can reach students with no human review |
| AI validation and repair of quizzes | Partially implemented | Functions exist; the results table is unused |
| Curriculum PDF analysis (find missing topics) | In source, unverified | |
| Generation analytics page | In source, unverified | Logs output and timing, not prompt or model |
| Spending limits on AI | Not present | Per-minute request limits only |

Depends on: lesson, version, asset, job and log tables; an AI gateway (one provider, two model sizes); image generation; e-mail.

**Edupreneurs 2.0 today:** the database already enforces the rules the prototype lacks — approved text can never change, the reviewer cannot be the author, sources must be rights-cleared, a pack contains only approved revisions (**existing and tested** at database level). But there is **no staff API, no staff sign-in, no editor, no worker**: content enters only through seed files. `app.background_jobs` exists as an empty queue.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | Rules: yes. Tools: no |
| New pieces | Staff database role and staff API; staff sign-in with a second factor; an authoring tool (web); a worker with job leasing; an AI generation service that writes **drafts only**; object storage for source documents |
| Depends on | Content format v2 (§5), pack pipeline (§6), audit trail (§17) |
| Surface | **S** only |
| Offline / low-end | Not applicable (staff work online) |
| Security / privacy | AI output never publishes itself. No learner data in prompts. Per-job and per-month cost ceilings. Prompts and model versions recorded for every draft. Rights status of every source recorded before approval |
| Priority | **P0** minimal pipeline (import, edit, review, approve, release); **P1** AI drafting; **P2** validation helpers, curriculum analysis |
| Launch | Required: a way to author, review and release lessons without editing seed files. Deferrable: AI generation — humans can write the first lessons |

---

## 5. Rich lesson content, interactive activities, mathematics, media

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Lesson body | In source, unverified | HTML with presentation classes for a specific web design |
| Mathematics | In source, unverified, **fragile** | No stored markup; formulas detected by pattern-matching when displayed, only for science-like subjects |
| Interactive activities | In source, unverified | Two kinds only (multiple choice, true/false), stored as marked-up text parsed by patterns |
| End-of-lesson quiz | In source, unverified | Three stored formats; in practice **regenerated by AI per student, per device, at viewing time** and cached in the browser |
| "Key points" cards and visual summaries | In source, unverified | Also generated per student at viewing time; not stored |
| Images in lessons | In source, unverified | Public storage; AI-generated explanatory images |
| Video | In source, unverified | YouTube only; suggestions from a search API; a ban list |
| Lesson feedback (rating + comment) | In source, unverified | |
| Lesson completion and score | In source, unverified | Written by the browser with a score it computed |

**Edupreneurs 2.0 today:** lesson = ordered list of typed blocks; four block types (`heading`, `paragraph`, `example`, `callout`); questions are separate records; one kind implemented (`mcq`), three reserved (`numeric`, `short_text`, `matching`); the server re-scores every answer from the stored key (**existing and tested**). No mathematics markup, images, tables, lists or audio.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | The structure: yes. The richness: no |
| New pieces | **Content format v2**: block types for mathematics (stored as LaTeX), image, list, table, audio reference, video link; question kinds `true_false`, `numeric`, `short_text`, ordering/matching, each with a versioned scoring rule and shared test vectors for phone and server. Schema: `content_assets` (images/audio in object storage, with size and hash). Native: a mathematics renderer that works offline on low-memory phones |
| Depends on | Object storage and packs (§6); staff editor (§4) |
| Surface | M (rendering), S (authoring) |
| Offline / low-end | Everything a lesson needs must be inside its pack. Mathematics must render with no network and little memory — prefer pre-rendered output in the pack over a heavy in-app engine. Images sized for small screens; audio optional per download. No per-student AI generation: every learner gets the same reviewed questions |
| Security / privacy | No HTML from authors or AI reaches the phone (blocks only). Fixed, reviewed questions are also what makes server scoring meaningful |
| Priority | **P0** mathematics, images, lists/tables, `true_false`/`numeric`; **P1** audio, `short_text`, matching; **P2** video links |
| Launch | Required: mathematics and images (the pilot subject is mathematics). Deferrable: audio, video |

---

## 6. Offline content downloads, audio and PDFs

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Offline page and static asset cache | In source, unverified | The app shell itself is not cached: a cold start offline shows only an "offline" page |
| Re-reading a lesson already viewed | Partially implemented | Kept 24 h in browser storage, used only when the request fails |
| Explicit "download for offline" | Not present | |
| Answering or saving progress offline | Not present | Quiz and activity tabs are disabled offline |
| Native app | Planned but missing | A wrapper configuration pointing at the hosted site; no native code or plugins |
| Lesson audio (text-to-speech) | Partially implemented | Four sections per lesson, public storage, enabled for first lessons only |
| PDFs (exam papers, e-books, curriculum) | In source, unverified | Public storage; viewed in an in-page reader |
| Slow-network mode | In source, unverified | Detects connection quality and reduces animation |

**Edupreneurs 2.0 today:** native app with local SQLite; lessons saved on the device; answers recorded offline and synchronised exactly once; survives restart and account switch (**existing and tested**: 52 mobile tests; validated on an Android 7 / 1 GB emulator in real airplane mode and on the iOS Simulator; **not yet on a physical phone**). Pack tables exist; pack manifests are placeholders; there is no object storage and no pack builder.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | Offline lessons and practice: yes, and well beyond the prototype. Packs, audio, PDFs: no |
| New pieces | Worker: pack builder (collect approved revisions + assets, hash, upload). Object storage (R2): immutable pack objects, download authorisation for paid content. API: manifest and download-grant endpoints. Native: background download with resume, storage budgeting, integrity check, atomic activation. Schema: complete the pack tables (real hashes), `content_assets` |
| Depends on | Content format v2 (§5), entitlements (§13) for paid packs |
| Surface | M |
| Offline / low-end | This *is* the offline design. Per-lesson and per-unit download sizes shown before download; audio and PDFs as optional extras; resume after interruption; never delete the last good copy; a storage cap with clear messages |
| Security / privacy | Public bucket only for content cleared as free; paid content through short-lived signed downloads; hashes checked on device; rights cleared before any exam PDF is redistributed |
| Priority | **P0** real packs with integrity checks; **P1** audio, PDF attachments |
| Launch | Required: packs. Deferrable: audio and PDFs |

---

## 7. Jude AI tutoring, model budgets and conversation storage

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Floating Jude chat on most screens | Partially implemented | Framed as a short "how do I use the platform" helper; receives nickname and current page, **not** the lesson or the learner's history |
| Conversation storage for that chat | Not present | Held in the page only; lost on reload |
| Jude inside community conversations | In source, unverified | Replies are stored as messages from a fixed account |
| Public chatbot on the landing page | In source, unverified | No sign-in needed |
| English and Spanish practice chat | In source, unverified | Stored per learner |
| Reading assistant in the e-book reader | In source, unverified | Not stored |
| Exam tutor (hint, check, reveal, ask) | In source, unverified | Stored per learner; see §8 |
| Mathematics, French and philosophy tutors | Planned but missing | Server functions exist; no screen calls them |
| Chess tutor / chess opponent | In source, unverified | A language model plays the moves |
| Voice | Partially implemented | Speech output for onboarding/tour/exam completion; none in chat; no speech input |
| 3D avatar | Planned but missing | Component exists, unused |
| Motivational pushes "from Jude" | In source, unverified | Templates, no AI |
| Per-user quotas, token budgets, cost tracking | Not present | Per-minute request limits only; no daily or monthly ceiling per learner or overall |
| Safety rules for minors in prompts | Partially implemented | "Education only"; no rules for self-harm, abuse or grooming disclosures |
| Paid-access check on AI endpoints | Not present | |

Depends on: one AI gateway (one fast model nearly everywhere), a speech provider, public audio storage.

**Edupreneurs 2.0 today:** **deliberately deferred** (`docs/NEXT_STEPS.md`): Jude is to be a read-only tutor using an allow-list of tools that call application services under the learner's own identity, with its own request budget, retention and consent policy first. No tables, no endpoint.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | No |
| New pieces | New `tutor` module and schema: request log without text, per-learner and global budgets, kill switch, optional thread storage. API: `POST /v1/jude/requests`. Tools that read approved lessons and the learner's own progress. A provider contract. Possibly a worker for long answers |
| Depends on | Curriculum and learning (grounding), entitlements (who may use it and how much), privacy/consent (minors' free text sent to a third party), notifications (none required) |
| Surface | M (contextual button on lesson and answer screens, as in the UX direction), not a floating chat |
| Offline / low-end | Online-only by nature. The **offline substitute already exists**: every question carries a reviewed explanation. Jude must fail politely and never block a lesson. Short answers, no streaming requirement, no voice at first |
| Security / privacy | The heaviest privacy item in the product: a child's free text goes to an AI company. Needs consent, a retention rule (default: do not store conversations), no personal data in prompts, safeguarding rules and an escalation path for worrying messages, per-learner cost ceilings, sign-in required on every endpoint |
| Priority | **P2**. Budget and consent design is **P1** because it shapes entitlements |
| Launch | Deferrable. Lessons, practice and explanations work without it |

---

## 8. Official exams and Baccalauréat preparation

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Exam catalogue by level, series and subject | In source, unverified | Two levels (9th-year and final-year), four final-year series |
| Adding exams from a PDF with AI extraction | In source, unverified | Staff upload → pages read by a vision model → preview → save; a manual editor also exists |
| Exercise types | In source, unverified | Multiple choice and open-ended; text and LaTeX mathematics blocks; reference texts |
| Practice and timed modes | In source, unverified | |
| Scoring | In source, unverified, **device-trusted** | The answer key is delivered to the browser, which grades and reports the score and a bonus |
| Exam tutor chat | In source, unverified | Conversations stored |
| Original exam PDFs | In source, unverified | Public storage; two files shipped with the app |
| Dissertation coach (philosophy) | Planned but missing | Unused component |

**Edupreneurs 2.0 today:** nothing specific. The model can already express it: an exam is a set of questions with fixed revisions and an assessment mode. Lessons declare `assessment_mode: offline_practice`, and the security notes say answer keys on the device make scores "not proof of knowledge — never use this path for graded exams".

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | No |
| New pieces | Schema: exam papers as publishable content (paper → sections → question revisions; year, session, series, duration, source and rights). New sync operation kinds for an exam session and its answers. Open-ended questions need a marking guide and self-assessment rather than automatic scoring. Worker: PDF ingestion as a staff drafting aid. Storage: original PDFs (if redistribution is allowed) |
| Depends on | Content format v2 (mathematics), packs, staff editor, rights clearance; Jude only for the optional tutor |
| Surface | M (inside **Réviser**, per the UX direction), S (ingestion and review) |
| Offline / low-end | High value offline: an exam pack downloads once and can be practised with no network. Timed mode runs on the device clock (untrusted, display only). Results sync later |
| Security / privacy | State plainly that this is **practice**: the key is on the device. Do not rank or reward on exam scores. Legal: redistribution rights for official ministry papers must be confirmed before any PDF or transcription ships |
| Priority | **P1** — the strongest motive for final-year learners — but after the content pipeline |
| Launch | Deferrable for a first launch aimed at regular lessons; required if the launch audience is exam candidates (decision PO-02) |

---

## 9. Gold, streaks, achievements, leaderboards and referrals

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Gold (points) | Partially implemented | A running total only; no history; nothing to spend it on; the device asks the server to add points |
| Streaks with freezes and milestone badges | Partially implemented | Computed in the database but triggered by any increase in gold, so it inherits the same trust problem; the "day" follows the server's time zone, not Haiti's |
| Achievements | Planned but missing | Shown but never awarded |
| Global leaderboard (top 10 by gold) | In source, unverified | Readable without signing in; shows nickname, grade, avatar |
| Weekly champion badge | Partially implemented | No schedule found |
| Referral links and points | Partially implemented | The recording step appears to be blocked by a later rule change; points have no use |

**Edupreneurs 2.0 today:** **deliberately deferred** ("no schema yet, by design"). The blueprint's rule: derive points and streaks on the server; never trust client-calculated totals.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | No. But v2 already has the right raw material: server-accepted, de-duplicated learning events |
| New pieces | Schema: `reward_ledger` (one row per award, tied to the learning event that earned it), `streak_state`, achievement definitions and awards. Logic: inside or next to the sync write function, so an award happens in the same transaction as the accepted answer and can never be claimed twice. API: read-only summary in `GET /v1/me/progress` and the change feed |
| Depends on | Learning/sync (source of truth), notifications (optional), Social-00 if anything is shown to other learners |
| Surface | M |
| Offline / low-end | The phone shows a **provisional** count for work done offline and replaces it with the server's figure after sync. A streak rule must be decided for work done offline on Monday and synced on Thursday (decision PO-09) |
| Security / privacy | No public leaderboard of minors. If comparison is wanted, keep it inside a verified class group (Social-00) and opt-in. Practice points must not be convertible to anything of value, because the answer key is on the device |
| Priority | **P1** ledger + streak (cheap once designed, and motivating); **P2** achievements; **P3** leaderboards, referrals |
| Launch | Deferrable. Decide the ledger model early (doc 09) |

---

## 10. Chess, Quiz Battle and multiplayer infrastructure

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Quiz Battle solo, friend, random opponent | In source, unverified | Questions generated by AI at match time; answer key sent to both players; the device reports whether an answer was right |
| Battle levels, weekly ranking, badges | In source, unverified | Written by the device |
| Chess against the computer | In source, unverified | No chess engine: a language model picks moves, with a random legal move as fallback |
| Chess online | In source, unverified | Moves and clocks reported by the devices; the server checks turn order only |
| Chess rating, puzzles, in-match chat | In source, unverified | Chat has no filter or reporting |
| Real-time transport | In source, unverified | Database change subscriptions; several always-on channels |
| Presence ("who is online") | In source, unverified | Every signed-in user receives the full list of who is online |

**Edupreneurs 2.0 today:** nothing; Supabase Realtime is disabled in configuration. Explicitly out of scope in the foundation brief and the UX direction ("do not add … live games").

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | No |
| New pieces | For real multiplayer: a `games` module with **server-authoritative** match state (the server validates every move and owns the clock), matchmaking, a real-time channel, abuse controls. This is a different kind of infrastructure from everything else in v2 |
| Depends on | Notifications, Social-00 (who may play whom), entitlements |
| Surface | M |
| Offline / low-end | Real-time play is the opposite of offline-first: it needs a stable, low-latency connection. Offline-friendly alternatives: solo quiz rounds built from reviewed questions already on the phone; chess against a small **on-device** engine; asynchronous "challenge" (each plays the same set when they can, results compared after sync) |
| Security / privacy | Never trust a device-reported result. No presence. No free-text chat between players. Random pairing of minors with strangers is exactly what both app stores scrutinise |
| Priority | **P2** offline solo quiz mode and asynchronous challenges inside class groups; **P3** real-time play, chess |
| Launch | Deferrable in full |

---

## 11. Social and community (coordinated with Social-00)

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Feed: text, image and video posts; likes, threaded comments, shares, mentions | In source, unverified | **No moderation before publication**; the word filter applies only to names |
| Follows with requests; public or followers-only posts | In source, unverified | |
| Direct messages and group chats with attachments | In source, unverified | **Anyone can message anyone**; no reporting of messages; attachments in storage reachable by link |
| Reporting posts and users; founder review screen | In source, unverified | Only two named accounts can review |
| Blocking a user | Not present | |
| Typing indicators, read receipts, reactions | In source, unverified | |

**Edupreneurs 2.0 today:** **designed, not built** — Social-00 (draft pull request #1). It replaces the prototype's model with a pre-moderated, text-only noticeboard in closed, verified groups; no direct messages, media or follows in the first schema; its own database schema and roles with no path to learning data.

**What v2 would need:** see Social-00. Platform-level points only:

| Point | Assessment |
|---|---|
| Shared concerns | Social-00 defines its own public profile, notification events, audit log, rate limits and staff roles. Doc 04 records which of these should become shared services and which should stay separate |
| Surface | M (reached from Accueil and Profil; the four tabs do not change), S (moderation console) |
| Offline / low-end | Separate social outbox; never blocks lesson sync |
| Priority | **P2** as a product; its prerequisites (staff sign-in with a second factor, rate limiting, account deletion) are **P0/P1** for other reasons |
| Launch | Deferrable. The learning product does not depend on it |

---

## 12. Notifications, push, e-mail and messaging infrastructure

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| In-app notification list with per-category preferences | In source, unverified | Notifications are created from the browser rather than by the server |
| Web push | In source, unverified | |
| Native push | Not present | |
| Transactional e-mail (about 15 kinds) | In source, unverified | Welcome, verification, reset, login notice, device check, onboarding series, expiry reminders, birthdays, donation thanks, deletion farewell |
| Announcements to all or to chosen grades | In source, unverified | |
| WhatsApp / SMS | Planned but missing | |
| Scheduled sends | Partially implemented | Four jobs referenced; their creation is not in source; two others have no schedule |
| Daily word notification | In source, unverified | |

**Edupreneurs 2.0 today:** nothing. The blueprint says: no hard dependency on notifications for core lessons.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | No |
| New pieces | A small shared `notify` module: an outbox table that other modules write to (never the device), delivery workers for push and e-mail, device push-token registry, per-learner preferences, quiet hours. Native: push permission and token handling. External: a push service and an e-mail provider. Scheduling through the job queue, with schedules kept in the repository |
| Depends on | Worker/jobs; identity. Producers: billing (expiry), learning (reminders), Social-00 (its own events), staff (announcements) |
| Surface | M (receive), S (compose announcements) |
| Offline / low-end | Push costs the learner almost no data. In-app list is pulled when the app is open. Nothing may depend on a notification arriving |
| Security / privacy | Content-free pushes for minors ("you have something new"), because phones are shared. No birthday e-mails (they need a stored birth date). Marketing consent separate from service messages. Only the server creates notifications |
| Priority | **P1** e-mail for account recovery and receipts (comes with auth and billing); **P1** outbox + push for study reminders; **P2** announcements; **P3** WhatsApp |
| Launch | Required: account e-mails (provided by the auth service) and, if launch is paid, receipts and expiry reminders. Deferrable: push |

---

## 13. MonCash, Stripe, subscriptions, entitlements, gifts and promo codes

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Plan | In source, unverified | One plan: 30 days, priced in gourdes or dollars; prices written into several files |
| **Paywall** | **Switched off in source** | A single setting makes every signed-in user "active". When on, it is checked in the web page only |
| Server-side enforcement of paid access | Not present | Published lessons are readable without a subscription, and without signing in |
| MonCash | Partially implemented | Through a payment aggregator; create → redirect → verify, plus a signed webhook. Integrity gaps (amount, repeat credit) withheld |
| NatCash | Planned but missing | Documented and configured; the functions are absent |
| Card payments | Partially implemented | One-time renewal, donations, gifts; recurring only for gifts |
| Subscription record | Partially implemented | Columns on the profile; no subscription history; the expiry job has no schedule in source |
| Gifts (someone else pays for a learner) | Partially implemented | Link-based; integrity gaps withheld |
| Promo codes and partner organisations | In source, unverified | Grant points and/or free access |
| Donations | Partially implemented | Card path complete in source; mobile-money path incomplete |
| Refunds, cancellation, grace period | Not present | |
| Manual receipt verification by staff | Partially implemented | Screen exists; approving does not grant access |

**Edupreneurs 2.0 today:** nothing ("billing, entitlements … no schema yet, by design"). Content visibility is "published or not" for everyone.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | No |
| New pieces | New `billing` schema with its own database role: plans and prices as data; payment orders; provider events stored raw and processed exactly once; **entitlements** as dated grants with a source (purchase, gift, promo, school, staff); refunds. API: `GET /v1/entitlements`, checkout start, provider webhooks. Worker: reconciliation with the provider. The catalogue and pack endpoints must consult entitlements; the phone holds a **signed, time-limited offline lease** |
| Depends on | Identity; curriculum (what a plan unlocks: everything, a grade, a course?); packs; notifications (receipts, reminders) |
| Surface | M (see status, start payment — subject to app-store payment rules), W (pay, gift, redeem), S (support, refunds) |
| Offline / low-end | The hard part. A learner who paid must keep access with no network for a defined period (suggested 30 days beyond last sync) and lose it gracefully after. Payment itself is online-only. Mobile money confirmation can be slow: the app needs a clear "payment pending" state that survives restart |
| Security / privacy | Access changes **only** from a verified provider event or an audited staff action — never from the device. Amount, currency and plan checked on the server. Each provider event applied once. Payment data kept out of the learning schema. App-store rules on digital purchases need a decision (PO-06) |
| Priority | **P0 to decide the entitlement model** (it shapes packs and the catalogue); **P0 to build** if launch is paid, otherwise **P1** |
| Launch | Depends on decision PO-01. Gifts, promos and donations are deferrable either way |

---

## 14. E-books, templates and downloadable resources

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Library of PDF books with in-app reader | In source, unverified | Files in public storage |
| Reading position, comments and ratings | In source, unverified | |
| Document templates (timetable, planner, CV, invoice, certificate…) with PDF export | Partially implemented | Public, no sign-in; PDF only |
| "Resources" page | In source, unverified | Not examined in detail |
| Daily word, study music | In source, unverified | Music is YouTube links |

**Edupreneurs 2.0 today:** nothing.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | No |
| New pieces | Books as downloadable assets attached to the catalogue (same pack mechanism as lessons), with a reading-position sync operation. Templates are a website feature unrelated to the learning backend |
| Depends on | Packs and object storage; entitlements; rights clearance for every book |
| Surface | M (books), W (templates) |
| Offline / low-end | Books are large: explicit download with size, resumable, optional. Prefer reflowable text over PDF on small screens |
| Security / privacy | Copyright is the main risk: the rights status of every title must be recorded (the `content_sources` model already exists for lessons). Comments on books are user-generated content and belong under Social-00's rules, or not at all |
| Priority | **P2** books; **P3** templates, music, daily word |
| Launch | Deferrable |

---

## 15. Study notes, goals and reading progress

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Notes on a lesson | In source, unverified | |
| General notes table | Planned but missing | Unused |
| Personal goals | Partially implemented | Read by the dashboard only |
| Study sessions (time spent) | Partially implemented | Read; no writer found |
| Favourite subjects | In source, unverified | |
| Reading position in books | In source, unverified | |

**Edupreneurs 2.0 today:** lesson progress stores `last_block_key` and `last_opened_at` (columns exist; a reading-position operation is in the backlog). No notes or goals.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | Partly (reading position columns) |
| New pieces | New sync operation kinds: `lesson_opened` (last block), `note_saved`, `goal_set`. Small tables in the learning schema. Each needs a merge rule for two devices (notes: last write wins per note with a version check) |
| Depends on | Sync only |
| Surface | M |
| Offline / low-end | Natural fit: written locally, synced later |
| Security / privacy | Notes are a child's free text: private to the owner, never used for AI or analytics, included in deletion and export |
| Priority | **P1** reading position; **P2** notes, goals |
| Launch | Deferrable |

---

## 16. Career orientation, translation and passion discovery

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Career orientation: 4-step questionnaire, 7 domains, 14 career sheets, recommendations, favourites, comparison | In source, unverified | Runs entirely in the browser, stored on the device, no AI; the only part of the prototype with an automated test. Its own roadmap says the career facts still need official confirmation |
| Translation tool (English, French, Creole, Spanish) | In source, unverified | Public, no sign-in, AI-backed |
| Passion discovery: interest quiz, modules (chess, music, arts, literature, civics), progress, videos | In source, unverified | Module content is written into the app; only scores, progress and video links are in the database |
| Passion tutor | In source, unverified | No sign-in needed; not stored |

**Edupreneurs 2.0 today:** nothing.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | No |
| New pieces | Orientation: almost none on the backend — it is static, reviewed content plus answers stored on the device; ship it as a content pack. Translation: an AI-backed online tool; belongs with Jude's budget and consent rules. Passions: content packs in the existing model plus progress operations |
| Depends on | Content pipeline (editorial review of career facts), packs |
| Surface | M (orientation, passions), W (translation) |
| Offline / low-end | Orientation and passion modules work fully offline as packs. Translation is online-only |
| Security / privacy | Career advice to minors must be accurate and sourced. Orientation answers are personal: keep them on the device unless the learner chooses to sync. An open, free AI endpoint is a cost risk |
| Priority | **P2** orientation (cheap, valuable for final-year learners); **P3** passions, translation |
| Launch | Deferrable |

---

## 17. Founder administration, analytics, reporting and audit trails

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Control centre with 12 modules (users, reports, payments, donations, announcements, statistics, daily words, blog, contact, lesson feedback, promo/partners, SEO) | In source, unverified | |
| Who is an administrator | In source, unverified | A short fixed list of account ids written into the database and several source files, with inconsistencies between the lists; plus an editor-roles table |
| Analytics pages | Partially implemented | Totals computed in the browser from profile and payment tables |
| Third-party analytics (two trackers) | Planned but missing | Consent-gated but configured with placeholder ids, so they never load |
| Visitor tracking | Planned but missing | Events are built and discarded |
| Audit trail | Partially implemented | Content changes only, written by the browser; nothing for admin actions, payments or access changes |
| Blog, contact form, landing pages, promo video sources | In source, unverified | |
| Granting or extending a subscription by staff | Not present | |

**Edupreneurs 2.0 today:** `app.staff_roles` (editor, reviewer, publisher, admin) and `app.audit_events` exist and are protected, but **nothing writes audit events and there is no staff API or sign-in** (listed in `docs/SECURITY.md`). No analytics.

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | Tables only |
| New pieces | Staff sign-in with a second factor; a staff API on its own database role; roles as data granted through an audited process (no ids in source code); audit events written by the server for every staff action and every access or payment change; a staff web portal (content first, then support, then finance); privacy-respecting product metrics computed on the server from events — no third-party trackers in the learner app |
| Depends on | Everything staff touch: content, billing, notifications, moderation (Social-00 has its own staff roles on purpose) |
| Surface | S; W for blog and contact (a separate, simple site) |
| Offline / low-end | Not applicable |
| Security / privacy | Least privilege per role; no shared founder account; every action attributable; reports use aggregates, not individual children's activity, unless a support case needs it and it is logged |
| Priority | **P0** staff sign-in + audit writes + minimal content portal; **P1** support tools (find a learner, see entitlement, grant access); **P2** dashboards |
| Launch | Required: staff sign-in, audit, content tools. Deferrable: dashboards, blog |

---

## 18. Child safety, privacy, consent, retention and account deletion

**Prototype**

| Feature | Status | Notes |
|---|---|---|
| Terms and privacy pages | In source, unverified | State that under-13s need parental consent |
| Age check or parental consent mechanism | Not present | Date of birth is collected and used for birthday e-mails |
| Record that a user accepted the terms | Not present | A checkbox validated in the browser only |
| Cookie consent | In source, unverified | Kept in the browser |
| Data export | Not present | |
| Account deletion by the user | Partially implemented | Deletes the account and relies on cascades; some stored files appear to be left behind; the farewell e-mail says everything was erased |
| Account deletion by an administrator | Partially implemented | Logs to a table that does not exist in source |
| Retention rules | Partially implemented | Only for AI jobs, rate-limit rows and stale games |
| Limits on what other users can see about a learner | Partially implemented | A restricted view exists but most screens bypass it; details withheld |
| Moderation, blocking, safeguarding escalation | See §11 | |

**Edupreneurs 2.0 today:** strong technical isolation (**existing and tested**: a learner can read only their own rows; 47 isolation tests), data minimisation in the profile, synthetic data only. But `docs/SECURITY.md` lists as open: no retention or deletion (deleting an account with learning data is blocked by foreign keys), no consent model, no audit trail written, no rate limiting. `docs/NEXT_STEPS.md` item 6: "Privacy decisions … blocks collecting real student data".

**What v2 would need**

| Point | Assessment |
|---|---|
| Equivalent in v2 | Isolation: yes. Consent, retention, deletion, export: no |
| New pieces | Schema: consent records (what was accepted, which version, by whom — learner, guardian or school), deletion requests, data-export requests, retention settings. An **erasure orchestrator** that calls each module's own erase function (learning, billing, social, tutor) and then removes the auth user. A retention job. API: request deletion and export from the app |
| Depends on | Every module that stores personal data must provide an erase function and a retention rule before it ships |
| Surface | M (request deletion/export, see what is stored), W (privacy notice, deletion page — both app stores require a web path), S (handle requests) |
| Offline / low-end | Deletion request can be queued offline; local data on the phone is wiped immediately on confirmation |
| Security / privacy | Legal advice needed on applicable law, consent age, school consent, retention periods (Social-00 doc 11 lists the same questions; one legal brief should cover both) |
| Priority | **P0** |
| Launch | Required. This is the one domain where "defer" means "do not launch" |
