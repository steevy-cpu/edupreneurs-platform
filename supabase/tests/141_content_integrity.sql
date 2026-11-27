-- Constraints and guards of the `content` schema, including the rights gate.
-- Runs as the migration owner on purpose: these rules must hold even for
-- privileged writers (future staff services, a person in a SQL console).
BEGIN;
SELECT * FROM no_plan();

\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set REVIEWER '''a0000000-0000-4000-8000-000000000004'''
\set CLEARED '''e0000000-0000-4000-8000-000000000001'''
\set UNCLEARED '''e0000000-0000-4000-8000-000000000141'''
\set SEED_REV '''c0000000-0000-4000-8000-000000000001'''
\set DRAFT '''c0000000-0000-4000-8000-000000001411'''
\set REVIEWED '''c0000000-0000-4000-8000-000000001412'''
\set PLAIN '''c0000000-0000-4000-8000-000000001413'''

-- Synthetic fixtures: a source whose rights are not cleared, three draft revisions.
INSERT INTO app.content_sources (id, source_title, rights_status) VALUES
  (:UNCLEARED, 'Synthetic picture source with unverified rights', 'unverified');
INSERT INTO app.lesson_revisions (id, lesson_id, revision, locale, title, blocks, created_by) VALUES
  (:DRAFT, 'b0000000-0000-4000-8000-000000000005', 1411, 'fr', 'content fixture 1411', '[{"key":"p","type":"paragraph","text":"x"}]', :EDITOR),
  (:REVIEWED, 'b0000000-0000-4000-8000-000000000005', 1412, 'fr', 'content fixture 1412', '[{"key":"p","type":"paragraph","text":"x"}]', :EDITOR),
  (:PLAIN, 'b0000000-0000-4000-8000-000000000005', 1413, 'fr', 'content fixture 1413', '[{"key":"p","type":"paragraph","text":"x"}]', :EDITOR);

-- One statement template for "insert an asset": everything valid unless overridden.
CREATE FUNCTION pg_temp.add_asset(
    p_seed text, p_mime text DEFAULT 'image/png', p_bytes bigint DEFAULT 1200,
    p_width integer DEFAULT 320, p_height integer DEFAULT 180, p_duration integer DEFAULT NULL,
    p_alt jsonb DEFAULT '{"fr": "Un schéma synthétique"}',
    p_source uuid DEFAULT 'e0000000-0000-4000-8000-000000000001',
    p_key text DEFAULT NULL, p_sha bytea DEFAULT NULL,
    p_author uuid DEFAULT 'a0000000-0000-4000-8000-000000000003')
RETURNS void LANGUAGE sql AS $fn$
    INSERT INTO content.assets (sha256, object_key, bytes, mime, width, height, duration_ms, alt_text, source_id, created_by)
    VALUES (COALESCE(p_sha, sha256(p_seed::bytea)),
            COALESCE(p_key, content.asset_object_key(COALESCE(p_sha, sha256(p_seed::bytea)))),
            p_bytes, p_mime, p_width, p_height, p_duration, p_alt, p_source, p_author)
$fn$;

-- ================================ assets ================================
SELECT lives_ok($$SELECT pg_temp.add_asset('img-cleared')$$, 'a valid image asset is accepted');
SELECT lives_ok($$SELECT pg_temp.add_asset('img-webp', 'image/webp', 200000, 1600, 1600)$$, 'an image at the byte and size limits is accepted');
SELECT lives_ok($$SELECT pg_temp.add_asset('audio-ok', 'audio/mp4', 2000000, NULL, NULL, 600000, '{"fr": "Explication audio", "ht": "Eksplikasyon odyo"}')$$, 'a valid audio asset at its limits is accepted');
SELECT lives_ok($$SELECT pg_temp.add_asset('img-uncleared', p_source => 'e0000000-0000-4000-8000-000000000141')$$, 'an asset may be registered before its rights are cleared (it cannot be published, see below)');
SELECT is((SELECT object_key FROM content.assets WHERE sha256 = sha256('img-cleared')),
    'assets/sha256/' || substr(encode(sha256('img-cleared'), 'hex'), 1, 2) || '/' || encode(sha256('img-cleared'), 'hex'),
    'the storage key is derived from the hash');

