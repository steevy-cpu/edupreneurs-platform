# 8. Launch readiness checklist

"Launch" = real learners use the mobile app to study reviewed lessons offline.
Items marked **[paid]** apply only if the launch charges money (decision PO-01).

State today, for each line: ✅ existing and tested on `main` · 🟡 partially
implemented · ⬜ missing · ➖ deliberately deferred (not a launch item).

This checklist extends, and does not replace, "Before any cloud deployment" in
`docs/NEXT_STEPS.md` and the open items in `docs/SECURITY.md`.

## A. Decisions

| | Item | State |
|---|---|---|
| A1 | Free or paid launch decided (PO-01) | ⬜ |
| A2 | First audience and first course decided (PO-02) | ⬜ |
| A3 | Personal data, ages and consent model decided with legal advice (PO-04) | ⬜ |
| A4 | Plan for existing prototype users decided and communicated (PO-03) | ⬜ |
| A5 | Prototype's future decided; private findings reviewed (PO-14) | ⬜ |

## B. Learning core

| | Item | State |
|---|---|---|
| B1 | Sign in; identity only from a verified token | ✅ |
| B2 | Catalogue and lesson fetch show only approved, released content | ✅ |
| B3 | Lessons open and questions can be answered with no network | ✅ |
| B4 | Every answer syncs exactly once; lost responses and retries are safe | ✅ |
| B5 | The server computes every score | ✅ |
| B6 | Two learners on one phone never see each other's data | ✅ |
| B7 | French and Haitian Creole | ✅ (interface and seed lesson) |
| B8 | Learner can choose and change grade and language | ⬜ |
| B9 | Progress snapshot for a new or reinstalled phone | ⬜ |
| B10 | Validated on a **physical** low-memory Android phone on mobile data | ⬜ (emulator and simulator only) |
| B11 | Redesigned screens (Mobile-02) merged and validated | 🟡 in progress on its own branch |

## C. Content

| | Item | State |
|---|---|---|
| C1 | Lessons can contain mathematics, images, lists and tables | ⬜ |
| C2 | Question kinds beyond multiple choice, scored identically on phone and server | 🟡 kinds reserved, one implemented |
| C3 | Staff can author, review and release without editing the database | ⬜ |
| C4 | A different person reviews each lesson; rights recorded for each source | ✅ enforced by the database · ⬜ no tool to do it |
| C5 | Real packs: built by a job, stored, hashed, verified on the phone | 🟡 tables exist, manifests are placeholders |
| C6 | At least one complete course, in both languages, educator-approved | ⬜ |
| C7 | No AI-written text reaches learners without human approval | ✅ enforced by the database |

## D. Accounts, privacy and safety

| | Item | State |
|---|---|---|
| D1 | A defined way to create accounts (invited, school-provisioned or self sign-up) | ⬜ (sign-up disabled; seed accounts only) |
| D2 | Account recovery that works on a slow connection | ⬜ |
| D3 | Consent recorded (who, what version, when) before any learning data is stored | ⬜ |
| D4 | Age band recorded; under-13 rule implemented as decided | ⬜ |
| D5 | Account deletion from the app and from a web page; actually erases | ⬜ (blocked by foreign keys today) |
| D6 | Retention periods set and enforced by a job | ⬜ |
| D7 | Privacy notice and terms in French and Haitian Creole, readable by a teenager | ⬜ |
| D8 | No third-party tracker in the learner app | ✅ (none present) |
| D9 | Personal data limited to what a feature needs | ✅ (grade, language, optional display name) |
| D10 | App-store declarations: data safety, age rating, account deletion path | ⬜ |
| D11 | A named person responsible for privacy and safety requests, with a published contact | ⬜ |

## E. Platform and operations

| | Item | State |
|---|---|---|
| E1 | Edupreneurs-owned staging and production projects (never the prototype's) | ⬜ |
| E2 | Migrations applied by CI; API role provisioned with a managed secret | ⬜ |
| E3 | HTTPS everywhere; asymmetric token keys on the hosted project | ⬜ |
| E4 | Rate limiting in front of the API | ⬜ |
| E5 | Connection pooler verified with transaction-scoped identity | ⬜ |
| E6 | Backups, and one timed restore drill | ⬜ |
| E7 | Structured logs without personal data; error tracking; health checks; alert on sync failure rate | ⬜ |
| E8 | Full test suite passes against staging in an explicit staging mode | ⬜ |
| E9 | Load test of the sync path | ⬜ |
| E10 | Production signing keys for the apps; store listings | ⬜ (test signing only) |
| E11 | Secrets only in the hosting platform's secret store | ✅ locally (no secrets in the repository) |
| E12 | An incident procedure: who is called, how the API or a release is rolled back | ⬜ |

## F. Staff

| | Item | State |
|---|---|---|
| F1 | Staff sign in with a second factor; separate from learner accounts | ⬜ |
| F2 | Roles granted through an audited process (no ids in code) | 🟡 table exists |
| F3 | Every staff action and every access change is written to the audit log | 🟡 table exists, nothing writes |
| F4 | Support can find a learner and see their sync state without seeing more than needed | ⬜ |

## G. Money [paid]

| | Item | State |
|---|---|---|
| G1 | Entitlement model built; only the server grants access | ⬜ |
| G2 | Paid content stays available offline for the agreed period, then locks cleanly | ⬜ |
| G3 | Mobile-money payment end to end, with a clear "pending" state | ⬜ |
| G4 | Provider messages applied exactly once; amount and plan verified on the server | ⬜ |
| G5 | Receipts, expiry reminders, refunds, cancellation | ⬜ |
| G6 | Staff can grant, extend and revoke access, audited | ⬜ |
| G7 | Daily reconciliation against the provider's records | ⬜ |
| G8 | Store rules on digital purchases checked for the chosen payment flow (PO-06) | ⬜ |

## Not required for launch

➖ Jude · ➖ rewards and streaks · ➖ exams (unless PO-02 says otherwise) ·
➖ push notifications · ➖ community · ➖ games · ➖ e-books and templates ·
➖ career orientation · ➖ audio · ➖ existing-user migration tooling ·
➖ analytics dashboards · ➖ website beyond the legally required pages.

## Summary

| Section | ✅ | 🟡 | ⬜ |
|---|---|---|---|
| A Decisions | 0 | 0 | 5 |
| B Learning core | 7 | 1 | 3 |
| C Content | 1 | 3 | 3 |
| D Accounts, privacy, safety | 2 | 0 | 9 |
| E Platform and operations | 1 | 0 | 11 |
| F Staff | 0 | 2 | 2 |
| **Free launch (A–F)** | **11** | **6** | **33** |
| G Money [paid] | 0 | 0 | 8 |

The learning core is the strongest part. The distance to launch is mostly
**content tooling, privacy basics and a real environment** — not features.
