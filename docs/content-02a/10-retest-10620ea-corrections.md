# 10. Corrections after the independent retest of `10620ea`

**Status: still DRAFT. Nothing is reviewed, approved, imported or published.** All 12 lesson-language records remain `draft_unreviewed` with no approvals. No lesson text, answer key, manifest entry or review sheet changed in this round: only the validator, the review generator's vocabulary, tests and this note.

The independent report (`docs/reviews/content-02a/FINAL_RETEST_10620EA.md`) and its test file (`tools/content-pilot/tests/test_postqa44_independent.py`, 38 cases) are included **byte-identical** to branch `qa/content-02a-retest-10620ea`.

## Why the previous correction was not enough

Round 9 added a *list of unsupported symbols* to the statement finder. A list of known bad characters is a blacklist: `⋅`, `∙`, fullwidth `＋`, an em dash, or a narrow no-break space were not on it, so each still cut a statement and left a "true" suffix (`2 ⋅ 3 = 3` was counted as the verified `3 = 3`). The fix here is the opposite approach: **decide by Unicode category what may join or border a statement, and accept only what is known to be safe.**

| Finding | Root cause | Correction |
|---|---|---|
| High: a true suffix stands in for a false claim (`2 ⋅ 3 = 3`, `1 234 = 234` with U+202F, `1 ＋ 2 = 2`, `—4 = 4`) | Unknown characters ended a run; only an enumerated few were treated as notation | Every mathematical symbol (Unicode `Sm`) outside the supported set, every non-ASCII digit, superscript or vulgar fraction (`Nd`, `No`, `Nl`), every space other than the ordinary and no-break space (`Zs`), and every dash (`Pd`) touching a number now **joins the run**, so the statement is reported as a whole. Digits are ASCII only. In addition a statement's **neighbours are whitelisted**: only letters, ordinary punctuation, arrows and prose dashes may border it; a zero-width character, a currency or degree sign, or anything else is reported ("the complete statement cannot be isolated"). |
| High: a remainder prefix certifies another value (`reste 0,5`, `rès 1.5`, `rès -1`, `reste`, `reste 0 + 1`) | The remainder pattern accepted the leading digits and ignored what followed; with no match the plain equality was used | Once the keyword `reste` / `rès` follows the equality, the statement **must** carry one complete whole number followed by a legitimate end (nothing, punctuation, or a new word). A decimal, a sign, an expression, a parenthesis or a missing value is reported and the plain equality is never used instead. `12 ÷ 4 = 3, reste 0.` (sentence-final period) still passes. |
| Medium: an unsupported relation disappears from the sheet (`1 ≈ 200`, `1 ＝ 2`) | A run without a *supported* relation was treated as "no claim" | Relation-like symbols (any `Sm` character that is not an operator) are recognised. A lookalike of a supported sign (`＝`, `＜`, fullwidth digits) is an **error**. A genuinely different relation (`≈`, `≡`, `∼` …) is recorded as `unsupported_relation` and **listed on the lesson sheet for manual review**, in both languages, with its location and full sentence. |
| Medium: malformed choice IDs crash export (`id: []`, `id: {}`) | Identifiers were put in a `set` before their type was checked; the cross-language comparison also ran on a file that had failed the contract | Non-string identifiers are a field-level `question_schema` finding; cross-language comparison and semantic verification do not run on a file that failed its contract; and the CLI has a last-resort guard so that any unforeseen exception becomes a controlled exit 2 (`internal_error`) instead of a traceback. Export creates and overwrites nothing. |

Prose parentheses are now understood: `(3 + 4 = 7)` and `(13 ÷ 4 = 3, reste 1)` are read as statements inside a sentence. An unmatched `(2 + 3 = 5` is still malformed and reported.

## Evidence

| Gate | Before (`10620ea`) | After |
|---|---|---|
| `test_postqa44_independent.py` (38 cases, unchanged) | 19 passed, **19 failed** | **38 passed** |
| New `test_postqa_10620ea_corrections.py` | — | **127 passed** |
| Full suite (`--runxfail`) | 574 passed | **739 passed** = 574 + 38 independent + 127 new |
| `validate --forbid-approvals` | 0 / 0 | 0 error(s), 0 warning(s) |
| `manifest --check`, `verify-manifest`, `review-pack --check` | OK | OK, review pack unchanged (9 files) |
| Ruff lint and format | pass | pass |

No earlier test needed to change in this round.

## Known limits (deliberate)

* **Conservative dashes.** Any dash touching a number is treated as a possible minus, so `… 3 + 4 = 7 — puis …` is *reported*, not judged. Rewrite with a comma or parentheses.
* **Not interpreted, listed for a human:** relations next to units, named-unit decompositions, literal formulas, relations without operands on both sides, and now relations written with a sign the tool does not read (`≈` …).
* **Errors, never verified:** `a/b`, decimals, powers, `%`, `√`, any Unicode operator or digit other than the supported `+ − × ÷ = ≠ < > ≤ ≥ ( )` and ASCII digits with no-break-space grouping.
* A French narrow no-break space (U+202F) as a thousands separator is typographically legitimate but **not supported**: the content pipeline uses U+00A0, and anything else is reported rather than guessed.
* Choice texts are still bound to proof records, not truth-scanned (distractors are false by design).
* The whitelist decides what the tool will *read*; it cannot judge pedagogy, vocabulary or Creole quality.

## CI and branch protection

The `content-pilot / verify` job runs the whole suite on every pull request, now including the 38 independent cases. As the independent report notes, `main` is **not protected** and no ruleset exists: making the job a required check is a repository setting the owner must apply.

## Request for independent retest

Codex #1: please rerun the original and preserved suites and the new file against the corrected SHA in the PR description, and try further characters or remainder tails that could still produce a verified count for a false step.
