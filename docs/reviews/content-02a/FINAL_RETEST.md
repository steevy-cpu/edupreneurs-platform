# Content-02A final independent retest

**Hold PR #37 at `cbb045e105e2e81156b8ecb176ae6613e7546c3a`.** All 60 delivered answer keys are mathematically defensible, the two reasoning questions now have one sufficient justification each, and all 74 original independent checks pass unchanged. The validator still accepts two demonstrably false worked equalities and complete French prose under a Haitian Creole filename. These findings affect the tool being merged alongside the drafts. They arose in temporary copies. The committed examples contain the correct calculations. [Reviewed correction](https://github.com/steevy-cpu/edupreneurs-platform/commit/cbb045e105e2e81156b8ecb176ae6613e7546c3a) · [Original independent evidence](https://github.com/steevy-cpu/edupreneurs-platform/pull/34)

## Verification record

GitHub reported the requested initial correction as the head of #37. The independent QA worktree started at that exact commit, whose parent is the reviewed #31 commit `71306c4b31c950183584ab951c8e4f4676374203`. The original QA report and test module match #34 (Git blobs `4da25086c4abf907c14240a4a4087ba2963003eb` and `fe23022a954b98c4fbb4db48caa59843251c61c8`, respectively).

| Gate | Independent result |
|---|---|
| Full content-pilot suite on the candidate | **318 passed**, 145.42 s. Includes the original authoring tests, 74 independent tests, and 99 correction tests. |
| Original independent suite, separate invocation | **74 passed**, 13.18 s. Its 60 question checks pin opaque choice IDs. Displayed letters and wording were checked separately below. |
| Seven new follow-up cases on the same candidate | **1 passed, 6 failed**, 5.26 s. The control restoring a correct example passed. Failures are retained. [Test file](../../../tools/content-pilot/tests/test_final_retest.py) |
| Strict draft validator and artifacts | Zero errors and warnings on the delivered files. Both manifest checks passed and all nine generated review files matched. All 12 lesson/locale states are `draft_unreviewed`. |
| Trusted authoring rebuild | Regenerated six lessons in a disposable archive checkout. The resulting pilot directory matched the pinned directory byte for byte. |
| Static checks | Ruff lint and format checks passed for the candidate tool and for the QA additions. Repository-wide lint and format also passed in the QA checkout. The candidate’s Git diff whitespace check flagged 12 generated Markdown two-space line endings, used as hard breaks. |
| Hosted CI | The candidate's existing CI passed. The counts above are from independent, offline local runs using Python 3.12. [Candidate CI](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45893330538) |

To repeat from the QA branch, use the following commands from the repository root. The first invocation selects just the 318 candidate tests. The second and third run the preserved and new independent cases separately.

```sh
bash tools/content-pilot/run.sh --test --ignore=tests/test_final_retest.py
(cd tools/content-pilot && uv run --no-project --python 3.12 --with jsonschema --with pytest python -m pytest -q tests/test_independent_qa.py)
(cd tools/content-pilot && uv run --no-project --python 3.12 --with jsonschema --with pytest python -m pytest -q tests/test_final_retest.py)
bash tools/content-pilot/run.sh validate --forbid-approvals
bash tools/content-pilot/run.sh manifest --check
bash tools/content-pilot/run.sh verify-manifest
bash tools/content-pilot/run.sh review-pack --check
```

## Mathematics in both learner files

I read each French and Kreyòl prompt, its four choices and feedback, and all 16 paired worked examples. The results below use the displayed positions for Q1–Q5. The answer IDs embedded by the author stayed stable while choices moved.

