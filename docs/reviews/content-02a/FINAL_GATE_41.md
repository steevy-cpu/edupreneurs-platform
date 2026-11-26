# Independent Content-02A integration gate

**Hold #41 at `e24168baddc39e88ea622f78ea99aa790ccd7da7`.** The validator and the generated review package still give a reviewer false assurance about learner-visible mathematics. The new CI gate reproduces the failures on a fresh GitHub runner. [Pinned candidate](https://github.com/steevy-cpu/edupreneurs-platform/commit/e24168baddc39e88ea622f78ea99aa790ccd7da7) · [Dedicated CI job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45903887668/job/140195910810)

GitHub confirmed the requested head before testing. The content QA worktree preserves the implementation, pilot and earlier evidence. The dedicated job first ran against QA commit `a3950f4841c69d4b6784570acbae6b1fae1151d8`. The only additions over the candidate were QA documentation, tests and the workflow.

| Test group | Result |
| --- | --- |
| Original #41 suite | **420/420 passed** in a separate local run (318.72 seconds) and on the hosted runner. This includes all 74 unchanged cases from #34 and all seven unchanged cases from #38. Their test blobs are `fe23022a954b98c4fbb4db48caa59843251c61c8` and `1573746c2c526a0785884e62e09c51f8f82f45f8`. |
| Prior independent #44 tests | **28 passed, 14 failed**. False suffix equalities, incorrect Euclidean remainders, silently unexamined claims and uncontrolled malformed-export errors all reproduced. [Original findings and test mapping](FINAL_VERIFICATION_41.md) |
| New unit-notation tests | **3 passed, 1 failed**. The parser avoided verifying unit-stripped magnitudes in all three controls. Review export still presented an unchecked false conversion as checked. [Regression file](../../../tools/content-pilot/tests/test_unit_notation_gate.py) |
| Combined gate | **451 passed, 15 failed** across 466 cases with `--runxfail`. All failures were in independent QA tests. A separate local run of the 127 cases from #34, #38, #44 and the unit file yielded **112 passed, 15 failed**. |
| Draft artifacts and formatting | Strict validation returned zero errors and warnings for the untouched pilot. Both manifest checks, review-package freshness, regeneration and comparison of all nine files, Ruff lint and formatting passed. |

## What blocks integration

**High — false calculations pass as verified.** The parser treats the denominator in `1/2 = 2` as a complete left-hand side. It also accepts `12 ÷ 4 = 3, reste 1` and the Creole form with `rès 1`. Recognize the entire mathematical statement before assigning a result, including a stated remainder on an exactly divisible dividend. Preserve the passing controls for grouping, chained comparisons, signed results, fractional values and division by zero.

**High — worked steps that the parser skips inherit the guide's verification claim.** In a disposable copy, the added worked step `8 km = 8 m` appeared on the lesson sheet, while the educator guide said every example calculation had been checked. Eight kilometres equals 8,000 metres. The tool can leave conversions for a human reviewer if the export identifies the unchecked step and describes the actual coverage. A dangling operator and a false expression after the per-text statement limit also passed strict validation.

**Medium — malformed review export still crashes.** A null Creole question explanation raised an uncaught `AttributeError` in both check and write mode. Return a field-specific validation error before generating files. The previous missing-key regression, whole-file French-to-Creole substitutions, bounded integer arithmetic and disposable symlink checks passed.

## Gate and next decision

Keep the [dedicated workflow](../../../.github/workflows/content-pilot.yml) and independent assertions with the eventual correction. The [general CI job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45903887532/job/140195910373) passed at the same QA commit while the dedicated job failed. The general workflow omits the authoring suite. The new read-only job uses locked dependencies and exercises pilot data, schemas, authoring code and review output on relevant pull requests and pushes to main. It runs the full suite with no database, credentials supplied by the project, or publication step. Its failing status currently reflects the 15 observed test failures.

Require a fresh independent rerun with all 466 cases passing before #41 enters #37. Then integrate #37 into #31 and run both general CI and the dedicated gate on the combined candidate before considering main. The six lessons and 60 French/Creole question instances retain the original pilot tree `c9b315bb5cbaf96d70595aaca5e654221c83daf1`. All 12 lesson–locale records remain `draft_unreviewed` with empty approval lists. Student publication still requires educator, native-speaker and licensing approval.
