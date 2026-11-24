# 6. Moderation workflow, safety operations and threat model

This document is about people and procedures as much as software. Software
cannot make a community of minors safe; it can only make the safe path the
default and the unsafe path visible and slow.

## Safety principles

1. **Approve first, publish second.** Nothing user-written is shown to others before a human approved it.
2. **Hide first, review second.** A serious report hides content immediately; a human then decides.
3. **Known people in small rooms.** Every member was confirmed by an adult; communities are small and closed.
4. **No private channels.** Everything a learner can say is said where moderators and the group's teacher can see it.
5. **No contact details.** The system refuses phone numbers, links, e-mail addresses and handles — the tools used to move a child to an unmoderated app.
6. **Collect little, keep it briefly.** Age band instead of birth date; text erased when no longer needed; logs without text.
7. **Two independent locks on anything powerful.** Database role *and* staff role; moderator *and* safety lead for the heaviest actions.
8. **Everything staff do is recorded and cannot be edited.**
9. **Calm by design.** No streaks, no follower counts, no "who liked you", no per-reaction notifications, no endless scroll, no engagement nudges.

## Eligibility controls

| Control | Rule | Enforced by |
|---|---|---|
| Enrolment | Created by staff / school official, never by the learner | `CHECK (enrolled_by <> user_id)`; no member function creates enrolments |
| Age band | Must be known before activation | `CHECK` on `enrollments` |
| Consent | Minors need `granted` consent with a recorded method and recorder; `not_required` only for `18_plus` | `CHECK` on `enrollments` |
| Under 13 | Enrolment allowed **only** if decision D-02 and legal advice permit; default in the pilot: not enrolled | Admin function rule (Social-02) |
| Community rules | Current version must be accepted before any write | `write_denial` → `guidelines_not_accepted` |
| Grade band | Learner can only be active in a community of their band | Trigger `membership_guard` |
| Verified membership | Confirmed by a teacher of the group or staff, never by oneself | `CHECK (verified_by <> user_id)`; `decide_join_request` |
| Withdrawal | Consent withdrawn → enrolment `paused` → no read or write access at once | `actor_access` on every request |

## Authorised-adult management

| Capability | Pilot (Social-03) | Later (Social-04) |
|---|---|---|
| Who authorises a learner | The **school**, under a written agreement that covers informing families and collecting their consent | School or a verified parent/guardian in the app |
| Proof kept by Edupreneurs | `consent_method = 'school_agreement'`, who recorded it, when | Plus `guardian_in_app` records |
| Adult can pause the learner's access | Through the school → staff | Self-service |
| Adult can switch off posting / commenting / reacting and lock it | Through staff | Self-service (`locked_by = 'adult'`) |
| Adult is told about a suspension or a serious incident | By the safety lead, through the school | In-app notice + school |
| Adult can request erasure | Through staff | Self-service request |
| Adult can read the child's posts | Decision D-05 | Decision D-05 |

Why school-mediated first: it avoids collecting and verifying parents' contact
details (a hard problem and a privacy risk of its own) before the feature has
proven its value, and it matches how families already relate to the school.
Whether a school may consent on behalf of parents is a **legal question** (L-2 in doc 11).

## The moderation workflow

```
 Learner taps "Envoyer"
        │
        ▼
 [1] LOCAL SCREEN (inside our API, no outside service)
        ├─ contact details / link ─► refused now, learner told which rule, nothing stored
        └─ otherwise ─► stored as pending_review, flags attached
        │
        ▼
 [2] QUEUE  priority 1 if flagged, 2 if clean; deadline = now + 24 h
        │
        ▼
 [3] MODERATOR claims next item (15-minute lease; never their own content)
        ├─ approve ─► published, author notified, others notified of the new comment
        ├─ reject + reason code ─► author sees the code's fixed text; may fix and resend
        └─ unsure / worrying ─► ESCALATE to safety lead (evidence put on hold)

 Any member taps "Signaler" on something published
        │
        ▼
 [4] REPORT stored with a copy of the text
        ├─ severe category, or 2 different reporters ─► content HIDDEN at once
        └─ queue item priority 0 (severe, 4 h deadline) or 1 (24 h)
        │
        ▼
 [5] MODERATOR reviews the report without seeing who filed it
        ├─ dismiss ─► content restored if it was hidden
        ├─ remove + reason code ─► author notified; consider a sanction
        └─ escalate ─► safety lead
        │
        ▼
 [6] SAFETY LEAD: sanction beyond a moderator's limit · contact school/family ·
     report to an authority · keep or release the evidence hold · close with an outcome
```

