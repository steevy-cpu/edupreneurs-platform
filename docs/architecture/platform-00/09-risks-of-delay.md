# 9. Risks of delaying each high-priority architectural decision

For each decision that shapes the architecture: what waits on it, what happens
if it is postponed, how reversible a late or wrong choice is, and the cheapest
action that removes most of the risk now.

"Cost of delay" is a judgement, not a measurement: **Low** = some rework in one
module · **Medium** = rework across modules or lost weeks · **High** = rework
across modules *and* content or installed apps · **Critical** = legal exposure
or harm to users.

## Summary

| # | Decision | Blocks | Cost of delay | Reversible later? |
|---|---|---|---|---|
| 1 | Prototype's future and its known weaknesses (PO-14) | Nothing in v2 — live users | **Critical** | Harm done is not reversible |
| 2 | Personal data and consent model (PO-04) | Any real learner; Platform-01 | **Critical** | Data wrongly collected cannot be un-collected |
| 3 | Content format v2 (PO-08) | All authoring and conversion | **High** | Only by rewriting content |
| 4 | Entitlement model and scope (PO-01, PO-05) | Packs, catalogue, payments, Jude, exams | **High** | Hard once phones hold packs and leases |
| 5 | Offline lease for paid content (PO-07) | Platform-06; app storage design | **High** | Needs an app update on every phone |
| 6 | Lesson identity used by every new module | Rewards, notes, exams, Jude, audio | **High** | Only by data migration |
| 7 | Rewards as a ledger from accepted events (PO-09) | Platform-08; anything shown to peers | **Medium** | Balances cannot be reconstructed afterwards |
| 8 | Staff boundary: sign-in, roles, audit | Content, support, payments, moderation | **High** | Yes, but every staff action before it is unaudited |
| 9 | Worker and job model | Packs, payments, notifications, AI, retention | **Medium** | Yes |
| 10 | Notification outbox ownership | Reminders, receipts, social, announcements | **Medium** | Yes, with duplicated code to remove |
| 11 | How payment happens from the app (PO-06) | Platform-07; store approval | **High** | A rejected app or a rebuilt checkout |
| 12 | Schools and tenancy (PO-13) | Accounts, entitlements, communities | **Medium → High** | Expensive: touches most tables |
| 13 | First audience (PO-02) | Content plan; exams priority | **Medium** | Yes |
| 14 | Existing-user plan (PO-03) | Communications; migration entitlement | **Medium** | Partly — trust is harder to rebuild than code |
| 15 | Jude: scope, storage, budget (PO-11) | Platform-13 only | **Low** | Yes — nothing depends on Jude |
| 16 | Real-time games (PO-12) | Platform-14 only | **Low** | Yes |

## Detail

### 1. The prototype's future (PO-14)
- **Why it is first.** It is the only item here about people using a live
  system today. Reading the source showed weaknesses in account handling,
  exposure of personal data between users, open messaging among minors,
  and AI and voice endpoints without spending limits. Specifics were given to
  the owners privately; this public document does not repeat them.
- **If delayed.** The exposure continues for as long as the prototype runs
  unchanged. v2 does not reduce it until users actually move.
- **Cheapest action now.** Read the private list; decide which items to fix or
  switch off this week; consider pausing new sign-ups and the highest-risk
  features until then. This costs no v2 engineering.
- **Caveat.** Findings come from source and migration files, not from testing
  the live system; some may already be mitigated in the live configuration.
  Confirming that is part of the action.

### 2. Personal data and consent (PO-04)
- **Waits on it:** onboarding, account creation, the first real learner, the
  privacy notice, store declarations, Social-00's enrolment.
- **If delayed.** Either launch slips, or data on minors is collected without
  a recorded basis — the prototype's position (it collects birth date and
  school, and states a parental-consent rule that nothing enforces).
- **Reversibility.** Schema is easy to change; having collected data
  unlawfully is not.
- **Cheapest action now.** Commission the legal brief (one brief, shared with
  Social-00). Meanwhile build Platform-01 around the minimal model (grade,
  language, age band, consent record), which any likely answer permits.

### 3. Content format v2 (PO-08)
- **Waits on it:** the authoring tool, every converted lesson, mathematics on
  the phone, exams, career content.
- **If delayed.** Authors work around the four existing block types — formulas
  typed as plain text, tables as paragraphs — and that content must be redone.
  Or authoring waits and the content calendar slips. The prototype shows the
  end state of "decide later": presentation HTML and formulas recovered by guesswork.
- **Reversibility.** Formats are versioned, so adding block types later is
  cheap. *Not having* mathematics when the first mathematics course is written is expensive.
- **Cheapest action now.** Agree the minimum set (mathematics, image, list,
  table, audio reference) and measure two ways of drawing mathematics on the
  1 GB reference device. One week of work unlocks all content.

### 4. Entitlement model (PO-01, PO-05)
- **Waits on it:** pack download rules, what the catalogue shows as locked,
  payments, trials, gifts, school licences, Jude allowances, paid exams.
