-- Structure, privileges and exposure of the private `notify` schema.
BEGIN;
SELECT * FROM no_plan();

-- ---- tables, keys, RLS -------------------------------------------------------
SELECT tables_are('notify', ARRAY['kinds','policy','preferences','outbox','deliveries','delivery_attempts'],
    'notify holds exactly its six tables');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'notify' AND c.relkind = 'r' AND NOT c.relrowsecurity), 0,
    'row-level security is enabled on every notify table');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'notify' AND c.relkind = 'r'
             AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p')), 0,
    'every notify table has a primary key');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'notify' AND c.relkind IN ('v','m')), 0, 'no views (nothing bypasses RLS)');
SELECT col_is_unique('notify', 'outbox', ARRAY['recipient_id','kind','dedupe_hash'],
    'one outbox row per (recipient, kind, dedupe key)');
SELECT fk_ok('notify', 'outbox', 'recipient_id', 'app', 'learner_profiles', 'user_id',
    'a notification can only exist for a real learner');
SELECT fk_ok('notify', 'outbox', 'kind', 'notify', 'kinds', 'kind', 'kind is an allow-list');
SELECT fk_ok('notify', 'preferences', 'learner_id', 'app', 'learner_profiles', 'user_id',
    'preferences belong to a real learner');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'notify'::regnamespace AND contype = 'f' AND confdeltype <> 'r'), 0,
    'no foreign key cascades: erasure is explicit (notify.erase_learner)');
SELECT is((SELECT count(*)::int FROM notify.policy), 1, 'exactly one policy row');
SELECT is((SELECT quiet_start::text || '-' || quiet_end::text FROM notify.policy), '21:00:00-06:00:00',
    'synthetic platform quiet hours are 21:00-06:00 (PO-10 pending)');
SELECT is((SELECT array_agg(kind ORDER BY kind) FROM notify.kinds),
    ARRAY['daily_word_available','entitlement_expiring','sync_reminder'], 'the kind allow-list');

-- ---- no column can hold free text ---------------------------------------------
-- Every text-like column in the schema is listed here, and each one is an
-- allow-list (CHECK ... IN / FK to notify.kinds). A new text column fails this test.
SELECT is((SELECT array_agg((table_name || '.' || column_name)::text
                            ORDER BY (table_name || '.' || column_name)::text COLLATE "C")
           FROM information_schema.columns
           WHERE table_schema = 'notify'
             AND data_type NOT IN ('uuid','boolean','integer','bigint','timestamp with time zone',
                                   'time without time zone','bytea')),
    ARRAY['deliveries.channel','deliveries.last_error_code','deliveries.state',
          'delivery_attempts.channel','delivery_attempts.error_code','delivery_attempts.outcome',
          'kinds.category','kinds.kind','outbox.channels','outbox.kind','outbox.refs','outbox.state',
          'preferences.muted_categories'],
    'the only non-id, non-time columns are allow-listed codes and the refs object');
SELECT is((SELECT count(*)::int FROM information_schema.columns
           WHERE table_schema = 'notify'
             AND column_name ~ '(title|body|message|text|name|email|phone|token|payload|note)'
             AND column_name <> 'lease_token'), 0,
    'no title/body/message/name/e-mail/phone/device-token column exists');

-- ---- policies -----------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'notify'), 4, '4 policies exist');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'notify' AND roles <> ARRAY['edu_api']::name[]), 0,
    'every policy applies to edu_api only');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'notify' AND cmd <> 'SELECT'), 0,
    'no policy allows INSERT, UPDATE or DELETE');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'notify'
           AND tablename IN ('deliveries','delivery_attempts')), 0,
    'delivery state and the attempt log have no policy at all (deny everything)');

-- ---- privileges ---------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'notify' AND grantee IN ('PUBLIC','anon','authenticated','authenticator','service_role')), 0,
    'PUBLIC / anon / authenticated / authenticator / service_role hold no table privilege in notify');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'notify' AND grantee IN ('PUBLIC','anon','authenticated','authenticator','service_role')), 0,
    '... and no column privilege');