### Queue priorities and deadlines

| Priority | What | Deadline (default) | Visible to others meanwhile? |
|---|---|---|---|
| 0 | Report in a severe category (`child_safety`, `sexual_content`, `self_harm`, `violence_threat`); any escalated item | 4 hours | No — hidden at once |
| 1 | Any other report; new content flagged by the local screen | 24 hours | Reported: yes until 2 reporters; new: no |
| 2 | New content with no flag; display names | 24 hours | No |
| 3 | Reserved (bulk re-review after a rule change) | — | — |

Deadlines are stored per item (`due_at`); "overdue" is a number on the queue
overview and the first operating metric to watch.

### Reason codes (the only thing an author is told)

`off_topic` · `unkind_language` · `personal_information` · `not_school_appropriate`
· `spam_or_repeat` · `unclear_please_rewrite` · `impersonation` · `safety_concern`
· `other_see_rules`

Each has one friendly sentence in French and Haitian Creole in the app, with a
link to the rules. Moderators cannot write free text to a learner: it removes
any chance of a moderator's message itself being inappropriate, and makes decisions comparable.

### Reporting

- Available on every post, comment and display name, from the item's menu — two taps.
- Categories are plain words with an icon; a note is optional.
- Works offline: the report is queued on the phone, the content is hidden
  locally at once, and the report is sent at the next connection.
- The reporter gets the same answer whether or not the content was hidden.
- The reported person is never told who reported. Moderators see a pseudonym
  per item; only the safety lead can reveal the identity, and that is audited.
- A learner who reports `self_harm` or `child_safety` is shown, immediately and
  offline, who to talk to (a trusted adult, the school, a local helpline — list to be confirmed, D-11).
- False reporting to silence someone is itself a sanctionable behaviour; the
  metric "reports dismissed per reporter" makes it visible.

### Blocking

- A blocks B → neither sees the other's posts or comments, neither is notified about the other.
- B is not told. B's content is simply absent for A (and A's for B).
- Teachers and staff cannot be blocked — safety notices must get through — but can be reported like anyone.
- Blocking does not replace reporting: the app offers "Signaler aussi ?" after a block.
- In a small class group a block is visible by inference (missing replies).
  Accepted: the alternative, no blocking, fails the stores' requirements and the learner.

### User suspension and other sanctions

| Sanction | Effect | Who | Maximum | Notice |
|---|---|---|---|---|
| Warning | None; recorded; learner sees a notice with the reason code | Moderator | — | In-app |
| Mute | Can read; cannot post, comment or react | Moderator | 7 days (longer: safety lead) | In-app |
| Suspension | No access to the social module (learning is **never** affected) | Moderator ≤ 7 days; safety lead beyond | Must have an end date | In-app + school/adult |
| Ban | No access until lifted | Safety lead only | Until appeal | In-app + school/adult |
| Community-scoped | Any of the above limited to one community | As above | | |

- A sanction takes effect on the next request (checked in the database every time).
- **Learning access is never part of a sanction.** The two modules cannot even see each other's data.
- Suggested ladder for ordinary unkindness: warning → 24-hour mute → 7-day mute →
  suspension with a conversation involving the school. Anything involving
  sexual content, threats or an adult's behaviour skips the ladder and goes to the safety lead.
- Appeal: the learner (or their adult) asks through the school or the published
  contact; a safety lead who did not impose the sanction reviews it. With one
  safety lead in the team, the founder acts as second reviewer (D-14).

### Escalation

