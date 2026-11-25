# Lane CONTENT — versioned rich lesson contracts, assets, pack manifests (F2 · M-05, M-06)

Worktree `/Volumes/EdupreneursDev/worktrees/overnight/content` · branch `overnight/content-format-v2` ·
stack API 56321 / DB 56322 · schema `content` · migrations `2026112403xxxx_*` · pgTAP `140–159_*`.

Owned paths: `packages/contracts/content/**` (**add** files; the existing v1 schema files stay
byte-identical), `supabase/migrations/2026112403*`, `supabase/tests/14*.sql`, `supabase/tests/15*.sql`,
`services/api/src/edu_api/content/**`, `tests/**/test_content_v2_*.py`, `tests/content_fixtures.py`,
`scripts/build_pack.py`, `docs/overnight-2026-11-24/lanes/content.md`.

Decision status: what format v2 must contain is PO-08 (`BLOCKED_BY_OWNER`). Build Platform-00's
recommended minimum — mathematics, images, lists, tables — plus an optional audio reference, as
**contracts, validators and test vectors**. Nothing here changes what learners are served today.

## Slice 1 — format v2 contracts (no database needed)
- `lesson-blocks.v2.schema.json` (JSON Schema 2020-12): every v1 block stays valid unchanged; new
  block types `math` (a restricted, documented, plain-text mathematical notation plus a mandatory
  plain-language `alt` — no HTML, no scripts, no external engine), `image` (asset reference by
  content hash, mandatory alt text, intrinsic size, byte budget), `list`, `table` (bounded rows and
  columns, header cells, mobile-readable at 320 dp — document the rule), `audio` (asset reference,
  duration, transcript reference; never autoplay). Bounded lengths everywhere; unknown block types
  and unknown properties are rejected.
- A format-version field and the **negotiation rule** for old mobile builds, written precisely in
  the lane doc: how a client declares the versions it understands, what the server sends an app
  that only knows v1, why a v1 pack never contains v2 blocks. Keep `v1` content readable.
- Question contracts for `true_false`, `numeric`, `short_text` with a **versioned scoring rule**
  each (normalisation, tolerance, accepted answers), as schemas plus pure reference scoring
  functions in Python. They are *not* wired into `app.sync_apply_operation` (verified module; the
  server keeps rejecting non-MCQ kinds) — say so plainly.
- Shared **test vectors** (`packages/contracts/content/vectors/*.json`): valid and invalid documents
  and `(question, response) → expected score` cases, designed to be consumed by both the server
  tests and the future phone implementation. Python validator module + unit tests running every vector.

## Slice 2 — asset metadata and deterministic pack manifests
- Schema `content`: `assets` (sha256 as identity, object key, bytes, mime allow-list, intrinsic
  metadata, alt text per locale, rights/source reference, created by) and
  `revision_assets` (which lesson revision uses which asset; FK to `app.lesson_revisions`).
  Private, RLS on, no learner write path; rights gate: an asset without a cleared source cannot be
  attached to an approved revision — design it so it does not require any change in `app`.
- Canonical manifest: a documented canonical JSON form listing a pack's revisions, questions and
  assets with true sha256 and sizes; byte-identical output for identical input (golden test);
  `scripts/build_pack.py` writes the manifest and blobs to a **local directory** storage adapter
  (no cloud, no R2) and verifies them back (corrupt-blob rejection test, size report per lesson).
- Staff write path for assets and for recording a release's real manifest hash: definer functions
  using `staff.require_role` / `ops.audit_write` once the staff lane's B1 is merged (the director
  will tell you when). No AI-generated material is published; nothing bypasses human review.

Order: slice 1 (commit, gate) → slice 2.
