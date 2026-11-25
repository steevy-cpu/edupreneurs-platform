-- The staff write path of the `content` schema: role matrix, input checks,
-- audit trail, and the manifest record. Statements run AS edu_staff (the staff
-- API role) with a verified actor, exactly as the staff API would.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_worker TO postgres WITH INHERIT FALSE, SET TRUE;
CREATE FUNCTION pg_temp.as_role(p_role text, p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    EXECUTE format('SET LOCAL ROLE %I', p_role);
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE || ':' || SQLERRM;
    END;
    EXECUTE 'RESET ROLE';
    PERFORM set_config('edu.actor_id', '', true);
    RETURN v_out;
END;
$fn$;
-- Same, keeping only 'ERROR:<sqlstate>' for failures.
CREATE FUNCTION pg_temp.code(p_role text, p_actor uuid, p_sql text) RETURNS text
LANGUAGE sql AS $fn$ SELECT substr(r, 1, CASE WHEN r LIKE 'ERROR:%' THEN 11 ELSE length(r) END) FROM pg_temp.as_role(p_role, p_actor, p_sql) r $fn$;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set REVIEWER '''a0000000-0000-4000-8000-000000000004'''
\set PUBLISHER '''a0000000-0000-4000-8000-000000000142'''
\set ADMIN '''a0000000-0000-4000-8000-000000000143'''
\set EXEDITOR '''a0000000-0000-4000-8000-000000000144'''
\set REV '''c0000000-0000-4000-8000-000000001421'''
\set REL '''f0000000-0000-4000-8000-000000001421'''

-- Synthetic staff: a publisher, an admin, and an editor whose role is inactive.
INSERT INTO auth.users (instance_id, id, aud, role, email)
SELECT '00000000-0000-0000-0000-000000000000', id, 'authenticated', 'authenticated', email FROM (VALUES
  (:PUBLISHER::uuid, 'publisher.142@edupreneur.test'),
  (:ADMIN::uuid, 'admin.142@edupreneur.test'),
  (:EXEDITOR::uuid, 'former.editor.142@edupreneur.test')) AS u(id, email);
INSERT INTO app.staff_roles (user_id, role, is_active) VALUES
  (:PUBLISHER, 'publisher', true), (:ADMIN, 'admin', true), (:EXEDITOR, 'editor', false);
INSERT INTO app.content_sources (id, source_title, rights_status) VALUES
  ('e0000000-0000-4000-8000-000000001421', 'Synthetic source, rights not verified', 'unverified');

-- Audit rows written by THIS test transaction (earlier, committed rows are older than now()).
CREATE VIEW pg_temp.new_audit AS SELECT * FROM app.audit_events WHERE created_at >= now();
CREATE FUNCTION pg_temp.audits(p_action text) RETURNS integer LANGUAGE sql AS
$fn$ SELECT count(*)::int FROM pg_temp.new_audit WHERE action = p_action $fn$;

-- ============================ register_asset: who ============================
CREATE FUNCTION pg_temp.q_register() RETURNS text LANGUAGE sql AS $fn$ SELECT $q$SELECT content.register_asset(sha256('img-142'), 1200, 'image/png', 320, 180, NULL, '{"fr": "Un schéma synthétique"}', 'e0000000-0000-4000-8000-000000000001') ->> 'created'$q$::text $fn$;
SELECT is(pg_temp.code('edu_staff', NULL, pg_temp.q_register()), 'ERROR:42501', 'no actor: refused');
SELECT is(pg_temp.code('edu_staff', :A::uuid, pg_temp.q_register()), 'ERROR:42501', 'a learner identity on the staff connection: refused');
SELECT is(pg_temp.code('edu_staff', :REVIEWER::uuid, pg_temp.q_register()), 'ERROR:42501', 'reviewer: may not register assets');
SELECT is(pg_temp.code('edu_staff', :PUBLISHER::uuid, pg_temp.q_register()), 'ERROR:42501', 'publisher: may not register assets');
SELECT is(pg_temp.code('edu_staff', :EXEDITOR::uuid, pg_temp.q_register()), 'ERROR:42501', 'an INACTIVE editor role does not count');
SELECT is(pg_temp.code('edu_api', :EDITOR::uuid, pg_temp.q_register()), 'ERROR:42501', 'the student API role cannot call it, even as an editor');
SELECT is(pg_temp.code('edu_worker', :EDITOR::uuid, pg_temp.q_register()), 'ERROR:42501', 'the worker role cannot call it');
SELECT is((SELECT count(*)::int FROM content.assets WHERE sha256 = sha256('img-142')), 0, 'refused calls wrote nothing');
SELECT is(pg_temp.audits('content.asset.register'), 0, 'refused calls left no "allowed" audit row');

SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, pg_temp.q_register()), 'true', 'editor: registers an asset');
SELECT is((SELECT created_by::text || '|' || object_key FROM content.assets WHERE sha256 = sha256('img-142')),
    'a0000000-0000-4000-8000-000000000003|' || content.asset_object_key(sha256('img-142')),
    'the author is the verified actor and the key is derived from the hash');
