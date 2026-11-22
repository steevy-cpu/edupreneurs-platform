-- Mon Edupreneur 2.0 / DB role & RLS for first student API (staging design)
-- Security prerequisite: FastAPI must verify Supabase access token and set
-- SET LOCAL edu.actor_id = '<verified auth.users UUID>' in EVERY transaction.
-- Create login credentials OUT OF BAND; no passwords appear in migration source.
-- NEVER connect as postgres, service_role, or a BYPASSRLS role for student requests.

BEGIN;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edu_api') THEN
        CREATE ROLE edu_api NOLOGIN NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='edu_api' AND rolbypassrls) THEN
        RAISE EXCEPTION 'edu_api must never have BYPASSRLS';
    END IF;
END $$;

GRANT USAGE ON SCHEMA app TO edu_api;
GRANT EXECUTE ON FUNCTION app.current_actor_id() TO edu_api;
GRANT EXECUTE ON FUNCTION app.next_change_version(uuid) TO edu_api;

-- All grants are explicitly limited to the first learner API. Editor/publisher
-- and worker roles will be provisioned in later, independently reviewed migrations.
GRANT SELECT, INSERT, UPDATE ON app.learner_profiles TO edu_api;
GRANT SELECT ON app.staff_roles TO edu_api;
GRANT SELECT ON app.grades, app.subjects, app.courses, app.units, app.lessons,
    app.lesson_revisions, app.question_revisions, app.pack_releases,
    app.pack_items, app.pack_current TO edu_api;
GRANT SELECT, INSERT, UPDATE ON app.lesson_progress, app.account_sync_state TO edu_api;
GRANT SELECT, INSERT ON app.practice_attempts, app.sync_receipts,
    app.account_change_feed TO edu_api;
GRANT INSERT ON app.audit_events TO edu_api;

CREATE POLICY profiles_select_own ON app.learner_profiles
    FOR SELECT TO edu_api USING (user_id = (SELECT app.current_actor_id()));
CREATE POLICY profiles_insert_own ON app.learner_profiles
    FOR INSERT TO edu_api WITH CHECK (user_id = (SELECT app.current_actor_id()));
CREATE POLICY profiles_update_own ON app.learner_profiles
    FOR UPDATE TO edu_api
    USING (user_id = (SELECT app.current_actor_id()))
    WITH CHECK (user_id = (SELECT app.current_actor_id()));

CREATE POLICY staff_read_own ON app.staff_roles
    FOR SELECT TO edu_api USING (user_id = (SELECT app.current_actor_id()));

CREATE POLICY grades_read ON app.grades FOR SELECT TO edu_api USING (is_active);
CREATE POLICY subjects_read ON app.subjects FOR SELECT TO edu_api USING (is_active);
CREATE POLICY courses_read ON app.courses FOR SELECT TO edu_api
    USING (visibility = 'published');
CREATE POLICY units_read ON app.units FOR SELECT TO edu_api
    USING (EXISTS (
        SELECT 1 FROM app.courses c WHERE c.id = course_id AND c.visibility = 'published'
    ));
CREATE POLICY lessons_read ON app.lessons FOR SELECT TO edu_api
    USING (is_active AND EXISTS (
        SELECT 1 FROM app.units u
        JOIN app.courses c ON c.id = u.course_id
        WHERE u.id = unit_id AND c.visibility = 'published'
    ));

CREATE POLICY pack_current_read ON app.pack_current FOR SELECT TO edu_api
    USING (true);
CREATE POLICY pack_releases_read ON app.pack_releases FOR SELECT TO edu_api
    USING (EXISTS (SELECT 1 FROM app.pack_current pc WHERE pc.release_id = id));
CREATE POLICY pack_items_read ON app.pack_items FOR SELECT TO edu_api
    USING (EXISTS (SELECT 1 FROM app.pack_current pc WHERE pc.release_id = pack_release_id));
CREATE POLICY revisions_read ON app.lesson_revisions FOR SELECT TO edu_api
    USING (status = 'approved' AND EXISTS (
        SELECT 1 FROM app.pack_items pi WHERE pi.lesson_revision_id = id
    ));
CREATE POLICY questions_read ON app.question_revisions FOR SELECT TO edu_api
    USING (EXISTS (
        SELECT 1 FROM app.lesson_revisions lr WHERE lr.id = lesson_revision_id
    ));

CREATE POLICY progress_select_own ON app.lesson_progress
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY progress_insert_own ON app.lesson_progress
    FOR INSERT TO edu_api WITH CHECK (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY progress_update_own ON app.lesson_progress
    FOR UPDATE TO edu_api
    USING (learner_id = (SELECT app.current_actor_id()))
    WITH CHECK (learner_id = (SELECT app.current_actor_id()));

CREATE POLICY attempts_select_own ON app.practice_attempts
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY attempts_insert_own ON app.practice_attempts
    FOR INSERT TO edu_api WITH CHECK (learner_id = (SELECT app.current_actor_id()));

CREATE POLICY state_select_own ON app.account_sync_state
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY state_insert_own ON app.account_sync_state
    FOR INSERT TO edu_api WITH CHECK (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY state_update_own ON app.account_sync_state
    FOR UPDATE TO edu_api
    USING (learner_id = (SELECT app.current_actor_id()))
    WITH CHECK (learner_id = (SELECT app.current_actor_id()));

CREATE POLICY receipts_select_own ON app.sync_receipts
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY receipts_insert_own ON app.sync_receipts
    FOR INSERT TO edu_api WITH CHECK (learner_id = (SELECT app.current_actor_id()));

CREATE POLICY feed_select_own ON app.account_change_feed
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY feed_insert_own ON app.account_change_feed
    FOR INSERT TO edu_api WITH CHECK (learner_id = (SELECT app.current_actor_id()));

CREATE POLICY audit_insert_self ON app.audit_events
    FOR INSERT TO edu_api WITH CHECK (
      actor_id = (SELECT app.current_actor_id()) AND actor_kind IN ('user','staff')
    );
COMMIT;
