# 10. Open decisions

Nothing below was decided by Jude-01. Where a decision is missing the code
denies, disables or uses a labelled placeholder.

## Owner decisions

| # | Decision | Why it matters | What the code does until then | Recommendation |
|---|---|---|---|---|
| J-1 | **Provider and model** (OpenRouter or direct; which model; a fallback or none) | Cost, Creole quality, where children's text goes | Mock only; live adapters refused | Choose after a small paid evaluation on reviewed French and Creole questions (Jude-02 step 1). Prefer one model, no fallback, at first. |
| J-2 | **Provider data terms**: retention, training use, region, sub-processors | A child's free text leaves Edupreneurs | No live call possible | Require zero retention and no training use in writing before any call; get counsel's view |
| J-3 | **Consent**: who consents for a minor (guardian, school), wording, versioning, withdrawal | Legal basis; PO-11 | `ConsentGate` denies unless `granted`; unknown ≠ granted | Counsel-approved wording; store version + who + when in the privacy module (#5) |
| J-4 | **Who may use Jude** (all signed-in learners, paying, pilot schools) | Shapes entitlements (#10) | `EntitlementGate` denies everyone | Start with a named pilot group |
| J-5 | **Limits**: answers per learner per day, cost per learner per day and month, global monthly ceiling, concurrency | Cost protection | Placeholders: 20/day, 0.05 USD/day, 0.50 USD/month, 50 USD/month global | Set the global ceiling to an amount you are willing to lose entirely in a bad month |
| J-6 | **Prices** per model and how they are updated | Accounting accuracy | One synthetic price for the mock | Enter the provider's published prices as a new `price_version`; review on every provider price change |
| J-7 | **Retention of usage rows** | Privacy, audit, finance | No purge runs; `purge_older_than` ready | Keep per-learner rows 90 days, keep aggregates |
| J-8 | **Should failures count against the learner?** Today a failed answer costs money on the ledger but not one of the learner's daily questions | Fairness vs abuse | As described | Keep; revisit if abuse appears |
| J-9 | **General knowledge beyond the lesson** on or off | Risk of unreviewed content vs usefulness | On, always labelled; one setting turns it off | Off for the pilot |
| J-10 | **Safeguarding path**: verified local support contacts to show; whether any human is ever alerted; who | Duty of care; Jude currently alerts nobody and says so | Fixed message, no numbers, no alert, nothing stored | Decide with a child-protection professional and counsel; do not add contacts that have not been verified |
| J-11 | **Who can flip the kill switch and change limits**, and how fast | Incident response | Functions exist; no staff route | Two named people; AD-9 console later, a runbook SQL call first |
| J-12 | **Multi-turn conversations** and whether any history is ever stored | PO-11 recommends none | Stateless single turn | Keep stateless through the pilot |
| J-13 | **Controlled assessments**: how a lesson or exam is marked as one | Jude must refuse answers there | Flag exists on the lesson object; every lesson today is practice | Decide with the exams work (Platform-00 §8) |

## Engineering decisions for Jude-02

| # | Question | Options |
|---|---|---|
| E-1 | Cross-language questions | Rank on the sibling-locale revision by shared block keys (needs an editorial rule that keys match across locales) · embeddings · translate the query |
| E-2 | Where privileged tutor functions live | New staff/worker roles from #4 · interim: owner-only SQL runbook |
| E-3 | Sweeper for expired reservations | Worker job (needs the worker) · rely on lazy per-learner expiry at first |
| E-4 | Global counter contention | Leave as is until measured · shard the global counter |
| E-5 | Language check on output | Current marker-word heuristic · a proper language-ID model |
| E-6 | Safety classifier | Provider moderation endpoint · separate small model · both |
| E-7 | Should `tutor.policy` hold the limits, or configuration? | Currently: in-memory store reads settings, PostgreSQL store reads the table. Pick one source of truth when migrating. |
| E-8 | Dedicated HTTP connection pool and circuit breaker for the provider | Add when a live provider exists |

## Blocked dependencies

| Needed | Lives in | Blocks |
|---|---|---|
| Staff boundary, audit writes, worker | #4 (draft) | Staff kill-switch route, sweeper, audit unification |
| Account lifecycle and erasure orchestrator, consent records | #5 (draft) | Real `ConsentGate`; calling `tutor.erase_learner` |
| Entitlements | #10 (draft) | Real `EntitlementGate` |
| Corrected backend integration candidate | #21 (draft) | Rebase target for the migration |
| Content format v2 | #7 (draft) | Formulas, tables, images in context |
| Mobile learning integration | #25 (draft) | Any UI |
| Admin console | Admin-00 merged as design only | AD-9 Jude console, metric M19 |

## Added by the security corrections

Nine further safety, legal and spending decisions (S-1 … S-9) are listed in
[12](12-security-corrections.md#decisions-still-open-safety-and-legal). S-1 — professional and
native-speaker review of the safety phrases and fixed replies — blocks any
student-facing route in code.
