# 8. Final validator corrections (after the PR #38 retest)

**Status: still DRAFT. No lesson content changed.** Every lesson is `draft_unreviewed` in both languages; nothing is approved, imported, published or merged. This round changes only the validation tool (`tools/content-pilot/`), its tests, and this documentation.

Independent retest inputs, included **unchanged** from PR #38 (`qa/content-02a-final-retest` at `903b4c2`): `docs/reviews/content-02a/FINAL_RETEST.md` and `tools/content-pilot/tests/test_final_retest.py`.

## Before / after

| Independent case (PR #38) | PR #37 `cbb045e` | This branch |
|---|---|---|
| `36 × 10 = 3600` accepted | FAILED | passes (rejected as `math_false`) |
| `4 501 ÷ 10 = 450` accepted | FAILED | passes (rejected) |
| French prose copied into `blocks.ht.json` | FAILED | passes (`translation_duplicate`) |
| French prose copied into `questions.ht.json` | FAILED | passes (`translation_duplicate`) |
| missing `answer_key`, review-pack check → `KeyError` | FAILED | passes (controlled exit 2, names lesson, question, field) |
| `sum([4, 4])` under a 3-bit limit returned 8 | FAILED | passes (`UnsafeExpression`) |
| control: restoring `36 × 10 = 360` is valid | passed | passes |

The "before" column was re-run locally against #37 (6 failed, 1 passed), matching the retest report.

## Root causes

1. **False equalities passed** because the validator never read the displayed equality. It checked that a *substring* from an authored `must_appear` string occurred in the step (`36×10=360` is a prefix of `36×10=3600`), and that the authored proof expression evaluated to the authored result. For division the proof used floor division (`//`), so `4501 // 10 = 450` was "true" while the learner read `4 501 ÷ 10 = 450`. The proof and the display were two independently authored strings that nothing compared mathematically.
2. **Wrong-language files passed** because the bilingual checks compared numerals, signs, keys and file names, which a verbatim copy satisfies trivially.
3. **The export crashed** because `build_review_pack` indexed the question files directly and was never routed through the validator.
4. **`sum` escaped the integer bound** because only binary operators checked bit length; the builtins returned whatever Python computed.
5. **Filesystem checks were pathname-based**: ancestors were checked with `lstat`, then the file was reopened by name; the explicit output directory's ancestors were not checked; enumeration sorted a whole directory before applying limits and counted regular files only.

## What changed

* **`mathcheck.py` (new): independent, exact verification of what the learner reads.** It finds every arithmetic statement in the displayed text, parses it (`+ − × ÷`, parentheses, `= ≠ < > ≤ ≥`, chained relations, NBSP-grouped numbers) and decides truth with exact integers and `fractions.Fraction`, never floats. It ignores every proof record.
  Invariants, all tested:
  * numbers are **whole tokens**, never substrings;
  * operand order and operator meaning are preserved (`702 − 345 = 357` true, `345 − 702 = 357` false; `2 + 3 × 4 = 14`);
  * `÷` is **exact** division: `4 501 ÷ 10 = 450` is false;
  * **Euclidean division is a separate, explicit form**: `a ÷ b = q, reste r` (Creole `rès r`) is true only if `a = b × q + r` and `0 ≤ r < b`; it excuses nothing else;
  * division by zero, unbalanced parentheses, trailing or dangling operators, numbers over 18 digits, statements over 80 tokens and more than 400 statements per text are reported (`math_unparsed`), never accepted;
  * every statement in lesson blocks, prompts and explanations must be true; a plain choice must say what its proof says; `prompt_math` equalities must be true and a prompt operation with `÷` must be an exact division.
* **Example checks** now require the shown line as **complete numbers** (steps are joined with a non-digit separator) and, for a displayed exact division, a simple `a // b` shape with remainder 0.
* **Bilingual diagnostic `translation_duplicate`.** Fr/ht text fields whose letters-only words (4 or more) are identical are reported once per file with the count and first fields. Digits, signs, formulas and short labels may be shared. **It only flags suspicious wholesale duplication. It does not and cannot assess translation quality or fluency.**
* **Review export** runs the same `validate` first; an invalid tree raises `review_input_invalid` naming the first problems (code, lesson, file, question, field) and the CLI exits 2 without writing. `--check` and `--write` behave the same.
* **Evaluator**: every builtin enforces the same integer bit bound as the operators (including the *running* total of `sum`), sequence work is charged to the step budget before the aggregate runs, `max/min/gcd` take at most 64 operands, lists and ranges stay bounded.
* **Filesystem** (see threat model): handle-relative, no-follow reads and enumeration; bounded streamed enumeration counting every entry; output directories fail closed on any linked ancestor.

## Filesystem threat model (what is claimed, and what is not)

* The **pilot root and the output directory are trusted operator inputs.** Run the tool on a tree you control and write to a private directory.
* Everything **below** the pilot root is untrusted data. Reads open each component relative to the previous directory handle with no-follow, so a link planted at any level below the root is refused and no name is re-resolved after checking. Enumeration is streamed and bounded by entries, depth and bytes (directories, links and other entries count).
* Explicit output directories **fail closed** if any ancestor is a symbolic link (for example `/tmp` on macOS): the tool asks for the real path. Writes go through a temporary file created and renamed by handle, so an existing link is replaced, never followed.
* **Tested:** links at file, directory, descriptor and output levels; linked ancestors in write and check modes; handle-relative opens; bounded enumeration (entries, depth, bytes); a flood of files or empty directories.
* **Not tested and not claimed:** defence against a concurrent attacker racing the tool, hard links, bind mounts, platforms without `O_NOFOLLOW` or `dir_fd`. The preview manifest remains unsigned and `--build` remains trusted repository Python.

## Known limits of the mathematical check

* Statements next to **units of measure** (`8 km = 8 × 1 000 m`) and **decompositions into named units** (`3 480 = 3 milliers + 4 centaines`) are deliberately **not interpreted**: they are not equalities of numbers. That is a limitation, not a verification.
* Fragments that begin or end with an operator are left alone. Only complete statements are judged.
* Prose such as "plus grand que" is not parsed; only the symbols are.
* The validator still relies on authored proof records for questions and examples. Making the **display itself** generated from one structured representation (so the two cannot differ) was **not** done; the independent text scan is the safeguard instead.

## Still needs people

Mathematics review by a 7AF teacher of every revised item; Haitian Creole fluency, meaning and pedagogy by a native-speaker educator; curriculum alignment; the owner's licence decision; approval records that are verified outside the editable descriptor; a required CI gate for strict mode. **A request to Codex #1: please independently retest this branch** (instructions in the PR).
