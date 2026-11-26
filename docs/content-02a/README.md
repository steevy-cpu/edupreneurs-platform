# Content-02A — first curriculum pilot (7AF mathematics, French + Haitian Creole)

**Status: DRAFT. Nothing here is approved.** No teacher and no native speaker has reviewed any of it. 7AF mathematics is a *proposed* pilot, not an owner decision. Nothing is published, seeded, deployed or merged.

## What this delivers

| Deliverable | Where |
|---|---|
| **6 lessons × 2 languages**, 5 multiple-choice questions each (60 question records, 30 per language), v1 contracts | `content/pilots/7af-math/` |
| Pilot descriptor: stable ids, provenance, rights, curriculum references, review status, source register | `content/pilots/7af-math/pilot.json` |
| Per-lesson **mathematical verification data** (every answer and worked example is recomputed) | `lessons/*/verification.json` |
| Validation tool, size estimates, hash-verified preview manifest, review-pack generator + tests | `tools/content-pilot/` |
| Deterministic **preview manifest** (not a production pack format) | `content/pilots/7af-math/manifest.preview.json` |
| **Educator review package** (French guide, one sheet per lesson, answer-key overview, decisions CSV) | `docs/content-02a/review/` |
| Research and design documentation | `docs/content-02a/01…07` |
| Independent QA report and regression suite (included unmodified from PR #34) | `docs/reviews/content-02a/FINAL_QA.md`, `tools/content-pilot/tests/test_independent_qa.py` |

## Documents

1. [Source register](01-source-register.md) — what was verified, what is uncertain, rights
2. [Curriculum alignment](02-curriculum-alignment.md) — coverage matrix and gaps
3. [Unit design](03-unit-design.md) — pedagogy, structure, limits
4. [Rights and provenance](04-rights-and-provenance.md)
5. [Verification evidence](05-verification-evidence.md) — commands run, exact results, sizes
6. [Path toward Content-02B](06-path-to-content-02b.md)
7. [Corrections after independent QA (PR #34)](07-corrections-after-qa.md) — what changed, what was not fixed

## For an educator

Start with [`review/00-guide-de-relecture.md`](review/00-guide-de-relecture.md). No application code needs to be read.

## For an engineer — commands

```bash
tools/content-pilot/run.sh validate --forbid-approvals    # contracts + pilot rules + maths + rights
tools/content-pilot/run.sh sizes                          # size estimates
tools/content-pilot/run.sh manifest --check               # preview manifest is current
tools/content-pilot/run.sh verify-manifest                # every file matches its sha256
tools/content-pilot/run.sh review-pack --check            # review sheets match the content
tools/content-pilot/run.sh --test                         # pytest (good and bad content)
tools/content-pilot/run.sh --build                        # regenerate the JSON from authoring/
```

`run.sh` uses `uv run --no-project` with only `jsonschema` (+ `pytest` for tests): nothing is installed into the repository environment, no database or network is used.

## Scope kept

Only `content/pilots/7af-math/`, `tools/content-pilot/`, `docs/content-02a/` and (QA files, unmodified) `docs/reviews/content-02a/` were added or changed. The mobile app, FastAPI, migrations, seeds, Admin-01 code, the shared stack and Lovable were not touched.
