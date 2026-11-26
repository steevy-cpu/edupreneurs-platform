# 7. Corrections after independent QA (PR #34)

**Status: still DRAFT. Nothing is reviewed or approved.** This round answers the independent QA of PR #31 (`docs/reviews/content-02a/FINAL_QA.md`, 74 new checks, 12 red). It changes content, the validator and the source register. It approves nothing, publishes nothing, imports nothing, and every lesson is still `draft_unreviewed` in both languages.

The QA report and the QA regression suite are included **unmodified** (byte-identical to branch `qa/content-02a-independent`): `docs/reviews/content-02a/FINAL_QA.md` and `tools/content-pilot/tests/test_independent_qa.py`. The QA branch itself was not touched.

## How the QA's 12 red checks were resolved

| QA failure | Cause | Fix |
|---|---|---|
| `null`, `[]` verification file; empty `checks` | A missing or malformed proof record skipped the maths pass | `schemas/verification.schema.json`: the record must be a typed object; at least one question and one example; every example has at least one check; required fields; no unknown fields. Semantic checks run only on a schema-valid record. |
| Comparison sign reversed in HT; subtraction order reversed in HT | Number comparison used *sorted* tokens; signs were never compared | Ordered number sequences and the sequence of arithmetic/comparison signs must be identical in fr and ht for every prompt, choice, explanation and block. The verification record also pins what the learner reads (see below). |
| Both locales may name the same file | Descriptor paths were arbitrary strings | Descriptor file names must be exactly `lessons/NN-slug/{blocks,questions}.{fr,ht}.json` and `verification.json`, by schema pattern **and** by an exact check against position and slug. |
| Manifest locale relabelled; duplicate entry | Only hashes and a digest of the entries were compared | `verify_manifest` rebuilds the canonical manifest from the validated descriptor and compares the **whole document** (order, roles, locales, ids, labels, totals, version, extra keys); duplicates and unlisted files are reported separately. |
| Duplicate JSON member in the descriptor | Last value won silently | Strict loader: duplicate members, NaN/Infinity, a byte-order mark, invalid UTF-8, excessive nesting and over-long integers are all findings (`json_duplicate_member`, `json_invalid`). |
| Absolute and `..` file references (schema) | No pattern on file references | Schema patterns; plus `safefs.check_relative` for every read. |
| `[2] * 2` accepted | Python sequence repetition | The evaluator accepts integers only for arithmetic (no lists, strings, floats or booleans). |

## Other findings fixed

**Validator and tool**

* **Confined file access (`safefs.py`).** One resolver for validation, sizes, manifest and review export: relative POSIX names only, no absolute paths, `..`, backslashes or NUL; every component below the root is checked with `lstat`, symbolic links are refused, only regular files are read (opened `O_NOFOLLOW | O_NONBLOCK`, so a FIFO cannot hang the tool), and bytes are bounded **before** parsing. A directory walk that never follows links reports links, non-regular files and files the descriptor does not name (`file_unsafe`, `unexpected_file`).
* **Safe outputs.** `manifest --write` and `review-pack --write` write through a temporary file and `os.replace`, refuse an existing link or a linked output directory, and derive output names only from a descriptor that passed the schema.
* **Bounded resources.** Limits (`model.Limits`, `safe_eval.EvalLimits`) on file size, total size, file count, JSON depth, expression length, syntax-tree size and depth, total evaluation steps, integer bit length, list length and range size. All are injectable, so tests use tiny limits instead of stress workloads. The size gate still measures the delivered unit; the verification file (not delivered) has its own byte limit.
* **Evaluation is bound to what the learner reads** (`checks.py`). Each question's verification entry now declares `prompt_numbers` (ordered), `prompt_math` where the prompt shows an operation (it must be the computed expression, or a *true* equality), and for every truth-mode choice its `numbers` and `symbols`. A worked-example line must be exactly the checked operation (`7 × 4 = 28` is bound to `7 * 4`, `equals 28`, same operands in the same order). Plain statements must match their proof expression sign for sign.
* **Controlled failures.** The CLI turns every content or file problem into a finding or an `error [code]` message and exit status 2 (never a traceback).
* **Review sheets** label choices by their **displayed** position (A–D), not by id.

**Content**

