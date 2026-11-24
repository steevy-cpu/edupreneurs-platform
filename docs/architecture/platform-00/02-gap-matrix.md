# 2. Prototype-to-v2 gap matrix

One row per capability. Read it left to right: what the prototype had, what v2
has, what kind of work closes the gap, how urgent, and whether launch needs it.

**Prototype status** — never "tested" (see README):
`SRC` in source, unverified · `PART` partially implemented · `PLAN` planned but missing · `—` not present

**v2 status:**
`TESTED` existing and tested · `PART` partially implemented · `DESIGN` designed, not built · `DEFER` deliberately deferred · `—` not present, not yet decided

**Work needed in v2:** `S` new schema · `A` new API · `W` worker/job · `O` object storage · `N` native capability · `X` external service · `C` content/editorial work · `P` policy or legal decision

**Port?** — `port` the idea carries over · `redesign` the feature is wanted but the prototype's approach must not be copied · `drop` not recommended · `new` v2 needs it and the prototype never had it

**Launch:** `yes` required · `if paid` required only if launch charges money (PO-01) · `no` can follow

## Identity and profile

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Sign in, verified tokens | SRC | TESTED | — | port | P0 | yes |
| Account creation path (who creates accounts) | SRC (open sign-up) | — (sign-up disabled) | A P | redesign | P0 | yes |
| E-mail verification, password recovery | SRC (custom) | — | X (auth service built-ins) | redesign | P0 | yes |
| Google sign-in | SRC | — | X | port | P2 | no |
| Device trust, login lock-out | PART | — | X (auth service limits) | drop custom build | P3 | no |
| Onboarding: grade and language | SRC | — | A N | port | P0 | yes |
| Onboarding: date of birth, school, gender, phone | SRC | — (by design) | P | drop unless justified | — | no |
| Profile edit | SRC | PART (row exists, no edit) | A | port | P0 | yes |
| UI in Haitian Creole | — | TESTED (mobile strings) | — | new | P0 | yes |
| Avatar | SRC (AI-generated) | — | — (built-in set) | redesign | P2 | no |
| Public profile and user search | SRC | — | — | redesign in Social-00 | P2 | no |
| Existing-user migration | — | — | A P | new | P1 | no |

## Curriculum and content

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Grades, subjects, courses, units, lessons | SRC (free text, no units) | TESTED | — | redesign (done) | P0 | yes |
| Stable lesson identity | SRC, inconsistent | TESTED | — | redesign (done) | P0 | yes |
| Per-language revisions (French / Creole) | — | TESTED | — | new | P0 | yes |
| Immutable approved revisions | PART | TESTED | — | redesign (done) | P0 | yes |
| Bac series on courses | PART | — | S | port | P1 | no |
| Real lesson content at scale | SRC (HTML) | — (one seed lesson) | **C** | **redesign: convert and re-review** | P0 | yes |
| Mathematics markup | SRC (guessed at display) | — | S N | redesign | P0 | yes |
| Images in lessons | SRC | — | S O N | port | P0 | yes |
| Lists, tables | SRC (HTML) | — | S N | redesign | P0 | yes |
| Question kinds beyond multiple choice | SRC (true/false) | PART (3 kinds reserved) | S A N | port | P0 | yes |
| Fixed, reviewed questions for every learner | — (AI per student) | TESTED | — | redesign (done) | P0 | yes |
| Server computes the score | — (device reports) | TESTED | — | redesign (done) | P0 | yes |
| Lesson audio | PART | — | S O W N X | port | P1 | no |
| Video links | SRC | — | S | port | P2 | no |
| Per-student AI summaries and visual cards | SRC | — | — | drop (replace with reviewed "key points" blocks) | — | no |
| Lesson feedback (rating) | SRC | — | S A | port | P2 | no |

## Staff tools and AI generation

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Staff sign-in with second factor | — | — | A X | new | P0 | yes |
| Roles as data, granted by audited process | PART (ids in code) | PART (table, no process) | A | redesign | P0 | yes |
| Authoring tool | SRC (HTML text areas) | — | A + staff web | redesign | P0 | yes |
| Review by a different person, enforced | — | TESTED (database) | A (expose it) | new | P0 | yes |
| Rights-cleared sources before approval | — | TESTED (database) | A | new | P0 | yes |
| Release as an immutable pack | — | PART (tables; no builder) | W O | new | P0 | yes |
| AI drafting of lessons | SRC | DEFER | W X S | redesign: drafts only | P1 | no |
| AI auto-publication | SRC | — (forbidden by triggers) | — | drop | — | no |
| AI cost ceilings | — | — | S W | new | P1 | no |
| AI validation helpers, curriculum gap analysis | PART | — | W | port | P2 | no |
| Scheduled publication | PLAN | — | W | port | P3 | no |

