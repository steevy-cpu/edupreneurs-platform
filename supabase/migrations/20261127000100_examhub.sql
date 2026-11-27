-- ExamHub-01: first server-authoritative exam workflow.
--
-- catalog -> exam selection -> question delivery -> answer submission -> scoring
--   -> explanation -> history
--
-- Rules this migration enforces in the database itself:
--   1. The student API role can read questions but NOT their answer key or
--      explanation (column-level grants). Keys leave the database only through
--      the functions below, and only after the learner has answered (practice)
--      or finished (timed).
--   2. A learner can never insert or update an attempt, an answer or a score
--      directly. Everything goes through SECURITY DEFINER functions that take
--      the actor from the session, never from an argument.
--   3. A timed attempt is bounded by the SERVER clock (expires_at). The phone's
--      timer is display only.
--   4. Only a published exam is visible. Publishing needs a second person's
--      approval and a source whose rights are cleared.
--   5. Offline practice (lesson questions, which ship their keys) is a separate
--      feature. Nothing here is delivered with keys.
--
-- Rollback: this migration only adds objects. `DROP TABLE app.exam_answers,
-- app.exam_attempts, app.exam_questions, app.exams CASCADE` and dropping the
-- four functions returns the schema to its previous state; no existing table
-- or function is altered.

-- ============================================================================
-- CONTENT
-- ============================================================================
CREATE TABLE app.exams (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,118}[a-z0-9]$'),
    grade_id uuid NOT NULL REFERENCES app.grades(id) ON DELETE RESTRICT,
    subject_id uuid NOT NULL REFERENCES app.subjects(id) ON DELETE RESTRICT,
    -- Baccalauréat series of the legacy ExamHub. NULL when the exam has none (9AF).
    series text CHECK (series IS NULL OR series IN ('SMP','SES','SVT','LLA')),
    exam_type text NOT NULL CHECK (exam_type IN ('official','model','practice','rattrapage')),
    session_year smallint CHECK (session_year IS NULL OR session_year BETWEEN 1990 AND 2100),
    duration_minutes smallint NOT NULL CHECK (duration_minutes BETWEEN 5 AND 300),
    titles jsonb NOT NULL CHECK (jsonb_typeof(titles) = 'object' AND titles ? 'fr'),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','approved','published','withdrawn')),
    source_id uuid REFERENCES app.content_sources(id) ON DELETE RESTRICT,
    -- Identifier in the legacy prototype, kept so an import is idempotent and traceable.
    legacy_id text UNIQUE CHECK (legacy_id IS NULL OR char_length(legacy_id) BETWEEN 1 AND 120),
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    approved_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- Nobody approves their own exam, and nothing is visible without an approver.
    CONSTRAINT exams_second_person CHECK (
        status IN ('draft','withdrawn')
        OR (approved_by IS NOT NULL AND approved_by <> created_by)
    )
);
CREATE INDEX idx_exams_grade_subject ON app.exams(grade_id, subject_id);

CREATE TABLE app.exam_questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_id uuid NOT NULL REFERENCES app.exams(id) ON DELETE RESTRICT,
    locale text NOT NULL CHECK (locale IN ('fr','ht')),
    position integer NOT NULL CHECK (position > 0),
    -- 'open' answers are stored and shown beside a model answer; they are never auto-scored.
    kind text NOT NULL CHECK (kind IN ('mcq','open')),
    points smallint NOT NULL DEFAULT 1 CHECK (points BETWEEN 0 AND 100),
    prompt jsonb NOT NULL CHECK (jsonb_typeof(prompt) = 'object'),
    response_spec jsonb NOT NULL CHECK (jsonb_typeof(response_spec) = 'object'),
    answer_key jsonb NOT NULL CHECK (jsonb_typeof(answer_key) = 'object'),
    explanation jsonb NOT NULL CHECK (jsonb_typeof(explanation) = 'object'),
    UNIQUE (exam_id, locale, position),
    CONSTRAINT exam_questions_mcq_shape CHECK (
        kind <> 'mcq'
        OR (jsonb_typeof(response_spec -> 'choices') = 'array'
            AND jsonb_array_length(response_spec -> 'choices') BETWEEN 2 AND 8
            AND jsonb_typeof(answer_key -> 'correct_choice_id') = 'string')
    ),
    CONSTRAINT exam_questions_open_unscored CHECK (kind <> 'open' OR points = 0)
);

