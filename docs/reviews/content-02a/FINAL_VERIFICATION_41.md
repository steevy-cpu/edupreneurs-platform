# Content-02A independent verification of PR #41

**Verdict — hold #41.** The correction passes the seven regressions from #38. New independent tests nevertheless show that strict validation can accept a false calculation in either language and that the generated educator package can present it as checked. These failures were reproduced in disposable copies of the pilot.

| Review reference | Exact commit |
| --- | --- |
| [Candidate #41](https://github.com/steevy-cpu/edupreneurs-platform/pull/41), GitHub head checked before testing | `e24168baddc39e88ea622f78ea99aa790ccd7da7` |
| [Parent #37](https://github.com/steevy-cpu/edupreneurs-platform/pull/37) | `cbb045e105e2e81156b8ecb176ae6613e7546c3a` |
| [Independent retest #38](https://github.com/steevy-cpu/edupreneurs-platform/pull/38) | `903b4c26396afa263536979f3df079dd46ec3c22` |

## Findings

| Severity | Reproduction and observed result | Required correction |
| --- | --- | --- |
| High · Partial expressions presented as true | For `1/2 = 2`, the prose parser verified the suffix `2 = 2`. Decimal comma (`1,5 = 5`), exponentiation (`3^2 = 2`) and ASCII minus (`-4 = 4`) also produced true suffixes. Strict draft validation accepted the slash example. Appending it to a worked example in both languages produced all nine review files, including the false step and the guide's claim that each example calculation had been checked. | Keep the boundaries of the whole mathematical claim. Record an unsupported result whenever the parser consumes only part of it. Require explicit coverage for worked calculations before describing them as checked. [Parser](../../../tools/content-pilot/content_pilot/mathcheck.py) · [Export wording](../../../tools/content-pilot/content_pilot/review.py) |
| High · Incorrect remainder accepted in French and Creole | `12 ÷ 4 = 3, reste 1` and `12 ÷ 4 = 3, rès 1` both returned true. The remainder must be zero. Strict draft validation also accepted the French form in a prose field. The parser only checks the remainder when the preceding equality evaluates false. | Recognize the complete division-with-remainder form first. Check the division identity and remainder range, including an exactly divisible dividend. Preserve the passing controls for zero and for a correct nonzero remainder. [Division judgment](../../../tools/content-pilot/content_pilot/mathcheck.py) |
| Medium · Skipped calculations leave no diagnostic | `2 + 2 = 5 +` returned neither a statement nor a problem. A text containing 400 true equalities followed by `1=2` also passed strict validation. Both CLI probes reported zero errors and zero warnings. | Preserve the resource cap and emit a coverage diagnostic when it is reached with claims remaining. Distinguish malformed math from surrounding prose. Carry uncovered worked steps through to the export decision. [Statement limits and run boundaries](../../../tools/content-pilot/content_pilot/mathcheck.py) |
| Medium · Malformed question crashes review export | Set the first Creole question's `explanation` to JSON `null`. Both `review-pack --check` and `--write` raised an uncaught `AttributeError` in `_verify_value` at line 552. The original missing-answer-key case now returns a controlled error. | Stop semantic access to malformed fields after schema validation, or guard their types. Return the localized field path and a controlled failure before writing review output. [Question verification](../../../tools/content-pilot/content_pilot/checks.py) |

## Test evidence

| Gate | Independent result |
| --- | --- |
| Unmodified candidate authoring suite | **420 passed** in 568.57 seconds on the pinned candidate. |
| Seven unchanged #38 cases, rerun separately | **7 passed**. Included in the candidate count. The result-token, non-exact division, duplicate-locale blocks and questions, missing answer key, bounded integer sum and valid control all behaved as expected. Separate temporary copies confirmed that substituting French for Creole produces an error with code `translation_duplicate` for either file type. |
| [Additional QA cases](../../../tools/content-pilot/tests/test_independent_verification_41.py) | **28 passed, 14 failed** across 42 cases. The failures include parser, CLI and exporter observations of the same underlying findings. No expected-failure masking. |
| Arithmetic controls | All seven independent exact-value oracles passed, including grouped thousands, nested parentheses, precedence, signed intermediate results and fractional division. Supported true and false chained relations were distinguished. Zero division, excessively long integers, nesting and token limits produced errors in the tested cases. |
| Confinement | Link and directory fixtures used temporary trees. The additional linked-output-ancestor test rejected both export modes and left its target empty. Source review confirmed descriptor-relative traversal and no-follow opens. The documented trusted-root and filesystem assumptions still apply. |
| Untouched pilot | `validate --forbid-approvals` returned **0 errors, 0 warnings**. Both `manifest --check` and `verify-manifest` passed. `review-pack --check` passed. Regeneration into a new temporary directory matched all nine tracked review files byte for byte. |
| Relevant CI checks | Repository Ruff lint and format checks passed. Mypy passed across 27 source files, OpenAPI was current and 71 API unit tests passed. The candidate's GitHub CI also passed. Its workflow does not invoke the content-pilot suite. [Candidate CI job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45897744963/job/140175737932) |

The pilot tree has the same Git object ID on #37 and #41, `c9b315bb5cbaf96d70595aaca5e654221c83daf1`. This covers all 32 pilot files, including the six lessons and 60 language-specific question instances. Each of the 12 lesson–locale records retains `draft_unreviewed` and an empty approval list. The original #38 test file and retest report were also identical on #38 and #41 (Git blobs `1573746c2c526a0785884e62e09c51f8f82f45f8` and `f8b6023eba28a6eb4364154e883c20affe8b9c93`, respectively).

## Reproduction and next decision

From the QA checkout, run these commands separately. The first selects the original suite. The other two isolate the prior regressions and the new evidence.

```sh
bash tools/content-pilot/run.sh --test --ignore=tests/test_independent_verification_41.py
(cd tools/content-pilot && uv run --no-project --python 3.12 --with jsonschema --with pytest python -m pytest -q tests/test_final_retest.py)
(cd tools/content-pilot && uv run --no-project --python 3.12 --with jsonschema --with pytest python -m pytest -q tests/test_independent_verification_41.py)
```

Keep #41 out of #37 pending correction and an independent rerun at the replacement SHA. Once those gates pass, integrate #41 into #37, then #37 into #31. Run fresh CI and the content tests against the combined branch before considering a draft-content merge to main. Student publication still requires educator, native-speaker and licensing approval.