| Lesson | Displayed keys in FR and HT | Independent solutions in question order | Worked-example check |
|---|---|---|---|
| L1 Place value | C D A B D | 700, 32,506, 6,054 < 6,540, 10,002, hundreds digit 4 | 4,305 decomposes correctly. The comparisons are decided at the thousands and tens places respectively. |
| L2 Addition and subtraction | A C D B C | 834, 357, 770 kg, 135, 280 + 260 = 540 | 348 + 275 = 623 and the reverse subtraction gives 348. Compensation gives 145. Revised warning preserves operand order, identifies the natural-number domain and handles equality. |
| L3 Products and division | D A B C A | 112, 135 chairs, 8, remainder 5, 29 = 4 × 7 + 1 | 6 × 12 = 72. The quotient/remainder pairs for 17 ÷ 5 and 85 ÷ 4 are (3,2) and (21,1). L3 Q5 now gives three distinct incorrect right-hand values, 27, 11 and 28. |
| L4 Powers-of-ten scaling | B D A C B | 3,500, 620, 8,000 m, 2,400 sheets, 48 | Scaling 36 gives 360, 3,600 and 36,000. The exact divisions give 450, 45 and 12. Conversions give 700 cm, 3,000 m and 9 m. |
| L5 Multiples and divisors | C B D A D | 36, {1,2,5,10}, 8 × 3 = 24, two positive divisors of 7, four books per row impossible | 28 is four sevens. The three factor pairs exhaust the positive divisors of 12. The text includes zero among the multiples of 4, excludes a zero divisor and qualifies the self-divisor rule. L5 Q2 and Q5 use correct quotient–remainder identities. |
| L6 Divisibility | A C B D A | 3,215, 351, 4,329, 1,236 divisible by 2/3/4 together, digit sum 9 for 126 | 612 passes 2/3/4/9 and fails 5/10. Of the six tests, 745 passes only 5. The final sharing problem yields 14 notebooks in each of 9 parcels. |

**Assessment quality improved.** In L5 Q3 only D supplies an exact product for 24. Option C's addition is true, but establishing divisibility from it also requires knowing that 32 and 8 are multiples of 8. In L6 Q5 only A supplies a sufficient rule. The number 16 refutes all three alternative criteria at once. Using 126 in place of the opening 135 tests transfer. In L6 Q4 all four statements list three divisors, removing the length cue. Each locale gives **A 8, B 7, C 7, D 8**. Repeating one position now earns at most 8/30, down from 16/30. The shorter factor-pair example in L5 explains when to stop searching.

**Classroom review remains necessary.** In L2 Q5, “le petit nombre” and “ti nonb la” still make size the cue for checking subtraction. Name the quantity subtracted and show how adding it back recovers the starting value. In L2 Q2, show the exchange across zero. L1 still promises six-digit work without a six-digit practice item. L3 can ask pupils to reject an impossible remainder. L4 should carry the unit through each equality and state when dropping written zeros works. L6 should show how the divisibility-by-four rule works on one digit.

For Kreyòl read-aloud review, check L1’s “katrevenn” and “trant-de”, L2’s “ponye sou yon nonb won”, L3’s objective “epi non dividand”, and L6’s “men pa pa 10”. Ask learners to explain the numbers, the intended action or which divisor is excluded. The new L5 reason prompt and L6 counterexample convey the intended distinction in both drafts. Native-speaker terminology, classroom performance and the 320 dp large-text layout still need human review.

## Validator findings and disposition