| Level | Trigger examples | Owner | Deadline | Actions |
|---|---|---|---|---|
| 1 · Safety lead | Moderator is unsure; repeated behaviour; any adult-to-child concern; any severe category confirmed | Safety lead | 4 h | Decide, sanction, hold evidence |
| 2 · Family / school | Bullying that continues offline; a learner at risk; a suspension | Safety lead | 24 h | Contact the school's named person; record the outcome code |
| 3 · External authority | Suspected sexual exploitation or abuse, credible threat of violence, imminent self-harm | Safety lead + founder | Immediately | Follow the written incident procedure; report to the competent authority; **do not** delete, forward or copy the content outside the system |

What "the competent authority" is — and what Edupreneurs is legally *obliged*
to report, to whom, and within what time — depends on where the company is
established and on Haitian law. This must be answered by counsel before any
learner is enrolled (L-3 in doc 11). The software provides the evidence hold,
the audit trail and the escalation record; it deliberately does not automate reporting.

Every escalation automatically places an **evidence hold**: retention and
deletion skip the held text until the safety lead releases it.

### Audit trail

| Recorded in | What | Can it be changed? |
|---|---|---|
| `moderation_actions` | Every approve, reject, dismiss, restore, remove, auto-hide, name decision, sanction, lift, escalation, erasure — who, when, on what, reason code, digest of the text | No (trigger). Deleted by the retention job after 730 days |
| `audit_events` | Sensitive non-moderation actions and **refused** attempts: join decisions, denied sanctions, erasures, reporter-identity reveals, config changes, enrolment and consent changes | No (trigger) |
| API logs | Request id, route, status, duration, actor id. **Never** request bodies or text | Standard log retention |

The safety lead reviews a weekly sample: 20 random approvals (were they
right?), all removals, all sanctions, all denied staff actions.

## Staffing and operating plan for a small team

The design choice that makes this workable: **the queue is bounded by the
limits, and the limits are settings.** If moderation falls behind, lower the
daily caps or freeze communities — do not let unreviewed content through.

### Capacity arithmetic (assumptions to validate in the pilot)

| Quantity | Pilot | Early growth |
|---|---|---|
| Enrolled learners | 150 (about 4 class groups) | 1 500 (about 40 groups) |
| Submissions per learner per day (posts + comments, average) | 0.5 | 0.5 |
| Items to review per day | ~75 | ~750 |
| Review speed for short text with context | ~120 items/hour | ~120 items/hour |
| Moderator time per day | **~40 minutes** | **~6.3 hours** |
| Largest possible queue at one moment (13 waiting items per learner) | 1 950 | 19 500 |
| Worst case allowed by the caps (5 posts + 30 comments each) | 5 250 | 52 500 — far above capacity |

Reading: the pilot fits two part-time people. At 1 500 learners, central
pre-moderation needs most of a full-time person every day, including weekends —
this is the point at which either teacher-delegated approval (D-04) or a
larger paid team must already be in place. The worst-case row is why the
"waiting for review" cap (3 posts, 10 comments per learner) matters more than
the daily cap: it is the real bound on the queue.

### People (pilot)

| Role | Number | Time | Requirements |
|---|---|---|---|
| Safety lead | 1 named person (the founder or a designate) + 1 backup | On call during open hours; ~3 h/week review | Accountable; child-safeguarding training; knows the incident procedure; reachable |
| Moderator | 2 part-time | 2 review windows a day, ~1 h each, 7 days in rotation | Fluent in Haitian Creole **and** French; trained on the rules and reason codes; background check appropriate to working with minors (L-5); signed code of conduct |
| School contact | 1 per partner school | As needed | Named in the school agreement; the path to families |

Nobody moderates alone for long: two moderators means cover for illness and a
second opinion. Moderator wellbeing matters even with text only — rotate,
debrief after serious cases, and never make one person the only reader of the severe queue.

### Hours and expectations

- **Community open hours** (suggested: 06:00–21:00 Haiti time). Outside them
  `submissions_open` is off: the feed is readable, sending is queued on the
  phone with a clear message. This removes late-night use and overnight queues
  in one move. Automating the switch is a small scheduled job (Social-03).
- **Review windows**: around midday and early evening. Learners are told
  honestly: "Les messages sont relus par notre équipe. Cela peut prendre quelques heures."
- **Targets**: new content — half reviewed within 4 h, all within 24 h. Severe
  reports — hidden instantly by the system, reviewed within 4 h during open hours.
