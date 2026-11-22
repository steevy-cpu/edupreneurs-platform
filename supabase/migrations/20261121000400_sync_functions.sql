-- Mon Edupreneur 2.0 — the offline-sync write boundary
--
-- [v0.2 change C01] In the v0.2 draft the student API role could INSERT its own
-- practice attempts (including the score), receipts and change-feed rows, and
-- UPDATE its own progress and version counter. One bug in the API layer would
-- have been enough to forge a score or rewind a learner's change history.
--
-- Here the API role has NO write access to those tables. The only way in is
-- app.sync_apply_operation(), which performs — atomically, in the caller's
-- transaction — everything that must be true together:
--
--   1. lock the learner's sync row (serialises that learner's operations),
--   2. de-duplicate on (learner, op_id) and detect op_id reuse,
--   3. check the content is approved and was really released to students,
--   4. SCORE THE ANSWER FROM THE STORED ANSWER KEY (the caller cannot pass a score),
--   5. write the canonical attempt / progress row,
--   6. allocate the next per-learner change version (gap-free),
--   7. append the change-feed row and the durable receipt.
--
-- The learner is ALWAYS app.current_actor_id(); there is no learner parameter.
--
-- Residual trust: the function trusts the API for (a) the actor id it placed in
-- the transaction and (b) the payload digest. A wrong digest can only weaken
-- de-duplication for the caller's own operations. See docs/SECURITY.md.

-- Has this revision ever been genuinely released to students?
-- 'retired' counts on purpose: a phone that was offline for weeks may still
-- hold an older pack, and its honest work must not be thrown away.
-- 'building', 'ready' and 'revoked' releases do not count.
CREATE FUNCTION app.revision_is_syncable(p_lesson_revision_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM app.lesson_revisions lr
        JOIN app.pack_items pi ON pi.lesson_revision_id = lr.id
        JOIN app.pack_releases pr ON pr.id = pi.pack_release_id
        WHERE lr.id = p_lesson_revision_id
          AND lr.status = 'approved'
          AND pr.status IN ('active', 'retired')
    )
$$;