SELECT is((SELECT actor_id::text || '|' || target_kind || '|' || outcome || '|' || (details ->> 'sha256') || '|' || (details ->> 'mime')
           FROM pg_temp.new_audit WHERE action = 'content.asset.register'),
    'a0000000-0000-4000-8000-000000000003|content_asset|allowed|' || encode(sha256('img-142'), 'hex') || '|image/png',
    'the registration is audited with ids and codes');
SELECT ok((SELECT NOT (details ? 'alt_text') AND details::text NOT LIKE '%synth%' FROM pg_temp.new_audit WHERE action = 'content.asset.register'),
    'the audit row carries no typed text (alt text is not copied)');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN::uuid, pg_temp.q_register()), 'false', 'same file, same metadata again: idempotent, nothing created');
SELECT is(pg_temp.audits('content.asset.register'), 1, 'the idempotent repeat is not audited as a second registration');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(sha256('img-142'), 1201, 'image/png', 320, 180, NULL, '{"fr": "x"}', 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:23505', 'same hash with a different size: refused');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(sha256('img-142'), 1200, 'image/png', 320, 180, NULL, '{"fr": "x"}', 'e0000000-0000-4000-8000-000000001421')$$), 'ERROR:23505', 'same hash under a different source: refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN::uuid, $$SELECT content.register_asset(sha256('img-142-unverified'), 900, 'image/webp', 100, 100, NULL, '{"ht": "Yon desen"}', 'e0000000-0000-4000-8000-000000001421') ->> 'created'$$), 'true', 'admin: registers an asset (from a source not cleared yet)');

-- ============================ register_asset: what ============================
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset('\x0102', 10, 'image/png', 1, 1, NULL, '{"fr": "x"}', 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:22023', 'a hash that is not 32 bytes: refused');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(NULL, 10, 'image/png', 1, 1, NULL, '{"fr": "x"}', 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:22023', 'NULL arguments: refused');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(sha256('n1'), 10, 'image/png', 1, 1, NULL, '{"fr": "x"}', gen_random_uuid())$$), 'ERROR:22023', 'unknown source: refused');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(sha256('n2'), 10, 'image/svg+xml', 1, 1, NULL, '{"fr": "x"}', 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:23514', 'SVG: refused by the allow-list');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(sha256('n3'), 200001, 'image/png', 1, 1, NULL, '{"fr": "x"}', 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:23514', 'over the byte budget: refused');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(sha256('n4'), 10, 'image/png', 1, 1, NULL, '{"fr": "<b>x</b>"}', 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:23514', 'markup in alt text: refused');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(sha256('n5'), 10, 'audio/mp4', NULL, NULL, NULL, '{"fr": "x"}', 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:23514', 'audio without duration: refused');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(sha256('n6'), 10, 'image/png', 1, 1, NULL, jsonb_build_object('fr', repeat('a', 5000)), 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:22023', 'oversized alt text payload: refused before any work');
-- edu_staff has no way around the functions.
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, 'SELECT count(*) FROM content.assets'), 'ERROR:42501', 'edu_staff cannot read the tables directly');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$UPDATE content.assets SET alt_text = '{"fr":"x"}' RETURNING 1$$), 'ERROR:42501', 'edu_staff cannot write the tables directly');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.staff_gate('editor')$$), 'ERROR:42501', 'edu_staff cannot call the internal seam');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.audit('content.asset.register', 'content_asset', NULL, '{}')$$), 'ERROR:42501', 'edu_staff cannot write content audit rows by hand');

-- ============================ attach / detach ============================
INSERT INTO app.lesson_revisions (id, lesson_id, revision, locale, title, blocks, created_by) VALUES
  (:REV, 'b0000000-0000-4000-8000-000000000005', 1421, 'fr', 'content fixture 1421',
   jsonb_build_array(
     jsonb_build_object('key', 'p', 'type', 'paragraph', 'text', 'x'),
     jsonb_build_object('key', 'i', 'type', 'image', 'alt', 'x', 'asset', jsonb_build_object(
        'sha256', encode(sha256('img-142'), 'hex'), 'mime', 'image/png', 'bytes', 1200, 'width', 320, 'height', 180))),
   :EDITOR);
INSERT INTO app.question_revisions (id, lesson_revision_id, question_key, position, kind, prompt, response_spec, answer_key, explanation) VALUES
  ('d0000000-0000-4000-8000-000000001421', :REV, 'q', 1, 'mcq', '{"text":"?"}', '{"choices":[{"id":"a","text":"1"},{"id":"b","text":"2"}]}', '{"correct_choice_id":"a"}', '{"text":"."}');

