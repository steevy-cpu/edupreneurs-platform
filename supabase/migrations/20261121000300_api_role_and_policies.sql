-- Mon Edupreneur 2.0 — row-level security, the student API role, and its policies
--
-- Derived from docs/reference/schema-v0.2/migrations/0002_api_role_and_policies.sql.
-- Deviations are tagged "[v0.2 change Cnn]"; see docs/SCHEMA_CHANGELOG.md.
--
-- MODEL
--   edu_api        NOLOGIN group role. Holds every privilege the student API has.
--   edu_api_login  LOGIN role, member of edu_api. NOT created here, because a
--                  migration must not contain a password. Locally it is created
--                  by scripts/local_stack.py with a random password; in a hosted
--                  environment it is created out of band (docs/SECURITY.md).
--
-- The student API can:
--   * read published curriculum content,
--   * read the calling learner's own profile / progress / attempts / receipts / feed,
--   * create the calling learner's own profile row (defaults only),
--   * execute app.sync_apply_operation() — the ONLY way learning data is written.
-- It cannot write scores, progress, receipts, change-feed rows, audit events,
-- staff roles, curriculum, packs or jobs. [v0.2 change C01]

-- ----------------------------------------------------------------------------
-- Default deny: RLS on every table in the private schema
-- ----------------------------------------------------------------------------
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'app' LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC, anon, authenticated;
-- NOTE [v0.2 change C10]: the draft also ran
--   ALTER DEFAULT PRIVILEGES IN SCHEMA app REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC
-- That statement is a silent no-op: PostgreSQL's built-in "PUBLIC may execute
-- new functions" default is global and cannot be revoked per schema. Instead,
-- every migration that creates functions ends with an explicit REVOKE, and
-- supabase/tests/010_structure.sql fails if any app function is executable by
-- PUBLIC, anon or authenticated.

-- ----------------------------------------------------------------------------
-- The student API group role
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edu_api') THEN
        CREATE ROLE edu_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'edu_api'
          AND (rolbypassrls OR rolsuper OR rolcreaterole OR rolcreatedb OR rolcanlogin OR rolreplication)
    ) THEN
        RAISE EXCEPTION 'edu_api must be a plain NOLOGIN role without BYPASSRLS or admin attributes';
    END IF;
END $$;

GRANT USAGE ON SCHEMA app TO edu_api;
GRANT EXECUTE ON FUNCTION app.current_actor_id() TO edu_api;

-- Own profile: read it, and create it with column defaults only. The API has
-- no profile-editing endpoint yet, so there is no UPDATE grant. [C01]
GRANT SELECT ON app.learner_profiles TO edu_api;
GRANT INSERT (user_id) ON app.learner_profiles TO edu_api;

-- Published curriculum: read-only.
GRANT SELECT ON app.grades, app.subjects, app.courses, app.units, app.lessons,
    app.lesson_revisions, app.question_revisions, app.pack_releases,
    app.pack_items, app.pack_current TO edu_api;

-- Learning + sync state: read-only. Writes go through app.sync_apply_operation().
GRANT SELECT ON app.lesson_progress, app.practice_attempts, app.account_sync_state,
    app.sync_receipts, app.account_change_feed TO edu_api;

-- Deliberately NO grants on: staff_roles, content_sources, lesson_revision_sources,
-- editorial_reviews, background_jobs, audit_events. [C01, C09]

-- ----------------------------------------------------------------------------
-- Policies: identity
-- ----------------------------------------------------------------------------
CREATE POLICY profiles_select_own ON app.learner_profiles
    FOR SELECT TO edu_api USING (user_id = (SELECT app.current_actor_id()));
CREATE POLICY profiles_insert_own ON app.learner_profiles
    FOR INSERT TO edu_api WITH CHECK (user_id = (SELECT app.current_actor_id()));

-- ----------------------------------------------------------------------------
-- Policies: published content
-- ----------------------------------------------------------------------------
-- A sub-query inside a policy is itself filtered by the caller's policies on the
-- tables it reads. The chain below therefore composes: a question is visible
-- only if its revision is, which needs a current pack item and a visible
-- lesson, which needs a published course. There are no cycles (no recursion).
CREATE POLICY grades_read ON app.grades FOR SELECT TO edu_api USING (is_active);
CREATE POLICY subjects_read ON app.subjects FOR SELECT TO edu_api USING (is_active);
CREATE POLICY courses_read ON app.courses FOR SELECT TO edu_api
    USING (visibility = 'published');
CREATE POLICY units_read ON app.units FOR SELECT TO edu_api
    USING (EXISTS (SELECT 1 FROM app.courses c WHERE c.id = units.course_id));
CREATE POLICY lessons_read ON app.lessons FOR SELECT TO edu_api
    USING (is_active AND EXISTS (SELECT 1 FROM app.units u WHERE u.id = lessons.unit_id));

CREATE POLICY pack_current_read ON app.pack_current FOR SELECT TO edu_api
    USING (true);
-- [v0.2 change C14] status = 'active' is re-checked here as defence in depth.
CREATE POLICY pack_releases_read ON app.pack_releases FOR SELECT TO edu_api
    USING (status = 'active'
           AND EXISTS (SELECT 1 FROM app.pack_current pc WHERE pc.release_id = pack_releases.id));
CREATE POLICY pack_items_read ON app.pack_items FOR SELECT TO edu_api
    USING (EXISTS (SELECT 1 FROM app.pack_releases pr WHERE pr.id = pack_items.pack_release_id));
-- [v0.2 change C14] The draft did not require the lesson/course to be visible,
-- so a revision in a current pack stayed readable after its course was
-- archived or its lesson deactivated.
CREATE POLICY revisions_read ON app.lesson_revisions FOR SELECT TO edu_api
    USING (status = 'approved'
           AND EXISTS (SELECT 1 FROM app.pack_items pi WHERE pi.lesson_revision_id = lesson_revisions.id)
           AND EXISTS (SELECT 1 FROM app.lessons l WHERE l.id = lesson_revisions.lesson_id));
CREATE POLICY questions_read ON app.question_revisions FOR SELECT TO edu_api
    USING (EXISTS (SELECT 1 FROM app.lesson_revisions lr WHERE lr.id = question_revisions.lesson_revision_id));

-- ----------------------------------------------------------------------------
-- Policies: the learner's own learning + sync records (read-only)
-- ----------------------------------------------------------------------------
CREATE POLICY progress_select_own ON app.lesson_progress
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY attempts_select_own ON app.practice_attempts
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY state_select_own ON app.account_sync_state
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY receipts_select_own ON app.sync_receipts
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY feed_select_own ON app.account_change_feed
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