## Offline

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Open the app with no network | — (offline page) | TESTED | — | new (done) | P0 | yes |
| Download lessons deliberately | — | TESTED (per lesson) | — | new (done) | P0 | yes |
| Answer and save progress offline | — | TESTED | — | new (done) | P0 | yes |
| Exactly-once sync, safe retries | — | TESTED | — | new (done) | P0 | yes |
| Shared-phone account switch | — | TESTED | — | new (done) | P0 | yes |
| Validation on a real low-end phone | — | — (emulator only) | test | new | P0 | yes |
| Real packs with hashes and object storage | — | PART | W O A N | new | P0 | yes |
| Paid content offline (time-limited lease) | — | — | S A N | new | P0 design | if paid |
| Audio and PDF attachments | PART (online) | — | O N | port | P1 | no |
| Native app | PLAN (wrapper config only) | TESTED | — | new (done) | P0 | yes |

## Learning extras

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Lesson completion | SRC (device-reported) | TESTED | — | redesign (done) | P0 | yes |
| Reading position | PART (books only) | PART (columns) | A N | port | P1 | no |
| Progress snapshot for a new device | — | — (backlog) | A | new | P1 | no |
| Notes | SRC | — | S A N | port | P2 | no |
| Goals | PART | — | S A N | port | P2 | no |
| Study time | PART | — | derive from events | redesign | P3 | no |
| Favourites | SRC | — | N (device only) | port | P3 | no |

## Exams

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Exam catalogue by level, series, subject | SRC | — | S A C | port | P1 | PO-02 |
| Exam practice, timed mode | SRC | — | S A N | port | P1 | PO-02 |
| Exam score | SRC (device-reported) | — | A (practice only, no ranking) | redesign | P1 | PO-02 |
| Open-ended questions with marking guide | SRC | — | S | port | P1 | no |
| PDF ingestion with AI | SRC | — | W X | port (staff aid) | P2 | no |
| Original exam PDFs | SRC | — | O P (rights) | port if permitted | P2 | no |
| Exam tutor chat | SRC | — | with Jude | redesign | P2 | no |

## AI tutoring

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Tutor grounded in the lesson and the learner's progress | — (platform helper only) | DEFER | S A X | new | P2 | no |
| Reviewed explanation for every question, offline | — | TESTED | — | new (done) | P0 | yes |
| Conversation storage | PART (some tutors) | — | S P | redesign: off by default | P2 | no |
| Per-learner budgets, cost tracking, kill switch | — | — | S | new | P1 design | no |
| Sign-in required on every AI endpoint | PART | — | A | redesign | P2 | no |
| Safeguarding rules and escalation | PART | — | P | new | P2 | no |
| Language practice chat | SRC | — | with Jude | port | P3 | no |
| Voice output | PART | — | X O | port as pre-recorded audio | P3 | no |
| 3D avatar | PLAN | — | — | drop | — | no |
| Public chatbot on the website | SRC | — | — | drop or static FAQ | — | no |

## Gamification

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Points | PART (device-requested, total only) | DEFER | S (ledger from accepted events) | redesign | P1 | no |
| Streaks, freezes | PART | DEFER | S | redesign | P1 | no |
| Achievements | PLAN | DEFER | S | port | P2 | no |
| Global public leaderboard | SRC | — | — | drop | — | no |
| Class-level comparison, opt-in | — | — | with Social-00 | new | P3 | no |
| Referrals | PART | — | S P | redesign | P3 | no |

## Games and real time

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Solo quiz rounds | SRC (AI questions) | — | N (from reviewed questions on device) | redesign | P2 | no |
| Head-to-head quiz, live | SRC (device-reported) | — | S A + real-time service | redesign | P3 | no |
| Asynchronous challenge | — | — | S A | new | P2 | no |
| Chess vs computer | SRC (AI picks moves) | — | N (on-device engine) | redesign | P3 | no |
| Chess online | SRC (device-reported) | — | real-time service | redesign | P3 | no |
| Presence | SRC | — | — | drop | — | no |
| In-game chat | SRC | — | — | drop | — | no |

## Community

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Feed, comments, reactions | SRC (unmoderated) | DESIGN (Social-00: pre-moderated, closed groups) | per Social-00 | redesign | P2 | no |
| Report, block, moderation queue, sanctions | PART (report only) | DESIGN | per Social-00 | redesign | P2 | no |
| Direct and group messages | SRC (open) | DESIGN (not approved) | — | redesign or drop | P3 | no |
| Media in posts | SRC | DESIGN (not approved) | — | redesign | P3 | no |
| Follows | SRC | — | — | drop | — | no |

