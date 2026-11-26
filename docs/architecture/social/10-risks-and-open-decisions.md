# 10. Risks, unanswered decisions and recommendations

## Decisions needed from the founder

Each has a recommendation and what it costs. D-01 to D-06 are needed to close
Social-00; the others before the milestone shown.

| Id | Decision | Options | Recommendation | Needed by |
|---|---|---|---|---|
| **D-01** | Is a moderated, text-only classroom noticeboard the right first product — rather than the open social feed of the prototype? | (a) Noticeboard as designed · (b) Open feed with post-moderation · (c) No community for now | **(a).** (b) cannot be made safe for minors with this team. (c) is a legitimate choice: the community is not needed for the offline-learning promise | Social-00 |
| **D-02** | Which ages may take part, and with whose consent? | (a) 16+ only at first · (b) 13+ with school-mediated consent · (c) all grades incl. under 13 | **(b) for the pilot, NS1–NS4 groups first; no under-13 enrolment until counsel answers L-1/L-2.** Note: 7AF nominally starts at 12, so (c) is what "7AF through NS4" literally needs, and it carries the heaviest legal duties | Social-00 (provisional), Social-03 (final) |
| **D-03** | Who moderates in the pilot, and who is the named safety lead? | Founder / a hired part-time person / a partner organisation | Founder as safety lead with one named backup; **two** part-time Creole- and French-fluent moderators. Do not start with one person | Social-00 |
| **D-04** | May a class group's teacher approve their own class's posts (later)? | (a) Never · (b) Yes, first-line, with central sampling | **(b), but only in Social-04** after the pilot shows how teachers use it. It is the only route to scale; it also gives an adult power over what children can say, so it needs vetting and sampling | Social-04 |
| **D-05** | May a parent/guardian read their own child's posts? | (a) No, settings and status only · (b) Yes, read-only | **(a) for now.** (b) helps safety but exposes other children's replies to an adult outside the class; needs legal and school input | Social-04 |
| **D-06** | Any third-party or AI-based moderation? | (a) None — local rules + humans · (b) A vendor, after a privacy and permission review | **(a).** Confirm in writing that no learner text leaves our systems. Revisit only with: a signed data-processing agreement, no training on our data, no retention, disclosure to families, and legal sign-off | Social-00 |
| D-07 | Direct messages between learners — ever? | Never / group-only inside a class / one-to-one with mutual acceptance | **Never one-to-one for minors.** If a need appears, a teacher-present group conversation inside a class group | Before any work on `F001` |
| D-08 | If messaging is ever built, is automated-only screening acceptable? | — | No. This is why it is not in the initial schema | Before `F001` |
| D-09 | Images on posts — ever? | Never / teacher-only / everyone | Teacher-only first, if at all; every image reviewed by a human | Before `F002` |
| D-10 | Where would images be stored and who pays for the data? | Supabase Storage / Cloudflare R2 (already planned for lesson packs) | R2, private bucket, signed URLs | Before `F002` |
| D-11 | Which help resources does the app show for self-harm or abuse? | — | Confirm locally valid contacts with the partner school and a child-protection organisation; must work offline | Social-03 |
| D-12 | Retention periods | Defaults in doc 02 (30 / 90 / 365 / 730 days) | Keep the defaults until counsel advises (L-4) | Social-03 |
| D-13 | What happens to a class group at the end of the school year? | Keep / freeze / archive | Freeze at year end, archive after 90 days, erase text after one more year | Social-03 |
| D-14 | Who reviews appeals when there is one safety lead? | — | The backup named in D-03 | Social-03 |
| D-15 | Display names: free choice (moderated) or set by the school? | (a) Learner chooses, moderator approves · (b) School sets first name + initial | **(b) for class groups** — classmates know each other anyway and it removes a moderation task; (a) for cross-school forums later. The schema supports both | Social-02 |
| D-16 | Community open hours | — | 06:00–21:00 Haiti time; closed overnight | Social-03 |
| D-17 | Should staff need a company device or network for the moderation console? | — | At least a second factor (already required); a dedicated browser profile; no moderation on shared phones | Social-02 |

## Risks

Likelihood and impact are judgements, not measurements.

### Safety and legal

| # | Risk | L | I | Mitigation | Owner |
|---|---|---|---|---|---|
| R-01 | A serious child-safety incident occurs in the community | Low | Very high | Closed verified groups, no private channel, pre-moderation, severe reports hide at once, escalation runbook, tabletop exercise before launch | Safety lead |
| R-02 | Legal duties (consent, reporting, retention) turn out to differ from the assumptions here | Medium | High | Questions L-1 to L-10 sent before Social-01; nothing reaches a learner before answers (P-9); limits and periods are settings, not code | Founder |
| R-03 | Moderators unavailable or overwhelmed; queue grows | High | High | Queue bounded by caps; alerts; standing instruction to close submissions rather than rush; growth gated on staffing | Safety lead |
| R-04 | A moderator approves something harmful | Medium | High | Reason-code training, weekly sampling, report button, two moderators | Safety lead |
| R-05 | Staff misuse of access to children's text | Low | Very high | Vetting, second factor, least privilege, append-only audit, no reporter identity, staff roles only out of band, weekly review of denied actions | Founder |
| R-06 | A verified teacher behaves inappropriately in the group | Low | Very high | Teachers' posts are moderated like everyone's; teachers can be reported and are hidden like anyone; only the safety lead may sanction them; school agreement | Safety lead |
| R-07 | App-store rejection or removal for UGC / child-safety policy reasons | Medium | High | Doc 11 checklist; report, block, filter and contact address built in from the start; correct age-rating answers | Founder |
| R-08 | Families or schools lose trust because of one bad experience | Medium | High | Start small, tell families in writing how it works, publish the rules and the contact, be honest about waiting times | Founder |
| R-09 | Word lists miss Creole slang or flag ordinary words | High | Medium | A Creole-fluent maintainer; the screen only prioritises; false-positive test set (SCR-13) | Moderators |

