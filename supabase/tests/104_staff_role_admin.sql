-- Administration of staff roles: admin only, never to oneself, never the last admin.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
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
CREATE FUNCTION pg_temp.staff(p_actor uuid, p_sql text) RETURNS text LANGUAGE sql AS
$$ SELECT pg_temp.as_role('edu_staff', p_actor, p_sql) $$;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set REVIEWER '''a0000000-0000-4000-8000-000000000004'''
\set ADMIN1 '''a0000000-0000-4000-8000-0000000000e1'''
\set ADMIN2 '''a0000000-0000-4000-8000-0000000000e2'''

-- A known starting point inside this transaction: exactly one active admin.
UPDATE app.staff_roles SET is_active = false WHERE role = 'admin';
INSERT INTO auth.users (instance_id, id, aud, role, email) VALUES
    ('00000000-0000-0000-0000-000000000000', :ADMIN1, 'authenticated', 'authenticated', 'admin1.t104@edupreneur.test'),
    ('00000000-0000-0000-0000-000000000000', :ADMIN2, 'authenticated', 'authenticated', 'admin2.t104@edupreneur.test');
INSERT INTO auth.users (instance_id, id, aud, role, email, is_anonymous) VALUES
    ('00000000-0000-0000-0000-000000000000', 'a0000000-0000-4000-8000-0000000000e3', 'authenticated', 'authenticated', NULL, true);
INSERT INTO auth.users (instance_id, id, aud, role, email, deleted_at) VALUES
    ('00000000-0000-0000-0000-000000000000', 'a0000000-0000-4000-8000-0000000000e4', 'authenticated', 'authenticated', 'gone.t104@edupreneur.test', now());
INSERT INTO app.staff_roles (user_id, role) VALUES (:ADMIN1, 'admin');   -- the bootstrap admin
CREATE TEMP TABLE base AS SELECT count(*) AS audit FROM app.audit_events;

-- ---- who may call -----------------------------------------------------------------------
SELECT is(left(pg_temp.as_role('edu_api', :ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-000000000001', 'admin')$$), 11), 'ERROR:42501', 'edu_api cannot grant roles, even as an admin');
SELECT is(left(pg_temp.as_role('edu_api', :ADMIN1::uuid, $$SELECT staff.list_role_assignments(10)$$), 11), 'ERROR:42501', 'edu_api cannot list role assignments');
SELECT is(left(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.lock_role_changes()$$), 11), 'ERROR:42501', 'lock_role_changes is internal');
SELECT is(left(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.check_role_target('a0000000-0000-4000-8000-000000000001', 'admin')$$), 11), 'ERROR:42501', 'check_role_target is internal');

SELECT is((SELECT array_agg(who ORDER BY who) FROM (VALUES ('learner', :A::uuid), ('editor', :EDITOR::uuid), ('reviewer', :REVIEWER::uuid), ('nobody', NULL::uuid)) AS t(who, actor)
           WHERE left(pg_temp.staff(actor, $$SELECT staff.grant_role('a0000000-0000-4000-8000-000000000002', 'editor')$$), 11) <> 'ERROR:42501'
              OR left(pg_temp.staff(actor, $$SELECT staff.revoke_role('a0000000-0000-4000-8000-000000000003', 'editor')$$), 11) <> 'ERROR:42501'
              OR left(pg_temp.staff(actor, $$SELECT staff.list_role_assignments(10)$$), 11) <> 'ERROR:42501'),
    NULL, 'only an admin may grant, revoke or list (learner, editor, reviewer, no actor: 42501)');
SELECT is(pg_temp.staff(:A::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-000000000001', 'admin')$$), 'ERROR:42501:A staff role is required for this action', 'a learner cannot make themselves admin');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-000000000003', 'admin')$$), 'ERROR:42501:A staff role is required for this action', 'an editor cannot make themselves admin');

-- ---- nobody grants to themselves ------------------------------------------------------------
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-0000000000e1', 'reviewer')$$), 'ERROR:42501:cannot_grant_to_self', 'an admin cannot give themselves another role');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-0000000000e1', 'admin')$$), 'ERROR:42501:cannot_grant_to_self', 'not even the role they already hold');
SELECT is((SELECT array_agg(role ORDER BY role) FROM app.staff_roles WHERE user_id = :ADMIN1), ARRAY['admin'], 'nothing was granted');

-- ---- inputs ------------------------------------------------------------------------------------
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-000000000002', 'superuser')$$), 'ERROR:ED422:role_invalid', 'unknown role');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role(gen_random_uuid(), 'editor')$$), 'ERROR:ED404:user_not_found', 'unknown account');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role(NULL, 'editor')$$), 'ERROR:ED404:user_not_found', 'NULL account');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-0000000000e3', 'editor')$$), 'ERROR:ED404:user_not_found', 'an anonymous sign-in cannot hold a staff role');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-0000000000e4', 'editor')$$), 'ERROR:ED404:user_not_found', 'a deleted account cannot hold a staff role');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.revoke_role('a0000000-0000-4000-8000-000000000002', 'editor')$$), 'ERROR:ED404:role_not_assigned', 'revoking a role that was never assigned');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.revoke_role('a0000000-0000-4000-8000-000000000003', 'boss')$$), 'ERROR:ED422:role_invalid', 'revoking an unknown role');
SELECT is((SELECT (count(*) - (SELECT audit FROM base))::int FROM app.audit_events), 0, 'nothing refused so far wrote an audit event');

