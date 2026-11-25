-- Word of the Day: structure, privileges and exposure of the private `vocab` schema.
BEGIN;
SELECT * FROM no_plan();
-- Never straddle Haiti midnight: if the date changes within 5 seconds, wait for it.
DO $$ BEGIN
    PERFORM pg_sleep(GREATEST(0, 5 - EXTRACT(epoch FROM
        vocab.haiti_day_start(vocab.haiti_date(clock_timestamp()) + 1) - clock_timestamp()))::int
        * CASE WHEN vocab.haiti_day_start(vocab.haiti_date(clock_timestamp()) + 1) - clock_timestamp() < interval '5 seconds' THEN 1 ELSE 0 END);
END $$;

-- ---- tables, keys, RLS -------------------------------------------------------
SELECT tables_are('vocab', ARRAY[
    'sources','words','word_revisions','reviews','audio_assets','daily_assignments'],
    'the 6 vocab tables are the intended ones');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'vocab' AND c.relkind = 'r' AND NOT c.relrowsecurity), 0,
    'row-level security is enabled on every vocab table');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'vocab' AND c.relkind = 'r'
             AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p')), 0,
    'every vocab table has a primary key');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'vocab'), 0,
    'no policy exists in vocab: tables deny everything to every non-owner role');
SELECT is((SELECT count(*)::int FROM pg_class c WHERE c.relnamespace = 'vocab'::regnamespace AND c.relkind IN ('v','m')), 0,
    'no view exists in vocab (a view could read around row-level security)');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'vocab'::regnamespace AND contype = 'f'
             AND confrelid = 'auth.users'::regclass AND confdeltype <> 'r'), 0,
    'every foreign key to auth.users is ON DELETE RESTRICT');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'vocab'::regnamespace AND contype = 'f' AND confdeltype <> 'r'), 0,
    'no foreign key in vocab cascades or nulls on delete');

SELECT col_is_pk('vocab', 'daily_assignments', ARRAY['haiti_date','locale'], 'the schedule is keyed by (Haiti date, locale)');
SELECT fk_ok('vocab', 'daily_assignments', ARRAY['word_revision_id','word_id','locale'],
             'vocab', 'word_revisions', ARRAY['id','word_id','locale'], 'an assignment pins a revision of that word in that locale');
SELECT col_is_unique('vocab', 'word_revisions', ARRAY['word_id','locale','revision'], 'revision numbers unique per word+locale');
SELECT col_is_unique('vocab', 'audio_assets', ARRAY['word_revision_id'], 'at most one recording per revision');
SELECT col_not_null('vocab', 'word_revisions', 'created_by', 'word revisions always have an author');
SELECT col_not_null('vocab', 'word_revisions', 'source_id', 'word revisions always cite a source/licence record');
SELECT col_not_null('vocab', 'audio_assets', 'source_id', 'recordings always cite a rights record');
SELECT hasnt_column('vocab', 'audio_assets', 'autoplay', 'there is no autoplay flag');

-- Every text column of the schema is bounded by a CHECK constraint.
SELECT is((SELECT array_agg(c.table_name || '.' || c.column_name ORDER BY c.table_name, c.column_name)
           FROM information_schema.columns c
           WHERE c.table_schema = 'vocab' AND c.data_type = 'text'
             AND NOT EXISTS (
                 SELECT 1 FROM pg_constraint k
                 JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = ANY (k.conkey)
                 WHERE k.contype = 'c' AND k.conrelid = format('vocab.%I', c.table_name)::regclass
                   AND a.attname = c.column_name)),
    NULL, 'every text column in vocab has a CHECK constraint (bounded length or closed list)');

-- ---- triggers --------------------------------------------------------------------
SELECT is((SELECT array_agg(c.relname || ':' || t.tgname ORDER BY c.relname, t.tgname) FROM pg_trigger t
           JOIN pg_class c ON c.oid = t.tgrelid
           WHERE c.relnamespace = 'vocab'::regnamespace AND NOT t.tgisinternal),
    ARRAY['audio_assets:protect_audio_asset',
          'daily_assignments:check_daily_assignment_day',
          'daily_assignments:guard_daily_assignment',
          'reviews:no_edit_reviews',
          'reviews:validate_review',
          'sources:guard_source',
          'word_revisions:guard_word_revision_insert',
          'word_revisions:protect_word_revision',
          'words:guard_word'],
    'the 9 integrity triggers are installed');
SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           WHERE c.relnamespace = 'vocab'::regnamespace AND NOT t.tgisinternal AND t.tgenabled <> 'O'), 0,
    'no vocab trigger is disabled');

