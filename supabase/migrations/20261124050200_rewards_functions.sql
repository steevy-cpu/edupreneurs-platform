-- Mon Edupreneur 2.0 — rewards: the award, reconcile, rebuild and erase functions
--
-- CONCURRENCY MODEL
--   Every function that reads-then-writes a learner's rewards first takes a
--   transaction-scoped ADVISORY lock keyed by that learner
--   (rewards.lock_learner). It is held until COMMIT/ROLLBACK.
--     * In the push path the award step runs after app.sync_apply_operation in
--       the same transaction, so it is already serialised per learner by the
--       sync row lock; it then takes the rewards lock as well. Order is always
--       "sync lock, then rewards lock".
--     * Reconcile, rebuild, reversal and erase take ONLY the rewards lock and
--       never the sync lock, so no lock cycle exists.
--     * These functions are VOLATILE plpgsql: under READ COMMITTED every
--       statement after the lock sees what the previous lock holder committed.
--   The lock makes cap checks and streak rebuilds race-free. It is NOT what
--   prevents a double award: that is the UNIQUE (learner_id, source_key)
--   constraint, which holds even for a writer that forgets the lock.
--
-- All functions: owner postgres, empty search_path, schema-qualified SQL,
-- EXECUTE revoked from everyone at the end, then granted one by one.

-- Namespace 54050 is this lane's (two-int advisory keys do not collide with
-- single-bigint keys). A hash collision only makes two learners wait for each
-- other; it can never let two writers for the same learner in together.
CREATE FUNCTION rewards.lock_learner(p_learner_id uuid)
RETURNS void
LANGUAGE sql VOLATILE
SET search_path = ''
AS $$ SELECT pg_advisory_xact_lock(54050, hashtext(p_learner_id::text)) $$;