CREATE FUNCTION pg_temp.q_attach() RETURNS text LANGUAGE sql AS $fn$ SELECT $q$SELECT content.attach_asset('c0000000-0000-4000-8000-000000001421', sha256('img-142')) ->> 'attached'$q$::text $fn$;
SELECT is(pg_temp.code('edu_staff', :REVIEWER::uuid, pg_temp.q_attach()), 'ERROR:42501', 'reviewer: may not attach assets');
SELECT is(pg_temp.code('edu_staff', :PUBLISHER::uuid, pg_temp.q_attach()), 'ERROR:42501', 'publisher: may not attach assets');
SELECT is(pg_temp.code('edu_staff', NULL, pg_temp.q_attach()), 'ERROR:42501', 'no actor: may not attach assets');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, pg_temp.q_attach()), 'ERROR:23503', 'editor: refused while the revision does not cite the asset''s source');
INSERT INTO app.lesson_revision_sources VALUES (:REV, 'e0000000-0000-4000-8000-000000000001');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, pg_temp.q_attach()), 'true', 'editor: attaches the asset to the draft');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, pg_temp.q_attach()), 'false', 'attaching again is a no-op');
SELECT is((SELECT attached_by::text || '|' || source_id::text FROM content.revision_assets WHERE lesson_revision_id = :REV),
    'a0000000-0000-4000-8000-000000000003|e0000000-0000-4000-8000-000000000001', 'the link records the actor and the asset''s source');
SELECT is((SELECT count(*)::int FROM pg_temp.new_audit WHERE action = 'content.asset.attach' AND target_kind = 'lesson_revision' AND target_id = :REV AND actor_id = :EDITOR), 1, 'the attachment is audited once');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.attach_asset('c0000000-0000-4000-8000-000000001421', sha256('never-registered'))$$), 'ERROR:22023', 'unknown asset: refused');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.attach_asset(gen_random_uuid(), sha256('img-142'))$$), 'ERROR:22023', 'unknown revision: refused');
SELECT is(pg_temp.code('edu_staff', :EDITOR::uuid, $$SELECT content.attach_asset('c0000000-0000-4000-8000-000000001421', sha256('img-142-unverified'))$$), 'ERROR:23503', 'an asset from an uncited (uncleared) source: refused');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT content.attach_asset('c0000000-0000-4000-8000-000000000001', sha256('img-142'))$$),
    'ERROR:P0001:Assets of reviewed/approved/packed lesson revisions are frozen', 'the published seed revision accepts no asset, even from an editor');
SELECT is(pg_temp.code('edu_staff', :REVIEWER::uuid, $$SELECT content.detach_asset('c0000000-0000-4000-8000-000000001421', sha256('img-142'))$$), 'ERROR:42501', 'reviewer: may not detach');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT content.detach_asset('c0000000-0000-4000-8000-000000001421', sha256('img-142')) ->> 'detached'$$), 'true', 'the author detaches from the draft (was: admin; since 20261125000300 only the author may)');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT content.detach_asset('c0000000-0000-4000-8000-000000001421', sha256('img-142')) ->> 'detached'$$), 'false', 'detaching again is a no-op');
SELECT is(pg_temp.audits('content.asset.detach'), 1, 'only the real detachment is audited');

-- ============================ record_release_manifest ============================
-- A lesson that references an asset which is NOT attached cannot be recorded.
UPDATE app.lesson_revisions SET status = 'in_review' WHERE id = :REV;
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES (:REV, :REVIEWER, 'changes_requested');
-- (the review froze the asset list without the asset: this revision is now unpackable by design)
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES (:REV, :REVIEWER, 'approved');
UPDATE app.lesson_revisions SET status = 'approved', approved_by = :REVIEWER, approved_at = now() WHERE id = :REV;
INSERT INTO app.pack_releases (id, pack_key, revision, locale, created_by) VALUES (:REL, 'content-142', 1, 'fr', :EDITOR);
INSERT INTO app.pack_items VALUES (:REL, :REV, 1);

-- The manifest the builder would produce for a release, with overridable parts.
CREATE FUNCTION pg_temp.manifest(
    p_release uuid, p_revision uuid, p_format integer DEFAULT 2, p_with_asset boolean DEFAULT true,
    p_asset_bytes bigint DEFAULT 1200, p_pack_key text DEFAULT 'content-142', p_questions integer DEFAULT 1)
RETURNS jsonb LANGUAGE sql AS $fn$
    SELECT jsonb_build_object(
        'manifest_version', 'pack-manifest-1', 'content_format', p_format,
        'pack', jsonb_build_object('release_id', p_release, 'pack_key', p_pack_key, 'locale', 'fr', 'revision', 1),
        'lessons', jsonb_build_array(jsonb_build_object('position', 1, 'revision_id', p_revision, 'bytes', 700)),
        'assets', CASE WHEN p_with_asset THEN jsonb_build_array(jsonb_build_object(
            'sha256', encode(sha256('img-142'), 'hex'), 'bytes', p_asset_bytes, 'mime', 'image/png', 'required', true))
            ELSE '[]'::jsonb END,
        'totals', jsonb_build_object('lessons', 1, 'questions', p_questions,
            'assets', CASE WHEN p_with_asset THEN 1 ELSE 0 END, 'lesson_bytes', 700,
            'required_asset_bytes', CASE WHEN p_with_asset THEN p_asset_bytes ELSE 0 END, 'optional_asset_bytes', 0))
