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

## 4. Assets and the rights gate (schema `content`)

Migration `20261124030100_content_assets_and_pack_manifests.sql` (after staff B1,
`20261124010000`). Nothing is created in `app`; no foreign key points at the five
learning tables (R-02); every function pins `search_path = pg_catalog, pg_temp` (R-03).

| Table | Holds |
|---|---|
| `content.assets` | one row per file: `sha256` (identity, primary key), derived `object_key`, `bytes`, `mime` (allow-list webp/png/jpeg/mp4/mpeg), intrinsic size or duration, `alt_text` per locale, `source_id` → `app.content_sources`, `created_by` |
| `content.revision_assets` | which lesson revision uses which asset (FK to `app.lesson_revisions`), with the asset's `source_id` |
| `content.pack_manifests` | the real manifest of a release: hash, sizes, counts, `content_format`, who recorded it; append-only |

Private: RLS on, **no policy**, no table grant to anyone. `edu_api`, `edu_worker`,
`anon`, `authenticated`, `authenticator`, `service_role` cannot use the schema.
`edu_staff` has `USAGE` and `EXECUTE` on four functions only. No learner read or
write path exists; no per-learner row is stored, so there is no `erase_learner` hook.

**Rights gate without touching `app`.** `revision_assets` has two composite foreign
keys: `(asset_sha256, source_id)` → `content.assets` and `(lesson_revision_id,
source_id)` → `app.lesson_revision_sources`. An asset can therefore only be attached
to a revision that *cites the asset's own source*, and that citation cannot be
removed while the asset is attached. The existing guards in `app` then apply
unchanged: approval requires every cited source to be rights-cleared; a pack cannot
be finalized while one is not. Attachments freeze at the first editorial review
(trigger), so nothing can be attached to a reviewed or approved revision.
Tested in `141_content_integrity.sql`, including the invariant "no approved
revision is linked to an asset whose source is not cleared".

## 5. Staff write path

`SECURITY DEFINER`, owner `postgres`, actor from `staff.require_role` (never a
parameter), each successful write audited through `ops.audit_write` in the same
transaction (ids, hashes, enum codes and numbers only — never alt text).

| Function | Roles | Does |
|---|---|---|
| `content.register_asset(sha256, bytes, mime, width, height, duration_ms, alt_text, source_id)` | editor, admin | records metadata; idempotent for identical metadata, `23505` otherwise |
| `content.attach_asset(revision_id, sha256)` / `content.detach_asset(...)` | editor, admin | drafts only; `23503` if the revision does not cite the asset's source |
| `content.record_release_manifest(release_id, manifest, manifest_sha256, manifest_bytes)` | publisher, admin | checks the manifest against the database (pack identity, ordered lessons, referenced assets attached, asset sizes/types, totals, **declared format ≥ required format**), then moves the release `building → ready` with the real hash and inserts the `pack_manifests` row |

The two functions `content.staff_gate` and `content.audit` are the only places
that mention `staff.*` / `ops.*`. **No HTTP route was added** (R-01 not needed;
`openapi.json` unchanged): the role matrix is tested at SQL level as `edu_staff`
in `142_content_staff_functions.sql`. There is no upload endpoint and no file
ever leaves this machine.

What the database cannot check: it cannot read object storage, so it does not
re-hash lesson objects. The recorded hash is trusted from the publisher; the
verifier (`verify_pack`) is what compares stored bytes with it.

## 6. Canonical manifest and pack builder

Specification: module docstrings of `edu_api/content/pack.py` and `canonical.py`;
schemas `pack-manifest.v1.schema.json`, `pack-lesson.v1.schema.json`.

- Canonical JSON `edu-canon-json-1`: NFC, sorted ASCII keys, integers only, no
  whitespace, UTF-8 — what `JSON.stringify` gives for sorted keys.
- Objects: `packs/<pack_key>/<locale>/<revision>/manifest.json`,
  `lessons/sha256/<aa>/<sha256>.json`, `assets/sha256/<aa>/<sha256>`
  (content-addressed: shared lessons and pictures are stored and downloaded once).
- No timestamp or random value: identical input → identical bytes. Golden vector
  `vectors/pack-manifest.json` (hash also pinned in the test); 25 shuffled
  re-builds and a separate Python process with another hash seed give the same bytes.
- `scripts/build_pack.py build | build-file | verify` — local directory only,
  read-only on the database, refuses a non-local database host, atomic writes,
  manifest written last, everything read back and verified.
- Corruption: for every object of the golden pack, a flipped byte, truncation,
  appended byte, emptied file and deletion are each rejected with the object named.
  A manifest rewritten consistently with a forged lesson is only caught by the
  recorded hash — which is why the hash lives in the database.

Measured (local, synthetic; uncompressed / with gzip on manifest and lesson objects):

| Pack | Manifest | Lesson object(s) | Assets | Total | gzip estimate |
|---|---|---|---|---|---|
| seed `math-9af` fr (1 format-1 lesson, 5 questions) | 1 223 B | 3 115 B | 0 | 4 338 B | 1 393 B |
| golden format-2 (3 lessons, 5 questions, 2 PNG + 1 audio placeholder) | 2 998 B | 4 422 B | 485 B | 7 905 B | — |
| synthetic format-2 from the database (1 lesson: math, PNG, table) | 1 027 B | 723 B | 662 B | 2 412 B | 1 642 B |

These are tiny synthetic lessons; they say nothing yet about real lesson sizes.

## 7. Known gaps and owner decisions

- **PO-08 `BLOCKED_BY_OWNER`**: block list, budgets, and how mathematics is drawn.
  No renderer exists; `math.asset` allows a pre-rendered image either way.
- Format 2 is not served: no endpoint reads `Edu-Content-Formats`. A format-2
  release made current today would be served by the unchanged `/v1/lessons` to old
  apps. Nothing in the database stops that activation (it would need a trigger in
  `app`); the activation function of the staff lane should call
  `content.release_required_format` and require a `content.pack_manifests` row.
- A release can still be moved to `ready` by other privileged SQL without a
  recorded manifest (seed and test fixtures do); `content.pack_manifests` is the
  marker of a real one.
- New question kinds are not scored by the server; `true_false` is not an accepted
  `question_revisions.kind`.
- The database does not validate lesson bodies; the builder does. Asset checks are
  hash, size, file signature, and PNG dimensions — JPEG/WebP dimensions and audio
  duration are trusted from metadata.
- `app.pack_releases.compressed_bytes` receives the total *uncompressed* pack bytes.
- No inline mathematics inside paragraphs, list items or table cells.
- No resumable download, device-side activation, or object-store adapter.
- Haitian Creole strings in vectors are draft wording pending native review.
