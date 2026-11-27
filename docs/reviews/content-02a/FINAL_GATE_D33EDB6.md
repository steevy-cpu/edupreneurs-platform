# Independent release follow-up for Content-02A

**HOLD #41 at `d33edb6183e102f688a0603cc57ac546ee3687ce`.** This correction fixes all 19 failures from the preceding independent retest. A new case still gets a false worked example counted as verified in both languages. Keep the six lessons as unreviewed drafts.

| Evidence | Independent result |
| --- | --- |
| Pinned correction | GitHub and the read-only T7 checkout agreed. The candidate Actions merge ref `f7f112ba72550c6bbaf37294e31ea87071bde7ce` had zero changed files relative to the head. |
| Previous regressions | The 38-case independent file matches its original Git blob `689a519711a95669d575da81cdbb8a81ef065d32`. **38/38 passed**, including every one of the previous 19 failures. |
| Candidate gate | **739/739 passed** unmasked. This includes the 38 independent cases and 127 new correction cases. Ruff, formatting, strict draft validation, manifest, all nine regenerated review files and 12 empty-approval draft records passed. [Fresh candidate job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45922290696/job/140256192585) |
| Additional boundaries | **7 passed and 7 failed** across 14 additional checks. QA runner total **746 passed, 7 failed**. Ordinary prose colons in French and Creole, exact division and a sentence-final period passed. Standard false division and a fraction-valued remainder were diagnosed. [Independent QA job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45922567871/job/140256442313) |

**High — punctuation between numbers can still turn a false worked step into a verified suffix.** The parser treated the colon in `6 : 3 = 3` as a prose boundary and judged `3 = 3` true. Using the colon for division, six divided by three is two. The same failure occurred for the parenthesized case, decimals with an omitted leading zero (`.5 = 5` and `,5 = 5`) and a quoted thousands group (`1’234 = 234`). In disposable copies, appending the colon example or the period-decimal example in both locales made the generated educator sheet's count rise from **18 to 20** with neither worked step marked for manual review. [Parser](../../../tools/content-pilot/content_pilot/mathcheck.py) · [QA tests](../../../tools/content-pilot/tests/test_independent_d33edb6.py)

**Correction and reproduction.** From `tools/content-pilot` on this QA branch, run `python -m pytest -q --runxfail tests/test_independent_d33edb6.py` with the project's locked dev environment. Distinguish punctuation separating prose from punctuation joining numeric operands or starting a decimal. For an ambiguous mathematical span, either reject it or identify the entire unchecked step in the educator sheet. Preserve the valid control `Calcule : 3 = 3.` and its Creole equivalent. Rerun the full 753-case suite on the next correction.

The pilot tree remains `c9b315bb5cbaf96d70595aaca5e654221c83daf1`. This retest exercised the new SHA only, entirely with synthetic lesson copies on the runner for mutable tests. No student-facing approval, import or publication was performed.