$fn$;
SELECT is(pg_temp.as_role('edu_staff', :PUBLISHER::uuid, format($$SELECT content.record_release_manifest(%L, convert_to(pg_temp.manifest(%L, %L)::text, 'UTF8'))$$, :REL, :REL, :REV)),
    'ERROR:22023:A packed lesson references an asset that is not attached to it', 'a referenced but unattached asset blocks the record');
SELECT is((SELECT status FROM app.pack_releases WHERE id = :REL), 'building', 'the release stays building');

-- A second revision, with the asset attached before review: the normal path.
\set REV2 '''c0000000-0000-4000-8000-000000001422'''
\set REL2 '''f0000000-0000-4000-8000-000000001422'''
INSERT INTO app.lesson_revisions (id, lesson_id, revision, locale, title, blocks, created_by)
SELECT :REV2, lesson_id, 1422, 'fr', 'content fixture 1422', blocks, :EDITOR FROM app.lesson_revisions WHERE id = :REV;
INSERT INTO app.question_revisions (lesson_revision_id, question_key, position, kind, prompt, response_spec, answer_key, explanation) VALUES
  (:REV2, 'q', 1, 'mcq', '{"text":"?"}', '{"choices":[{"id":"a","text":"1"},{"id":"b","text":"2"}]}', '{"correct_choice_id":"a"}', '{"text":"."}');
INSERT INTO app.lesson_revision_sources VALUES (:REV2, 'e0000000-0000-4000-8000-000000000001');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT content.attach_asset('c0000000-0000-4000-8000-000000001422', sha256('img-142')) ->> 'attached'$$), 'true', 'fixture: asset attached to the second draft');
UPDATE app.lesson_revisions SET status = 'in_review' WHERE id = :REV2;
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES (:REV2, :REVIEWER, 'approved');
UPDATE app.lesson_revisions SET status = 'approved', approved_by = :REVIEWER, approved_at = now() WHERE id = :REV2;
INSERT INTO app.pack_releases (id, pack_key, revision, locale, created_by) VALUES (:REL2, 'content-142', 2, 'fr', :EDITOR);
INSERT INTO app.pack_items VALUES (:REL2, :REV2, 1);

CREATE FUNCTION pg_temp.record(p_actor uuid, p_manifest text, p_role text DEFAULT 'edu_staff') RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.as_role(p_role, p_actor, format(
        'SELECT content.record_release_manifest(%L, convert_to((%s)::text, %L)) ->> %L',
        'f0000000-0000-4000-8000-000000001422', p_manifest, 'UTF8', 'status'))
$fn$;
CREATE FUNCTION pg_temp.q_good() RETURNS text LANGUAGE sql AS $fn$ SELECT $q$pg_temp.manifest('f0000000-0000-4000-8000-000000001422', 'c0000000-0000-4000-8000-000000001422', 2, true, 1200, 'content-142', 1) || jsonb_build_object('pack', jsonb_build_object('release_id', 'f0000000-0000-4000-8000-000000001422', 'pack_key', 'content-142', 'locale', 'fr', 'revision', 2))$q$::text $fn$;

SELECT is(substr(pg_temp.record(NULL, pg_temp.q_good()), 1, 11), 'ERROR:42501', 'no actor: may not record a manifest');
SELECT is(substr(pg_temp.record(:A::uuid, pg_temp.q_good()), 1, 11), 'ERROR:42501', 'learner identity: may not record a manifest');
SELECT is(substr(pg_temp.record(:EDITOR::uuid, pg_temp.q_good()), 1, 11), 'ERROR:42501', 'editor: may not record a manifest (publishing is a separate duty)');
SELECT is(substr(pg_temp.record(:REVIEWER::uuid, pg_temp.q_good()), 1, 11), 'ERROR:42501', 'reviewer: may not record a manifest');
SELECT is(substr(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good(), 'edu_api'), 1, 11), 'ERROR:42501', 'the student API role cannot call it, even as a publisher');
SELECT is(substr(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good(), 'edu_worker'), 1, 11), 'ERROR:42501', 'the worker role cannot call it');

SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || '{"content_format": 1}'$$),
    'ERROR:22023:Pack declares content format 1 but contains format-2 content', 'NEGOTIATION RULE: a format-1 pack cannot contain a format-2 lesson');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || '{"content_format": 3}'$$), 'ERROR:22023:Unsupported content format', 'unknown content format: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, $$pg_temp.manifest('f0000000-0000-4000-8000-000000001422', 'c0000000-0000-4000-8000-000000001422')$$),
    'ERROR:22023:Manifest describes a different pack release', 'a manifest for another revision number of the pack: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || jsonb_build_object('lessons', jsonb_build_array(jsonb_build_object('position', 1, 'revision_id', 'c0000000-0000-4000-8000-000000000001', 'bytes', 700)))$$),
    'ERROR:22023:Manifest lessons do not match the items of the pack release', 'a manifest listing another lesson: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || jsonb_build_object('lessons', jsonb_build_array(jsonb_build_object('position', 2, 'revision_id', 'c0000000-0000-4000-8000-000000001422', 'bytes', 700)))$$),
    'ERROR:22023:Manifest lessons do not match the items of the pack release', 'a manifest with the wrong lesson order: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || '{"lessons": []}'$$),
    'ERROR:22023:Manifest lessons do not match the items of the pack release', 'a manifest that drops a lesson: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || '{"assets": []}'$$),
    'ERROR:22023:Manifest assets do not match the assets recorded for this pack', 'a manifest that omits an asset: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || jsonb_build_object('assets', jsonb_build_array(jsonb_build_object('sha256', encode(sha256('img-142'), 'hex'), 'bytes', 1199, 'mime', 'image/png', 'required', true)))$$),
    'ERROR:22023:Manifest assets do not match the assets recorded for this pack', 'a manifest with a wrong asset size: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || jsonb_build_object('assets', jsonb_build_array(jsonb_build_object('sha256', encode(sha256('img-142'), 'hex'), 'bytes', 1200, 'mime', 'image/png', 'required', false)))$$),
    'ERROR:22023:Manifest assets do not match the assets recorded for this pack', 'an image declared optional: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || jsonb_build_object('totals', jsonb_build_object('lessons', 1, 'questions', 9, 'assets', 1, 'lesson_bytes', 700, 'required_asset_bytes', 1200, 'optional_asset_bytes', 0))$$),
    'ERROR:22023:Manifest totals are inconsistent', 'wrong totals: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || jsonb_build_object('lessons', jsonb_build_array(jsonb_build_object('position', 1, 'revision_id', 'not-a-uuid', 'bytes', 700)))$$),
    'ERROR:22023:Malformed manifest', 'a malformed id inside the manifest is a clean error');
SELECT is(pg_temp.record(:PUBLISHER::uuid, $$'{"manifest_version": "pack-manifest-1"}'::jsonb$$), 'ERROR:22023:Malformed manifest', 'an incomplete manifest is a clean error');
SELECT is(pg_temp.record(:PUBLISHER::uuid, $$'[]'::jsonb$$), 'ERROR:22023:Malformed manifest record', 'a manifest that is not an object: refused');
SELECT is(pg_temp.code('edu_staff', :PUBLISHER::uuid, $$SELECT content.record_release_manifest(gen_random_uuid(), '{}'::bytea)$$), 'ERROR:22023', 'unknown release: refused');
SELECT is(pg_temp.code('edu_staff', :PUBLISHER::uuid, $$SELECT content.record_release_manifest('f0000000-0000-4000-8000-000000000001', '{}'::bytea)$$), 'ERROR:55000', 'a release that is already active: refused');

-- ---- review H2 (a): the hash and the size come from the bytes, the bytes must be a JSON object ----
CREATE FUNCTION pg_temp.good_bytes() RETURNS bytea LANGUAGE plpgsql AS $fn$
DECLARE v bytea;
BEGIN
    EXECUTE 'SELECT convert_to((' || pg_temp.q_good() || ')::text, ''UTF8'')' INTO v;
    RETURN v;
END $fn$;
CREATE FUNCTION pg_temp.record_bytes(p_bytes_sql text) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.as_role('edu_staff', 'a0000000-0000-4000-8000-000000000142', format(
        'SELECT content.record_release_manifest(%L, %s) ->> %L', 'f0000000-0000-4000-8000-000000001422', p_bytes_sql, 'status'))
$fn$;
SELECT is((SELECT count(*)::int FROM pg_proc WHERE pronamespace = 'content'::regnamespace AND proname = 'record_release_manifest' AND pronargs <> 2), 0,
    'H2: the signature that took a caller-asserted hash and size no longer exists');
