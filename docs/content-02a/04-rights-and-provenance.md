# 4. Rights and provenance

| Question | Answer |
|---|---|
| Who wrote the lesson text, examples, exercises, explanations? | Written for this pilot on 2026-11-26 by Claude (Anthropic), working at the direction of the project owner. Marked `authoring: ai_assisted_original`. |
| Was any text copied from a curriculum, textbook, website or prototype? | **No.** The official programmes (S1, S2) were read only to identify topics; nothing was copied. The Lovable prototype was not opened. `derived_from_third_party` is `false` for every lesson and the validator rejects `true`. |
| Is the Creole a translation? | It is an **independent draft** written separately from the French (no translation tool, no script), tied to the French only by identifiers and numbers. `translation: ai_drafted_separately_from_french`. It is **not** native-speaker work. |
| Under which licence may Edupreneurs publish the content? | **Not decided.** `licence_status: unassigned_owner_decision`. AI-assisted authorship and local copyright law make this a question for the owner and counsel; this repository asserts no licence. |
| May we quote the official programmes? | **No** for S1 (all rights reserved) and **unknown** for S2. Only short factual locators are stored. |
| Are any third-party images, fonts, audio or datasets used? | None. |
| Can third-party material be added later? | Only with a rights record: the validator refuses `third_party_material: true` until the model is extended (Content-02B). |
| Who is responsible for the mathematics? | Until a qualified teacher signs, **nobody has certified it**. The tool recomputed every answer and worked example, which proves arithmetic consistency, not pedagogical quality. |

## Review and approval status

Every lesson, in both languages, is `draft_unreviewed` with `required_approvals: [mathematics_teacher, native_speaker]` and an empty `approvals` list. The validator:

* refuses `approved` unless **both** roles have a recorded approval (name, date, reference to the signed sheet);
* refuses any approval at all when run with `--forbid-approvals` (used for this PR’s verification);
* warns when approvals exist but the status is not `approved`.

No statement in this repository says that a person has reviewed the content, because none has.

## AI-assisted content: obligations to carry forward

* Keep `provenance` in `pilot.json` and surface “AI-assisted draft” to reviewers (as Admin-00 requires for AI drafts).
* Reviewer must differ from the author (the author here is the AI; the human reviewers are independent by construction).
* Re-check licensing position with the owner before any publication.