-- ----------------------------------------------------------------------------
-- Rebuilds (derived caches)
-- ----------------------------------------------------------------------------
CREATE FUNCTION rewards.rebuild_balance(p_learner_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_before bigint;
    v_balance bigint;
    v_lifetime bigint;
    v_entries bigint;
BEGIN
    IF p_learner_id IS NULL THEN
        RAISE EXCEPTION 'Learner id required' USING ERRCODE = '22023';
    END IF;
    PERFORM rewards.lock_learner(p_learner_id);

    SELECT b.balance INTO v_before FROM rewards.balances b WHERE b.learner_id = p_learner_id;
    SELECT COALESCE(sum(l.amount), 0), COALESCE(sum(l.amount) FILTER (WHERE l.amount > 0), 0), count(*)
      INTO v_balance, v_lifetime, v_entries
    FROM rewards.ledger l WHERE l.learner_id = p_learner_id;

    IF v_entries = 0 THEN
        DELETE FROM rewards.balances b WHERE b.learner_id = p_learner_id;
    ELSE
        INSERT INTO rewards.balances AS b (learner_id, balance, lifetime_earned)
        VALUES (p_learner_id, v_balance, v_lifetime)
        ON CONFLICT (learner_id) DO UPDATE
            SET balance = EXCLUDED.balance, lifetime_earned = EXCLUDED.lifetime_earned,
                updated_at = now()
            WHERE b.balance IS DISTINCT FROM EXCLUDED.balance
               OR b.lifetime_earned IS DISTINCT FROM EXCLUDED.lifetime_earned;
    END IF;

    RETURN jsonb_build_object(
        'balance_before', COALESCE(v_before, 0),
        'balance', v_balance,
        'ledger_entries', v_entries,
        'corrected', COALESCE(v_before, 0) <> v_balance);
END;
$$;

-- Recompute the streak row from the activity days (gaps-and-islands). Called
-- only when a NEW day appears, i.e. at most once per learner per day, plus
-- reconciliation. Correct in any arrival order, which matters because
-- reconciliation may examine old operations after newer ones.
CREATE FUNCTION rewards.rebuild_streak(p_learner_id uuid)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_latest record;
    v_longest record;
BEGIN
    IF p_learner_id IS NULL THEN
        RAISE EXCEPTION 'Learner id required' USING ERRCODE = '22023';
    END IF;
    PERFORM rewards.lock_learner(p_learner_id);

    WITH numbered AS (
        SELECT d.day, d.day - (row_number() OVER (ORDER BY d.day))::integer AS island
        FROM rewards.activity_days d WHERE d.learner_id = p_learner_id
    ), runs AS (
        SELECT min(day) AS run_start, max(day) AS run_end, count(*)::integer AS run_days
        FROM numbered GROUP BY island
    )
    SELECT r.run_start, r.run_end, r.run_days INTO v_latest
    FROM runs r ORDER BY r.run_end DESC LIMIT 1;

    IF NOT FOUND THEN
        DELETE FROM rewards.streak_state s WHERE s.learner_id = p_learner_id;
        RETURN;
    END IF;

    WITH numbered AS (
        SELECT d.day, d.day - (row_number() OVER (ORDER BY d.day))::integer AS island
        FROM rewards.activity_days d WHERE d.learner_id = p_learner_id
    ), runs AS (
        SELECT max(day) AS run_end, count(*)::integer AS run_days
        FROM numbered GROUP BY island
    )
    SELECT r.run_end, r.run_days INTO v_longest
    FROM runs r ORDER BY r.run_days DESC, r.run_end DESC LIMIT 1;

    INSERT INTO rewards.streak_state AS s (
        learner_id, latest_run_days, latest_run_start, last_active_day,
        longest_run_days, longest_run_end)
    VALUES (p_learner_id, v_latest.run_days, v_latest.run_start, v_latest.run_end,
            v_longest.run_days, v_longest.run_end)
    ON CONFLICT (learner_id) DO UPDATE
        SET latest_run_days = EXCLUDED.latest_run_days,
            latest_run_start = EXCLUDED.latest_run_start,
            last_active_day = EXCLUDED.last_active_day,
            longest_run_days = EXCLUDED.longest_run_days,
            longest_run_end = EXCLUDED.longest_run_end,
            updated_at = now();
END;
$$;

-- ----------------------------------------------------------------------------
-- The core: examine ONE accepted operation of ONE learner, exactly once
-- ----------------------------------------------------------------------------
-- Internal (EXECUTE granted to nobody). Everything it uses is server-written:
-- the receipt, the scored attempt, the progress row. Nothing comes from the
-- device and nothing from the caller except WHICH operation to look at.
CREATE FUNCTION rewards.apply_operation(p_learner_id uuid, p_op_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_none CONSTANT jsonb := jsonb_build_object(
        'status', 'no_award', 'replayed', false, 'gold', 0, 'achievements', '[]'::jsonb);
    v_receipt record;
    v_done record;
    v_day date;
    v_event text;
    v_lesson_id uuid;
    v_question_key text;
    v_attempt record;
    v_rule record;
    v_outcome text;
    v_gold integer := 0;
    v_inserted uuid;
    v_new_day boolean := false;
    v_definition record;
    v_metric integer;
    v_bonus record;
    v_bonus_ledger uuid;
    v_achievements jsonb := '[]'::jsonb;
BEGIN
    IF p_learner_id IS NULL OR p_op_id IS NULL THEN
        RETURN v_none;
    END IF;

    -- Unknown, rejected and "someone else's" operations are indistinguishable
    -- here: the look-up is by (learner, op) and anything but an accepted
    -- receipt gives the same empty answer, without taking a lock.
    SELECT r.op_kind, r.result, r.created_at INTO v_receipt
    FROM app.sync_receipts r
    WHERE r.learner_id = p_learner_id AND r.op_id = p_op_id AND r.result_code = 'accepted';
    IF NOT FOUND THEN
        RETURN v_none;
    END IF;

    PERFORM rewards.lock_learner(p_learner_id);

    -- Already examined (a replay, a concurrent retry, or reconcile got here
    -- first): repeat the recorded decision, change nothing.
    SELECT p.outcome, p.gold INTO v_done
    FROM rewards.processed_operations p
    WHERE p.learner_id = p_learner_id AND p.op_id = p_op_id;
    IF FOUND THEN
        RETURN jsonb_build_object('status', v_done.outcome, 'replayed', true,
                                  'gold', v_done.gold, 'achievements', '[]'::jsonb);
    END IF;

    v_day := rewards.haiti_day(v_receipt.created_at);

    -- Streak: any accepted learning operation makes the day an active day.
    INSERT INTO rewards.activity_days (learner_id, day, first_op_id)
    VALUES (p_learner_id, v_day, p_op_id)
    ON CONFLICT (learner_id, day) DO NOTHING;
    IF FOUND THEN
        v_new_day := true;
        PERFORM rewards.rebuild_streak(p_learner_id);
    END IF;

    -- Which rewardable event, if any, does this operation stand for?
    IF v_receipt.op_kind = 'practice_answer' THEN
        SELECT a.score, lr.lesson_id, q.question_key INTO v_attempt
        FROM app.practice_attempts a
        JOIN app.question_revisions q ON q.id = a.question_revision_id
        JOIN app.lesson_revisions lr ON lr.id = a.lesson_revision_id
        WHERE a.learner_id = p_learner_id AND a.op_id = p_op_id;
        IF FOUND AND v_attempt.score = 1 THEN
            v_event := 'question_first_correct';
            v_lesson_id := v_attempt.lesson_id;
            v_question_key := v_attempt.question_key;
        END IF;
    ELSIF v_receipt.op_kind = 'lesson_completed' THEN
        v_lesson_id := (v_receipt.result ->> 'lesson_id')::uuid;
        IF v_lesson_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM app.lesson_progress lp
            WHERE lp.learner_id = p_learner_id AND lp.lesson_id = v_lesson_id
              AND lp.completed_at IS NOT NULL
        ) THEN
            v_event := 'lesson_first_completed';
        END IF;
    END IF;
    -- Any other operation kind (future: exams, notes, ...) earns nothing until
    -- a rule and a branch are added for it on purpose.

    IF v_event IS NULL THEN
        v_outcome := 'not_eligible';
    ELSE
        SELECT r.code, r.version, r.amount, r.per_lesson_cap, r.per_day_cap INTO v_rule
        FROM rewards.rules r WHERE r.code = v_event AND r.is_active;
        IF NOT FOUND THEN
            v_outcome := 'no_active_rule';
        ELSIF EXISTS (
            SELECT 1 FROM rewards.ledger l
            WHERE l.learner_id = p_learner_id
              AND l.source_key = CASE v_event
                    WHEN 'question_first_correct' THEN 'q:' || v_lesson_id::text || ':' || v_question_key
                    ELSE 'l:' || v_lesson_id::text END
        ) THEN
            v_outcome := 'duplicate';
        ELSIF v_rule.per_lesson_cap IS NOT NULL AND v_rule.amount + (
            SELECT COALESCE(sum(l.amount), 0) FROM rewards.ledger l
            WHERE l.learner_id = p_learner_id AND l.entry_kind = 'award'
              AND l.rule_code = v_rule.code AND l.lesson_id = v_lesson_id
        ) > v_rule.per_lesson_cap THEN
            v_outcome := 'capped_lesson';
        ELSIF v_rule.per_day_cap IS NOT NULL AND v_rule.amount + (
            SELECT COALESCE(sum(l.amount), 0) FROM rewards.ledger l
            WHERE l.learner_id = p_learner_id AND l.entry_kind = 'award'
              AND l.rule_code = v_rule.code AND l.accepted_day = v_day
        ) > v_rule.per_day_cap THEN
            v_outcome := 'capped_day';
        ELSE
            INSERT INTO rewards.ledger (
                learner_id, entry_kind, amount, rule_code, rule_version, source_kind,
                source_op_id, lesson_id, question_key, accepted_at, accepted_day)
            VALUES (
                p_learner_id, 'award', v_rule.amount, v_rule.code, v_rule.version, v_event,
                p_op_id, v_lesson_id, v_question_key, v_receipt.created_at, v_day)
            ON CONFLICT ON CONSTRAINT ledger_exactly_once DO NOTHING
            RETURNING id INTO v_inserted;
            IF v_inserted IS NULL THEN
                v_outcome := 'duplicate';
            ELSE
                v_outcome := 'awarded';
                v_gold := v_rule.amount;
            END IF;
        END IF;
    END IF;

    -- Achievements can only newly apply when something changed.
    IF v_inserted IS NOT NULL OR v_new_day OR v_event = 'lesson_first_completed' THEN
        FOR v_definition IN
            SELECT d.code, d.criterion_kind, d.threshold, d.bonus_rule_code
            FROM rewards.achievement_definitions d
            WHERE d.is_active AND NOT EXISTS (
                SELECT 1 FROM rewards.achievement_awards a
                WHERE a.learner_id = p_learner_id AND a.achievement_code = d.code)
            ORDER BY d.sort_order, d.code
        LOOP
            IF v_definition.criterion_kind = 'lessons_completed' THEN
                SELECT count(*)::integer INTO v_metric FROM (
                    SELECT 1 FROM app.lesson_progress lp
                    WHERE lp.learner_id = p_learner_id AND lp.completed_at IS NOT NULL
                    LIMIT v_definition.threshold) t;
            ELSIF v_definition.criterion_kind = 'questions_correct' THEN
                SELECT count(*)::integer INTO v_metric FROM (
                    SELECT 1 FROM rewards.ledger l
                    WHERE l.learner_id = p_learner_id
                      AND l.source_kind = 'question_first_correct'
                    LIMIT v_definition.threshold) t;
            ELSE -- streak_days
                SELECT COALESCE(max(s.longest_run_days), 0) INTO v_metric
                FROM rewards.streak_state s WHERE s.learner_id = p_learner_id;
            END IF;
            CONTINUE WHEN v_metric < v_definition.threshold;

            v_bonus_ledger := NULL;
            IF v_definition.bonus_rule_code IS NOT NULL THEN
                SELECT r.code, r.version, r.amount INTO v_bonus
                FROM rewards.rules r
                WHERE r.code = v_definition.bonus_rule_code AND r.is_active
                  AND r.event_kind = 'achievement';
                IF FOUND THEN
                    INSERT INTO rewards.ledger (
                        learner_id, entry_kind, amount, rule_code, rule_version, source_kind,
                        source_op_id, achievement_code, accepted_at, accepted_day)
                    VALUES (
                        p_learner_id, 'award', v_bonus.amount, v_bonus.code, v_bonus.version,
                        'achievement', p_op_id, v_definition.code, v_receipt.created_at, v_day)
                    ON CONFLICT ON CONSTRAINT ledger_exactly_once DO NOTHING
                    RETURNING id INTO v_bonus_ledger;
                    IF v_bonus_ledger IS NOT NULL THEN
                        v_gold := v_gold + v_bonus.amount;
                    END IF;
                END IF;
            END IF;

            INSERT INTO rewards.achievement_awards (
                learner_id, achievement_code, source_op_id, ledger_id, awarded_at, awarded_day)
            VALUES (p_learner_id, v_definition.code, p_op_id, v_bonus_ledger,
                    v_receipt.created_at, v_day)
            ON CONFLICT (learner_id, achievement_code) DO NOTHING;
            IF FOUND THEN
                v_achievements := v_achievements || to_jsonb(v_definition.code);
            END IF;
        END LOOP;
    END IF;

    INSERT INTO rewards.processed_operations (learner_id, op_id, outcome, gold, accepted_day)
    VALUES (p_learner_id, p_op_id, v_outcome, v_gold, v_day);

    RETURN jsonb_build_object('status', v_outcome, 'replayed', false,
                              'gold', v_gold, 'achievements', v_achievements);
END;
$$;

-- ----------------------------------------------------------------------------
-- Student API entry point (the push hook)
-- ----------------------------------------------------------------------------
-- The learner is ALWAYS app.current_actor_id(); there is no learner parameter
-- and no amount parameter.
CREATE FUNCTION rewards.award_for_operation(p_op_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    RETURN rewards.apply_operation(v_actor, p_op_id);
END;
$$;

-- ----------------------------------------------------------------------------
-- Reconciliation: examine accepted operations that were never examined
-- ----------------------------------------------------------------------------
-- This is what makes the ledger self-healing: if the push hook was switched
-- off, failed, or timed out, the learning operation still committed and is
-- found here later, oldest first. Bounded per call.
CREATE FUNCTION rewards.reconcile_learner_internal(p_learner_id uuid, p_limit integer)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 200), 1), 500);
    v_op record;
    v_result jsonb;
    v_examined integer := 0;
    v_gold integer := 0;
    v_more boolean;
    v_rebuild jsonb;