SELECT is(pg_temp.record_bytes($$NULL::bytea$$), 'ERROR:22023:Malformed manifest record', 'H2: no bytes: refused');
SELECT is(pg_temp.record_bytes($$''::bytea$$), 'ERROR:22023:Malformed manifest record', 'H2: empty bytes: refused');
SELECT is(pg_temp.record_bytes($$'\xff7b7d'::bytea$$), 'ERROR:22023:Malformed manifest record', 'H2: bytes that do not start with an object: refused');
SELECT is(pg_temp.record_bytes($$'\x7bff7d'::bytea$$), 'ERROR:22023:Malformed manifest record', 'H2: invalid UTF-8: refused');
SELECT is(pg_temp.record_bytes($$'\x7b007d'::bytea$$), 'ERROR:22023:Malformed manifest record', 'H2: a NUL byte: refused');
SELECT is(pg_temp.record_bytes($$convert_to('{not json}', 'UTF8')$$), 'ERROR:22023:Malformed manifest record', 'H2: text that is not JSON: refused');
SELECT is(pg_temp.record_bytes($$pg_temp.good_bytes() || '\x0a'::bytea$$), 'ERROR:22023:Malformed manifest record', 'H2: a trailing line break is not the stored manifest: refused');
SELECT is(pg_temp.record_bytes($$'\xefbbbf'::bytea || pg_temp.good_bytes()$$), 'ERROR:22023:Malformed manifest record', 'H2: a byte-order mark: refused');
SELECT is(pg_temp.record_bytes($$convert_to(repeat('[', 100000), 'UTF8')$$), 'ERROR:22023:Malformed manifest record', 'H2: hostile nesting: a clean refusal');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || '{"evil": 1}'$$), 'ERROR:22023:Malformed manifest', 'H2: an unknown top-level property: refused');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || jsonb_build_object('totals', jsonb_build_object('lessons', 1, 'questions', 1, 'assets', 1, 'lesson_bytes', 700, 'required_asset_bytes', 1200, 'optional_asset_bytes', 0, 'extra', 1))$$),
    'ERROR:22023:Malformed manifest', 'H2: an unknown property in totals: refused');

-- ---- review L5: counts and sizes outside the contract are a clean 22023, never a constraint error ----
CREATE FUNCTION pg_temp.q_sizes(p_lesson_bytes text, p_total_lesson_bytes text) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.q_good() || format(
        $q$ || jsonb_build_object('lessons', jsonb_build_array(jsonb_build_object('position', 1, 'revision_id', 'c0000000-0000-4000-8000-000000001422') || %L::jsonb),
               'totals', jsonb_build_object('lessons', 1, 'questions', 1, 'assets', 1, 'required_asset_bytes', 1200, 'optional_asset_bytes', 0) || %L::jsonb)$q$,
        p_lesson_bytes, p_total_lesson_bytes)
$fn$;
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_sizes('{"bytes": -5}', '{"lesson_bytes": -5}')), 'ERROR:22023:Malformed manifest', 'L5: negative lesson bytes: 22023');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_sizes('{}', '{"lesson_bytes": 0}')), 'ERROR:22023:Malformed manifest', 'L5: missing lesson bytes: 22023');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_sizes('{"bytes": 700}', '{}')), 'ERROR:22023:Malformed manifest', 'L5: missing total: 22023');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_sizes('{"bytes": 0}', '{"lesson_bytes": 0}')), 'ERROR:22023:Malformed manifest', 'L5: zero lesson bytes: 22023');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_sizes('{"bytes": 9223372036854775807}', '{"lesson_bytes": 9223372036854775807}')), 'ERROR:22023:Malformed manifest', 'L5: bigint-max lesson bytes: 22023 (no overflow)');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_sizes('{"bytes": 1e30}', '{"lesson_bytes": 1e30}')), 'ERROR:22023:Malformed manifest', 'L5: a number beyond bigint: 22023');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_sizes('{"bytes": 700.5}', '{"lesson_bytes": 700.5}')), 'ERROR:22023:Malformed manifest', 'L5: fractional bytes: 22023');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_sizes('{"bytes": "700"}', '{"lesson_bytes": "700"}')), 'ERROR:22023:Malformed manifest', 'L5: bytes written as text: 22023');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_sizes('{"bytes": 262145}', '{"lesson_bytes": 262145}')), 'ERROR:22023:Malformed manifest', 'L5: a lesson object above the contract limit: 22023');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || jsonb_build_object('totals', jsonb_build_object('lessons', 1, 'questions', -1, 'assets', 1, 'lesson_bytes', 700, 'required_asset_bytes', 1200, 'optional_asset_bytes', 0))$$),
    'ERROR:22023:Malformed manifest', 'L5: a negative question count: 22023');
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good() || $$ || jsonb_build_object('totals', jsonb_build_object('lessons', 1, 'questions', 1, 'assets', 1, 'lesson_bytes', 700, 'required_asset_bytes', 1200, 'optional_asset_bytes', -1))$$),
    'ERROR:22023:Malformed manifest', 'L5: negative optional bytes: 22023');