-- ---- grant / revoke ---------------------------------------------------------------------------
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-000000000002', 'publisher')$$), 'true', 'the admin grants publisher to B');
SELECT is((SELECT row(is_active, granted_by, granted_at = now())::text FROM app.staff_roles WHERE user_id = :B AND role = 'publisher'),
    row(true, 'a0000000-0000-4000-8000-0000000000e1'::uuid, true)::text, 'the row records who granted it and when (server time)');
SELECT is(pg_temp.staff(:B::uuid, $$SELECT staff.actor_roles()::text$$), '{publisher}', 'B now holds the role');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-000000000002', 'publisher')$$), 'false', 'granting it again changes nothing');
SELECT is(left(pg_temp.staff(:B::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-000000000001', 'publisher')$$), 11), 'ERROR:42501', 'a publisher cannot pass the role on');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.revoke_role('a0000000-0000-4000-8000-000000000002', 'publisher')$$), 'true', 'the admin revokes it');
SELECT is((SELECT is_active FROM app.staff_roles WHERE user_id = :B AND role = 'publisher'), false, 'the row is kept, inactive');
SELECT is(pg_temp.staff(:B::uuid, $$SELECT staff.actor_roles()::text$$), '{}', 'B holds nothing any more');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.revoke_role('a0000000-0000-4000-8000-000000000002', 'publisher')$$), 'false', 'revoking it again changes nothing');

-- ---- the last admin ---------------------------------------------------------------------------
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.revoke_role('a0000000-0000-4000-8000-0000000000e1', 'admin')$$), 'ERROR:ED409:last_admin', 'the only admin cannot give up the role');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-0000000000e2', 'admin')$$), 'true', 'a second admin is appointed');
SELECT is(pg_temp.staff(:ADMIN2::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-0000000000e1', 'reviewer')$$), 'true', 'the second admin can give the first one another role');
SELECT is(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.revoke_role('a0000000-0000-4000-8000-0000000000e1', 'admin')$$), 'true', 'with another admin in place, an admin may step down');
SELECT is(left(pg_temp.staff(:ADMIN1::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-000000000002', 'editor')$$), 11), 'ERROR:42501', 'a former admin administers nothing');
SELECT is(pg_temp.staff(:ADMIN2::uuid, $$SELECT staff.revoke_role('a0000000-0000-4000-8000-0000000000e2', 'admin')$$), 'ERROR:ED409:last_admin', 'the remaining admin is now the last one');
SELECT is(pg_temp.staff(:ADMIN2::uuid, $$SELECT staff.revoke_role('a0000000-0000-4000-8000-0000000000e1', 'admin')$$), 'false', 'revoking an already inactive admin is a no-op, not a lockout');
SELECT is((SELECT count(*)::int FROM app.staff_roles WHERE role = 'admin' AND is_active), 1, 'there is still exactly one active admin');
SELECT is(pg_temp.staff(:ADMIN2::uuid, $$SELECT staff.grant_role('a0000000-0000-4000-8000-0000000000e1', 'admin')$$), 'true', 'an inactive assignment is reactivated by a new grant');
SELECT is((SELECT granted_by FROM app.staff_roles WHERE user_id = :ADMIN1 AND role = 'admin'), :ADMIN2::uuid, 'and records the new grantor');

-- ---- audit ---------------------------------------------------------------------------------------
SELECT is((SELECT (count(*) - (SELECT audit FROM base))::int FROM app.audit_events), 6,
    'six changes, six audit events (no-ops and refusals wrote none)');
SELECT is((SELECT count(*)::int FROM app.audit_events e WHERE e.created_at = now()
           AND (e.target_kind <> 'user' OR e.actor_id IS NULL OR e.outcome <> 'allowed'
                OR e.action NOT IN ('staff_role.grant', 'staff_role.revoke'))), 0,
    'each names the account concerned and the admin who acted');
SELECT is((SELECT count(*)::int FROM app.audit_events e WHERE e.created_at = now() AND e.action = 'staff_role.revoke'), 2, 'two revocations');

-- ---- listing -------------------------------------------------------------------------------------
SELECT is(pg_temp.staff(:ADMIN2::uuid, $$SELECT (SELECT count(*) FROM jsonb_array_elements(staff.list_role_assignments(500)) AS e WHERE e.value ->> 'user_id' = 'a0000000-0000-4000-8000-000000000002')$$), '1', 'the listing includes inactive assignments');
SELECT is(pg_temp.staff(:ADMIN2::uuid, $$SELECT staff.list_role_assignments(500)::text LIKE '%@%'$$), 'false', 'the listing contains no e-mail address');

SELECT * FROM finish();
ROLLBACK;
