-- account.update_own_profile(): only the caller's own row, validated, audited by field name.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
-- Same helper as 020_rls_isolation.sql: run one statement AS THE STUDENT API
-- ROLE with the given actor. Returns the first column as text or 'ERROR:<sqlstate>'.
CREATE FUNCTION pg_temp.as_api(p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    EXECUTE 'SET LOCAL ROLE edu_api';
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE;
    END;
    EXECUTE 'RESET ROLE';
    PERFORM set_config('edu.actor_id', '', true);
    RETURN v_out;
END;
$fn$;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''

-- Record what the audit seam is asked to write. The replacement lives only in
-- this transaction; it stands in for ops.audit_write() until B1 is merged.
CREATE TEMP TABLE seam_calls (
    n serial, actor uuid, action text, target_kind text, target_id uuid, outcome text, details jsonb);
CREATE OR REPLACE FUNCTION account.audit_seam(
    p_action text, p_target_kind text, p_target_id uuid, p_outcome text, p_details jsonb DEFAULT '{}'::jsonb)
RETURNS uuid LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
    INSERT INTO pg_temp.seam_calls (actor, action, target_kind, target_id, outcome, details)
    VALUES (app.current_actor_id(), p_action, p_target_kind, p_target_id, p_outcome, p_details);
    RETURN NULL;
END;
$fn$;

-- Exact starting point (rolled back with the transaction; nothing is really
-- removed): the API tests may have left a learner profile for the editor.
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
DELETE FROM app.learner_profiles WHERE user_id = :EDITOR::uuid;

-- An extra active grade and an inactive one for the negative cases.
INSERT INTO app.grades (id, code, sort_order, labels, is_active) VALUES
    ('b0000000-0000-4000-8000-0000000000f1', 'NS4', 7001, '{"fr": "Nouveau secondaire 4 (synthétique)"}', true),
    ('b0000000-0000-4000-8000-0000000000f2', 'ZZOFF', 7002, '{"fr": "Classe inactive (synthétique)"}', false);

CREATE TEMP TABLE b_before AS
    SELECT * FROM app.learner_profiles WHERE user_id = :B::uuid;

-- ---- no actor / no profile ------------------------------------------------------
SELECT is(pg_temp.as_api(NULL, $$SELECT account.update_own_profile('{"preferred_locale":"ht"}')$$), 'ERROR:42501', 'no actor: refused');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-0000000000ee', $$SELECT account.update_own_profile('{"preferred_locale":"ht"}')$$), 'ERROR:42501', 'an actor without a profile row: refused');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT account.update_own_profile('{"preferred_locale":"ht"}')$$), 'ERROR:42501', 'the function never creates a profile');

-- ---- A edits A ------------------------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"preferred_locale":"ht"}')$$)::jsonb,
    '{"status":"ok","changed":["preferred_locale"]}'::jsonb, 'A changes language');
SELECT is((SELECT preferred_locale FROM app.learner_profiles WHERE user_id = :A::uuid), 'ht', 'language stored');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"grade_code":"NS4","display_name":"Synthetic A"}')$$)::jsonb,
    '{"status":"ok","changed":["grade_code","display_name"]}'::jsonb, 'A changes grade and name together');
SELECT is((SELECT grade_id::text || '|' || display_name || '|' || preferred_locale FROM app.learner_profiles WHERE user_id = :A::uuid),
    'b0000000-0000-4000-8000-0000000000f1|Synthetic A|ht', 'grade and name stored; omitted field kept');
SELECT ok((SELECT updated_at > created_at FROM app.learner_profiles WHERE user_id = :A::uuid), 'updated_at moved');

SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"grade_code":"NS4","display_name":"Synthetic A","preferred_locale":"ht"}')$$)::jsonb,
    '{"status":"ok","changed":[]}'::jsonb, 'a repeated request changes nothing');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":null}')$$)::jsonb,
    '{"status":"ok","changed":["display_name"]}'::jsonb, 'null clears the display name');
SELECT is((SELECT display_name FROM app.learner_profiles WHERE user_id = :A::uuid), NULL, 'display name cleared');

-- ---- B is untouched; there is no way to name another user -------------------------
SELECT is((SELECT count(*)::int FROM (SELECT * FROM app.learner_profiles WHERE user_id = :B::uuid
                                     EXCEPT SELECT * FROM b_before) d), 0, 'B profile is byte-identical after A edits');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":"x","user_id":"a0000000-0000-4000-8000-000000000002"}')$$), 'ERROR:22023', 'a user_id key is an unknown field');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"grade_id":"b0000000-0000-4000-8000-0000000000f1"}')$$), 'ERROR:22023', 'grade_id is not editable (only grade_code)');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"created_at":"2020-01-01T00:00:00Z"}')$$), 'ERROR:22023', 'created_at is not editable');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"updated_at":"2020-01-01T00:00:00Z"}')$$), 'ERROR:22023', 'updated_at is not editable');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE app.learner_profiles SET display_name = 'direct' RETURNING 1$$), 'ERROR:42501', 'A still cannot UPDATE the profile table directly');