-- ---- review H2 (b): the body gate ----
SELECT is(content.blocks_accountable(blocks), true, 'body gate: the fixture lesson body is contract-shaped') FROM app.lesson_revisions WHERE id = :REV2;
SELECT is((SELECT bool_and(content.blocks_accountable(lr.blocks)) FROM app.lesson_revisions lr), true, 'body gate: every lesson body in the seed is contract-shaped');
SELECT is(content.blocks_accountable(b.body::jsonb), b.expected, 'body gate: ' || b.label)
FROM (VALUES
    ('[{"key":"a","type":"paragraph","text":"x"}]', true, 'a paragraph'),
    ('[{"key":"m","type":"math","notation":"edu-math-1","source":"x","alt":"x"}]', true, 'math without an image'),
    ('[{"key":"i","type":"image","alt":"x","asset":{"sha256":"' || repeat('ab', 32) || '","mime":"image/png","bytes":1,"width":1,"height":1}}]', true, 'an image with a contract-shaped asset'),
    ('[{"key":"l","type":"list","style":"bullet","items":["a"]},{"key":"t","type":"table","caption":"c","columns":["a","b"],"rows":[["1","2"]],"row_headers":true}]', true, 'list and table'),
    (NULL, false, 'NULL'),
    ('{}', false, 'not an array'),
    ('[]', false, 'an empty body'),
    ('["x"]', false, 'a block that is not an object'),
    ('[{"key":"a","text":"x"}]', false, 'a block without a type'),
    ('[{"key":"a","type":["paragraph"],"text":"x"}]', false, 'a type that is not a string'),
    ('[{"type":"html","html":"x"}]', false, 'an unknown block type'),
    ('[{"key":"a","type":"Paragraph","text":"x"}]', false, 'a type in another case'),
    ('[{"key":"a","type":"paragraph","text":"x","src":"https://example.invalid/x.png"}]', false, 'a property the type does not have (remote reference)'),
    ('[{"key":"a","type":"paragraph","text":"x","asset":{"sha256":"' || repeat('ab', 32) || '"}}]', false, 'an asset on a block type that has none'),
    ('[{"key":"i","type":"image","alt":"x"}]', false, 'an image without an asset'),
    ('[{"key":"i","type":"image","alt":"x","asset":["' || repeat('ab', 32) || '"]}]', false, 'an asset that is an array'),
    ('[{"key":"i","type":"image","alt":"x","asset":"' || repeat('ab', 32) || '"}]', false, 'an asset that is a bare string'),
    ('[{"key":"i","type":"image","alt":"x","asset":null}]', false, 'a null asset'),
    ('[{"key":"i","type":"image","alt":"x","asset":{}}]', false, 'an asset without sha256'),
    ('[{"key":"i","type":"image","alt":"x","asset":{"sha256":["' || repeat('ab', 32) || '"]}}]', false, 'a sha256 that is not a string'),
    ('[{"key":"i","type":"image","alt":"x","asset":{"sha256":"' || repeat('AB', 32) || '"}}]', false, 'an upper-case sha256'),
    ('[{"key":"i","type":"image","alt":"x","asset":{"sha256":"' || repeat('ab', 31) || '"}}]', false, 'a short sha256'),
    ('[{"key":"i","type":"image","alt":"x","asset":{"sha256":"' || repeat('ab', 32) || '\n"}}]', false, 'a sha256 followed by a line feed'),
    ('[{"key":"a","type":"paragraph","text":"x"},{"type":"html"}]', false, 'one bad block among good ones')
) AS b(body, expected, label);

-- The reviewer's reproduction: an approved revision whose body has an unknown block
-- type, a remote reference and an asset reference in a shape the rights gate cannot
-- see. (The baseline accepts any jsonb array as a body.) It can no longer become 'ready'.
\set REV3 '''c0000000-0000-4000-8000-000000001423'''
\set REL3 '''f0000000-0000-4000-8000-000000001423'''
INSERT INTO app.lesson_revisions (id, lesson_id, revision, locale, title, blocks, created_by)
SELECT :REV3, lesson_id, 1423, 'fr', 'content fixture 1423',
       jsonb_build_array(
           jsonb_build_object('key', 'i', 'type', 'image', 'alt', '<script>x</script>', 'src', 'https://example.invalid/x.png',
                              'asset', jsonb_build_array(encode(sha256('img-142'), 'hex'))),
           jsonb_build_object('type', 'html', 'html', '<script>x</script>')),
       :EDITOR FROM app.lesson_revisions WHERE id = :REV;
