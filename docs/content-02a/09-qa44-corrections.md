# 9. Corrections after independent verification of PR #41 (QA PR #44)

**Status: still DRAFT. Nothing is reviewed or approved.** Every lesson is `draft_unreviewed` in both languages (12 records, no approvals). No lesson text, answer key, approval record, manifest entry or student record changed: only the validator, the review-package generator (its wording and a new "Calculs" section), the CI workflow and tests.

QA #44 (`docs/reviews/content-02a/FINAL_VERIFICATION_41.md`, commit `d4fd9db…`, against `e24168b…`) held #41 on four findings. The QA report and its two test files are included **byte-identical** to the QA branch: `tests/test_independent_verification_41.py` (42 cases) and `tests/test_unit_notation_gate.py` (6 cases, from the same QA branch).

## Root causes

| # | Finding | Root cause |
|---|---|---|
| 1 | `1/2 = 2`, `1,5 = 5`, `3^2 = 2`, `-4 = 4` judged true | The statement finder cut a run at **any** character it did not know. `/`, `^`, `,`, `-` ended the run, so the part after the unknown symbol (`2 = 2`) looked like a complete statement. The parser had no notion of the *boundaries* of a claim. |
| 2 | `12 ÷ 4 = 3, reste 1` judged true | The remainder was consulted **only if the plain equality was false**. `12 ÷ 4 = 3` is true, so the wrong remainder was never examined. |
| 3 | `2 + 2 = 5 +` and a false statement after 400 true ones passed | Operator-edged runs were skipped on shape alone (so a dangling operator vanished), and the statement cap `return`ed silently. Skipped relations were not recorded, so the review guide could still say that every calculation had been checked. |
| 4 | `explanation: null` crashed both export modes | The schema reported the error, but the semantic pass (`_verify_math`) still ran on the same malformed question and read `q["explanation"]["text"]`. A second unguarded read of `response_spec.choices: null` was found by the new tests (it crashed `validate` itself). |

## What changed

**Parser (`mathcheck.py`) — whole claims, not suffixes**

* Runs now include **unsupported mathematical symbols**: `/ ^ * % √ · ² ³ ½…`, a decimal comma or point (`1,5`, `1.5`), an ASCII hyphen or en dash used as a minus (`-4`, `5 - 3`; a list bullet `- item` is not), a letter `x` between numbers (`3 x 4`), and a single letter glued to a number (`2x`, `x2`; unit letters `m g l` are left to the unit rule).
* A run that contains a relation **and** any such symbol is reported (`math_unparsed`, "unsupported notation") and is **never** reduced to a verified suffix. The same rule covers a claim glued to letters.
* A run that begins or ends with an operator while the relation has operands on both sides is reported as incomplete (`2 + 2 = 5 +`, `+ 2 = 5`). A fragment without operands on both sides (`= 1 000`) is skipped and recorded, as before.
* **Euclidean division** is recognised as a whole statement *before* any equality is evaluated: `a ÷ b = q, reste r` (`rès r` in Creole) is true exactly when `a = b × q + r`, the divisor is positive and `0 ≤ r < b`. `a`, `b`, `q` may be parenthesised expressions (`(6 + 7) ÷ (2 + 2) = 3, reste 1`) but must be whole numbers. Any other shape with a remainder (`12 = 3, reste 1`, two divisions, a chained relation) is reported, not judged.
* The statement cap is kept (400 per text) but reaching it with statements remaining is now `math_limit` (an error), and so is a false statement after the cap.

**Coverage that cannot be overstated**

* `analyze()` also returns what was **deliberately not interpreted**, by kind: `unit`, `named_unit`, `fragment`. `statements()` keeps its two-value contract.
* The review guide no longer says "chaque calcul des exemples". It says what is checked (relations written with `+ − × ÷ = ≠ < > ≤ ≥`, in text, prompts and explanations), what is not interpreted, and that **no message means every calculation is correct**.
* Every lesson sheet has a new section "Calculs : ce que l'outil a vérifié et ce qu'il n'a PAS interprété": the exact number of statements verified (both languages) and a list, with the sentence and location, of every relation that was left to a human.

**Export (`checks.py`, `review.py`)**

* Semantic verification is **not run** on content that failed structural validation (`verification_skipped` warning names the first cause), and every read of a question field is type-guarded (`_choice_list`, explanation text).
* `review-pack --check/--write` validates first and exits **2** with `review_input_invalid`, the lesson, question and field; it creates and overwrites nothing (tested with an existing review directory).