| Priority | Observation at the pinned commit | Correction and acceptance evidence |
|---|---|---|
| High · false worked equality | L4's first multiplication changed to **36 × 10 = 3600** in both locales passes strict validation with the original proof. The checked text is a substring ending inside the longer answer token. | Match complete mathematical tokens within the actual step and check the full equality. The wrong result must produce a finding and restoring 360 must pass. [Worked-example validation](../../../tools/content-pilot/content_pilot/checks.py) |
| High · exact versus integer division | In an isolated L4 example, **4,501 ÷ 10 = 450** passes when its proof computes the floor quotient. The quotient is 450 with remainder 1, so the displayed equality is false. The proof also could not distinguish exact division from floor division by comparing the operator spelling. | For exact equalities, require a nonzero divisor and zero remainder, or use exact rational arithmetic. Keep Euclidean quotient/remainder identities as a distinct supported form. Pass the non-exact test while preserving the valid L3 examples. [Math checks](../../../tools/content-pilot/content_pilot/checks.py) |
| Medium · wrong-language delivery | Both independent fixtures passed strict validation with zero findings after complete French blocks or questions were copied to the correctly named HT file. Path, key and numeric parity can all hold while a learner receives the wrong language. | Flag complete duplication of prose-bearing content for review, allowing shared mathematical notation. An explicit diagnostic suffices. Human review must still address meaning and fluency. [Locale comparisons](../../../tools/content-pilot/content_pilot/checks.py) |
| Medium · malformed export input | Removing an answer key from the private question copy makes standalone review-pack checking raise an uncaught `KeyError` at `review.py:152`. A reviewer receives a traceback before seeing which question to fix. | Validate the child documents before indexing them for export. Return a controlled nonzero status and a diagnostic naming the missing field and question. [Review export](../../../tools/content-pilot/content_pilot/review.py) |
| Medium · evaluator bound | With a three-bit integer limit, adding 4 and 4 exceeds the bound. The aggregate form returns 8. The terminal result of `sum` does not pass the same bit-length check as binary addition. The test used two small integers. | Apply the integer result limit to aggregate/builtin paths and account for sequence work in the evaluator budget. Preserve the tiny-limit regression. [Evaluator](../../../tools/content-pilot/content_pilot/safe_eval.py) |

**Boundaries that held.** The candidate rejected missing, null, empty and mistyped verification records covered by the suites, reversed subtraction and changed comparison signs, duplicated JSON members, and substitution of a different locale's pathname. Canonical preview checking detected changed labels, duplicated entries and file tampering. Static links inside the pilot, non-regular files, and existing linked output targets were refused in the tested cases. The arithmetic interpreter uses a restricted AST with per-expression limits. The preview is unsigned and the authoring build remains trusted repository Python.

**Remaining filesystem and resource conditions from code inspection.** The input resolver checks ancestors by pathname and subsequently opens by pathname with a final-component no-follow flag. Atomic output replacement protects a single file. A writable ancestor changing concurrently is still outside the proven boundary. The explicit review-output path checks its final directory, leaving linked ancestors unchecked, and review-pack check mode does not perform the default write path's ancestor walk. For a confinement guarantee, bind traversal and output operations to checked directory handles, or enforce an immutable private input tree and a trusted private output root. No filesystem race or external write was exercised. Inventory sorts entire directory listings before testing global limits, checks totals after traversal, and counts regular files only. Enforce traversal budgets during enumeration, including directories and other entries. The aggregate evaluator test above does not measure exhaustion. [Filesystem helpers](../../../tools/content-pilot/content_pilot/safefs.py) · [CLI output paths](../../../tools/content-pilot/content_pilot/cli.py) · [Inventory](../../../tools/content-pilot/content_pilot/checks.py)

## Curriculum, approval and merge decision

The revised source register distinguishes the 2024 publisher-hosted programme's final-version label from its unfinished preamble and unverified adoption. Its grade-7 fraction-of-quantity work continues on printed p. 39, with the explicit fraction addition/subtraction row in grade 8 on printed p. 40. The older 2019 copy places fraction addition/subtraction in 7AF on PDF p. 14. L4 and L5 now correctly describe the 2019 support as contextual. These corrections answer the original citation findings. The reported rollout remains secondary evidence. [2024 programme](https://www.editions-jpl.com/_files/ugd/28b65f_7f7bb36133ec4f28837548f716aa384b.pdf#page=39) · [2019 minimum competencies](https://www.haiti-now.org/wp-content/uploads/2021/02/7eme-AF.pdf#page=14)

**Recommended next decision.** Correct the false-positive mathematics checks, wrong-locale diagnostic, controlled export failure and evaluator limit. Address or explicitly narrow the filesystem and traversal guarantees before accepting contributed trees. Rerun the 318 candidate checks and the seven new cases on the correction SHA. A clean independent retest would support merging the pilot as unreviewed drafts. Student publication still requires per-locale educator and native-speaker decisions and an owner licensing decision. The editable approval records, opt-in strict mode and absence of a required content CI gate remain open from #34. This review grants no publication approval.