INSERT INTO app.lesson_revision_sources VALUES (:REV3, 'e0000000-0000-4000-8000-000000000001');
UPDATE app.lesson_revisions SET status = 'in_review' WHERE id = :REV3;
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES (:REV3, :REVIEWER, 'approved');
UPDATE app.lesson_revisions SET status = 'approved', approved_by = :REVIEWER, approved_at = now() WHERE id = :REV3;
INSERT INTO app.pack_releases (id, pack_key, revision, locale, created_by) VALUES (:REL3, 'content-142', 3, 'fr', :EDITOR);
INSERT INTO app.pack_items VALUES (:REL3, :REV3, 1);
SELECT is(pg_temp.as_role('edu_staff', :PUBLISHER::uuid, $$SELECT content.record_release_manifest('f0000000-0000-4000-8000-000000001423',
        convert_to((pg_temp.manifest('f0000000-0000-4000-8000-000000001423', 'c0000000-0000-4000-8000-000000001423', 2, false, 0, 'content-142', 0)
            || jsonb_build_object('pack', jsonb_build_object('release_id', 'f0000000-0000-4000-8000-000000001423', 'pack_key', 'content-142', 'locale', 'fr', 'revision', 3)))::text, 'UTF8'))$$),
    'ERROR:22023:A packed lesson body has a block or an asset reference outside the content contract',
    'H2: a release whose lesson body is outside the contract cannot be recorded (the reviewer''s reproduction)');
SELECT is((SELECT status || '|' || (manifest_sha256 IS NULL)::text FROM app.pack_releases WHERE id = :REL3), 'building|true', 'H2: that release stays building, nothing recorded');
SELECT is((SELECT count(*)::int FROM content.pack_manifests WHERE pack_release_id = :REL3), 0, 'H2: no manifest row for it');

SELECT is((SELECT status || '|' || (manifest_sha256 IS NULL)::text FROM app.pack_releases WHERE id = :REL2), 'building|true', 'every refusal left the release untouched');
SELECT is((SELECT count(*)::int FROM content.pack_manifests WHERE pack_release_id = :REL2) + pg_temp.audits('content.pack.manifest_recorded'), 0, 'every refusal recorded and audited nothing');

-- Rights withdrawn before publication: the existing app guard refuses, and nothing is recorded.
UPDATE app.content_sources SET rights_status = 'blocked' WHERE id = 'e0000000-0000-4000-8000-000000000001';
SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good()), 'ERROR:P0001:Pack includes content with uncleared rights', 'withdrawn rights stop the record (app guard, unchanged)');
SELECT is((SELECT count(*)::int FROM content.pack_manifests WHERE pack_release_id = :REL2), 0, 'nothing was recorded');
UPDATE app.content_sources SET rights_status = 'cleared' WHERE id = 'e0000000-0000-4000-8000-000000000001';

SELECT is(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good()), 'ready', 'publisher: records the manifest; the release becomes ready');
SELECT is((SELECT status || '|' || manifest_object_key || '|' || encode(manifest_sha256, 'hex') || '|' || compressed_bytes FROM app.pack_releases WHERE id = :REL2),
    'ready|packs/content-142/fr/2/manifest.json|' || encode(sha256(pg_temp.good_bytes()), 'hex') || '|' || (octet_length(pg_temp.good_bytes()) + 700 + 1200),
    'the release carries the hash and size COMPUTED from the manifest bytes, the canonical key and the total size (manifest + 700 + 1200)');
SELECT is((SELECT encode(manifest_sha256, 'hex') || '|' || manifest_bytes FROM content.pack_manifests WHERE pack_release_id = :REL2),
    encode(sha256(pg_temp.good_bytes()), 'hex') || '|' || octet_length(pg_temp.good_bytes()), 'the manifest record holds the same computed hash and size (review H2)');
SELECT is((SELECT content_format || '|' || lesson_count || '|' || question_count || '|' || asset_count || '|' || recorded_by FROM content.pack_manifests WHERE pack_release_id = :REL2),
    '2|1|1|1|a0000000-0000-4000-8000-000000000142', 'the manifest record holds format, counts and the publisher');
SELECT is((SELECT actor_id::text || '|' || target_kind || '|' || (details ->> 'manifest_sha256') || '|' || (details ->> 'content_format') FROM pg_temp.new_audit WHERE action = 'content.pack.manifest_recorded' AND target_id = :REL2),
    'a0000000-0000-4000-8000-000000000142|pack_release|' || encode(sha256(pg_temp.good_bytes()), 'hex') || '|2', 'the record is audited');
SELECT is(substr(pg_temp.record(:PUBLISHER::uuid, pg_temp.q_good()), 1, 11), 'ERROR:55000', 'a manifest is recorded once: the release is no longer building');
SELECT is(substr(pg_temp.record(:ADMIN::uuid, pg_temp.q_good()), 1, 11), 'ERROR:55000', 'not even an admin can record it again');
SELECT throws_ok($$UPDATE app.pack_releases SET manifest_sha256 = sha256('tampered') WHERE id = 'f0000000-0000-4000-8000-000000001422'$$,
    'P0001', 'Finalized pack contents are immutable', 'the recorded hash is now immutable (app guard)');
SELECT is((SELECT status FROM app.pack_current pc JOIN app.pack_releases r ON r.id = pc.release_id WHERE pc.pack_key = 'content-142'), NULL,
    'recording a manifest does not activate the release or move the current pointer');

SELECT * FROM finish();
ROLLBACK;