**CI (`.github/workflows/content-pilot.yml`)** — see below.

## Evidence

| Gate | Before (`e24168b`) | After |
|---|---|---|
| QA #44 `test_independent_verification_41.py` (42 cases) | 28 passed, **14 failed** | **42 passed** |
| QA #44 `test_unit_notation_gate.py` (4 cases) | 3 passed, **1 failed** | **4 passed** |
| New corrections `test_qa44_corrections.py` | — | **108 passed** |
| Full suite (CI command, `--runxfail`) | 420 passed | **574 passed** = 420 + 46 QA #44 + 108 new |
| `validate --forbid-approvals` | 0 / 0 | 0 error(s), 0 warning(s) |
| `manifest --check`, `verify-manifest`, `review-pack --check` | OK | OK (9 files) |
| `ruff check`, `ruff format --check` | pass | pass |

The 14 originally failing observations are preserved as independent cases (unchanged files); no assertion was edited, skipped or masked, and CI runs with `--runxfail`.

Two tests of my own from #41 (`test_final_validator.py`) asserted the old contract and were updated to the stricter one: an unsupported remainder shape is now *reported* (previously "judged false"), and reaching the statement cap now adds a finding to the problem list. They still assert that such text is never judged true and that the cap holds. No QA assertion was touched.

## Continuous integration

New workflow `content-pilot` (job `verify`), locked dependencies (`uv sync --locked --only-group dev`, Python 3.12), no secrets, no database, no deployment:

1. `ruff check` and `ruff format --check` on `tools/content-pilot`;
2. `validate --forbid-approvals`, `manifest --check`, `verify-manifest`, `review-pack --check`, then regeneration into a temporary directory compared byte for byte with the tracked review package;
3. a check that all 12 lesson-language records are `draft_unreviewed` with no approvals;
4. the **complete** pytest suite (`--runxfail`), including the preserved independent regressions.

Any failing step fails the job. **Runtime:** about 4–5 minutes on a developer laptop; QA measured about 9.5 minutes for the suite on a loaded machine; the job has a 30-minute timeout. There is intentionally no `paths:` filter, so the check always reports and can be required.

**Branch protection must be configured separately.** A workflow file cannot make a check blocking. The repository owner must add the status check **`content-pilot / verify`** as required for `main` (and for the stacked content branches if desired). Until then the job is informative only.

## Mathematical invariants the validator now enforces

* A relation is judged only as a whole, with exact integer/rational arithmetic; operand order, operator meaning and precedence are preserved.
* `÷` is exact division; inexact division is valid only as an explicit Euclidean statement with a positive divisor and `0 ≤ r < b`.
* A claim containing notation the tool cannot read is an **error**, never a "true" fragment.
* The tool never stops silently: the statement cap, unreadable notation and incomplete expressions are findings.

## Known unsupported forms and limitations (intentional)

* **Not read, therefore an error when part of a relation:** fractions written `a/b`, `½`-style characters, decimal comma or point, powers (`^`, `²`), `*`, `%`, `√`, `·`, ASCII `-` and en dash as a minus, `x` as a times sign, letters attached to numbers (`2x`).
* **Not interpreted, listed for a human (never counted as checked):** relations next to physical units (`8 km = 8 m`, `1 m = 100 cm`), decompositions into named units (`3 480 = 3 milliers + 4 centaines`), literal formulas (`Dividende = diviseur × quotient + reste`), and relations without operands on both sides (`3 < 5` quoted with a sign sentence). On the current drafts this is **24 relations** over the six lessons, listed on the lesson sheets.
* **Not scanned for truth:** the text of answer *choices* (distractors are false by design); they are bound to their machine-checked proof records instead.
* A bare number run without a relation (a prompt such as `4 501 ÷ 10`) is only checked for being well formed.
* Operands written with an ordinary space instead of a no-break space (`1 000`) are two numbers and are reported when inside a relation.
* The validator checks arithmetic and structure. It cannot judge pedagogy, vocabulary or Creole quality.

## Still required before any publication

Nothing here changes the publication gate: a qualified mathematics teacher, a native Haitian Creole speaker, curriculum alignment and the owner's licensing decision. Approval records are still editable assertions; no import, publication or approval was performed.

## Request for independent re-test

Codex #1: please re-run, against the corrected SHA recorded in the PR description, (a) the original candidate suite, (b) `test_final_retest.py`, (c) `test_independent_verification_41.py`, (d) `test_unit_notation_gate.py`, (e) `test_qa44_corrections.py`, and attempt further notation that could still yield a "true" suffix or an unreported skip.