-- A published exam is immutable: its questions cannot change under a learner.
CREATE FUNCTION app.exam_guard_published()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_exam_id uuid := COALESCE(NEW.exam_id, OLD.exam_id);
    v_status text;
BEGIN
    SELECT status INTO v_status FROM app.exams WHERE id = v_exam_id;
    IF v_status = 'published' THEN
        RAISE EXCEPTION 'questions of a published exam are immutable'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;
CREATE TRIGGER exam_questions_immutable_when_published
    BEFORE INSERT OR UPDATE OR DELETE ON app.exam_questions
    FOR EACH ROW EXECUTE FUNCTION app.exam_guard_published();

-- Publishing needs cleared rights, at least one question, and a valid key for every MCQ.
CREATE FUNCTION app.exam_guard_publication()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_rights text;
BEGIN
    IF NEW.status = 'published' AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'published') THEN
        SELECT rights_status INTO v_rights FROM app.content_sources WHERE id = NEW.source_id;
        IF v_rights IS DISTINCT FROM 'cleared' THEN
            RAISE EXCEPTION 'an exam can be published only with a source whose rights are cleared'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM app.exam_questions q WHERE q.exam_id = NEW.id) THEN
            RAISE EXCEPTION 'an exam without questions cannot be published'
                USING ERRCODE = 'check_violation';
        END IF;
        IF EXISTS (
            SELECT 1 FROM app.exam_questions q
            WHERE q.exam_id = NEW.id AND q.kind = 'mcq'
              AND NOT EXISTS (
                  SELECT 1 FROM jsonb_array_elements(q.response_spec -> 'choices') c
                  WHERE c ->> 'id' = q.answer_key ->> 'correct_choice_id')
        ) THEN
            RAISE EXCEPTION 'every multiple-choice question needs a key that names one of its choices'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER exams_publication_guard
    BEFORE INSERT OR UPDATE ON app.exams
    FOR EACH ROW EXECUTE FUNCTION app.exam_guard_publication();

-- ============================================================================
-- LEARNER STATE
-- ============================================================================
CREATE TABLE app.exam_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    exam_id uuid NOT NULL REFERENCES app.exams(id) ON DELETE RESTRICT,
    locale text NOT NULL CHECK (locale IN ('fr','ht')),
    -- 'practice': feedback after each answer, no time limit, not an exam score.
    -- 'timed'   : bounded by the server clock, feedback only after finishing.
    mode text NOT NULL CHECK (mode IN ('practice','timed')),
    status text NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','finished','expired')),
    started_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    finished_at timestamptz,
    score_points integer CHECK (score_points IS NULL OR score_points >= 0),
    max_points integer CHECK (max_points IS NULL OR max_points >= 0),
    scoring_version text,
    CONSTRAINT exam_attempts_timed_has_deadline CHECK ((mode = 'timed') = (expires_at IS NOT NULL)),
    CONSTRAINT exam_attempts_closed_has_score CHECK (
        (status = 'in_progress') = (finished_at IS NULL AND score_points IS NULL)
    ),
    CONSTRAINT exam_attempts_score_in_range CHECK (score_points IS NULL OR score_points <= max_points)
);
CREATE INDEX idx_exam_attempts_learner ON app.exam_attempts(learner_id, started_at DESC);
-- One open timed attempt per learner and exam: starting again resumes it.
CREATE UNIQUE INDEX uq_exam_attempts_one_open_timed
    ON app.exam_attempts(learner_id, exam_id) WHERE status = 'in_progress' AND mode = 'timed';

CREATE TABLE app.exam_answers (
    attempt_id uuid NOT NULL REFERENCES app.exam_attempts(id) ON DELETE RESTRICT,
    question_id uuid NOT NULL REFERENCES app.exam_questions(id) ON DELETE RESTRICT,
    response jsonb NOT NULL CHECK (jsonb_typeof(response) = 'object'),
    -- NULL for open answers: they are not auto-scored.
    is_correct boolean,
    points_awarded smallint NOT NULL DEFAULT 0 CHECK (points_awarded >= 0),
    answered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (attempt_id, question_id)
);