-- ---- schema and table privileges ----------------------------------------------------
SELECT is(has_schema_privilege('anon', 'vocab', 'USAGE'), false, 'anon cannot use schema vocab');
SELECT is(has_schema_privilege('authenticated', 'vocab', 'USAGE'), false, 'authenticated cannot use schema vocab');
SELECT is(has_schema_privilege('authenticator', 'vocab', 'USAGE'), false, 'authenticator (Data API) cannot use schema vocab');
SELECT is(has_schema_privilege('service_role', 'vocab', 'USAGE'), false, 'service_role cannot use schema vocab');
SELECT is(has_schema_privilege('public', 'vocab', 'USAGE'), false, 'PUBLIC cannot use schema vocab');
SELECT is(has_schema_privilege('edu_api', 'vocab', 'USAGE'), true, 'edu_api may enter schema vocab (to call one function)');
SELECT is(has_schema_privilege('edu_api', 'vocab', 'CREATE'), false, 'edu_api cannot create objects in vocab');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'vocab' AND grantee <> 'postgres'), 0,
    'nobody but the owner holds any table privilege in vocab (not PUBLIC, anon, authenticated, authenticator, service_role or edu_api)');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'vocab' AND grantee <> 'postgres'), 0,
    'nobody but the owner holds any column privilege in vocab');

-- ---- functions ------------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'vocab'::regnamespace
           AND (has_function_privilege('public', p.oid, 'EXECUTE')
             OR has_function_privilege('anon', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticated', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticator', p.oid, 'EXECUTE')
             OR has_function_privilege('service_role', p.oid, 'EXECUTE'))), 0,
    'no vocab function is executable by PUBLIC, anon, authenticated, authenticator or service_role');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'vocab'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['daily_word'], 'edu_api may execute exactly one vocab function: daily_word');
SELECT is((SELECT pg_get_function_identity_arguments(p.oid) FROM pg_proc p
           WHERE p.pronamespace = 'vocab'::regnamespace AND p.proname = 'daily_word'),
    'p_locale text', 'daily_word takes a locale and NO clock');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'vocab'::regnamespace AND has_function_privilege('edu_staff', p.oid, 'EXECUTE')),
    ARRAY['calendar','create_draft','create_word','register_source','remove_audio','retire_word','review_queue',
          'review_revision','schedule_word','set_audio','set_source_rights','staff_ensure_assignments',
          'submit_revision','unschedule_date','update_draft'],
    'edu_staff may execute exactly the 15 staff workflow functions (each starts with a role check)');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'vocab'::regnamespace AND has_function_privilege('edu_worker', p.oid, 'EXECUTE')),
    ARRAY['ensure_assignments'], 'edu_worker may execute exactly ensure_assignments');
SELECT is((SELECT count(*)::int FROM pg_proc p
           CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
           JOIN pg_roles g ON g.oid = acl.grantee
           WHERE p.pronamespace = 'vocab'::regnamespace
             AND g.rolname NOT IN ('postgres', 'edu_api', 'edu_staff', 'edu_worker')), 0,
    'no other role is granted any vocab function');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'vocab'::regnamespace
             AND NOT has_function_privilege('edu_api', p.oid, 'EXECUTE')
             AND NOT has_function_privilege('edu_staff', p.oid, 'EXECUTE')
             AND NOT has_function_privilege('edu_worker', p.oid, 'EXECUTE')
             AND p.prorettype <> 'trigger'::regtype),
    ARRAY['_assign_word','_assignable_revision','_audit','_lock_schedule','_own_revision_for_update','_require_staff',
          'daily_word_at','erase_learner','haiti_date','haiti_day_start','is_day_locked','schedule_freeze'],
    'internal helpers, the clock seam and the erasure hook are executable by the owner only');
SELECT is(has_schema_privilege('edu_staff', 'vocab', 'USAGE') AND has_schema_privilege('edu_worker', 'vocab', 'USAGE')
          AND NOT has_schema_privilege('edu_staff', 'vocab', 'CREATE') AND NOT has_schema_privilege('edu_worker', 'vocab', 'CREATE'),
    true, 'edu_staff and edu_worker may enter schema vocab and create nothing in it');
-- Ruling R-03: temporary schema explicitly last, so it can never shadow a name.
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'vocab'::regnamespace
           AND p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']), 0,
    'every vocab function pins exactly search_path = pg_catalog, pg_temp (and sets nothing else)');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'vocab'::regnamespace
           AND p.prosecdef AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'every SECURITY DEFINER vocab function is owned by postgres');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'vocab'::regnamespace
           AND p.proname IN ('_require_staff', '_audit')
           AND (p.prosrc ILIKE '%app.staff_roles%' OR p.prosrc ILIKE '%app.audit_events%')), 0,
    'the two seams no longer touch app tables: they call staff.require_role and ops.audit_write');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'vocab'::regnamespace
           AND p.prosrc ILIKE '%insert into app.%'), 0, 'no vocab function inserts into an app table');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'vocab'::regnamespace
           AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'vocab functions are owned by the migration owner (postgres)');