SELECT is(has_schema_privilege('anon', 'notify', 'USAGE'), false, 'anon cannot use schema notify');
SELECT is(has_schema_privilege('authenticated', 'notify', 'USAGE'), false, 'authenticated cannot use schema notify');
SELECT is(has_schema_privilege('authenticator', 'notify', 'USAGE'), false, 'authenticator (Data API) cannot use schema notify');
SELECT is(has_schema_privilege('service_role', 'notify', 'USAGE'), false, 'service_role cannot use schema notify');
SELECT is(has_schema_privilege('edu_api', 'notify', 'CREATE'), false, 'edu_api cannot create objects in notify');

SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'notify' AND grantee = 'edu_api' AND privilege_type <> 'SELECT'), 0,
    'edu_api has no table-level write privilege in notify');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'notify' AND grantee = 'edu_api' AND privilege_type <> 'SELECT'), 0,
    'edu_api has no column-level write privilege in notify');
SELECT is((SELECT array_agg(DISTINCT table_name::text ORDER BY table_name::text) FROM information_schema.column_privileges
           WHERE table_schema = 'notify' AND grantee = 'edu_api'),
    ARRAY['kinds','outbox','policy','preferences'],
    'edu_api can read kinds, policy, preferences and outbox only');
SELECT is(has_column_privilege('edu_api', 'notify.outbox', 'dedupe_hash', 'SELECT'), false,
    'edu_api cannot read the dedupe digest');

-- ---- functions ------------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'notify'::regnamespace
           AND (has_function_privilege('public', p.oid, 'EXECUTE')
             OR has_function_privilege('anon', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticated', p.oid, 'EXECUTE')
             OR has_function_privilege('service_role', p.oid, 'EXECUTE'))), 0,
    'no notify function is executable by PUBLIC, anon, authenticated or service_role');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'notify'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['set_preferences'],
    'edu_api may execute exactly set_preferences: no client request can create a notification');
-- SEAM(notify-worker-role): when the worker role is granted claim_due and
-- record_attempt, this expectation becomes the two extra (function, grantee) pairs.
SELECT is((SELECT array_agg(p.proname || '>' || pg_get_userbyid(a.grantee) ORDER BY 1)
           FROM pg_proc p, aclexplode(p.proacl) a
           WHERE p.pronamespace = 'notify'::regnamespace AND a.grantee <> p.proowner),
    ARRAY['set_preferences>edu_api'],
    'the only EXECUTE grant to a non-owner in notify is set_preferences to edu_api');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'notify'::regnamespace
           AND NOT COALESCE(p.proconfig @> ARRAY['search_path=""'], false)), 0,
    'every notify function pins an empty search_path');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'notify'::regnamespace
           AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'every notify function is owned by the migration owner (postgres)');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'notify'::regnamespace
           AND p.proname IN ('set_preferences')
           AND pg_get_function_identity_arguments(p.oid) ~ 'uuid'), 0,
    'set_preferences takes no user id: the actor comes from the transaction');

-- ---- nothing leaked into app ----------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc WHERE pronamespace = 'app'::regnamespace AND proname ~ 'notif'), 0,
    'no notification function was created in app');
SELECT is((SELECT count(*)::int FROM pg_tables WHERE schemaname = 'app' AND tablename ~ 'notif'), 0,
    'no notification table was created in app');

-- ---- Supabase Data API roles cannot reach the schema ---------------------------
SET LOCAL ROLE anon;
SELECT throws_ok('SELECT count(*) FROM notify.outbox', '42501', NULL, 'anon: schema notify is unreachable');
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','k')$$, '42501', NULL, 'anon: cannot enqueue');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT throws_ok('SELECT count(*) FROM notify.preferences', '42501', NULL, 'authenticated (Data API): schema notify is unreachable');
SELECT throws_ok($$SELECT notify.set_preferences(true, '{}', NULL, NULL)$$, '42501', NULL, 'authenticated (Data API): cannot set preferences');
RESET ROLE;
SET LOCAL ROLE service_role;
SELECT throws_ok('SELECT count(*) FROM notify.outbox', '42501', NULL, 'service_role: schema notify is unreachable');
RESET ROLE;

SELECT * FROM finish();
ROLLBACK;