ALTER TABLE app.exams ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.exam_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.exam_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.exam_answers ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON app.exams, app.exam_questions, app.exam_attempts, app.exam_answers
    FROM PUBLIC, anon, authenticated;

GRANT SELECT ON app.exams TO edu_api;
-- NOT answer_key, NOT explanation: the API role cannot read them at all.
GRANT SELECT (id, exam_id, locale, position, kind, points, prompt, response_spec)
    ON app.exam_questions TO edu_api;
GRANT SELECT ON app.exam_attempts, app.exam_answers TO edu_api;

CREATE POLICY exams_read_published ON app.exams FOR SELECT TO edu_api
    USING (status = 'published');
CREATE POLICY exam_questions_read ON app.exam_questions FOR SELECT TO edu_api
    USING (EXISTS (SELECT 1 FROM app.exams e WHERE e.id = exam_questions.exam_id));
CREATE POLICY exam_attempts_select_own ON app.exam_attempts FOR SELECT TO edu_api
    USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY exam_answers_select_own ON app.exam_answers FOR SELECT TO edu_api
    USING (EXISTS (SELECT 1 FROM app.exam_attempts a WHERE a.id = exam_answers.attempt_id));

-- ============================================================================
-- FUNCTIONS (the only write path, and the only way a key leaves the database)
-- ============================================================================

-- Internal: close an attempt and compute its score from the stored answers.
CREATE FUNCTION app.exam_close_attempt(p_attempt_id uuid, p_status text)
RETURNS void
LANGUAGE plpgsql VOLATILE
SET search_path = ''
AS $$
DECLARE
    v_attempt app.exam_attempts%ROWTYPE;
    v_score integer;
    v_max integer;
BEGIN
    SELECT * INTO v_attempt FROM app.exam_attempts WHERE id = p_attempt_id FOR UPDATE;
    IF v_attempt.status <> 'in_progress' THEN
        RETURN;
    END IF;
    SELECT COALESCE(sum(q.points), 0) INTO v_max
    FROM app.exam_questions q
    WHERE q.exam_id = v_attempt.exam_id AND q.locale = v_attempt.locale AND q.kind = 'mcq';
    -- A timed attempt only counts answers recorded before its deadline.
    SELECT COALESCE(sum(a.points_awarded), 0) INTO v_score
    FROM app.exam_answers a
    WHERE a.attempt_id = p_attempt_id
      AND (v_attempt.expires_at IS NULL OR a.answered_at <= v_attempt.expires_at);
    UPDATE app.exam_attempts
    SET status = p_status,
        finished_at = LEAST(now(), COALESCE(expires_at, now())),
        score_points = v_score,
        max_points = v_max,
        scoring_version = 'exam-mcq-v1'
    WHERE id = p_attempt_id;
END;
$$;

CREATE FUNCTION app.exam_start_attempt(p_exam_id uuid, p_locale text, p_mode text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_exam app.exams%ROWTYPE;
    v_attempt app.exam_attempts%ROWTYPE;
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('status', 'unauthenticated');
    END IF;
    IF p_mode IS NULL OR p_mode NOT IN ('practice','timed') OR p_locale IS NULL OR p_locale NOT IN ('fr','ht') THEN
        RETURN jsonb_build_object('status', 'invalid_request');
    END IF;
    SELECT * INTO v_exam FROM app.exams WHERE id = p_exam_id AND status = 'published';
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1 FROM app.exam_questions q WHERE q.exam_id = p_exam_id AND q.locale = p_locale
    ) THEN
        RETURN jsonb_build_object('status', 'exam_not_found');
    END IF;

    IF p_mode = 'timed' THEN
        -- Serialise this learner's starts so two requests cannot open two timed attempts.
        PERFORM pg_advisory_xact_lock(hashtextextended(v_actor::text || ':' || p_exam_id::text, 0));
        SELECT * INTO v_attempt FROM app.exam_attempts
        WHERE learner_id = v_actor AND exam_id = p_exam_id AND mode = 'timed' AND status = 'in_progress';
        IF FOUND THEN
            IF now() > v_attempt.expires_at THEN
                PERFORM app.exam_close_attempt(v_attempt.id, 'expired');
            ELSE
                RETURN jsonb_build_object('status', 'resumed', 'attempt_id', v_attempt.id);
            END IF;
        END IF;
    END IF;

    INSERT INTO app.exam_attempts (learner_id, exam_id, locale, mode, expires_at)
    VALUES (v_actor, p_exam_id, p_locale, p_mode,
            CASE WHEN p_mode = 'timed' THEN now() + make_interval(mins => v_exam.duration_minutes) END)
    RETURNING * INTO v_attempt;
    RETURN jsonb_build_object('status', 'started', 'attempt_id', v_attempt.id);