- **If a window is missed**: the safety lead gets an alert when any priority-0
  item is older than 2 h or the queue exceeds one day of capacity; the standing
  instruction is to close submissions rather than rush approvals.

### Tools (kept deliberately small)

| Need | Pilot solution |
|---|---|
| Review console | A minimal web page over the moderation endpoints: one item at a time, context, four buttons, reason-code list. No bulk approve |
| Alerts | An e-mail or message to the safety lead from a scheduled check of the queue overview |
| Weekly numbers | `GET /moderation/metrics` |
| Incident procedure | A two-page written runbook (who to call, what to record, what never to do), rehearsed once before launch |

### Operating metrics (reviewed weekly)

Median and 90th-percentile time to review · overdue items · rejection rate ·
reports per 100 active members · share of reports dismissed · time to review
severe reports · sanctions by kind · repeat offenders · learners who posted
once and never again (a signal that the wait is too long).

## Threat model

Scope: the social module as designed. Format follows `docs/SECURITY.md`.
"Test" refers to ids in [08-test-specification.md](08-test-specification.md).

### Harms to children

| # | Threat | Controls | Residual risk | Test |
|---|---|---|---|---|
| H1 | **Grooming**: an adult, or an adult posing as a learner, builds contact with a child | No public sign-up; enrolment by staff; verified membership; no private messages; no member directory; contact details refused; everything pre-moderated; teachers reportable | A verified adult (teacher) behaving badly *in public view* is slowed, not stopped; offline contact is outside the system | DB-M01…M05, DB-F08, SCR-01…08 |
| H2 | **Moving the conversation elsewhere** ("add me on WhatsApp 3712…") | Hard refusal of phone numbers, links, e-mails, handles, app names flagged; human review | Spelled-out numbers ("trois sept un…"), codes in images (no images) — caught only by the human | SCR-01…08 |
| H3 | **Bullying and exclusion** | Pre-moderation; reports; auto-hide; mutes; blocks; no downvotes; reaction totals only; no member lists | Subtle exclusion, sarcasm, in-jokes; bullying that continues at school | MOD-04…06, DB-F06 |
| H4 | **Sexual or violent content** | Text only; pre-moderation; severe reports hide at once | Text can still be explicit; a tired moderator can approve by mistake → weekly sampling | DB-C03, MOD-04 |
| H5 | **Self-harm disclosure** | Report category with top priority; help text shown at once; escalation level 3 | Slow response outside open hours → help text must not depend on the network | E2E-06 |
| H6 | **Personal information exposure** (address, school, family details, photos) | No photos; profile has no personal fields; display names moderated; screen flags; moderators trained to reject | Free text can always contain it; depends on the reviewer | SCR-01…08 |
| H7 | **Mixing ages** | Grade-band separation enforced by trigger; age band recorded | Grade is not age — an older learner in a younger grade is in that band's groups | DB-M03 |
| H8 | **Compulsive use / late-night use** | Open hours; no realtime; no streaks or counts; slow feedback loop by design | Minimal | — |
| H9 | **Impersonation of a teacher or staff member** | Badges derive from `account_kind`, set only by staff; display names moderated | A learner choosing a name like a teacher's — moderators must reject | MOD-07 |
| H10 | **Shared or borrowed phone**: another person reads or posts as the learner | Per-account local database, cleared social cache on sign-out, content-free notifications | While signed in, the phone holder is the learner. Same as the learning app | MOB-07, MOB-08 |

### Abuse of the system