## Notifications

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Account e-mails (verify, recover) | SRC (custom) | — | X (auth service) | redesign | P0 | yes |
| Notification outbox written only by the server | — | — | S W | new | P1 | no |
| Native push | — | — | N X W | new | P1 | no |
| Preferences, quiet hours | SRC | — | S A | port | P1 | no |
| Receipts and expiry reminders | SRC | — | W | port | P1 | if paid |
| Announcements by grade | SRC | — | A (staff) | port | P2 | no |
| Marketing / lifecycle e-mails | SRC | — | P (consent) | port | P3 | no |
| Birthday e-mails | SRC | — | — | drop | — | no |
| WhatsApp / SMS | PLAN | — | X | port | P3 | no |
| Schedules kept in the repository | — (created by hand) | — | W | new | P1 | no |

## Money and access

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Entitlement model (who may use what, until when) | PART (profile columns, browser-checked, switched off) | — | **S A** | **redesign** | **P0 design** | if paid |
| Server-side enforcement on content | — | — | S A | new | P0 design | if paid |
| Plans and prices as data | — (in code) | — | S | redesign | P1 | if paid |
| Mobile-money payment | PART | — | A W X | redesign | P1 | if paid |
| Card payment | PART | — | A W X | redesign | P2 | no |
| Provider events applied exactly once | — | — | S W | new | P1 | if paid |
| Free trial | SRC (browser-granted) | — | S | redesign | P1 | if paid |
| Gifts | PART | — | S A | redesign | P2 | no |
| Promo codes, partner organisations, school licences | SRC | — | S A | redesign | P2 | no |
| Refunds, cancellation, grace period | — | — | S A P | new | P1 | if paid |
| Staff can grant or extend access, audited | — | — | A | new | P1 | if paid |
| Donations | PART | — | website | port | P3 | no |

## Library and enrichment

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| E-books | SRC | — | S O N C P (rights) | port | P2 | no |
| Book comments and ratings | SRC | — | — | drop or Social-00 | P3 | no |
| Templates with PDF export | PART | — | website | port | P3 | no |
| Career orientation | SRC | — | C N (content pack) | port | P2 | no |
| Passion modules | SRC | — | C | port | P3 | no |
| Translation tool | SRC | — | with Jude budget | port | P3 | no |
| Daily word | SRC | — | C | port | P3 | no |
| Study music | SRC | — | — | drop | — | no |

## Administration, analytics, audit

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| Audit trail written by the server | PART (content only, browser-written) | PART (table, nothing writes) | A | redesign | P0 | yes |
| Staff portal: content | SRC | — | staff web | redesign | P0 | yes |
| Staff portal: learner support | SRC | — | A + staff web | port | P1 | no |
| Staff portal: payments | PART | — | A + staff web | redesign | P1 | if paid |
| Product metrics | PART (browser totals) | — | W S | redesign | P2 | no |
| Third-party trackers in the learner app | PLAN (placeholders) | — | — | drop | — | no |
| Blog, contact form, landing pages | SRC | — | website | port | P3 | no |

## Safety and privacy

| Capability | Prototype | v2 | Work | Port? | Priority | Launch |
|---|---|---|---|---|---|---|
| A learner sees only their own data | PART | TESTED | — | redesign (done) | P0 | yes |
| Minimal personal data | — | TESTED (by design) | — | new (done) | P0 | yes |
| Recorded consent (learner, guardian or school) | — | — | S A P | new | P0 | yes |
| Age band and under-13 rule | — | DESIGN (Social-00 only) | S P | new | P0 | yes |
| Account deletion that really erases | PART | — | S A W | redesign | P0 | yes |
| Data export | — | — | A W | new | P1 | no |
| Retention rules | PART | — | W P | new | P0 | yes |
| Rate limiting | PART | — | gateway | new | P0 | yes |
| Hosted environment, backups, restore drill | (hosted by vendor) | — | infra | new | P0 | yes |

## Totals

Counted from the tables above.

| | Count |
|---|---|
| Capabilities listed | 137 |
| v2 **existing and tested** | 20 |
| v2 partially implemented | 7 |
| v2 designed elsewhere (Social-00) | 5 |
| v2 deliberately deferred | 5 |
| Required for launch (`yes`) | 44 |
| Required only if launch is paid | 11 |
| Depends on the first audience (PO-02) | 3 |
| Recommended **redesign** (wanted, but not the prototype's way) | 46 |
| Recommended **port** (the idea carries over) | 39 |
| **New** in v2 (the prototype never had it) | 38 |
| Recommended **drop** | 14 |