END;
$$;

CREATE FUNCTION app.exam_submit_answer(p_attempt_id uuid, p_question_id uuid, p_response jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_attempt app.exam_attempts%ROWTYPE;
    v_question app.exam_questions%ROWTYPE;
    v_choice text;
    v_text text;
    v_correct boolean;
    v_points smallint := 0;
    v_response jsonb;
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('status', 'unauthenticated');
    END IF;
    -- Someone else's attempt is indistinguishable from one that does not exist.
    SELECT * INTO v_attempt FROM app.exam_attempts
    WHERE id = p_attempt_id AND learner_id = v_actor FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'attempt_not_found');
    END IF;
    IF v_attempt.status = 'in_progress' AND v_attempt.expires_at IS NOT NULL AND now() > v_attempt.expires_at THEN
        PERFORM app.exam_close_attempt(v_attempt.id, 'expired');
        RETURN jsonb_build_object('status', 'attempt_expired');
    END IF;
    IF v_attempt.status <> 'in_progress' THEN
        RETURN jsonb_build_object('status', 'attempt_closed');
    END IF;
    SELECT * INTO v_question FROM app.exam_questions
    WHERE id = p_question_id AND exam_id = v_attempt.exam_id AND locale = v_attempt.locale;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'question_not_found');
    END IF;
    IF p_response IS NULL OR jsonb_typeof(p_response) <> 'object' THEN
        RETURN jsonb_build_object('status', 'invalid_response');
    END IF;

    IF v_question.kind = 'mcq' THEN
        IF jsonb_typeof(p_response -> 'choice_id') IS DISTINCT FROM 'string' THEN
            RETURN jsonb_build_object('status', 'invalid_response');
        END IF;
        v_choice := p_response ->> 'choice_id';
        IF NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(v_question.response_spec -> 'choices') c
            WHERE c ->> 'id' = v_choice
        ) THEN
            RETURN jsonb_build_object('status', 'invalid_response');
        END IF;
        v_correct := (v_choice = v_question.answer_key ->> 'correct_choice_id');
        v_points := CASE WHEN v_correct THEN v_question.points ELSE 0 END;
        v_response := jsonb_build_object('choice_id', v_choice);
    ELSE
        IF jsonb_typeof(p_response -> 'text') IS DISTINCT FROM 'string' THEN
            RETURN jsonb_build_object('status', 'invalid_response');
        END IF;
        v_text := p_response ->> 'text';
        IF char_length(v_text) NOT BETWEEN 1 AND 4000 THEN
            RETURN jsonb_build_object('status', 'invalid_response');
        END IF;
        v_correct := NULL;
        v_response := jsonb_build_object('text', v_text);
    END IF;

    IF v_attempt.mode = 'practice' THEN
        -- Feedback was already given for this question: the first answer stands.
        INSERT INTO app.exam_answers (attempt_id, question_id, response, is_correct, points_awarded)
        VALUES (v_attempt.id, v_question.id, v_response, v_correct, v_points)
        ON CONFLICT (attempt_id, question_id) DO NOTHING;
        IF NOT FOUND THEN
            RETURN jsonb_build_object('status', 'already_answered');
        END IF;
        RETURN jsonb_build_object(
            'status', 'recorded',
            'is_correct', v_correct,
            'answer_key', v_question.answer_key,
            'explanation', v_question.explanation);
    END IF;

    -- Timed: an answer may be changed until the attempt is finished; nothing is revealed.
    INSERT INTO app.exam_answers (attempt_id, question_id, response, is_correct, points_awarded)
    VALUES (v_attempt.id, v_question.id, v_response, v_correct, v_points)
    ON CONFLICT (attempt_id, question_id) DO UPDATE
        SET response = EXCLUDED.response, is_correct = EXCLUDED.is_correct,
            points_awarded = EXCLUDED.points_awarded, answered_at = now();
    RETURN jsonb_build_object('status', 'recorded');
