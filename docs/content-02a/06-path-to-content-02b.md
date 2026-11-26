# 6. Path toward Content-02B

**Nothing below is started or approved.** Order of work, with the gate that must open first.

| Step | Work | Gate |
|---|---|---|
| 0 | **Owner decisions**: confirm 7AF mathematics as the pilot (or change it); licence for AI-assisted text; who recruits the reviewers | Owner |
| 1 | **Human review** of the six lessons with `docs/content-02a/review/`; record decisions | Qualified mathematics teacher **and** native Creole speaker, independent of the author |
| 2 | **Corrections** applied in `tools/content-pilot/authoring/` (or the JSON), re-run `validate`, regenerate manifest and review pack | Step 1 |
| 3 | **Record approvals** in `pilot.json` (`approvals`, `decision_ref`) — the validator then accepts `approved` | Signed sheets |
| 4 | **Programme questions** answered: is S1 final? 2027-28 calendar for maths? 8e vs 7e for priority of operations/powers? licence to cite official wording? | MENFP / owner |
| 5 | **Extend coverage** to the S1 items left out (fractions, decimals, equivalent fractions, fraction of a quantity): ~6 more lessons, same skeleton, same tool | Steps 1-4 for the style; new teacher review |
| 6 | **Tool extensions**: other grades/subjects (generalise `PILOT_ID`), free-response contract if approved, rights model for third-party material (the JSON schema for `verification.json` now exists) | Content contract decisions |
| 7 | **Delivery integration (separate work, not here)**: map approved lessons to `app.lesson_revisions` / `app.question_revisions` through the existing editorial flow (reviewer ≠ author, sources and rights recorded), with Admin-01’s workflow as the editor UI; pack format and signing per Content-Delivery-00 doc 4 | Backend/editorial milestones; **never** by direct seed or database write |
| 8 | **Learner testing**: a few students on old Android phones offline; measure time and errors; compare with the author’s difficulty estimate | Physical-device access, consent |

## How the pilot maps onto the existing contracts (for step 7)

* `blocks.*.json` is exactly the value of `app.lesson_revisions.blocks`.
* Each item of `questions.*.json` splits into `question_key`, `position` and the four JSON columns of `app.question_revisions` (`prompt`, `response_spec`, `answer_key`, `explanation`).
* Lesson/unit uuids are deterministic (uuid5 of the slug) so re-importing never creates duplicates; the database may of course assign its own ids instead.
* The preview manifest is **not** the pack manifest and must not be served.

## Not to be done in 02B without a decision

Publishing, seeding the shared database, enabling flags, editing the mobile app or API, or describing any lesson as approved.
