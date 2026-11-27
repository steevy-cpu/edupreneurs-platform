# Content Migration-01

A read-only source adapter, private conversion planner and in-memory import simulation for 7AF–NS4. [Discovery, coverage and HOLD decision](DISCOVERY.md) · [Aggregate evidence](inventory-evidence.json) · [Manifest schema](manifest.schema.json). This directory has no database writer, network client, renderer or deployment entry point.

## Reproduce the synthetic proof

From the repository root with Node 22 and the repository's locked Python development environment installed:

```sh
cd tools/content-migration-01
node --test migration.test.mjs
set -o pipefail
node cli.mjs simulate synthetic.json | ../../.venv/bin/python verify_contracts.py
```

The GitHub workflow runs those steps on a disposable runner using synthetic inputs only. For an original example, the fixture contains `<p>2 + 3 = 5</p>` followed by an ordered list. Projection produces a paragraph containing the unchanged equation, then paragraphs beginning with `1. ` and `2. `. Source order and every visible item are asserted. A table, unknown attribute or unresolved diagram yields a reason and a null whole-lesson target. In the private review output the semantic tree retains supported markup and source paths. For malformed input the reviewer consults the separate private original by ID. Never render either document as HTML.

## Stable identifiers and manifest

Entities use a documented UUIDv8 derivation. Hash the UTF-8 string `edupreneurs:legacy-v1/<table>/<lowercase-uuid>` using SHA-256. Take the first 32 hexadecimal digits, set the 13th and 17th hex digits to 8, and insert standard UUID hyphens. The namespace and table are part of the identity. SQL and Node implement the same derivation. Index slots by source table, legacy ID, locale and positive source revision. Derive revision UUIDs with `edupreneurs:revision-v1/<native-id>/<locale>/<revision>` and the same bit convention. Legacy practice items without stable IDs use revision-scoped ordinal identities. Linking attempts across revisions requires a separate reviewed mapping.

The manifest records a snapshot timestamp and editor commit, transformation version, entity and revision IDs, grade/series/subject/unit/parent relationships, locale, provenance, source and target fingerprints, asset observations, validation reasons, draft state and exercise classification. The source digest binds the whole normalized record. A separate content digest binds the title and six lesson fields before projection. Target hashes bind exact projected payloads. Canonical JSON sorts object keys, preserves string contents and array order, and accepts only safe integers as JSON numbers. Null fields are explicit. Asset byte hashes use raw bytes. Changes in enrichment, rights or input with the same revision surface as a conflict. Identical authoring input and decisions produce identical targets; never replace a previous revision to silence a conflict.

Non-lesson tables without a converter stay inventory-only. An exam descriptor is a private mapping proposal. Automatic grading is unavailable in the planner. An isolated sealed-key diagnostic accepts only a matching proposal and separately authenticated owner-accepted review record. Real keys must stay in the controlled exam subsystem. Educational practice answers are private during conversion and must never be copied into an exam delivery response.

## Private rehearsal procedure

1. Pin the source schema/editor, target commit and tool commit. Use a disposable engineering workspace. On the Mac, verify that the T7 is mounted, writable and has capacity; use `umask 077`, a private directory outside every worktree, and T7-scoped temporary/cache paths. Do not enable shell tracing. For a real run, keep the raw snapshot, decision register, review packet and target observation in separate private files. Use synthetic data only in CI.
2. Use an authorized read-only content role, one repeatable-read read-only transaction, UTC, a statement timeout and a fixed allowlist of educational tables/buckets. Run `inventory.sql`, `snapshot.sql`, `exam-inventory.sql` and `asset-inventory.sql`. Keep per-entity rows from `inventory-page.sql` private. Persist the cursor and roots with the snapshot identity. Full reruns need a stable snapshot or an immutable authorized copy. If a keyset page is truncated or its last key fails to advance, stop and retain the discrepancy.
3. Bind the last UUID for `lesson-page.sql`, `paper-page.sql` and `exercise-page.sql`. Fetch bounded batches, enforce a byte cap and do not query student, author, payment or social records. Assemble subject/unit decisions separately from the lesson being tested. Call `adaptLesson(row,subject,assignment)` with approved unit/locale evidence bound to the content digest and current source version. Supply `adaptPaper` an explicit subject crosswalk keyed by the JSON tuple of grade, series and source slug, and pass that paper to `adaptExercise`. Current exercise metadata reads expose answer presence and a private change fingerprint only. Missing locale stays null. Other languages are not synthesized.
4. Build the private planner input in the shape of `synthetic.json`. Run the census against a same-scope independent entity list before per-revision reconciliation. Inspect extra nonempty fields quarantined by the adapter. For present but unsupported source material, retain the original and record its location and fingerprint. For images and audio/PDFs, resolve reference to allowlisted bucket and object ID, independently identify MIME and compare read bytes/length/SHA-256 using `observeAsset`. This prototype does not fetch assets or authenticate a MIME detector. Keep unresolved URLs, rights and bytes on hold.
5. Run the commands below only in the private workspace. Output from plan, simulation and review may contain source text, practice keys and asset references. Send it to mode-0600 files; never log or commit packets. `OBSERVED_PACKETS` is a JSON array of packets independently read from the disposable target. For a simulated run, extract the `packets` array from a previous simulation. `REGISTER` is optional, is supplied out of band, and requires a source SHA, reason and decision reference. Authentication and revocation of external decisions are future integration requirements.

```sh
node cli.mjs census INPUT EXPECTED_ENTITIES > entity-report.json
node cli.mjs plan INPUT > plan.json
node cli.mjs review INPUT > private-review.json
node cli.mjs simulate INPUT > first-run.json
node cli.mjs simulate INPUT PREVIOUS_PACKETS > repeat-run.json
node cli.mjs reconcile INPUT OBSERVED_PACKETS REGISTER > reconciliation.json
```

6. Inspect the per-run report, denominators and exit status. Zero means a clean comparison within the supplied scope. Exit 2 records missing, unexpected, changed or quarantined items. Exit 1 records an invalid run. Keep fatal diagnostics and restart from the same snapshot after correction. A clean simulation compares with generated output; only independently reading back an isolated target tests an actual import. Count `matched`, `transformed`, `quarantined`, `missing`, `unexpected`, `changed` and `approved_exclusion` separately. Exclusions never increase structural success. A zero listed-asset denominator says nothing about undiscovered links; report it alongside inventory counts and unresolved references.
7. Have independent reviewers compare field ordering, formatting, formula meaning, correct-choice identity, locale, assets and rights against private originals. Math checking covers only whole, small integer equalities with supported operators. Other prose requires educational review. Inspect the separate current and historical snapshots. The private manifest cannot make an approval decision. Learner publication is always false.

## Stop and rollback

On a source-root difference, same-revision conflict, unaccounted record, disputed rights, misclassified key or data loss, stop the batch and keep the previous committed ledger/snapshot. Simulation is pure and leaves its input unchanged. For a future authorized staging writer, allocate a new run ID, insert drafts and exact revision IDs in a transaction, independently reconcile the readback and preserve the previous catalog pointers. Roll back that run's new staging rows under a transaction only after proving zero inbound dependencies. If any are referenced, retain them and restore the previous catalog pointers. Never delete learner attempts, pending operations or shared data. This PR contains no writer or rollback SQL.

Retain private artifacts only for the approved review window on the encrypted T7. Record owner, access and cleanup deadline when a run begins. After review, remove only the run-owned private directory per the owner's retention policy; retain authorized aggregate counts, hashes and the decision log. The discovery used no local private directory. Claude #1's independent review, repeatable sampling, native-device compatibility and a disposable database round trip remain outstanding.
