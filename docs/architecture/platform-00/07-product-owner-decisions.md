# 7. Decisions needed from the product owners

Engineering cannot make these. Each has options, a recommendation, and what it
unblocks. "Needed by" is the roadmap milestone (doc 06) that cannot be designed
properly without it. The cost of *not* deciding is in doc 09.

## Decide first (they shape everything)

| Id | Decision | Options | Recommendation | Needed by |
|---|---|---|---|---|
| **PO-01** | **Is the first v2 launch free or paid?** | (a) Free pilot, payments later · (b) Paid from day one · (c) Free core, paid extras (exams, Jude) | **(a) or (c).** The prototype itself is running in free-access mode today, and it never enforced payment on the server, so there is no proven paid model to port. A free pilot removes the largest block of work from the launch path while the entitlement *model* is still designed now | Platform-06; launch scope |
| **PO-02** | **Who is the first audience?** | (a) One lower-secondary grade, mathematics · (b) Exam candidates (9th year, final year) · (c) All grades at once | **(a)**, with (b) as the second release. One complete, reviewed course beats thin coverage. If (b) is first, exams move ahead of rewards and notifications in the roadmap | Content-02; Platform-11 |
| **PO-03** | **What happens to existing prototype users?** | (a) Nothing; v2 is new · (b) Invitation to create a v2 account, remaining paid time honoured · (c) Automatic account migration | **(b).** Do not move accounts or data automatically (doc 05, last section). Decide also what users are told and when | Platform-01; communications |
| **PO-04** | **What personal data does v2 hold, and on whose consent?** Which ages may use it; who consents for minors (parent, school); is an age band recorded | (a) Grade and language only, age band, consent via school or guardian · (b) Fuller profile as in the prototype (name, birth date, school, phone, gender) | **(a).** Needs legal advice — the same questions Social-00 lists (its doc 11). Commission **one** legal brief covering both | Platform-01; launch |
| **PO-14** | **What is the prototype's future?** | (a) Keep running unchanged until v2 replaces it · (b) Keep running, fix the weaknesses found · (c) Freeze sign-ups / switch off risky features now · (d) Retire on a date | Owners' call. Input from this audit: the weaknesses given privately concern accounts, personal data of minors, open messaging and unmetered AI spend. **At minimum, review that private list promptly and decide (b) or (c) for the items on it** | Independent of v2; urgent |

## Decide before the milestone named