| QA finding | Change |
|---|---|
| Lesson 2 warning taught "always take the smaller from the larger" | Rewritten in fr and ht: the written order is kept; `275 − 623` has no result among the naturals; equal operands give 0. |
| Lesson 5 assumed positive numbers and ignored 0 | Domain stated: divisors are of positive numbers and are never 0 in the lesson; 0 is a multiple of every number and is set aside; the list of multiples now starts at 0; objectives say "positive". |
| Lesson 5 Q2/Q5 feedback used `10 ÷ 3 = 3` / `18 ÷ 4 = 4, reste 2` | Division identities (`10 = 3 × 3 + 1`, `18 = 4 × 4 + 2`). |
| Lesson 5 Q3 and lesson 6 Q5 were yes/no with two "yes" choices | Both now ask which reason or sentence establishes the result; one choice is a valid justification, the others are wrong reasons, each **machine-proved insufficient** (for example "126 is even" is checked against every even number below 200). |
| Lesson 6 Q5 repeated the opening scenario verbatim | New quantities (126 exercise books, 9 parcels). |
| Lesson 3 Q5: two distractors both equal 11 | Distinct distractors (`29 = 4 × 7` replaces `29 = 4 × 1 + 7`). |
| Lesson 6 Q4: the correct choice was conspicuously longer | Four statements of the same shape and length. |
| Lesson 5 worked example: seven near-identical lines | Five lines using factor pairs; the tip no longer duplicates it. |
| 16 of 30 questions were answered by an always-B learner | Correct answers are spread over positions A–D (8/7/7/8, no run of three). See "Choice ids" below. |

**Sources and alignment (honesty, no adoption claim)**

* The S1 note and register now state the two checked facts together: the PDF calls itself a *définitive* version dated 28 July 2024 (PDF p. 2) **and** its preamble page still holds an unfinished drafting instruction (PDF p. 3). The author re-read PDF pp. 2–3 and 39–42 for this round. No signed ministry adoption record for this exact version was found.
* The 7AF table's third sub-goal continues on printed p. 39 together with the start of the 8e table; the register now says so, and separates 7e fractions (equivalent fractions, fraction of a quantity) from the explicit fraction add/subtract rows listed under 8e. QA's reading of S2 fractions (PDF pp. 13–14) is recorded as **QA-reported, not re-checked** because S2 was not re-read in this round.
* Lesson 1's S2 relation is now *partial*, lessons 4 and 5 are marked *context only* for S2, and the claim that the two documents agree on everything taught is removed.
* Descriptor locators and register text now **paraphrase** objective wording (page and code numbers are kept), which matches the repository's locator-only rule for an all-rights-reserved source. The owner should still review rights.

## Choice ids and displayed order (a decision worth knowing)

The QA suite pins each question's **`correct_choice_id`**, and the contract treats choice ids as opaque. To follow both the QA suite and its recommendation to redistribute answer positions, ids stay stable (`a`–`d`, in authoring order) and only the **displayed order** changed. `question-mcq` scores by id, so scoring is unaffected. The review sheets and the answer-key overview now show the displayed letter. If you would rather have ids that follow the displayed order, the QA pins would be re-derived and re-reviewed.

## Not fixed in this round (left for educator review or a later round)

Deliberately out of scope or judged to need a human:

* QA lesson notes not listed in the correction brief: a six-digit case with internal zeros in lesson 1; the carry rule for more than two addends and the borrowing explanation in lesson 2; naming the *whole-number quotient* and diagnosing an invalid remainder in lesson 3; unit-factor labelling and the integer condition in the lesson 4 feedback; the one-digit case of the rule for 4 in lesson 6; a short mixed set and a "explain your choice" task; and the 320 dp layout check.
* The **Kreyòl review prompts** in the QA report (number names, comparison wording, negative constructions). They remain questions for a native speaker; the Creole stays an AI draft.
* **Approval records** are still author-supplied assertions in an editable descriptor; strict mode (`--forbid-approvals`) is opt-in and there is no CI gate. This must be solved before any publication integration (verified decisions bound to lesson, locale, role and revision digest).
* The authoring modules are trusted repository Python run by `--build`; keep that command out of any data-only validation job for third-party drafts.
* Nothing was tested with learners, on a device or a network.