SELECT throws_ok($$SELECT pg_temp.add_asset('img-cleared')$$, '23505', NULL, 'the same file cannot be registered twice');
SELECT throws_ok($$SELECT pg_temp.add_asset('short', p_sha => '\x0102'::bytea)$$, '23514', NULL, 'the identity must be a 32-byte hash');
SELECT throws_ok($$SELECT pg_temp.add_asset('k1', p_key => 'assets/elsewhere.png')$$, '23514', NULL, 'the storage key cannot be chosen freely');
SELECT throws_ok($$SELECT pg_temp.add_asset('k2', p_key => content.asset_object_key(sha256('img-cleared')))$$, '23514', NULL, 'the storage key cannot point at another asset''s bytes');
SELECT throws_ok($$SELECT pg_temp.add_asset('svg', 'image/svg+xml')$$, '23514', NULL, 'SVG is not on the mime allow-list');
SELECT throws_ok($$SELECT pg_temp.add_asset('gif', 'image/gif')$$, '23514', NULL, 'GIF is not on the mime allow-list');
SELECT throws_ok($$SELECT pg_temp.add_asset('html', 'text/html')$$, '23514', NULL, 'HTML is not on the mime allow-list');
SELECT throws_ok($$SELECT pg_temp.add_asset('wav', 'audio/wav', 1000, NULL, NULL, 1000)$$, '23514', NULL, 'WAV is not on the mime allow-list');
SELECT throws_ok($$SELECT pg_temp.add_asset('big', p_bytes => 200001)$$, '23514', NULL, 'an image over 200 000 bytes is rejected');
SELECT throws_ok($$SELECT pg_temp.add_asset('zero', p_bytes => 0)$$, '23514', NULL, 'an empty file is rejected');
SELECT throws_ok($$SELECT pg_temp.add_asset('wide', p_width => 1601)$$, '23514', NULL, 'an image wider than 1600 px is rejected');
SELECT throws_ok($$SELECT pg_temp.add_asset('flat', p_height => 0)$$, '23514', NULL, 'an image needs a positive height');
SELECT throws_ok($$SELECT pg_temp.add_asset('nosize', p_width => NULL)$$, '23514', NULL, 'an image needs its intrinsic size (NULL does not slip through the check)');
SELECT throws_ok($$SELECT pg_temp.add_asset('imgdur', p_duration => 1000)$$, '23514', NULL, 'an image has no duration');
SELECT throws_ok($$SELECT pg_temp.add_asset('audsize', 'audio/mpeg', 1000, 10, 10, 1000)$$, '23514', NULL, 'audio has no width or height');
SELECT throws_ok($$SELECT pg_temp.add_asset('audnodur', 'audio/mpeg', 1000, NULL, NULL, NULL)$$, '23514', NULL, 'audio needs a duration (NULL does not slip through the check)');
SELECT throws_ok($$SELECT pg_temp.add_asset('audlong', 'audio/mpeg', 1000, NULL, NULL, 600001)$$, '23514', NULL, 'audio longer than 10 minutes is rejected');
SELECT throws_ok($$SELECT pg_temp.add_asset('audbig', 'audio/mpeg', 2000001, NULL, NULL, 1000)$$, '23514', NULL, 'audio over 2 000 000 bytes is rejected');
SELECT throws_ok($$SELECT pg_temp.add_asset('alt0', p_alt => '{}')$$, '23514', NULL, 'alt text needs at least one locale');
SELECT throws_ok($$SELECT pg_temp.add_asset('alt1', p_alt => '{"en": "A diagram"}')$$, '23514', NULL, 'alt text only in known locales');
SELECT throws_ok($$SELECT pg_temp.add_asset('alt2', p_alt => '{"fr": ""}')$$, '23514', NULL, 'alt text cannot be empty');
SELECT throws_ok($$SELECT pg_temp.add_asset('alt3', p_alt => jsonb_build_object('fr', repeat('a', 301)))$$, '23514', NULL, 'alt text is at most 300 characters');
SELECT throws_ok($$SELECT pg_temp.add_asset('alt4', p_alt => '{"fr": "<img src=x onerror=alert(1)>"}')$$, '23514', NULL, 'alt text cannot carry markup');
SELECT throws_ok($$SELECT pg_temp.add_asset('alt5', p_alt => '{"fr": 12}')$$, '23514', NULL, 'alt text must be text');
SELECT throws_ok($$SELECT pg_temp.add_asset('alt6', p_alt => '["fr"]')$$, '23514', NULL, 'alt text must be an object');
SELECT throws_ok($$SELECT pg_temp.add_asset('alt7', p_alt => jsonb_build_object('fr', 'a' || chr(10) || 'b'))$$, '23514', NULL, 'alt text is a single line');
SELECT throws_ok($$SELECT pg_temp.add_asset('alt8', p_alt => NULL)$$, '23502', NULL, 'alt text is mandatory');
SELECT throws_ok($$SELECT pg_temp.add_asset('src0', p_source => gen_random_uuid())$$, '23503', NULL, 'the source must exist');
SELECT throws_ok($$SELECT pg_temp.add_asset('src1', p_source => NULL)$$, '23502', NULL, 'a source is mandatory');
SELECT throws_ok($$SELECT pg_temp.add_asset('who', p_author => gen_random_uuid())$$, '23503', NULL, 'the author must be a real account');

