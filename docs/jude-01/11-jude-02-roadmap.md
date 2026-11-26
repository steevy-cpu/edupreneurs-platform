# 11. Jude-02 implementation roadmap

Ordered so that each step is small, reviewable and reversible, and so that no
learner is exposed before the step that makes it safe.

## Gate 0 — decisions (no code)

Owner settles J-1 to J-5 and J-10 from [10](10-open-decisions.md). Without them
Jude-02 stops after step 2.

## Steps

| # | Step | Depends on | Done when |
|---|---|---|---|
| 1 | **Offline model evaluation harness.** A script (not a route) that runs a fixed, reviewed set of French and Creole questions, injection attempts and safety probes through the pipeline against a candidate model, with a hard spend cap, and reports: valid-output rate, citation validity, language adherence, level adherence, refusal correctness, cost per answer. | J-1, J-2 authorised for *synthetic* questions only | A written comparison of 2–3 models on real numbers |
| 2 | **Prompt v2** from what step 1 shows, as `jude-tutor.v2` (v1 stays immutable). | 1 | v2 beats v1 on the harness |
| 3 | **Native-speaker and safeguarding review** of every fixed message, the screen's phrase lists and the Creole prompt instruction. | reviewers | Signed-off wording; `TEMPLATES_VERSION` bumped |
| 4 | **Usage schema as a migration.** Follow the checklist in [08](08-database-proposal.md); pgTAP tests; `PostgresUsageStore` becomes the default store. | #4 merged (or interim role decision E-2) | `make test-db` and `tests/tutor_pg` green on the migrated schema |
| 5 | **Real gates.** `ConsentGate` over the consent records; `EntitlementGate` over entitlements; register `tutor.erase_learner` with the erasure orchestrator. | #5, #10 | Integration tests with real records; erasure test deletes tutor rows |
| 6 | **Staff controls.** Kill switch, policy and price changes behind the staff boundary, audited; usage read model for Admin-00 M19. | #4 | A staff member can pause Jude in under a minute; runbook written |
| 7 | **Register the router behind `EDU_TUTOR_ENABLED=false`.** Add to `main.py`, regenerate `openapi.json`, add a dedicated provider HTTP pool, rate limit per token, body limit check. | 4, 5 | Route exists in staging, returns `tutor_disabled` |
| 8 | **Safety classifier** in front of the model (E-6), evaluated in the harness; the deterministic screen stays as the floor. | 1 | Measured recall on the probe set |
| 9 | **Staging with the real provider, synthetic accounts only.** Tiny global ceiling. Chaos checks: provider down, slow, garbage output, kill switch mid-flight. | 7, 8, J-2 | Failure table in [01](01-architecture.md) reproduced against the real provider |
| 10 | **Mobile surface** (owned by the mobile agents): contextual button on lesson and answer screens, the client rules in [07](07-api-proposal.md), offline behaviour. | #25, 7 | Device-verified; Jude failure never blocks a lesson |
| 11 | **Pilot** with a named group, consent recorded, low limits, daily cost and outcome review. | all above, legal review | Owner go/no-go on written results |

## Later, deliberately not in Jude-02

- Cross-language retrieval (E-1) — after step 1 shows how much it matters.
- Learner-state grounding ("what did I get wrong in this lesson").
- Multi-turn threads (J-12), streaming, voice.
- Content format v2 block types.
- Exam tutoring, language-practice chat, translation tool (Platform-00 P2/P3).

## Carried risks

| Risk | Mitigation in place | Still open |
|---|---|---|
| A real model ignores instructions embedded as data | Trust boundary; output validation; canary | Rate unknown until step 1 |
| A child in distress is missed by the screen | Model told to flag; fixed message (unreviewed) | Needs step 3 and step 8 |
| Cost runaway | Worst-case reservation, global ceiling, kill switch, bounded calls | Provider-side spend cap should also be set (belt and braces) |
| Creole quality is poor on the chosen model | Language check on output | Step 1 measures it; may decide the provider |
| Lexical retrieval misses paraphrases | "Not in this lesson" reply instead of a guess | Measured only on synthetic questions |
| Provider keeps or trains on children's text | No live call possible today | J-2 before step 9 |