| # | Threat | Controls | Test |
|---|---|---|---|
| A1 | Flooding the queue to exhaust moderators | Per-day caps; "waiting for review" caps; global and per-community switches | API-R01…R05 |
| A2 | Mass false reports to hide a classmate's posts | One report per person per item; daily report cap; threshold of 2 *distinct* reporters (1 for severe categories — a deliberate choice of safety over availability); dismissal rate per reporter is tracked; sanction | API-S06, MOD-05 |
| A3 | Guessing invite codes | ≥ 40 bits of entropy; stored as digest; 5 attempts/hour including failures; uniform failure; a valid code still only creates a *request* | API-C04, API-C05 |
| A4 | Leaked invite code posted publicly | Expiry; use limit; revocation; teacher approval still needed; grade-band check | API-C06 |
| A5 | Evading the word filter (spacing, look-alike characters, slang) | Unicode normalisation and invisible-character stripping; the filter is only a helper — the human decides | SCR-09…12 |
| A6 | Approve-then-edit | No editing exists; text immutable by trigger; approval tied to the text digest | DB-C02, DB-C04 |
| A7 | Posting queued offline, sent after a suspension | Standing is checked when the server receives it, not when it was written | API-O03 |
| A8 | Banned learner returns with a new account | No public sign-up; accounts provisioned by staff/school | — (process) |
| A9 | Scraping by a member | No directory, no search, page size ≤ 20, per-account request limits; a member can still read what they are allowed to read | PERF-04 |
| A10 | Using reports/blocks to learn who reported or blocked | Reporter and blocker identities are not readable; uniform responses | DB-R07, API-S07 |

### Attacks on the platform

| # | Threat | Controls | Test |
|---|---|---|---|
| P1 | Learner reads another community's content (IDOR) | Row-level security by membership + explicit filters; uniform 404 | DB-R01…R06, API-A03 |
| P2 | Social code reads grades or scores | No grants on `app`, no cross-schema objects, separate pools, import rule | DB-B01…B06, API-B01 |
| P3 | Learning code reads social data | `edu_api` has nothing on `social` | DB-B02 |
| P4 | Client sends another user's id, a status, a count or a "published" flag | No such inputs exist; unknown fields rejected; the database assigns everything | API-A04 |
| P5 | A bug or injection gives SQL as the member role | No table writes; publishing needs a different role; staff tables unreadable | SEC-01 (list of statements that must all fail) |
| P6 | Learner reaches moderation routes | Different pool and role; staff role checked in the database; MFA claim | API-M01…M04 |
| P7 | Malicious or careless moderator | No self-moderation; role limits; append-only actions; no reporter identity; weekly sampling; staff role granted only out of band | DB-A01…A04, MOD-08 |
| P8 | Stored script / markup injection | Plain text only, stored and returned as text; apps render as text, never as HTML or links | MOB-05, API-V03 |
| P9 | Hidden-character tricks (direction overrides, zero-width) | Stripped during normalisation | SCR-10 |
| P10 | Oversized or compressed-bomb bodies | Existing middleware limits apply to the new routes | API-V05 |
| P11 | Replay / double submit / concurrent retries | `client_op_id` uniqueness; per-account serialisation by row lock | API-I01…I05 |
| P12 | Expensive queries as denial of service | Small fixed page sizes; keyset pagination; statement timeout; separate pool so learning is unaffected | PERF-01…03 |
| P13 | Suspended user keeps using a valid token | Standing read from the database on every request | API-A06 |
| P14 | Cursor tampering | Cursor carries no authority; account tag; RLS still applies | API-P04 |
| P15 | Notification leaks content on a lock screen or to a person who lost access | Events hold ids only; content fetched through normal authorisation; push (later) carries no text | DB-N02 |
| P16 | Data exposure through the Supabase Data API | `social` not in exposed schemas; no grants to `anon`/`authenticated`/`service_role` | API-B03 |
| P17 | Erasure used to destroy evidence | Erasure refused under an evidence hold; reports keep a snapshot; action log keeps digests | DB-E03 |
| P18 | Logs leaking children's text | Bodies never logged; validation errors never echo input (existing behaviour) | API-L01 |

### Not solved by this design

1. **A human approves something they should not.** Pre-moderation moves the
   failure from "nobody looked" to "somebody misjudged". Training, sampling and
   the report button are the answer, not more software.
2. **Coded language and context only classmates understand.** A moderator who
   does not know the class will miss it. Teacher involvement helps (D-04).
3. **Harm that continues offline.** The system can flag and escalate; resolving it is the school's and family's work.
4. **Staff misconduct by the only safety lead.** Mitigated by audit and a second person; not eliminated in a very small team.
5. **Legal duties are not yet known** (doc 11). Until they are, the retention
   periods, the escalation targets and the under-13 rule are placeholders.