SELECT throws_ok($$UPDATE content.assets SET bytes = 1 WHERE sha256 = sha256('img-cleared')$$,
    'P0001', 'Asset identity and intrinsic metadata are immutable', 'the recorded size cannot be changed');
SELECT throws_ok($$UPDATE content.assets SET mime = 'image/jpeg' WHERE sha256 = sha256('img-cleared')$$,
    'P0001', 'Asset identity and intrinsic metadata are immutable', 'the recorded type cannot be changed');
SELECT throws_ok($$UPDATE content.assets SET sha256 = sha256('other'), object_key = content.asset_object_key(sha256('other')) WHERE sha256 = sha256('img-cleared')$$,
    'P0001', 'Asset identity and intrinsic metadata are immutable', 'an asset cannot be re-pointed at other bytes');
SELECT throws_ok($$UPDATE content.assets SET created_by = 'a0000000-0000-4000-8000-000000000004' WHERE sha256 = sha256('img-cleared')$$,
    'P0001', 'Asset identity and intrinsic metadata are immutable', 'authorship cannot be reassigned');
SELECT lives_ok($$UPDATE content.assets SET alt_text = '{"fr": "Un schéma corrigé"}' WHERE sha256 = sha256('img-cleared')$$,
    'alt text of an asset nobody has reviewed yet can be corrected');
SELECT lives_ok($$DELETE FROM content.assets WHERE sha256 = sha256('img-webp')$$, 'an asset that nothing uses can be removed');

-- ============================ revision_assets ============================
-- Without a citation of the asset's source, the link is refused (rights gate, half 2).
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES ('c0000000-0000-4000-8000-000000001411', sha256('img-uncleared'), 'e0000000-0000-4000-8000-000000000141', 'a0000000-0000-4000-8000-000000000003')$$,
    '23503', NULL, 'an asset cannot be attached to a revision that does not cite its source');
INSERT INTO app.lesson_revision_sources VALUES
  (:DRAFT, :CLEARED), (:DRAFT, :UNCLEARED), (:REVIEWED, :CLEARED), (:PLAIN, :CLEARED);
