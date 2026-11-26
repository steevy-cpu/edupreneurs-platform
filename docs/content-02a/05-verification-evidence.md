# 5. Verification evidence

All commands run from the worktree on the final commit (base `main` @ `6ad3fdb`). Python 3.12 via `uv run --no-project` with only `jsonschema` (and `pytest`, `ruff` where noted).

| Command | Result |
|---|---|
| `tools/content-pilot/run.sh validate --forbid-approvals` | **OK: 0 errors, 0 warnings** |
| `tools/content-pilot/run.sh manifest --check` | up to date |
| `tools/content-pilot/run.sh verify-manifest` | OK: every file matches the preview manifest |
| `tools/content-pilot/run.sh review-pack --check` | OK: review pack is up to date (9 files) |
| `tools/content-pilot/run.sh --test` (original PR #31 commit) | **145 passed** (about 70-90 s; each bad-content test validates a fresh copy) |
| `ruff check .` and `ruff format --check .` at the repository root (the CI commands) | All checks passed; 116 files already formatted |

## Correction round (after independent QA, PR #34) — final results

Run on branch `content/02a-corrections` (stacked on #31 at `71306c4`). Python 3.12 via `uv run --no-project`.

| Command | Result |
|---|---|
| `tools/content-pilot/run.sh --test` (everything) | **318 passed** in 138 s = 145 existing + 74 independent QA (unmodified from PR #34) + 99 new hardening tests |
| independent QA suite alone (`-k independent_qa`) | **74 passed** (the 12 that were red in PR #34 are green) |
| `validate --forbid-approvals` | OK: 0 errors, 0 warnings |
| `manifest --check`, `verify-manifest`, `review-pack --check` | up to date; every file matches; 9 files current |
| `ruff check .` / `ruff format --check .` (repository root) | All checks passed / 121 files formatted (the QA test file is exempted in `tools/content-pilot/ruff.toml` so it stays byte-identical) |
| JSON schema validation | lesson blocks and questions against `packages/contracts`; descriptor against `pilot.schema.json`; verification records against the new `verification.schema.json` (all inside `validate`, and re-checked independently by `test_good_content`) |

Content sizes after the changes: whole pilot 27 686 bytes fr / 25 031 ht (9 085 / 8 416 gzip); largest unit 5 217 bytes (advisory limit 8 KB). Transfer time is arithmetic (about 2.3 s at 32 kbit/s), not measured.

What the new tests cover is mapped in `07-corrections-after-qa.md`. The two sections below describe the **original** 145 tests.

## What the original 145 tests cover

* **Good content (about 17 tests):** validator finds nothing; shape (6 lessons, 2 languages, 5 questions); **independent re-validation with `jsonschema` straight from `packages/contracts`**; exactly one correct choice per question; **all 30 answers recomputed by a second, different evaluator**; every worked example verified; fr/ht share structure, keys and numbers; Creole is not a copy of French; stable uuid5 identities; nothing approved and every draft requires both reviewers; source references honest (partial relations, a not-located source); size budgets; manifest and review pack current and deterministic.
* **Bad content (about 100 cases):** duplicate block/question keys; contract violations (unknown/v2 block type, too long, extra field, bad key, bad tone, empty); missing translation files and blocks; a translation that changes a number or a tone or the answer key; malformed answers (unknown correct id, duplicate ids/texts, single choice, missing explanation, bad id, bad positions, duplicate prompt); too few questions; **wrong answer key, no/duplicate matching choice, choice text disagreeing with its value, explanation not stating the answer, two true choices, wrong worked-example arithmetic, wrong verification, missing verification**; unsafe expressions (`__import__`, `open`, attribute access, huge power, division by zero, syntax error); **18 kinds of bad text** (zero-width, NUL, replacement character, bidi override, BOM, tab, newline, HTML, unclosed tag, entity, Markdown bold/code/link, URL, leading/double space, decomposed accent, blank) in lesson blocks, prompts, choices and explanations; maths symbols not mistaken for markup; **rights** (third-party material, missing/inconsistent licence, derived-from-third-party, unknown or duplicate source, claimed licence on a source, no curriculum reference); unstable ids; approvals (approved without both roles, forbidden approvals, approvals without status, weakened requirements); invalid JSON, missing files, oversized unit; manifest tampering, addition, deletion, corruption, location independence; CLI exit codes.
* **Safe evaluator:** 16 allowed and 18 refused expressions.

## Sizes (delivery-shaped minified UTF-8 JSON, blocks + questions per lesson)

| Lesson | fr bytes | fr gzip | ht bytes | ht gzip |
|---|---|---|---|---|
| 1 lire-ecrire-comparer-entiers | 4 515 | 1 556 | 4 077 | 1 459 |
| 2 additionner-soustraire | 4 628 | 1 606 | 4 289 | 1 472 |
| 3 multiplier-diviser | 4 202 | 1 446 | 3 946 | 1 362 |
| 4 multiplier-diviser-10-100-1000 | 3 984 | 1 285 | 3 738 | 1 181 |
| 5 multiples-diviseurs | 4 567 | 1 464 | 4 079 | 1 348 |
| 6 criteres-de-divisibilite | 5 025 | 1 379 | 4 345 | 1 296 |
| **Whole pilot** | **26 921** | **8 736** | **24 474** | **8 118** |

Transfer time of the gzip total: about 2.2 s (fr) / 2.0 s (ht) at an assumed 32 kbit/s and 0.5 s at 128 kbit/s. These are arithmetic on the byte counts; they ignore latency, TLS and HTTP overhead and were **not measured on a network or a device**. The advisory limit is 8 KB and the hard limit 16 KB per lesson and language; the largest unit is 5 KB.

## What this evidence does **not** show

* It does not show that the content is **pedagogically good**, that the Creole is natural, or that it matches the official programme: only humans can say.
* The mathematical check proves arithmetic consistency of answers and examples; it cannot judge whether a question is clear or fair.
* The tool was not run against real student devices, the API or the database; the lesson JSON was **not imported** anywhere.
* The pilot manifest is **not** the production pack format.
