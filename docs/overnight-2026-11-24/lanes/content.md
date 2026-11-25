# Lane CONTENT — content format v2, assets, pack manifests

Branch `overnight/content-format-v2` · schema `content` · migrations `2026112403xxxx_*` ·
pgTAP `140–159_*`. Local, synthetic, not merged, not deployed.

**Nothing in this lane changes what learners are served today.** `/v1/catalog`,
`/v1/lessons/{id}`, `app.sync_apply_operation`, schema `app`, the four verified
migrations, `seed.sql`, the format-1 schema files and the existing tests are
untouched.

Decision status: what format 2 must contain, and how mathematics is drawn on old
phones, is **PO-08 — `BLOCKED_BY_OWNER`**. This lane builds Platform-00's
recommended minimum (mathematics, images, lists, tables) plus an optional audio
reference, as contracts, validators and test vectors. Every number below
(byte budgets, sizes, table width) is a synthetic default awaiting that decision.

## 1. What exists

| Piece | Where | Kind |
|---|---|---|
| Format-2 lesson body schema | `packages/contracts/content/lesson-blocks.v2.schema.json` | contract |
| Question schemas `true_false`, `numeric`, `short_text` | `packages/contracts/content/question-*.schema.json` | contract |
| Rules that JSON Schema cannot express, and the vector layout | `packages/contracts/content/README.md` | contract (normative text) |
| Shared test vectors | `packages/contracts/content/vectors/*.json` | contract |
| Plain-Python validators, reference scoring, negotiation | `services/api/src/edu_api/content/` | code, standard library only |
| Unit tests running every vector against both the JSON Schemas and the Python code | `tests/unit/test_content_v2_vectors.py` | test |

The validators are written in plain Python on purpose: `jsonschema` is a
development-only dependency, so nothing that could run in production or in the
pack builder imports it. The unit tests use `jsonschema` to prove that the
published schema files and the Python validators give the same verdict on every
vector and on 8 000 randomly damaged documents.

## 2. The format version and the negotiation rule

**Field.** The content format is a small integer, `content_format`: `1` or `2`.
It is carried by every pack manifest, by every lesson object inside a pack, and
recorded per release in `content.pack_manifests`. A lesson body itself stays a
bare JSON array (`app.lesson_revisions.blocks` must be an array), so the format
of a revision is *derived*, never trusted from the author:

> **Required format of a lesson revision** = the smallest format whose contract
> accepts all its blocks and all its question kinds. Format 1: blocks `heading`,
> `paragraph`, `example`, `callout`; question kind `mcq`. Anything else
> (`math`, `image`, `list`, `table`, `audio`; `true_false`, `numeric`,
> `short_text`) makes it 2.
> (`edu_api.content.formats.required_format`, `content.revision_required_format`.)

**The rule.**

1. **A pack release declares exactly one `content_format`**, and contains only
   revisions whose required format is not higher. *Therefore a format-1 pack
   never contains a format-2 block or question.* A format-2 pack may contain
   format-1 lessons (every format-1 block is valid format 2, unchanged).
2. **A client declares the formats it can render** in the request header
   `Edu-Content-Formats`: a comma-separated list of positive integers, for
   example `Edu-Content-Formats: 1,2`. Blanks around commas are ignored. A
   missing, empty or malformed header (anything that is not 1 to 8 entries of
   `[1-9][0-9]{0,2}`) means `{1}` — every build shipped so far sends no header,
   and failing towards the oldest format is the safe direction.
3. **The server offers the highest format that the client declared, that exists
   for that pack and that the server itself knows** (`negotiate`). An app that
   only knows format 1 receives the format-1 release. If only a format-2 release
   exists, the content is **absent** for that app (not listed, `404` on direct
   access) — it never receives a format-2 body.
4. **No conversion on the fly.** A format-2 lesson is never stripped down to
   format 1 for an old app. Reviewers approved the lesson as a whole; removing a
   formula or a table silently changes what was approved. A lesson that must
   reach old apps needs its own reviewed format-1 revision in a format-1 pack.
5. **Format 1 stays readable forever by newer apps.** A build that declares
   `1,2` must still open format-1 packs; `1` is only dropped from the header by
   a build that genuinely cannot render it (none is planned).

Vectors: `packages/contracts/content/vectors/negotiation.json` (39 cases).

**What enforces it today, honestly.**

| Part of the rule | Enforced by | Status |
|---|---|---|
| Required format of a revision | Python `required_format`; SQL `content.revision_required_format` | tested |
| A pack never contains content above its declared format | the pack builder refuses to build; `content.record_release_manifest` refuses to record the manifest, so the release cannot become `ready` through the staff path | tested |
| Header parsing and choice of format | pure functions `parse_client_formats`, `negotiate` | tested, **not wired into any endpoint** |
| `/v1/catalog` and `/v1/lessons/{id}` never send format 2 | **not enforced.** These endpoints are unchanged and do not read the header; they serve whatever is in a *current* pack. They are format-1 endpoints by definition | gap, see §6 |

Until a format-aware delivery endpoint exists, **no format-2 release may be made
current** (`app.pack_current`). The database cannot refuse that without a
trigger on an `app` table, which this mission forbids; the helper
`content.release_required_format(release_id)` exists so that the future
activation function (staff lane) or a reviewed `app` migration can.

## 3. Question kinds and scoring

`true-false-v1`, `numeric-v1` and `short-text-v1` are specified in
`packages/contracts/content/README.md`, implemented as pure reference functions
in `edu_api/content/scoring.py`, and pinned by 96 `(question, response) →
expected result` vectors. Scores are the integers 0 and 1; numeric comparison is
exact rational arithmetic with an inclusive tolerance; text normalisation is
spelled out code point by code point.

**They are not wired into `app.sync_apply_operation`.** That function is a
verified module and is untouched: the server still rejects every kind other than
`mcq` with `unsupported_question_kind`. Two further facts a future migration must
handle: `app.question_revisions.kind` accepts `numeric` and `short_text` but
**not `true_false`**, and the sync payload schema only models `choice_id`.
