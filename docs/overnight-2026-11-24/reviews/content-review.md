# Content lane review — format v2 contracts, validators, pack manifests, schema `content`

Reviewed: branch `overnight/content-format-v2` at `d1f5bf7` (content work only; the merged staff-lane commit `7c3d2fb` is out of scope).
Reviewer environment: QA worktree `qa1`, own disposable Supabase stack, database reset to the reviewed commit.
Date: 2026-11-25. Independent review; nothing was fixed or modified in the lane.

## Verdict: APPROVE WITH FIXES

Nothing in this lane changes what learners are served today, the database privileges are tight, and the builder/verifier
caught every single-object corruption tried. But the validators and the verifier are not yet the security boundary the
brief asks for: two HIGH items and four MEDIUM items below must be fixed before any format-2 content is authored for
real, and H1/M1/M2 should be fixed before the vectors are handed to the phone team (they would teach the phone the gap).

Suites observed on `d1f5bf7`: pgTAP **600 passed** (10 files), pytest **788 passed**, `make lint` clean, `make typecheck` clean
(42 source files). These match the author's counts.

## Findings

### HIGH

**H1 — The pack verifier and the manifest schema accept a format-1 pack that carries format-2 question kinds.**
Location: `services/api/src/edu_api/content/pack.py` `verify_pack` / `_verify_lesson_object` (≈ lines 569–683),
`validate_manifest` / `_manifest_lesson` (question `kind` enum is all four kinds regardless of format),
`packages/contracts/content/pack-manifest.v1.schema.json` and `pack-lesson.v1.schema.json`.
Problem: the negotiation rule ("a format-1 pack never contains a format-2 block or question") is enforced by the
builder (`_check_lesson` → `required_format`) and by `content.record_release_manifest`, but not by the verifier nor by
the published schemas. The verifier only validates blocks against the lesson's declared format; question kinds are not
tied to the format at all. Evidence: a self-consistent stored pack with manifest `content_format: 1`, one lesson object
with `content_format: 1` and a `numeric` question was returned as intact by `verify_pack`; the same manifest is
accepted by both `validate_manifest` and the JSON Schema. The verifier is the reference the phone will copy, so a phone
that only knows format 1 would accept such a pack.
Smallest fix: in `_verify_lesson_object` compute `required_format(blocks, kinds)` and require it to equal the lesson's
`content_format` (and be ≤ the manifest's); in both schemas add `if content_format = 1 then kind = mcq`; add a
shared negative vector (verifier-side, not only builder-side).

**H2 — `content.record_release_manifest` finalises a release without validating lesson bodies and without binding the
recorded hash to the manifest it was shown; an asset reference in a non-contract shape escapes the attachment/rights gate.**
Location: `supabase/migrations/20261124030100_content_assets_and_pack_manifests.sql`, `content.record_release_manifest`,
`content.block_asset_hashes`, `content.blocks_required_format`.
Problem: this is the first staff-callable path that moves a release to `ready`. It checks identity, lesson list, asset
list and totals, but (a) lesson bodies are never checked against the format contract — the author documents "the
database does not validate lesson bodies; the builder does", yet nothing proves the builder ran; (b)
`p_manifest_sha256` / `p_manifest_bytes` are caller-asserted and unrelated to `p_manifest` (jsonb); (c) the
attachment check only sees assets written exactly as `block.asset.sha256` inside an object, so a body that refers to
media in any other shape (which the validators would reject) is simply not seen by the rights gate. Evidence (run as
`edu_staff` with a publisher actor, rolled back): a release whose only lesson body contained an unknown block type,
markup text, a remote media reference and an asset hash in a shape the helper ignores was recorded `ready` with an
arbitrary hash and an empty asset list, and could then be activated through the unchanged baseline transition.
The contract-valid paths are sound (see "verified sound"). Severity is HIGH as a precondition for format 2; today the
practical exposure is limited because no API route calls the function and reviewers still approve every revision.
Smallest fix: (1) make the function refuse any body it cannot account for — every block `type` in the nine known
types, `asset` present only as an object with a 64-hex `sha256`, no other media-bearing property — or better, call it
only from a server-side build step that has run `build_pack`/`verify_pack`; (2) take the manifest as bytes, compute
`sha256` and length in the function, then parse it; (3) run the Python validators at revision submit/approval in the
staff API so a non-contract body can never be approved.

### MEDIUM

**M1 — The math notation accepts HTML-shaped sources.**
Location: `content/blocks.py` `_math` (`_MATH_CHARSET`, no `plain=True`), `content/math_notation.py` (`<`, `>`, `/`,
`=`, letters and spaces are literals), `lesson-blocks.v2.schema.json` `$defs.math.source` (no `noMarkup`).
Problem: the brief requires "no HTML, no scripts". Every other new text field rejects a `<` directly followed by a
letter, `/`, `!` or `?`; the math source does not, so complete element-shaped strings (including ones with event
attributes) pass both the validator and the schema, bare or inside `\text{…}`. Harmless with a native renderer;
script execution if any client ever feeds the source to a web view or an HTML-based maths engine.
Evidence: format-2 documents with such sources returned no issues from `validate_blocks` and were accepted by the schema.
Smallest fix: apply the same `noMarkup` rule to `source` (authors write `a < b` with a space), in schema and validator,
plus negative vectors; state in the README that a renderer must never pass `source` to an HTML engine.

**M2 — The nesting limit of the math grammar is bypassed through the root index.**
Location: `content/math_notation.py` `_command` (`self._expr(depth, "]")` does not increase `depth`).
Problem: groups are limited to depth 4, but a root inside a root index does not count; 39 nested levels fit in the
400-character limit and validate. A phone renderer sized for depth 4 gets depth 39 (layout blow-up / stack use on a
low-end phone). Called directly with a long string (the docstring says "safe on any input"), `check_math_source`
raises `RecursionError`. Timing is otherwise linear: worst cases at the length limit took ≤ 0.15 ms; 200 worst-case
math blocks 0.4 ms.
Smallest fix: parse the index with `depth + 1` and check the limit there; add vectors for nested indices.

**M3 — `verify_pack` does not check several things the manifest asserts.**
Location: `content/pack.py` `verify_pack`, `_verify_lesson_object`, `_manifest_lesson`.
Problem / evidence (re-signed manifests, all returned intact): `totals` are never compared with the lists (a phone that
budgets its download from `totals` is misled); the same lesson object may be listed twice at two positions (no
uniqueness on `revision_id` / `lesson_id`); a lesson object may contain the same question (same id and position)
twice; lesson `title` is only length-checked (control characters and markup pass, in builder and verifier; in practice
the database column cannot hold NUL). When the caller passes the expected hash these need a malicious builder, but the
CLI allows verification without a hash and the phone reference should be self-consistent.
Smallest fix: recompute and compare `totals`; require unique `revision_id`, `lesson_id`, question ids and positions;
give `title` the plain-text rule.

**M4 — Invisible and direction-changing characters are accepted everywhere; old block types accept control characters and markup inside a format-2 lesson.**
Location: `content/issues.py` `_CONTROL` (`[\u0000-\u001f\u007f]` only), the `noControl` definition of every schema,
`content.is_locale_text_map` in the migration; `_heading` / `_paragraph` / `_example` / `_callout`, question
`prompt` / `explanation` / MCQ choice texts (no `plain` rule).
Problem / evidence: bidi overrides and isolates (U+202A–202E, U+2066–2069), zero-width characters, U+2028/2029, C1
controls (U+0080–009F) and lone surrogates pass in alt texts, captions, list items, table cells, accepted answers and
asset alt text in the database. A reviewer can be shown text that reads differently from what is stored, and the
table-width rule counts characters that take no space. Paragraph, heading, callout and example text and all question
text additionally accept NUL, any control character and element-shaped markup, also when validated as format 2
("v1 blocks stay valid unchanged" — a deliberate constraint, but then the rendering rule must be written down).
Smallest fix: extend the forbidden set for the new fields (bidi controls, zero-width, U+2028/2029, C1, lone
surrogates); state normatively in the README that every string is plain text and is never interpreted as markup;
decide (owner) whether format 2 tightens the four old block types.

### LOW

- **L1 — "Validator and schema agree on every document" does not hold under the test harness.** My own mutation run
  (40,000 mutated lesson bodies × 2 formats, 30,000 questions, 15,000 manifests) found two disagreement classes for
  blocks and questions: integral floats (`10.0`, `1e2`: schema accepts, Python rejects — 38 block cases, 10 question
  cases) and a trailing line feed on `$`-anchored patterns in the unchanged v1 schemas (`key`, MCQ choice ids: Python
  `jsonschema` accepts, the validator rejects — 6 + 1 cases). 317 manifest disagreements were all "schema accepts,
  Python rejects"; targeted probes reproduced the integral-float class there, I did not classify all 317. In every
  case Python is the stricter side, and the README documents both conventions (ECMA `$`, integers without fraction),
  but a JavaScript phone cannot tell `10.0` from `10`, so server and phone will differ on such input. Fix: state the
  rule in the vectors (a case each), and make the harness use an ECMA-faithful end anchor or `\z`-style check.
- **L2 — Validation happens before NFC normalisation.** `canonical_json` normalises after `_check_lesson` validated.
  Text whose NFC form is longer (composition exclusions) or that only becomes element-shaped after NFC builds
  successfully and then fails the read-back verification — fail-closed, but the objects *and the manifest* are already
  written, and because keys are immutable a corrected rebuild of the same release is then refused. Fix: normalise
  first, validate the normalised document, and verify before the manifest is put.
- **L3 — Builder input errors that escape as tracebacks instead of `PackBuildError`:** a block `type` that is a list
  (`TypeError` in `required_format`, also on the database path of `scripts/build_pack.py`), a lone surrogate in any
  string (`UnicodeEncodeError` in `canonical_json`; `is_canonical_json` does not catch it either), non-integer
  `revision` / `position` in a JSON description. Fix: type checks in `_check_identity` / `required_format`, catch
  `UnicodeEncodeError`.
- **L4 — Key rules disagree:** `pack_key` may start with `_` or `-` (builder, schema, database CHECK) but the storage
  adapter requires every path component to start with `[a-z0-9]`, so such a pack builds and cannot be stored.
- **L5 — `record_release_manifest` leaks raw constraint errors** (`23514`, `22003`) for negative, missing or
  overflowing byte counts instead of the clean `22023`; nothing is recorded.
- **L6 — Question kinds do not line up:** `app.question_revisions.kind` allows `matching` (unknown to the contracts;
  the builder refuses it) and does not allow `true_false` (documented by the author). Needs an `app` migration before v2.
- **L7 — Scoring rule under-specified for other runtimes:** "Unicode default lower-casing" does not say full vs simple
  case mapping, and NFC/lower-casing depend on the runtime's Unicode version; the scoring vectors contain no case
  that separates the two (no ß, İ, final sigma). Irrelevant for French/Creole answers today; add two vectors or
  restrict the rule to the Latin ranges actually accepted.
- **L8 — `scripts/build_pack.py build`** reads with the local admin URL and does not look at the release status or
  refuse non-building releases; it is read-only and local-only, so this is hygiene.

### NOTE

- File-signature sniffing is deliberately weak (documented): any ISO-BMFF file is `audio/mp4`, anything starting with
  `ID3` is `audio/mpeg`; JPEG/WebP dimensions and audio duration are trusted.
- `score()` raises on an invalid answer key (documented: validate first); responses never raise.
- Files left in the store that no manifest references are not reported by the verifier (content-addressed sharing; by design).
- `content.assets` can be registered against an unverified source — by design; the gate is at approval and at `ready`.
- An admin alone can register, attach and record (no separation of duties inside `admin`).

## The author's statement: nothing prevents a format-2 release being made current for old clients

Confirmed, and correctly disclosed (lane doc §6–7). Severity: **HIGH if any format-2 release is ever activated** —
the unchanged `/v1/lessons` would send blocks old builds do not know to children's phones, with untested behaviour.
It is acceptable for this merge only because no staff path activates a release and no v2 content exists. Before any
format-2 content ships, all of the following must exist:

1. An activation gate: making a release current must require a `content.pack_manifests` row and must refuse
   `content_format > 1` for the `/v1` delivery path (function or reviewed `app` trigger; the helper
   `content.release_required_format` is ready for it).
2. A format-aware delivery endpoint that reads `Edu-Content-Formats`, uses `negotiate`, and has tests proving a
   client without the header never receives a format-2 body.
3. Contract validation at a choke point the database can rely on (revision submit/approval and manifest recording), and
   the recorded hash computed from the manifest bytes — H2.
4. Verifier and schemas enforcing the format rule for questions — H1; math markup and nesting — M1, M2.
5. The `app` migration for question kinds and server scoring wired to the versioned rules (L6).
6. A written rendering rule (all strings are plain text; math source never reaches an HTML engine) and the owner's
   decision PO-08.

## Verified sound (tried to break, could not)

- Unknown block types, unknown properties at every level, missing properties, wrong types, booleans as integers,
  NaN/Infinity, oversized documents (201 blocks, 4001 characters, 10^6 blocks, 10^7 characters, 100,000-deep nesting:
  all rejected without recursion, ≤ 37 ms), asset references by URL / upper-case hash / extra properties / SVG / zero
  or negative or 2^63 sizes, table dimensions (1 and 5 columns, 0 and 21 rows, nested cells), list nesting and length,
  audio `autoplay`, duplicate transcript keys: rejected by both implementations.
- Format-1 documents: every v1 vector still valid; a format-1 validation rejects every v2 block type; the builder
  refuses a pack declared format 1 with any v2 block or question; `required_format` cannot be lowered by extra or
  differently-cased keys.
- Duplicate JSON keys, floats, `-0`, leading zeros, BOM, trailing newline, escaped forms, NFD text: rejected by
  `is_canonical_json`.
- Reference scoring: exponents, NaN/Infinity strings, hex, underscores, full-width and Arabic digits, 33-digit input,
  bare separators, division by zero are `not_a_number`; comma decimal, leading zeros, `+`, U+2212, negative zero and
  tolerance boundaries are exact (rational arithmetic, no float anywhere); non-boolean true/false responses rejected.
- Header negotiation fails towards `{1}` on every malformed value tried.
- Determinism: golden hashes reproduce; lesson order, dictionary key order and NFD input give the same bytes.
- Verifier: flip / truncate / append / delete / empty of every object rejected; manifest tampering rejected with and
  without the expected hash; traversal in manifest object keys rejected; missing audio tolerated only with the flag and
  a present-but-corrupt audio file still rejected. Storage adapter: keys cannot contain `..`, absolute paths or
  leading dots; resolved path must stay under the root; existing keys cannot be overwritten with different bytes.
- Database: `anon`, `authenticated`, `service_role`, `authenticator`, `edu_api`, `edu_worker` (and their logins) have
  no USAGE on `content`; `edu_staff` has USAGE and EXECUTE on exactly the four staff functions, no table privilege, no
  CREATE, no helper function; RLS enabled on the three tables with no policy; all 15 functions owned by `postgres`
  with `search_path=pg_catalog, pg_temp`; nothing created in `app`; no foreign key to learning tables (FKs go to
  `app.content_sources`, `app.lesson_revisions`, `app.lesson_revision_sources`, `app.pack_releases`, `auth.users`).
- Role matrix (live): editor/admin for register/attach/detach, publisher/admin for record; no actor, learner,
  wrong role, `edu_api`, `edu_worker` refused.
- Rights gate for contract-shaped content (live): an asset cannot be attached unless the revision cites the asset's
  own source; approval and `ready` both require all cited sources cleared (baseline guards); attachments are frozen
  after the first review, approval or packing; a packed lesson that references an unattached asset cannot be recorded;
  recorded manifests are append-only even for the owner.
- Audit rows contain hashes, ids, mime, byte counts and format only.
- v1 schema files unchanged against `origin/main`; no secrets in the content files.

## Missing tests

- Verifier-side negative cases: format-1 pack with a v2 question kind, wrong totals, duplicated lesson entry,
  duplicated question (H1, M3).
- Math: HTML-shaped sources, nested root indices (M1, M2).
- Vectors for integral floats and trailing line feed (L1), NFC-expanding text (L2), bidi / zero-width / C1 / lone
  surrogate (M4), case-mapping edge cases (L7).
- `record_release_manifest` with a non-contract lesson body, and with negative / overflowing byte counts (H2, L5).

## Not examined

Concurrency (attachment vs. concurrent review/approval), the PostgREST gateway live (privileges only, from the
catalogue), JPEG/WebP/audio handling, the full text of the README and lane doc, the pgTAP files 140/141 and
`tests/integration/test_content_v2_database.py` line by line (they were run, not audited), the merged staff-lane code.
