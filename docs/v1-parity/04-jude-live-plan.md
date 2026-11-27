# Jude: from the mock engine to a live, provider-backed tutor

**Status:** plan. **No paid provider was called, no learner data was transmitted, nothing was spent.** Based on PRs #28, #30, #35, #43 and their reports, read on 2026-11-26. None of those PRs is merged.

## Where things stand

| Item | State |
|---|---|
| Engine (#28): lexical retrieval over one lesson, opaque citations, pinned prompt, output validation, budget logic, deterministic safeguarding screen, mock provider | Built, tested on a throwaway app only. No route on `main`, no migration |
| Independent security review (#30) | 13 of 19 added assertions failed: hold #28 |
| Security corrections (#43, J-01…J-09) | Claimed fixed or mitigated; **awaiting independent re-review**. J-02 (bill can exceed the hold) is mitigated, not guaranteed; J-08 (personal details in prompts) and J-09 (safeguarding misclassification) are partial |
| Evaluation harness (#35) | 215 cases, 13 suites, fr + ht. **No real model has been run.** Not rebased onto #43 |
| Retrieval quality (mock study) | Cross-language question 11% → 86% with proposed fixes, **not yet wired in** |
| Prototype's Jude | Gemini 2.5 Flash through Lovable's gateway; a French navigation helper; no grounding, no cost cap, JWT verification off. **Not a base to build on** |
| Approved content to retrieve from | **None** (only a synthetic fixture) |

## Target design

```
lesson / exam screen ──► POST /v1/jude/requests ──► admission ──► retrieval ──► gateway ──► provider
                            (auth, flag,            (consent,      (approved      (caps, timeout,
                             rate limit)             entitlement,   revisions      retry, fallback,
                                                     quota hold)    only, RLS)     kill switch)
                         ◄── GET status ◄── validation (citations, language, leaks) ◄── reply
```

| Requirement | Design | State |
|---|---|---|
| **Approved-content retrieval** | Only approved revisions in a current pack, read as the learner under RLS. Lesson context from the lesson screen; exam context only in review mode, **never during a timed attempt** (J-13) | Built for lessons; exam context to add |
| **Source-grounded explanations** | Model cites opaque ids mapped server-side to lesson, revision, block. An answer with no valid citation is rejected and replaced by "not in this lesson" | Built; F1/F5 gaps open (padded questions, quoted injections) |
| **French / Creole** | Reply in the learner's language; cross-language retrieval through sibling-revision mapping and a glossary (Jude-02A fixes) | Fixes proposed, not wired. **No candidate model documents Creole support**: human rubric required |
| **Age-appropriate safeguards** | Deterministic screen before any model call → fixed fr/ht support message; no model-authored reply to distress. Student route blocked in code until a professional and native-speaker review is recorded (S-1) | Screen built; **review not done**; indirect distress (F4) weak |
| **Consent and third-party boundary** | `ConsentGate` and `EntitlementGate` deny by default. Minimum data to the provider: the question and retrieved passages. No name, email, id, grade history. Free-text redaction before dispatch | Gates are interfaces; real ones depend on #5/#10 and OD-5 |
| **Provider-side cost limits** | Three layers: per-learner daily/monthly budget and global monthly budget in the database (reserve → settle); max output tokens; **a hard spend limit set at the provider account**, since the server cannot guarantee a ceiling (J-02) | Logic built; schema is not a migration; provider limit is an owner action (S-5) |
| **Timeouts and outages** | 20 s request budget, 1–2 attempts, optional fallback model, circuit breaker; on failure the learner sees a plain "Jude est indisponible" state and the lesson remains usable | Gateway built on the mock; breaker and real-provider chaos test missing |
| **Rate limiting and abuse** | Per-token HTTP rate limit, body size limit, concurrency 1 per learner, daily quota; repeated safeguarding or injection hits raise a staff flag | Quota and concurrency built; HTTP limit not built |
| **Privacy-safe logging** | Codes, counts, token totals, latency. **No transcripts, no prompt or reply text** in logs or tables; erasure function per learner | Built by design; retention (J-7) undecided |
| **Safe disable / fallback** | Server flag off by default; staff kill switch re-checked before every provider call; app shows the static hint card when disabled | Built (J-05 fix), pending re-review |
| **Secrets** | Provider key only in the API server environment (`SecretStr`), never in the app, never in logs | Needs a hosted secret store (staging not hosted yet) |

## Path, in order (each step is a small PR or an owner action)

| Step | What | Gate to pass |
|---|---|---|
| 0 | **Owner Gate 0**: provider and model (J-1), written data terms incl. zero retention (J-2), consent for minors (J-3), pilot group (J-4), limits (J-5), safeguarding path and contacts (J-10, S-2) | Decisions recorded |
| 1 | Independent re-review of #43; rebase #35 onto #43; merge #28+#43 behind the off flag | Reviewer sign-off; CI green |
| 2 | Usage schema as a real migration (needs staff roles from #4) | pgTAP: holds, settlement, erasure |
| 3 | Wire the retrieval fixes from Jude-02A; close F1, F5 | Benchmark targets on the mock |
| 4 | Register the router behind the flag; add HTTP rate limit and body limit; consent and entitlement gates backed by #5/#10 | Integration tests: deny-by-default proven |
| 5 | Safeguarding and Creole wording review by a professional and a native speaker | S-1 recorded |
| 6 | **Bounded live evaluation** (see below), **only after explicit authorization** | Acceptance thresholds |
| 7 | Mobile entry points on lesson and exam-review screens (coordinate with the Mobile-03 owner); disabled/outage states in fr and ht | Device test |
| 8 | Staff-only pilot, then a small consented student group, kill switch rehearsed | Owner go |

## Bounded evaluation plan (prepared; not run)

* **Data:** the synthetic Jude-02A benchmark only (7 lessons, 215 cases). **No learner data.**
* **Budget:** provider-account hard limit set by the owner before the first call (suggested ceiling for the whole evaluation: 10 USD); server caps on top; run aborts on the first cap hit.
* **Models:** two or three candidates from the Jude-02A shortlist, one run each, fixed seed and prompt fingerprint.
* **Acceptance (proposed in #35):** ≥ 97% accepted replies; 0 unsupported claims; 0 obeyed injections; hints withheld ≥ 95%; human Creole rubric ≥ 3.0 / 4 by a native speaker; written zero-retention terms.
* **Output:** scores, cost per request, latency distribution, failure taxonomy; blind review packet for the educator.
* **Indicative cost at pilot scale** (Jude-02A estimate, assumed workload, unverified prices): 200 learners × 5 questions/day ≈ 6–82 USD/month.

## Blockers, most severe first

1. Owner Gate 0 is open (provider, terms, minors' consent, safeguarding).
2. Nothing is merged; #43 has no independent re-review.
3. No approved curriculum exists for Jude to retrieve from.
4. Safeguarding and Creole wording unreviewed.
5. Dependencies unmerged: staff roles (#4), consent/erasure (#5), entitlements (#10).
6. No hosted environment to hold the provider secret.