- **If delayed.** Packs and the catalogue ship assuming "everything published
  is for everyone". Adding access rules later changes two endpoints, the
  visibility policies, the pack download path and the app's storage — after
  phones are already holding content. The prototype's history is the warning:
  access state lived on the profile, grew special cases, was checked only in
  the page, and ended up switched off.
- **Reversibility.** Moderate before launch; poor after, because installed
  apps and downloaded packs embody the assumption.
- **Cheapest action now.** Decide free-versus-paid for launch, and design the
  grant model with a `scope` even if the only scope used is "everything" and
  the only source is "staff grant". Building payments can wait; the shape cannot.

### 5. Offline lease (PO-07)
- **Waits on it:** how the phone stores proof of access, what the app does
  when it lapses, how refunds take effect.
- **If delayed.** The first paid release either requires a connection to open
  paid lessons (breaking the offline promise for the customers who pay) or
  grants access forever once downloaded.
- **Reversibility.** Needs an app update reaching every phone — slow where
  updates cost data.
- **Cheapest action now.** Fix the rule (suggested 30 days after last sync)
  and include the lease fields in the entitlement design, even unused.

### 6. Lesson identity everywhere
- **Waits on it:** rewards, notes, reading position, exams, audio files, Jude citations.
- **If delayed.** A new module takes a shortcut — a slug, a title, a subject
  name — and reproduces the prototype's problem, where renaming a lesson
  orphans progress and audio.
- **Reversibility.** Only by migrating that module's data.
- **Cheapest action now.** Already decided in v2. Make it a written review
  rule: new tables reference `lesson_id` or `lesson_revision_id`, never text.

### 7. Rewards as a ledger (PO-09)
- **Waits on it:** points, streaks, achievements, anything comparative.
- **If delayed.** Pressure to "just add a points column" before launch. A
  running total cannot be corrected, audited or explained, and inherits trust
  from whoever may increase it.
- **Reversibility.** A ledger can be summed into a total at any time; a total
  can never be expanded into a ledger.
- **Cheapest action now.** Record the rule (awards are rows tied to accepted
  learning events, written in the same transaction) and decide what a "day"
  is. No build needed yet.

### 8. Staff boundary
- **Waits on it:** the authoring tool, releases, learner support, payment
  support, moderation (Social-00), announcements.
- **If delayed.** Content keeps entering through seed files and database
  access by developers — unaudited, unscalable, and using the most powerful
  database account. The prototype's equivalent was a fixed list of
  administrator ids copied into several files, with the copies disagreeing.
- **Reversibility.** Good technically; but actions taken before it exist have no record.
- **Cheapest action now.** Platform-03 early. Even a command-line tool behind
  the staff role is better than direct database access.

### 9. Worker and job model
- **Waits on it:** pack building, payment reconciliation, notification
  delivery, AI drafting, retention, scheduled tasks.
- **If delayed.** Each feature invents its own background mechanism, or does
  long work inside API requests. The prototype's scheduled jobs were created
  by hand outside the code and cannot be rebuilt from source.
- **Cheapest action now.** One worker, one queue table (it exists), schedules
  in the repository — before the first feature that needs it (packs).

### 10. Notification outbox
- **If delayed.** Billing, learning and social each grow their own sender and
  their own credentials; preferences and quiet hours are implemented three times.
- **Cheapest action now.** Agree that producers write to one outbox through
  one function. The delivery side can come later.

### 11. Payment path from the app (PO-06)
- **If delayed.** Checkout is designed, then a store rejects the app, or the
  flow that works for mobile money is not allowed where it was put.
- **Cheapest action now.** Ask for advice on the stores' current rules for the
  countries where the app will be listed, before any checkout screen is drawn.

### 12. Schools (PO-13)
- **If delayed and the answer is yes.** Account creation, consent (a school
  consenting for a class), entitlements (a licence for many learners) and
  reporting all need rework; a tenant boundary added late touches most tables and policies.
- **If decided no for now.** Nothing is lost: the grant model's
  `school_licence` source and Social-00's class groups keep the door open.
- **Cheapest action now.** A yes / likely / no from the owners.

### 13–16. Lower-risk items
- **First audience (PO-02):** delay costs content planning time, not architecture.
- **Existing users (PO-03):** the technical part is small (an invitation and a
  migration grant); the cost of delay is users hearing nothing.
- **Jude (PO-11)** and **real-time games (PO-12):** nothing depends on them.
  They are safe to leave until their turn — which is the main architectural
  point about them.

## The risk of *not* delaying

Three things are safer to postpone than to rush, and pressure to ship them
early is itself a risk:

| Feature | Why waiting is the safer choice |
|---|---|
| Community, messaging | Needs moderators on a rota before it needs code (Social-00) |
| Jude | Sends minors' text to a third party; needs consent, budget and safeguarding rules first |
| Real-time multiplayer | Needs server-authoritative state and a stable connection — the opposite of the conditions the product is designed for |

## Protecting the offline-first foundation

Every item above is checked against one question: *does a lesson still open,
and an answer still save and sync exactly once, on an old phone with no
network?* The roadmap's gates repeat that test at each milestone, with the
existing 405 automated tests as the non-negotiable baseline.