SELECT has_function('vocab', 'ensure_assignments', ARRAY['date','integer'], 'vocab.ensure_assignments(date, integer) exists');
SELECT has_function('vocab', 'erase_learner', ARRAY['uuid'], 'the erasure hook exists');
SELECT is(vocab.erase_learner('a0000000-0000-4000-8000-000000000001'), '{}'::jsonb,
    'erase_learner returns an empty result: this schema stores no per-learner row');
SELECT is((SELECT count(*)::int FROM information_schema.columns
           WHERE table_schema = 'vocab' AND column_name IN ('learner_id', 'user_id')), 0,
    'no vocab table has a learner column');

-- ---- nothing was created in `app` for this feature -----------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'app'::regnamespace
           AND p.proname ILIKE '%word%'), 0, 'no word function was added to schema app');
SELECT is((SELECT count(*)::int FROM pg_roles WHERE rolname IN ('edu_vocab', 'vocab')), 0,
    'this lane created no database role');

-- ---- the student API role: one door only ---------------------------------------------
-- Run one statement AS THE STUDENT API ROLE with the given actor, then switch
-- back. Returns the first column of the first row as text, or 'ERROR:<sqlstate>'.
GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
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
-- Empty schedule so the last two answers are exact. Inside the test
-- transaction and rolled back at the end: nothing is really deleted.
TRUNCATE vocab.daily_assignments, vocab.audio_assets, vocab.reviews, vocab.word_revisions, vocab.words, vocab.sources;
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM vocab.words'), 'ERROR:42501', 'edu_api cannot read words');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM vocab.word_revisions'), 'ERROR:42501', 'edu_api cannot read word revisions');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM vocab.daily_assignments'), 'ERROR:42501', 'edu_api cannot read the schedule (so no future date leaks)');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM vocab.reviews'), 'ERROR:42501', 'edu_api cannot read reviews');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM vocab.audio_assets'), 'ERROR:42501', 'edu_api cannot read audio metadata');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM vocab.sources'), 'ERROR:42501', 'edu_api cannot read sources');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM vocab.daily_word_at('fr', now() + interval '3 days')$$), 'ERROR:42501', 'edu_api cannot call the clock seam');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM vocab.ensure_assignments(current_date, 7)$$), 'ERROR:42501', 'edu_api cannot run the schedule fill');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT vocab.haiti_date()$$), 'ERROR:42501', 'edu_api cannot call helper functions');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT vocab.create_word('x-word')$$), 'ERROR:42501', 'edu_api cannot call a staff function');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT vocab.schedule_word(current_date + 3, gen_random_uuid())$$), 'ERROR:42501', 'edu_api cannot schedule');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT vocab.review_revision(gen_random_uuid(), 'approved')$$), 'ERROR:42501', 'edu_api cannot review');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT vocab.erase_learner('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'edu_api cannot call the erasure hook');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (current_date + 3, 'fr', gen_random_uuid(), gen_random_uuid(), 'auto') RETURNING 1$$), 'ERROR:42501', 'edu_api cannot write the schedule');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM vocab.daily_word('fr')$$), '0', 'edu_api can call daily_word (nothing scheduled: zero rows, not an error)');
SELECT is(pg_temp.as_api(NULL, $$SELECT count(*) FROM vocab.daily_word('fr')$$), 'ERROR:42501', 'daily_word refuses a connection with no verified actor');

-- ---- Supabase Data API roles cannot reach the schema at all ---------------------------
SET LOCAL ROLE anon;
SELECT throws_ok('SELECT count(*) FROM vocab.words', '42501', NULL, 'anon: schema vocab is unreachable');
SELECT throws_ok($$SELECT * FROM vocab.daily_word('fr')$$, '42501', NULL, 'anon: cannot call vocab functions');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT throws_ok('SELECT count(*) FROM vocab.daily_assignments', '42501', NULL, 'authenticated (Data API): schema vocab is unreachable');
SELECT throws_ok($$SELECT * FROM vocab.daily_word('fr')$$, '42501', NULL, 'authenticated (Data API): cannot call vocab functions');
RESET ROLE;
SET LOCAL ROLE service_role;
SELECT throws_ok('SELECT count(*) FROM vocab.word_revisions', '42501', NULL, 'service_role: schema vocab is unreachable');
RESET ROLE;

SELECT * FROM finish();
ROLLBACK;