END;
$$;

CREATE FUNCTION app.exam_finish_attempt(p_attempt_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_attempt app.exam_attempts%ROWTYPE;
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('status', 'unauthenticated');
    END IF;
    SELECT * INTO v_attempt FROM app.exam_attempts
    WHERE id = p_attempt_id AND learner_id = v_actor FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'attempt_not_found');
    END IF;
    IF v_attempt.status = 'in_progress' THEN
        PERFORM app.exam_close_attempt(
            v_attempt.id,
            CASE WHEN v_attempt.expires_at IS NOT NULL AND now() > v_attempt.expires_at
                 THEN 'expired' ELSE 'finished' END);
    END IF;
    RETURN jsonb_build_object('status', 'closed');
END;
$$;

-- Review of one of the caller's own attempts. Keys and explanations are included
-- ONLY for questions the learner may now see: every question once the attempt is
-- closed, and only the answered ones while a practice attempt is in progress.
CREATE FUNCTION app.exam_attempt_review(p_attempt_id uuid)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_attempt app.exam_attempts%ROWTYPE;
    v_items jsonb;
BEGIN
    IF v_actor IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT * INTO v_attempt FROM app.exam_attempts WHERE id = p_attempt_id AND learner_id = v_actor;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    -- "revealed" is decided once per question; verdict, points, key and explanation all follow it,
    -- so an open timed attempt discloses nothing about correctness.
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'question_id', r.id,
               'position', r.position,
               'kind', r.kind,
               'points', r.points,
               'prompt', r.prompt,
               'response_spec', r.response_spec,
               'response', r.response,
               'revealed', r.revealed,
               'is_correct', CASE WHEN r.revealed THEN r.is_correct END,
               'points_awarded', CASE WHEN r.revealed THEN COALESCE(r.points_awarded, 0) ELSE 0 END,
               'answer_key', CASE WHEN r.revealed THEN r.answer_key END,
               'explanation', CASE WHEN r.revealed THEN r.explanation END
           ) ORDER BY r.position), '[]'::jsonb)
    INTO v_items
    FROM (
        SELECT q.id, q.position, q.kind, q.points, q.prompt, q.response_spec, q.answer_key, q.explanation,
               a.response, a.is_correct, a.points_awarded,
               (v_attempt.status <> 'in_progress'
                OR (v_attempt.mode = 'practice' AND a.question_id IS NOT NULL)) AS revealed
        FROM app.exam_questions q
        LEFT JOIN app.exam_answers a ON a.question_id = q.id AND a.attempt_id = v_attempt.id
        WHERE q.exam_id = v_attempt.exam_id AND q.locale = v_attempt.locale
    ) r;
    RETURN v_items;
END;
$$;

REVOKE ALL ON FUNCTION app.exam_close_attempt(uuid, text),
    app.exam_start_attempt(uuid, text, text),
    app.exam_submit_answer(uuid, uuid, jsonb),
    app.exam_finish_attempt(uuid),
    app.exam_attempt_review(uuid),
    app.exam_guard_published(),
    app.exam_guard_publication()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.exam_start_attempt(uuid, text, text),
    app.exam_submit_answer(uuid, uuid, jsonb),
    app.exam_finish_attempt(uuid),
    app.exam_attempt_review(uuid) TO edu_api;
-- app.exam_close_attempt() is internal: only the functions above (running as
-- their owner) call it.