CREATE FUNCTION app.sync_apply_operation(
    p_op_id uuid,
    p_kind text,
    p_payload jsonb,
    p_payload_sha256 bytea,
    p_canon_version text,
    p_client_recorded_at timestamptz DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_receipt record;
    v_result_code text;
    v_result jsonb;
    v_version bigint;
    -- practice_answer
    v_question_id uuid;
    v_choice text;
    v_question record;
    v_correct_choice text;
    v_is_correct boolean;
    v_score numeric(5,4);
    v_attempt_id uuid;
    -- lesson_completed
    v_revision_id uuid;
    v_lesson_id uuid;
    v_progress record;
    v_completed_at timestamptz;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    IF p_op_id IS NULL OR p_kind IS NULL OR p_canon_version IS NULL
       OR p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object'
       OR p_payload_sha256 IS NULL OR octet_length(p_payload_sha256) <> 32 THEN
        RAISE EXCEPTION 'Malformed sync operation arguments' USING ERRCODE = '22023';
    END IF;
    IF p_kind NOT IN ('practice_answer', 'lesson_completed') THEN
        RAISE EXCEPTION 'Unsupported sync operation kind' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.learner_profiles WHERE user_id = v_actor) THEN
        RAISE EXCEPTION 'Learner profile required' USING ERRCODE = '42501';
    END IF;

    -- (1) Per-learner serialisation. Two devices, or twenty parallel retries of
    -- the same request, queue up here one at a time for this learner only;
    -- other learners are not blocked. The lock is held until COMMIT, so change
    -- versions become visible to readers strictly in order.
    INSERT INTO app.account_sync_state (learner_id) VALUES (v_actor)
        ON CONFLICT (learner_id) DO NOTHING;
    PERFORM 1 FROM app.account_sync_state WHERE learner_id = v_actor FOR UPDATE;

    -- (2) De-duplication. Runs after the lock, so it sees every receipt
    -- committed by whoever held the lock before us.
    SELECT r.payload_sha256, r.result_code, r.result INTO v_receipt
    FROM app.sync_receipts r
    WHERE r.learner_id = v_actor AND r.op_id = p_op_id;
    IF FOUND THEN
        IF v_receipt.payload_sha256 = p_payload_sha256 THEN
            RETURN jsonb_build_object(
                'status', v_receipt.result_code, 'replayed', true, 'result', v_receipt.result);
        END IF;
        RETURN jsonb_build_object(
            'status', 'conflict', 'replayed', false,
            'result', jsonb_build_object('code', 'op_id_reused_with_different_payload'));
    END IF;

    IF p_kind = 'practice_answer' THEN
        v_question_id := (p_payload ->> 'question_revision_id')::uuid;
        v_choice := p_payload #>> '{response,choice_id}';
        IF v_question_id IS NULL OR v_choice IS NULL THEN
            RAISE EXCEPTION 'Malformed practice_answer payload' USING ERRCODE = '22023';
        END IF;

        SELECT q.id, q.lesson_revision_id, q.kind, q.response_spec, q.answer_key, lr.lesson_id
          INTO v_question
        FROM app.question_revisions q
        JOIN app.lesson_revisions lr ON lr.id = q.lesson_revision_id
        WHERE q.id = v_question_id;

        -- "Unknown" and "exists but is a draft" give the same answer on purpose,
        -- so this cannot be used to probe for unpublished content.
        IF NOT FOUND OR NOT app.revision_is_syncable(v_question.lesson_revision_id) THEN
            v_result_code := 'rejected';
            v_result := jsonb_build_object('code', 'content_not_available');
        ELSIF v_question.kind <> 'mcq' THEN
            v_result_code := 'rejected';
            v_result := jsonb_build_object('code', 'unsupported_question_kind');
        ELSIF NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(
                CASE WHEN jsonb_typeof(v_question.response_spec -> 'choices') = 'array'
                     THEN v_question.response_spec -> 'choices' ELSE '[]'::jsonb END) c
            WHERE c ->> 'id' = v_choice
        ) THEN
            v_result_code := 'rejected';
            v_result := jsonb_build_object('code', 'invalid_choice');
        ELSE
            v_correct_choice := v_question.answer_key ->> 'correct_choice_id';
            IF v_correct_choice IS NULL THEN
                RAISE EXCEPTION 'Published question % has no answer key', v_question.id
                    USING ERRCODE = 'XX000';
            END IF;
            -- (4) Server-side scoring.
            v_is_correct := (v_choice = v_correct_choice);
            v_score := CASE WHEN v_is_correct THEN 1 ELSE 0 END;

            -- (5) Canonical attempt.
            INSERT INTO app.practice_attempts (
                learner_id, op_id, lesson_revision_id, question_revision_id,
                response, score, scoring_version, client_recorded_at)
            VALUES (
                v_actor, p_op_id, v_question.lesson_revision_id, v_question.id,
                jsonb_build_object('choice_id', v_choice), v_score, 'mcq-v1', p_client_recorded_at)
            RETURNING id INTO v_attempt_id;

            -- (6) Next change version for this learner.
            UPDATE app.account_sync_state SET current_version = current_version + 1
             WHERE learner_id = v_actor
            RETURNING current_version INTO v_version;

            -- (7) Change feed.
            INSERT INTO app.account_change_feed (learner_id, version, entity_type, entity_id, change_data)
            VALUES (v_actor, v_version, 'practice_attempt', v_attempt_id, jsonb_build_object(
                'op_id', p_op_id,
                'lesson_id', v_question.lesson_id,
                'lesson_revision_id', v_question.lesson_revision_id,
                'question_revision_id', v_question.id,
                'choice_id', v_choice,
                'is_correct', v_is_correct,
                'score', v_score,
                'scoring_version', 'mcq-v1'));

            v_result_code := 'accepted';
            v_result := jsonb_build_object(
                'attempt_id', v_attempt_id,
                'question_revision_id', v_question.id,
                'is_correct', v_is_correct,
                'score', v_score,
                'scoring_version', 'mcq-v1',
                'change_version', v_version);
        END IF;

    ELSE -- lesson_completed
        v_revision_id := (p_payload ->> 'lesson_revision_id')::uuid;
        IF v_revision_id IS NULL THEN
            RAISE EXCEPTION 'Malformed lesson_completed payload' USING ERRCODE = '22023';
        END IF;

        SELECT lr.lesson_id INTO v_lesson_id
        FROM app.lesson_revisions lr WHERE lr.id = v_revision_id;

        IF NOT FOUND OR NOT app.revision_is_syncable(v_revision_id) THEN
            v_result_code := 'rejected';
            v_result := jsonb_build_object('code', 'content_not_available');
        ELSE
            SELECT lp.completed_at, lp.last_revision_id, lp.last_change_version INTO v_progress
            FROM app.lesson_progress lp
            WHERE lp.learner_id = v_actor AND lp.lesson_id = v_lesson_id;

            IF FOUND AND v_progress.completed_at IS NOT NULL THEN
                -- Completion merges monotonically: the FIRST completion wins and
                -- keeps pointing at the revision the learner actually studied.
                -- A second device completing the same lesson changes nothing and
                -- therefore produces no new change-feed entry.
                v_result_code := 'accepted';
                v_result := jsonb_build_object(
                    'lesson_id', v_lesson_id,
                    'lesson_revision_id', v_progress.last_revision_id,
                    'completed_at', v_progress.completed_at,
                    'already_completed', true,
                    'change_version', v_progress.last_change_version);
            ELSE
                UPDATE app.account_sync_state SET current_version = current_version + 1
                 WHERE learner_id = v_actor
                RETURNING current_version INTO v_version;

                -- Completion time is the server's clock, never the phone's.
                v_completed_at := now();
                INSERT INTO app.lesson_progress (
                    learner_id, lesson_id, last_revision_id, completed_at, updated_at, last_change_version)
                VALUES (v_actor, v_lesson_id, v_revision_id, v_completed_at, v_completed_at, v_version)
                ON CONFLICT (learner_id, lesson_id) DO UPDATE
                    SET last_revision_id = EXCLUDED.last_revision_id,
                        completed_at = EXCLUDED.completed_at,
                        updated_at = EXCLUDED.updated_at,
                        last_change_version = EXCLUDED.last_change_version;

                INSERT INTO app.account_change_feed (learner_id, version, entity_type, entity_id, change_data)
                VALUES (v_actor, v_version, 'lesson_progress', v_lesson_id, jsonb_build_object(
                    'op_id', p_op_id,
                    'lesson_id', v_lesson_id,
                    'lesson_revision_id', v_revision_id,
                    'completed_at', v_completed_at));

                v_result_code := 'accepted';
                v_result := jsonb_build_object(
                    'lesson_id', v_lesson_id,
                    'lesson_revision_id', v_revision_id,
                    'completed_at', v_completed_at,
                    'already_completed', false,
                    'change_version', v_version);
            END IF;
        END IF;
    END IF;

    -- Durable receipt for accepted AND rejected outcomes: a retry of either
    -- gets exactly the same answer back.
    INSERT INTO app.sync_receipts (
        learner_id, op_id, op_kind, canon_version, payload_sha256, result_code, result)
    VALUES (v_actor, p_op_id, p_kind, p_canon_version, p_payload_sha256, v_result_code, v_result);

    RETURN jsonb_build_object('status', v_result_code, 'replayed', false, 'result', v_result);
END;
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.current_actor_id() TO edu_api;
GRANT EXECUTE ON FUNCTION app.sync_apply_operation(uuid, text, jsonb, bytea, text, timestamptz) TO edu_api;
-- app.revision_is_syncable() is internal: only the function above (running as
-- its owner) calls it.