BEGIN
    IF p_learner_id IS NULL THEN
        RAISE EXCEPTION 'Learner id required' USING ERRCODE = '22023';
    END IF;

    -- Fast path without the lock: nothing pending, nothing to do.
    IF NOT EXISTS (
        SELECT 1 FROM app.sync_receipts r
        WHERE r.learner_id = p_learner_id AND r.result_code = 'accepted'
          AND NOT EXISTS (SELECT 1 FROM rewards.processed_operations p
                          WHERE p.learner_id = r.learner_id AND p.op_id = r.op_id)
    ) THEN
        RETURN jsonb_build_object('examined', 0, 'gold', 0, 'more', false,
                                  'balance_corrected', false);
    END IF;

    PERFORM rewards.lock_learner(p_learner_id);

    FOR v_op IN
        SELECT r.op_id
        FROM app.sync_receipts r
        WHERE r.learner_id = p_learner_id AND r.result_code = 'accepted'
          AND NOT EXISTS (SELECT 1 FROM rewards.processed_operations p
                          WHERE p.learner_id = r.learner_id AND p.op_id = r.op_id)
        ORDER BY r.created_at, r.op_id
        LIMIT v_limit
    LOOP
        v_result := rewards.apply_operation(p_learner_id, v_op.op_id);
        IF NOT (v_result ->> 'replayed')::boolean THEN
            v_examined := v_examined + 1;
            v_gold := v_gold + (v_result ->> 'gold')::integer;
        END IF;
    END LOOP;

    v_more := EXISTS (
        SELECT 1 FROM app.sync_receipts r
        WHERE r.learner_id = p_learner_id AND r.result_code = 'accepted'
          AND NOT EXISTS (SELECT 1 FROM rewards.processed_operations p
                          WHERE p.learner_id = r.learner_id AND p.op_id = r.op_id));

    PERFORM rewards.rebuild_streak(p_learner_id);
    v_rebuild := rewards.rebuild_balance(p_learner_id);

    RETURN jsonb_build_object('examined', v_examined, 'gold', v_gold, 'more', v_more,
                              'balance_corrected', (v_rebuild ->> 'corrected')::boolean);