### Product

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R-10 | Waiting hours for approval makes the community feel dead; learners stop posting | High | Medium | Say so honestly in the app; measure "posted once, never again"; teacher first-line approval (D-04) is the planned answer; accept that this is a noticeboard, not a chat |
| R-11 | The community distracts from learning | Medium | Medium | No fifth tab, no notifications per reaction, open hours, no post text on the home screen |
| R-12 | Scope creep back toward the prototype (DMs, media, follows) under user pressure | High | High | The "future" files exist to make the cost of each explicit; each needs its own decision D-07…D-10 |
| R-13 | The community is built before the core learning product has real users | Medium | High | D-01 option (c) is on the table; Social-01 and -02 expose nothing and can pause at either gate |

### Technical

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R-14 | The proposed SQL has errors (it was parsed, never run) | High | Low | That is the purpose of Social-01; expected problem areas are listed in doc 03 |
| R-15 | Row-level-security helper functions make feed queries slow | Medium | Medium | PERF-01 before any learner; fallback design recorded in doc 07 |
| R-16 | Three pools exceed the managed database's connection limit, or the pooler misbehaves | Medium | Medium | P-3; small pool sizes; moderation pool of 2 |
| R-17 | A grant mistake lets a social role read learning data, or the reverse | Low | Very high | No cross-schema objects at all; tests DB-B01…B06 on every CI run; static check on migration text |
| R-18 | Functions owned by a role that bypasses row-level security contain a bug | Low | High | Same as `docs/SECURITY.md` item 4: empty `search_path`, no dynamic SQL, narrow `EXECUTE`; hardening option is a dedicated owner role |
| R-19 | The global visibility clock becomes a bottleneck | Very low | Low | Hundreds of changes per second available, tens per hour needed; split per community if ever required |
| R-20 | Social work collides with Mobile-02 | Low | Medium | Social-00 to -02 touch no file under `apps/`; Social-03 starts after Mobile-02 is merged |
| R-21 | A removed post stays on an offline phone | Medium | Medium | `updates` tombstones, 7-day cache expiry, cache cleared on suspension and sign-out — but a phone that never reconnects keeps what it has for up to 7 days |
| R-22 | Deadlocks between a report and a moderator decision on the same item | Low | Low | Fixed lock order; one automatic retry on `40P01`; concurrency tests |
| R-23 | Retention erases something later needed as evidence | Low | High | Escalation places a hold automatically; holds are checked by the retention job (DB-T02); periods are generous by default |
| R-24 | No hosted environment, backups or monitoring exist yet | Certain | High for Social-03 | P-1, P-7; not a blocker for Social-01 |

## Known limitations of this design

1. **Human judgement is the main control.** The design makes sure a human looks; it cannot make them right.
2. **Grade is not age.** Communities are separated by grade band; an older learner in a lower grade is in that band's groups.
3. **A block is noticeable in a small class.** Missing replies give it away.
4. **A single severe-category report hides content.** A learner can use this to silence a classmate for a few hours; it is traceable and sanctionable. Chosen deliberately: safety over availability.
5. **No search, no directory, no cross-community discovery.** Finding an old post means scrolling. Acceptable for class-sized groups.
6. **Impersonation of a learner is possible with arbitrary SQL on the member connection** (same residual risk as the learning API). It cannot publish anything.
7. **Erasing a teacher or staff account leaves references** in `verified_by` / `created_by` that must be reassigned by hand.
8. **Fixed-window limits** allow a short double burst at the window boundary.
9. **Counters are maintained by functions, not recomputed.** A bug could let them drift; a consistency test and a repair query are specified.
10. **Nothing here has run.** Every performance number and byte budget is an estimate.

## Architecture recommendations

In priority order.

1. **Decide D-01 honestly before spending more.** The strongest alternative to
   this design is not a different architecture; it is *not building a community
   yet*. The learning product does not depend on it, and a community for minors
   is an operational commitment — people on a rota, every day — more than a software feature.
2. **If yes: adopt the noticeboard model and treat pre-moderation as a
   non-negotiable invariant.** Keep it in the database trigger, keep the single
   allowed `moderation_mode`, and require a reviewed migration to change either.
3. **Keep the boundary absolute.** No bridge function "just for the grade", no
   shared role "just for one report". The moment one exists, the claim "social
   cannot read academic data" stops being provable.
4. **Send the legal questions now** (doc 11). They have the longest lead time
   and they decide the age range, the consent model and the retention periods.
5. **Proceed to Social-01 only** (database, local, no learner impact) while the
   decisions and legal answers arrive. It is cheap, reversible, and turns this
   paper design into tested fact — or shows where it is wrong.
6. **Fix the shared prerequisites as their own work**, not inside the social
   milestones: rate limiting, staff authentication with a second factor, the
   pooler test, account deletion, backups. They are needed by the learning
   product regardless.
7. **Staff before you scale.** Never enrol more learners than the moderation
   arithmetic in doc 06 supports. Make that a written rule, with the kill
   switch as the response when it is broken.
8. **Start with teacher-led class groups in one school.** Known people, an
   accountable adult in the room, a school relationship for consent and for
   incidents. Cross-school forums are a different risk level and come later.
9. **Do not build messaging or media on momentum.** Each is a separate decision
   with a separate safety case; the recommendation today is no one-to-one
   messaging for minors at all.
10. **Measure the pilot against numbers agreed in advance**, including a number
    that says "stop".