| Id | Decision | Options | Recommendation | Needed by |
|---|---|---|---|---|
| **PO-05** | **What does paying unlock?** (entitlement scope) | Everything · a grade · a course · features (exams, Jude) | Model `scope` from the start; sell **everything** at first. Leaves room for per-grade pricing and school licences without a redesign | Platform-06 |
| **PO-06** | **How do learners pay from the mobile app?** App stores have rules about selling digital content inside apps, with exceptions that differ by country and change over time | (a) Pay on the website only; the app shows status · (b) Store in-app purchase · (c) Both | Get advice before designing checkout. Mobile money is essential in Haiti and is not a store payment method, which points to **(a)** — but whether the app may *link* to it must be checked for each store | Platform-07 |
| **PO-07** | **How long does paid access last with no connection?** | 7 / 30 / 90 days after the last sync | **30 days.** Long enough for a learner with rare connectivity; short enough that an expired or refunded subscription stops | Platform-06 |
| **PO-08** | **What must lessons be able to contain in format v2?** | Minimum: mathematics, images, lists, tables · plus audio · plus video links · plus interactive widgets | Minimum + audio reference. Decide how mathematics is drawn on old phones (pre-rendered in the pack vs. a renderer in the app) after a measurement on the reference device | Platform-04 |
| **PO-09** | **Rewards rules.** What earns points; what a "day" is for streaks; how offline work synced days later counts; whether practice can be repeated for points | — | Points only for first correct answers and completions accepted by the server; day = Haiti local date; offline work counts on the day the *server* accepts it unless a bounded back-dating rule is agreed (e.g. up to 3 days). No points for exam scores | Platform-08 |
| **PO-10** | **Notification policy.** Which messages, at what hours, to whom; marketing versus service | — | Service messages only at first; quiet hours 21:00–06:00 Haiti time; content-free pushes; marketing needs separate consent | Platform-10 |
| **PO-11** | **Jude.** Scope (lesson help only, or open chat); provider; whether conversations are stored; who may use it; cost ceiling per learner and overall | — | Lesson- and question-scoped help only; no stored conversations; signed-in, entitled learners; a hard monthly ceiling; consent wording approved by counsel | Platform-13 |
| **PO-12** | **Games.** Any real-time play, or only solo and asynchronous? Chess at all? | — | Solo rounds and class challenges; no real-time, no stranger matching. Chess only as an on-device opponent, if at all | Platform-14 |
| **PO-13** | **Schools.** Will schools enrol classes and pay for them? | Not now · likely within a year · core to the model | If likely: say so now. It affects account creation (PO-03/04), entitlements (school licence source) and Social-00's class groups, and is cheap to allow for early and expensive to add late | Platform-01, -06 |
| **PO-15** | **Content conversion.** Which prototype lessons are worth converting; who reviews; in what order | — | Start with the pilot course. Treat prototype text as a *draft* for a human author, never as approved content. Budget reviewer time explicitly — it is the real bottleneck | Content-02 |
| **PO-16** | **AI in the content pipeline.** May AI draft lessons and questions for human review? Which provider? What monthly budget? | — | Yes for drafts, never for publication (already enforced by the database). Set a budget before the first job runs | Platform-03 onward |
| **PO-17** | **Exam papers.** Does Edupreneurs have the right to reproduce official exam papers and their PDFs? | — | Confirm in writing before any exam content is released. If not, original practice papers "in the style of" are an alternative | Platform-11 |
| **PO-18** | **Books and other third-party material.** Rights status of every title in the prototype's library | — | Do not carry over a title without recorded rights | Platform-12 |
| **PO-19** | **Website and staff portal.** Who builds and hosts them; are they part of this repository | — | Staff portal in this repository (it shares the contract); marketing site can live elsewhere | Content-01 |
| **PO-20** | **Analytics.** Which product questions matter, and may any third-party tracker run in an app used by minors | — | Server-side aggregates from learning events; no third-party trackers in the learner app | Platform-08 onward |

## Decisions already made (recorded so they are not reopened by accident)

| Decision | Where recorded |
|---|---|
| One FastAPI service, one PostgreSQL database, private schemas | Blueprint ADR-001; `docs/ARCHITECTURE.md` |
| The prototype is a proof of concept, not the source of truth; start from a fresh database | Blueprint ADR-008 |
| The device is never trusted for identity, scores or time | `docs/ARCHITECTURE.md`, `docs/SECURITY.md` |
| Approved content is immutable; reviewer ≠ author; rights-cleared sources | `supabase/tests/040_integrity_guards.sql` |
| No hard dependency on AI, presence, payments or notifications for lessons and practice | Blueprint ADR-009 |
| Four tabs: Accueil · Apprendre · Réviser · Profil | `docs/design/`, Mobile-02 |
| Community is a pre-moderated noticeboard, if built (pending its own review) | Social-00, draft PR #1 |
| Jude and generation agents: read-only tools; drafts only | `docs/NEXT_STEPS.md` |

## Suggested order for a decision meeting

1. PO-14 (prototype's future) — it concerns live users.
2. PO-01, PO-02 (free or paid; first audience) — together they define "launch".
3. PO-04 (data and consent) — commission the legal brief.
4. PO-03, PO-13 (existing users; schools).
5. PO-05 to PO-08 — can be delegated with the recommendations above as defaults.
6. The rest when their milestone approaches.