END;
$$;

-- Student API: reconcile the CALLER only.
CREATE FUNCTION rewards.reconcile_learner(p_limit integer DEFAULT 200)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    RETURN rewards.reconcile_learner_internal(v_actor, p_limit);
END;
$$;

-- SEAM for the worker / staff lane (EXECUTE granted to NOBODY tonight):
-- reconcile up to p_max_learners learners that have unexamined operations.
-- Learners are taken in id order so that two concurrent batches lock in the
-- same order.
CREATE FUNCTION rewards.reconcile_batch(p_max_learners integer DEFAULT 50,
                                        p_max_ops_per_learner integer DEFAULT 200)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_max integer := LEAST(GREATEST(COALESCE(p_max_learners, 50), 1), 500);
    v_learner record;
    v_result jsonb;
    v_learners integer := 0;
    v_examined integer := 0;
    v_gold integer := 0;
BEGIN
    FOR v_learner IN
        SELECT pending.learner_id FROM (
            SELECT DISTINCT r.learner_id
            FROM app.sync_receipts r
            WHERE r.result_code = 'accepted'
              AND NOT EXISTS (SELECT 1 FROM rewards.processed_operations p
                              WHERE p.learner_id = r.learner_id AND p.op_id = r.op_id)
            LIMIT v_max
        ) pending
        ORDER BY pending.learner_id
    LOOP
        v_result := rewards.reconcile_learner_internal(v_learner.learner_id, p_max_ops_per_learner);
        v_learners := v_learners + 1;
        v_examined := v_examined + (v_result ->> 'examined')::integer;
        v_gold := v_gold + (v_result ->> 'gold')::integer;
    END LOOP;
    RETURN jsonb_build_object('learners', v_learners, 'examined', v_examined, 'gold', v_gold);