SELECT is((SELECT count(*)::int FROM (SELECT * FROM app.learner_profiles WHERE user_id = :B::uuid
                                     EXCEPT SELECT * FROM b_before) d), 0, 'B profile still untouched');

-- ---- validation -----------------------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile(NULL)$$), 'ERROR:22023', 'NULL patch');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{}')$$), 'ERROR:22023', 'empty patch');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('["display_name"]')$$), 'ERROR:22023', 'array patch');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('"x"')$$), 'ERROR:22023', 'scalar patch');
SELECT is(pg_temp.as_api(:A::uuid, format('SELECT account.update_own_profile(%L)', jsonb_build_object('display_name', repeat('x', 3000)))), 'ERROR:22023', 'oversized patch');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"grade_code":null}')$$), 'ERROR:22023', 'grade cannot be cleared');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"grade_code":7}')$$), 'ERROR:22023', 'grade_code must be a string');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"preferred_locale":"en"}')$$), 'ERROR:22023', 'unsupported language');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"preferred_locale":null}')$$), 'ERROR:22023', 'language cannot be null');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":7}')$$), 'ERROR:22023', 'display_name must be text');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"grade_code":"NOPE"}') ->> 'code'$$), 'grade_not_available', 'unknown grade is rejected');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"grade_code":"ZZOFF"}') ->> 'code'$$), 'grade_not_available', 'inactive grade is rejected the same way');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"grade_code":"NOPE","preferred_locale":"fr"}') ->> 'status'$$), 'rejected', 'a rejected patch...');
SELECT is((SELECT preferred_locale FROM app.learner_profiles WHERE user_id = :A::uuid), 'ht', '...applies none of its fields');

SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":""}') ->> 'code'$$), 'invalid_display_name', 'empty name');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":" padded"}') ->> 'code'$$), 'invalid_display_name', 'leading space');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":"padded "}') ->> 'code'$$), 'invalid_display_name', 'trailing space');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":"two\nlines"}') ->> 'code'$$), 'invalid_display_name', 'line feed');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":"car\rret"}') ->> 'code'$$), 'invalid_display_name', 'carriage return');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":"tab\tbed"}') ->> 'code'$$), 'invalid_display_name', 'tab');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":"esc\u001b[1m"}') ->> 'code'$$), 'invalid_display_name', 'escape character');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":"del\u007f"}') ->> 'code'$$), 'invalid_display_name', 'DEL');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":"nel\u0085x"}') ->> 'code'$$), 'invalid_display_name', 'C1 control (NEL)');
SELECT is(pg_temp.as_api(:A::uuid, format('SELECT account.update_own_profile(%L) ->> %L', jsonb_build_object('display_name', 'ls' || chr(8232) || 'x'), 'code')), 'invalid_display_name', 'line separator');
SELECT is(pg_temp.as_api(:A::uuid, format('SELECT account.update_own_profile(%L) ->> %L', jsonb_build_object('display_name', 'ps' || chr(8233) || 'x'), 'code')), 'invalid_display_name', 'paragraph separator');
SELECT is(pg_temp.as_api(:A::uuid, format('SELECT account.update_own_profile(%L) ->> %L', jsonb_build_object('display_name', 'e' || chr(769) || 'leve'), 'code')), 'invalid_display_name', 'not NFC-normalised');
SELECT is(pg_temp.as_api(:A::uuid, format('SELECT account.update_own_profile(%L) ->> %L', jsonb_build_object('display_name', repeat('x', 81)), 'code')), 'invalid_display_name', '81 characters');
SELECT is(pg_temp.as_api(:A::uuid, format('SELECT account.update_own_profile(%L) ->> %L', jsonb_build_object('display_name', repeat(chr(233), 80)), 'status')), 'ok', '80 accented characters are accepted (characters, not bytes)');
SELECT is((SELECT char_length(display_name) FROM app.learner_profiles WHERE user_id = :A::uuid), 80, '80-character name stored');

-- ---- audit seam: who + which fields, never the name ------------------------------
SELECT is((SELECT count(*)::int FROM seam_calls), 4, 'one audit call per request that changed something (none for no-ops or rejections)');
SELECT is((SELECT count(*)::int FROM seam_calls
           WHERE actor = :A::uuid AND action = 'account.profile_updated' AND target_kind = 'learner_profile'
             AND target_id = :A::uuid AND outcome = 'allowed'), 4, 'audit calls carry actor, action, target and outcome');
SELECT is((SELECT details FROM seam_calls ORDER BY n LIMIT 1 OFFSET 1), '{"fields":["grade_code","display_name"]}'::jsonb, 'audit details list the changed field names');
SELECT is((SELECT count(*)::int FROM seam_calls s, jsonb_object_keys(s.details) k WHERE k <> 'fields'), 0, 'audit details contain nothing but the field list');
SELECT is((SELECT count(*)::int FROM seam_calls WHERE details::text ~ 'Synthetic A|NS4|xxxx'), 0, 'no profile value appears in any audit call');

SELECT * FROM finish();
ROLLBACK;