-- The link must carry the asset's real source (rights gate, half 1).
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES ('c0000000-0000-4000-8000-000000001411', sha256('img-uncleared'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003')$$,
    '23503', NULL, 'a link cannot claim a different (cleared) source than the asset really has');
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES ('c0000000-0000-4000-8000-000000001411', sha256('never-registered'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003')$$,
    '23503', NULL, 'an unregistered asset cannot be attached');
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES (gen_random_uuid(), sha256('img-cleared'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003')$$,
    '23503', NULL, 'an asset cannot be attached to an unknown revision');
SELECT lives_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by) VALUES
    ('c0000000-0000-4000-8000-000000001411', sha256('img-uncleared'), 'e0000000-0000-4000-8000-000000000141', 'a0000000-0000-4000-8000-000000000003'),
    ('c0000000-0000-4000-8000-000000001411', sha256('img-cleared'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003'),
    ('c0000000-0000-4000-8000-000000001413', sha256('img-cleared'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003')$$,
    'assets can be attached to drafts that cite their sources');
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES ('c0000000-0000-4000-8000-000000001411', sha256('img-cleared'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003')$$,
    '23505', NULL, 'the same asset is attached to a revision once');
SELECT throws_ok($$UPDATE content.revision_assets SET attached_at = now() WHERE lesson_revision_id = 'c0000000-0000-4000-8000-000000001413'$$,
    'P0001', 'Asset attachments cannot be edited; detach and attach again', 'links are not edited in place');

-- While an asset is attached, the pieces of the gate cannot be pulled apart.
SELECT throws_ok($$DELETE FROM app.lesson_revision_sources WHERE lesson_revision_id = 'c0000000-0000-4000-8000-000000001411' AND source_id = 'e0000000-0000-4000-8000-000000000141'$$,
    '23503', NULL, 'the citation of an attached asset''s source cannot be removed from the draft');
SELECT throws_ok($$UPDATE content.assets SET source_id = 'e0000000-0000-4000-8000-000000000001' WHERE sha256 = sha256('img-uncleared')$$,
    '23503', NULL, 'an attached asset cannot be quietly moved to a cleared source');
SELECT throws_ok($$DELETE FROM content.assets WHERE sha256 = sha256('img-uncleared')$$,
    '23503', NULL, 'an attached asset cannot be deleted');
SELECT throws_ok($$DELETE FROM app.lesson_revisions WHERE id = 'c0000000-0000-4000-8000-000000001413'$$,
    '23503', NULL, 'a draft revision with attached assets cannot be deleted from under them');

-- ---- THE RIGHTS GATE: an asset without a cleared source cannot reach an approved revision ----
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES (:DRAFT, :REVIEWER, 'approved');
SELECT throws_ok($$UPDATE app.lesson_revisions SET status = 'approved', approved_by = 'a0000000-0000-4000-8000-000000000004', approved_at = now() WHERE id = 'c0000000-0000-4000-8000-000000001411'$$,
    'P0001', 'Approval requires at least one source and all sources rights-cleared',
    'a revision carrying an asset whose source is not cleared cannot be approved (existing app guard, unchanged)');
SELECT is((SELECT status FROM app.lesson_revisions WHERE id = :DRAFT), 'draft', 'the revision stays unapproved');
-- After review the asset list is frozen: the uncleared asset cannot be swapped out to sneak through.
SELECT throws_ok($$DELETE FROM content.revision_assets WHERE lesson_revision_id = 'c0000000-0000-4000-8000-000000001411' AND asset_sha256 = sha256('img-uncleared')$$,
    'P0001', 'Assets of reviewed/approved/packed lesson revisions are frozen', 'a reviewed revision''s assets cannot be detached');
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES ('c0000000-0000-4000-8000-000000001411', sha256('audio-ok'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003')$$,
    'P0001', 'Assets of reviewed/approved/packed lesson revisions are frozen', 'nothing can be attached after the review');
SELECT throws_ok($$UPDATE content.assets SET alt_text = '{"fr": "changé après relecture"}' WHERE sha256 = sha256('img-uncleared')$$,
    'P0001', 'Assets used in reviewed material are immutable', 'what the reviewer saw cannot be reworded afterwards');
SELECT throws_ok($$UPDATE content.assets SET alt_text = '{"fr": "changé après relecture"}' WHERE sha256 = sha256('img-cleared')$$,
    'P0001', 'Assets used in reviewed material are immutable', 'the same holds for every asset the reviewed revision uses');

-- Once the rights are really cleared, the same revision can be approved.
UPDATE app.content_sources SET rights_status = 'cleared', verified_at = now() WHERE id = :UNCLEARED;
SELECT lives_ok($$UPDATE app.lesson_revisions SET status = 'approved', approved_by = 'a0000000-0000-4000-8000-000000000004', approved_at = now() WHERE id = 'c0000000-0000-4000-8000-000000001411'$$,
    'with every source cleared, approval goes through');

-- An approved revision accepts no new asset, cleared or not.
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES ('c0000000-0000-4000-8000-000000001411', sha256('audio-ok'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003')$$,
    'P0001', 'Assets of reviewed/approved/packed lesson revisions are frozen', 'nothing can be attached to an approved revision');
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES ('c0000000-0000-4000-8000-000000000001', sha256('img-cleared'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003')$$,
    'P0001', 'Assets of reviewed/approved/packed lesson revisions are frozen', 'nothing can be attached to the published seed revision');
SELECT throws_ok($$DELETE FROM content.revision_assets WHERE lesson_revision_id = 'c0000000-0000-4000-8000-000000001411'$$,
    'P0001', 'Assets of reviewed/approved/packed lesson revisions are frozen', 'an approved revision''s assets cannot be detached');
-- ... and an asset from a new uncleared source cannot even be linked to it.
INSERT INTO app.content_sources (id, source_title, rights_status) VALUES
  ('e0000000-0000-4000-8000-000000000142', 'Second synthetic source, restricted', 'restricted');
SELECT lives_ok($$SELECT pg_temp.add_asset('img-restricted', p_source => 'e0000000-0000-4000-8000-000000000142')$$, 'fixture: an asset from a restricted source');
SELECT throws_ok($$INSERT INTO app.lesson_revision_sources VALUES ('c0000000-0000-4000-8000-000000001411', 'e0000000-0000-4000-8000-000000000142')$$,
    'P0001', 'Reviewed source references cannot be modified', 'its source cannot be cited by the approved revision ...');
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES ('c0000000-0000-4000-8000-000000001411', sha256('img-restricted'), 'e0000000-0000-4000-8000-000000000142', 'a0000000-0000-4000-8000-000000000003')$$,
    NULL, NULL, '... so the asset cannot be attached to the approved revision by any route');
SELECT is((SELECT count(*)::int FROM content.revision_assets ra JOIN content.assets a ON a.sha256 = ra.asset_sha256
           JOIN app.content_sources s ON s.id = a.source_id JOIN app.lesson_revisions lr ON lr.id = ra.lesson_revision_id
           WHERE lr.status = 'approved' AND s.rights_status <> 'cleared'), 0,
    'invariant: no approved revision is linked to an asset whose source is not cleared');

-- Rights withdrawn AFTER approval: the pack cannot be finalized (existing app guard).
INSERT INTO app.pack_releases (id, pack_key, revision, locale) VALUES ('f0000000-0000-4000-8000-000000000141', 'content-it', 1, 'fr');
INSERT INTO app.pack_items VALUES ('f0000000-0000-4000-8000-000000000141', :DRAFT, 1);
UPDATE app.content_sources SET rights_status = 'blocked' WHERE id = :UNCLEARED;
SELECT throws_ok($$UPDATE app.pack_releases SET status = 'ready', manifest_object_key = 'x', manifest_sha256 = sha256('x'), compressed_bytes = 1 WHERE id = 'f0000000-0000-4000-8000-000000000141'$$,
    'P0001', 'Pack includes content with uncleared rights', 'withdrawn asset rights stop the pack from being finalized');
UPDATE app.content_sources SET rights_status = 'cleared' WHERE id = :UNCLEARED;

-- A reviewed (not approved) revision is frozen as well.
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES (:REVIEWED, :REVIEWER, 'changes_requested');
SELECT throws_ok($$INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES ('c0000000-0000-4000-8000-000000001412', sha256('img-cleared'), 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003')$$,
    'P0001', 'Assets of reviewed/approved/packed lesson revisions are frozen', 'a revision under review accepts no new asset');
-- A plain draft is still editable.
SELECT lives_ok($$DELETE FROM content.revision_assets WHERE lesson_revision_id = 'c0000000-0000-4000-8000-000000001413'$$, 'an unreviewed draft''s assets can be detached');

-- ============================ pack_manifests ============================
SELECT throws_ok($$INSERT INTO content.pack_manifests (pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes, lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes, optional_asset_bytes, recorded_by)
    VALUES ('f0000000-0000-4000-8000-000000000141', 'pack-manifest-1', 1, sha256('m'), 100, 1, 0, 0, 900, 0, 0, 'a0000000-0000-4000-8000-000000000003')$$,
    'P0001', 'A manifest can only be recorded for a finalized pack release', 'no manifest row for a release that is still building');
SELECT throws_ok($$INSERT INTO content.pack_manifests (pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes, lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes, optional_asset_bytes, recorded_by)
    VALUES (gen_random_uuid(), 'pack-manifest-1', 1, sha256('m'), 100, 1, 0, 0, 900, 0, 0, 'a0000000-0000-4000-8000-000000000003')$$,
    'P0001', 'A manifest can only be recorded for a finalized pack release', 'no manifest row for an unknown release');
SELECT throws_ok($$INSERT INTO content.pack_manifests (pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes, lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes, optional_asset_bytes, recorded_by)
    VALUES ('f0000000-0000-4000-8000-000000000001', 'pack-manifest-1', 1, sha256('some other manifest'), 96, 1, 5, 0, 4000, 0, 0, 'a0000000-0000-4000-8000-000000000003')$$,
    'P0001', 'Recorded manifest does not match the pack release', 'the recorded hash must be the one the release carries');
SELECT throws_ok($$INSERT INTO content.pack_manifests (pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes, lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes, optional_asset_bytes, recorded_by)
    SELECT id, 'pack-manifest-1', 1, manifest_sha256, 96, 1, 5, 0, 4001, 0, 0, 'a0000000-0000-4000-8000-000000000003' FROM app.pack_releases WHERE id = 'f0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Recorded manifest does not match the pack release', 'the recorded sizes must add up to the size the release carries');
SELECT throws_ok($$INSERT INTO content.pack_manifests (pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes, lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes, optional_asset_bytes, recorded_by)
    SELECT id, 'pack-manifest-1', 3, manifest_sha256, 96, 1, 5, 0, 4000, 0, 0, 'a0000000-0000-4000-8000-000000000003' FROM app.pack_releases WHERE id = 'f0000000-0000-4000-8000-000000000001'$$,
    '23514', NULL, 'an unknown content format is rejected');
SELECT throws_ok($$INSERT INTO content.pack_manifests (pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes, lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes, optional_asset_bytes, recorded_by)
    SELECT id, 'pack-manifest-2', 1, manifest_sha256, 96, 1, 5, 0, 4000, 0, 0, 'a0000000-0000-4000-8000-000000000003' FROM app.pack_releases WHERE id = 'f0000000-0000-4000-8000-000000000001'$$,
    '23514', NULL, 'an unknown manifest version is rejected');
SELECT lives_ok($$INSERT INTO content.pack_manifests (pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes, lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes, optional_asset_bytes, recorded_by)
    SELECT id, 'pack-manifest-1', 1, manifest_sha256, 96, 1, 5, 0, 4000, 0, 0, 'a0000000-0000-4000-8000-000000000003' FROM app.pack_releases WHERE id = 'f0000000-0000-4000-8000-000000000001'$$,
    'a row that matches the release exactly is accepted');
SELECT throws_ok($$UPDATE content.pack_manifests SET content_format = 2$$, 'P0001', 'Recorded pack manifests are append-only', 'a recorded manifest cannot be edited');
SELECT throws_ok($$DELETE FROM content.pack_manifests$$, 'P0001', 'Recorded pack manifests are append-only', 'a recorded manifest cannot be deleted');
SELECT throws_ok($$INSERT INTO content.pack_manifests (pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes, lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes, optional_asset_bytes, recorded_by)
    SELECT id, 'pack-manifest-1', 1, manifest_sha256, 96, 1, 5, 0, 4000, 0, 0, 'a0000000-0000-4000-8000-000000000003' FROM app.pack_releases WHERE id = 'f0000000-0000-4000-8000-000000000001'$$,
    '23505', NULL, 'a release has one recorded manifest');

-- ================================ helpers ================================
SELECT is(content.blocks_required_format((SELECT blocks FROM app.lesson_revisions WHERE id = :SEED_REV)), 1::smallint, 'the seed lesson is format 1');
SELECT is(content.blocks_required_format('[{"key":"a","type":"paragraph","text":"x"},{"key":"m","type":"math","notation":"edu-math-1","source":"x","alt":"x"}]'), 2::smallint, 'a math block makes a lesson format 2');
SELECT is((SELECT array_agg(content.blocks_required_format(jsonb_build_array(jsonb_build_object('type', t))) ORDER BY t)
           FROM unnest(ARRAY['audio','callout','example','heading','image','list','paragraph','table']) t),
    ARRAY[2,1,1,1,2,2,1,2]::smallint[], 'exactly the four format-1 block types are format 1');
SELECT is(content.blocks_required_format('[{"type":"html"}]'), 2::smallint, 'an unknown block type is never mistaken for format 1');
SELECT is(content.blocks_required_format('[{"key":"no-type"}]'), 2::smallint, 'a block without a type is never mistaken for format 1');
SELECT is(content.blocks_required_format('{"type":"paragraph"}'), NULL, 'a body that is not an array has no format');
SELECT is(content.revision_required_format(:SEED_REV), 1::smallint, 'the seed revision (v1 blocks, mcq only) requires format 1');
SELECT is(content.revision_required_format(gen_random_uuid()), NULL, 'an unknown revision has no format');
INSERT INTO app.question_revisions (lesson_revision_id, question_key, position, kind, prompt, response_spec, answer_key, explanation)
VALUES (:PLAIN, 'num', 1, 'numeric', '{"text":"?"}', '{"allow_fraction":false}', '{"scoring_version":"numeric-v1","value":"1","tolerance":"0"}', '{"text":"."}');
SELECT is(content.revision_required_format(:PLAIN), 2::smallint, 'a non-mcq question makes a revision format 2 even with format-1 blocks');
SELECT is(content.release_required_format('f0000000-0000-4000-8000-000000000001'), 1::smallint, 'the seed release requires format 1');
SELECT is(content.release_required_format(gen_random_uuid()), NULL, 'an unknown or empty release has no format');
SELECT is((SELECT array_agg(h ORDER BY h) FROM content.block_asset_hashes(
    '[{"type":"image","asset":{"sha256":"aa"}},{"type":"audio","asset":{"sha256":"bb"}},{"type":"math","asset":{"sha256":"aa"}},{"type":"paragraph","text":"x"},{"type":"image","asset":"cc"},"junk"]') h),
    ARRAY['aa','bb'], 'referenced asset hashes are collected once each, junk is ignored');
SELECT is((SELECT count(*)::int FROM content.block_asset_hashes('{"asset":{"sha256":"aa"}}')), 0, 'a non-array body references nothing');
SELECT is(content.asset_object_key('\x00ff'::bytea), 'assets/sha256/00/00ff', 'object keys are sharded by the first hash byte');
SELECT ok(content.is_locale_text_map('{"fr":"a","ht":"b"}', 10), 'a two-locale text map is accepted');
SELECT ok(NOT content.is_locale_text_map(NULL, 10), 'NULL is not a text map');
SELECT ok(NOT content.is_locale_text_map('"fr"', 10), 'a string is not a text map');
SELECT ok(content.is_locale_text_map('{"fr":"x < 3"}', 10), 'a comparison sign is plain text, not markup');

SELECT * FROM finish();
ROLLBACK;