END;
$$;

-- ----------------------------------------------------------------------------
-- SEAM for staff corrections (EXECUTE granted to NOBODY tonight)
-- ----------------------------------------------------------------------------
-- A correction never edits history: it appends the single reversal of one
-- award. The reversed source key stays taken, so the same thing cannot be
-- earned again afterwards. When the staff lane lands, a staff-schema wrapper
-- should check the caller's role, call this, and write ops.audit_write.
CREATE FUNCTION rewards.reverse_entry(p_ledger_id uuid, p_reason text)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_original record;
    v_now timestamptz := now();
    v_id uuid;
BEGIN
    SELECT l.learner_id, l.amount, l.rule_code, l.rule_version, l.entry_kind INTO v_original
    FROM rewards.ledger l WHERE l.id = p_ledger_id;
    IF NOT FOUND OR v_original.entry_kind <> 'award' THEN
        RAISE EXCEPTION 'Only an existing award can be reversed' USING ERRCODE = '22023';
    END IF;
    PERFORM rewards.lock_learner(v_original.learner_id);

    INSERT INTO rewards.ledger (
        learner_id, entry_kind, amount, rule_code, rule_version, source_kind,
        reverses_ledger_id, accepted_at, accepted_day, reason)
    VALUES (
        v_original.learner_id, 'reversal', -v_original.amount, v_original.rule_code,
        v_original.rule_version, 'reversal', p_ledger_id, v_now, rewards.haiti_day(v_now), p_reason)
    RETURNING id INTO v_id;  -- a second reversal of the same row violates ledger_exactly_once
    RETURN v_id;
END;
$$;

-- ----------------------------------------------------------------------------
-- Erasure hook (plan §3; EXECUTE granted to NOBODY — the account orchestrator
-- calls it as owner)
-- ----------------------------------------------------------------------------
-- Removes every rewards row of one learner. ORDER MATTERS for the caller:
-- erase (or keep out of reach) the learner's accepted receipts FIRST, otherwise
-- a later reconciliation would faithfully re-derive the rewards from them; and
-- call this BEFORE deleting app.learner_profiles (foreign keys are RESTRICT).
CREATE FUNCTION rewards.erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_awards bigint;
    v_ledger bigint;
    v_processed bigint;
    v_days bigint;
    v_streak bigint;
    v_balances bigint;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'Learner id required' USING ERRCODE = '22023';
    END IF;
    PERFORM rewards.lock_learner(p_user_id);
    -- Lets the append-only guards delete THIS learner's rows, in this transaction only.
    PERFORM set_config('rewards.erasing_learner', p_user_id::text, true);

    WITH gone AS (DELETE FROM rewards.achievement_awards WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_awards FROM gone;
    WITH gone AS (DELETE FROM rewards.ledger WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_ledger FROM gone;
    WITH gone AS (DELETE FROM rewards.processed_operations WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_processed FROM gone;
    WITH gone AS (DELETE FROM rewards.activity_days WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_days FROM gone;
    WITH gone AS (DELETE FROM rewards.streak_state WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_streak FROM gone;
    WITH gone AS (DELETE FROM rewards.balances WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_balances FROM gone;

    PERFORM set_config('rewards.erasing_learner', '', true);

    RETURN jsonb_build_object(
        'schema', 'rewards',
        'deleted', jsonb_build_object(
            'achievement_awards', v_awards, 'ledger', v_ledger,
            'processed_operations', v_processed, 'activity_days', v_days,
            'streak_state', v_streak, 'balances', v_balances));
END;
$$;

-- ----------------------------------------------------------------------------
-- Privileges
-- ----------------------------------------------------------------------------
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA rewards FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rewards.award_for_operation(uuid) TO edu_api;
GRANT EXECUTE ON FUNCTION rewards.reconcile_learner(integer) TO edu_api;
GRANT EXECUTE ON FUNCTION rewards.haiti_day(timestamptz) TO edu_api;
-- NOT granted to anyone: apply_operation, reconcile_learner_internal,
-- reconcile_batch, rebuild_balance, rebuild_streak, reverse_entry,
-- erase_learner, lock_learner and the trigger functions.
