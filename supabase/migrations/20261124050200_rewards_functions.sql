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
-- All functions: owner postgres, `search_path = pg_catalog, pg_temp` (ruling
-- R-03: the temporary schema explicitly LAST, so a session's temp objects can
-- never shadow a catalog type or function), schema-qualified SQL,
-- EXECUTE revoked from everyone at the end, then granted one by one.

-- Namespace 54050 is this lane's (two-int advisory keys do not collide with
-- single-bigint keys). A hash collision only makes two learners wait for each
-- other; it can never let two writers for the same learner in together.
CREATE FUNCTION rewards.lock_learner(p_learner_id uuid)
RETURNS void
LANGUAGE sql VOLATILE
SET search_path = pg_catalog, pg_temp
AS $$ SELECT pg_advisory_xact_lock(54050, hashtext(p_learner_id::text)) $$;

-- Bounded variant for callers that must not wait behind another holder: the
-- push path (which is holding the learner's SYNC lock) and the worker batch.
-- Tries for about p_wait_ms, then gives up and returns false. It never raises
-- and never depends on the connection's lock_timeout.
CREATE FUNCTION rewards.try_lock_learner(p_learner_id uuid, p_wait_ms integer)
RETURNS boolean
LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_deadline timestamptz := clock_timestamp() + make_interval(secs => GREATEST(COALESCE(p_wait_ms, 0), 0) / 1000.0);
BEGIN
    LOOP
        IF pg_try_advisory_xact_lock(54050, hashtext(p_learner_id::text)) THEN
            RETURN true;
        END IF;
        EXIT WHEN clock_timestamp() >= v_deadline;
        PERFORM pg_sleep(0.01);
    END LOOP;
    RETURN false;
END;
$$;

-- ----------------------------------------------------------------------------
-- Rebuilds (derived caches)
-- ----------------------------------------------------------------------------
CREATE FUNCTION rewards.rebuild_balance(p_learner_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
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
SET search_path = pg_catalog, pg_temp
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
-- Decide ONE rewardable event (internal; the caller holds the learner lock)
-- ----------------------------------------------------------------------------
-- Returns {"outcome", "gold"}. p_op_id is the accepted operation that earned
-- it and must still have its receipt (the ledger trigger checks).
--
-- FINALITY (security review L1). 'capped_lesson' and 'capped_day' are recorded
-- per SOURCE KEY in rewards.forfeited_sources: the same question or lesson is
-- then never paid through a later operation ('forfeited'). Caps therefore bind
-- a modified client exactly as they bind an honest one.
-- NOT final: 'awaiting_evidence' (decided when the first scored answer of the
-- lesson is examined) and 'no_active_rule' (integration review L3: forgotten
-- and re-examined when rewards.set_active_rule_version switches a rule on).
CREATE FUNCTION rewards.try_award_event(
    p_learner_id uuid, p_event text, p_lesson_id uuid, p_question_key text, p_op_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_key text := CASE p_event
        WHEN 'question_first_correct' THEN 'q:' || p_lesson_id::text || ':' || p_question_key
        WHEN 'lesson_first_completed' THEN 'l:' || p_lesson_id::text END;
    v_receipt record;
    v_day date;
    v_rule record;
    v_refusal text;
    v_inserted uuid;
BEGIN
    IF v_key IS NULL THEN
        RAISE EXCEPTION 'Unknown rewardable event' USING ERRCODE = '22023';
    END IF;
    SELECT r.created_at INTO v_receipt FROM app.sync_receipts r
    WHERE r.learner_id = p_learner_id AND r.op_id = p_op_id AND r.result_code = 'accepted';
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'not_eligible', 'gold', 0);
    END IF;
    v_day := rewards.haiti_day(v_receipt.created_at);

    IF EXISTS (SELECT 1 FROM rewards.ledger l
               WHERE l.learner_id = p_learner_id AND l.source_key = v_key) THEN
        RETURN jsonb_build_object('outcome', 'duplicate', 'gold', 0);
    END IF;
    IF EXISTS (SELECT 1 FROM rewards.forfeited_sources f
               WHERE f.learner_id = p_learner_id AND f.source_key = v_key) THEN
        RETURN jsonb_build_object('outcome', 'forfeited', 'gold', 0);
    END IF;

    SELECT r.code, r.version, r.amount, r.per_lesson_cap, r.per_day_cap, r.requires_scored_answer
      INTO v_rule
    FROM rewards.rules r WHERE r.code = p_event AND r.event_kind = p_event AND r.is_active;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'no_active_rule', 'gold', 0);
    ELSIF v_rule.requires_scored_answer AND NOT EXISTS (
        SELECT 1 FROM app.practice_attempts a
        JOIN app.lesson_revisions lr ON lr.id = a.lesson_revision_id
        WHERE a.learner_id = p_learner_id AND lr.lesson_id = p_lesson_id
    ) THEN
        -- Not a refusal: the completion waits for the first scored answer.
        INSERT INTO rewards.pending_completions (learner_id, lesson_id, op_id)
        VALUES (p_learner_id, p_lesson_id, p_op_id)
        ON CONFLICT (learner_id, lesson_id) DO NOTHING;
        RETURN jsonb_build_object('outcome', 'awaiting_evidence', 'gold', 0);
    ELSIF v_rule.per_lesson_cap IS NOT NULL AND v_rule.amount + (
        SELECT COALESCE(sum(l.amount), 0) FROM rewards.ledger l
        WHERE l.learner_id = p_learner_id AND l.entry_kind = 'award'
          AND l.rule_code = v_rule.code AND l.lesson_id = p_lesson_id
    ) > v_rule.per_lesson_cap THEN
        v_refusal := 'capped_lesson';
    ELSIF v_rule.per_day_cap IS NOT NULL AND v_rule.amount + (
        SELECT COALESCE(sum(l.amount), 0) FROM rewards.ledger l
        WHERE l.learner_id = p_learner_id AND l.entry_kind = 'award'
          AND l.rule_code = v_rule.code AND l.accepted_day = v_day
    ) > v_rule.per_day_cap THEN
        v_refusal := 'capped_day';
    END IF;

    IF v_refusal IS NOT NULL THEN
        INSERT INTO rewards.forfeited_sources (learner_id, source_key, outcome, op_id, accepted_day)
        VALUES (p_learner_id, v_key, v_refusal, p_op_id, v_day)
        ON CONFLICT (learner_id, source_key) DO NOTHING;
        RETURN jsonb_build_object('outcome', v_refusal, 'gold', 0);
    END IF;

    INSERT INTO rewards.ledger (
        learner_id, entry_kind, amount, rule_code, rule_version, source_kind,
        source_op_id, lesson_id, question_key, accepted_at, accepted_day)
    VALUES (
        p_learner_id, 'award', v_rule.amount, v_rule.code, v_rule.version, p_event,
        p_op_id, p_lesson_id, p_question_key, v_receipt.created_at, v_day)
    ON CONFLICT ON CONSTRAINT ledger_exactly_once DO NOTHING
    RETURNING id INTO v_inserted;
    IF v_inserted IS NULL THEN
        RETURN jsonb_build_object('outcome', 'duplicate', 'gold', 0);
    END IF;
    RETURN jsonb_build_object('outcome', 'awarded', 'gold', v_rule.amount);
END;
$$;

-- ----------------------------------------------------------------------------
-- The core: examine ONE accepted operation of ONE learner, exactly once
-- ----------------------------------------------------------------------------
-- Internal (EXECUTE granted to nobody). Everything it uses is server-written:
-- the receipt, the scored attempt, the progress row. Nothing comes from the
-- device and nothing from the caller except WHICH operation to look at.
-- p_wait_ms NULL = wait for the learner lock (reconcile); a number = wait at
-- most that long and answer 'deferred' (nothing examined, nothing written).
CREATE FUNCTION rewards.apply_operation(p_learner_id uuid, p_op_id uuid,
                                        p_wait_ms integer DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_none CONSTANT jsonb := jsonb_build_object(
        'status', 'no_award', 'replayed', false, 'gold', 0, 'achievements', '[]'::jsonb);
    v_receipt record;
    v_done record;
    v_day date;
    v_lesson_id uuid;
    v_attempt record;
    v_scored_lesson uuid;
    v_pending record;
    v_result jsonb;
    v_outcome text := 'not_eligible';
    v_gold integer := 0;
    v_changed boolean := false;
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

    IF p_wait_ms IS NULL THEN
        PERFORM rewards.lock_learner(p_learner_id);
    ELSIF NOT rewards.try_lock_learner(p_learner_id, p_wait_ms) THEN
        RETURN jsonb_build_object('status', 'deferred', 'replayed', false, 'gold', 0,
                                  'achievements', '[]'::jsonb);
    END IF;

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
        v_changed := true;
        PERFORM rewards.rebuild_streak(p_learner_id);
    END IF;

    -- Which rewardable event, if any, does this operation stand for?
    IF v_receipt.op_kind = 'practice_answer' THEN
        SELECT a.score, lr.lesson_id, q.question_key INTO v_attempt
        FROM app.practice_attempts a
        JOIN app.question_revisions q ON q.id = a.question_revision_id
        JOIN app.lesson_revisions lr ON lr.id = a.lesson_revision_id
        WHERE a.learner_id = p_learner_id AND a.op_id = p_op_id;
        IF FOUND THEN
            v_scored_lesson := v_attempt.lesson_id;
            IF v_attempt.score = 1 THEN
                v_result := rewards.try_award_event(
                    p_learner_id, 'question_first_correct', v_attempt.lesson_id,
                    v_attempt.question_key, p_op_id);
            END IF;
        END IF;
    ELSIF v_receipt.op_kind = 'lesson_completed' THEN
        v_lesson_id := (v_receipt.result ->> 'lesson_id')::uuid;
        IF v_lesson_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM app.lesson_progress lp
            WHERE lp.learner_id = p_learner_id AND lp.lesson_id = v_lesson_id
              AND lp.completed_at IS NOT NULL
        ) THEN
            v_result := rewards.try_award_event(
                p_learner_id, 'lesson_first_completed', v_lesson_id, NULL, p_op_id);
        END IF;
    END IF;
    -- Any other operation kind (future: exams, notes, ...) earns nothing until
    -- a rule and a branch are added for it on purpose.

    IF v_result IS NOT NULL THEN
        v_outcome := v_result ->> 'outcome';
        v_gold := (v_result ->> 'gold')::integer;
        v_changed := v_changed OR v_outcome = 'awarded';
    END IF;

    -- A scored answer (right or wrong) is the evidence a waiting completion of
    -- the same lesson needs. The completion is decided now, under ITS OWN
    -- operation and acceptance day; its Gold is credited because of this one.
    IF v_scored_lesson IS NOT NULL THEN
        DELETE FROM rewards.pending_completions pc
        WHERE pc.learner_id = p_learner_id AND pc.lesson_id = v_scored_lesson
        RETURNING pc.op_id INTO v_pending;
        IF FOUND THEN
            v_result := rewards.try_award_event(
                p_learner_id, 'lesson_first_completed', v_scored_lesson, NULL, v_pending.op_id);
            IF v_result ->> 'outcome' = 'awarded' THEN
                v_gold := v_gold + (v_result ->> 'gold')::integer;
                v_changed := true;
            END IF;
        END IF;
    END IF;

    -- Achievements can only newly apply when something changed.
    IF v_changed THEN
        FOR v_definition IN
            SELECT d.code, d.criterion_kind, d.threshold, d.bonus_rule_code
            FROM rewards.achievement_definitions d
            WHERE d.is_active AND NOT EXISTS (
                SELECT 1 FROM rewards.achievement_awards a
                WHERE a.learner_id = p_learner_id AND a.achievement_code = d.code)
            ORDER BY d.sort_order, d.code
        LOOP
            IF v_definition.criterion_kind = 'streak_days' THEN
                SELECT COALESCE(max(s.longest_run_days), 0) INTO v_metric
                FROM rewards.streak_state s WHERE s.learner_id = p_learner_id;
            ELSE
                -- Counted on REWARDED events, so an achievement needs the same
                -- evidence as the Gold it celebrates.
                SELECT count(*)::integer INTO v_metric FROM (
                    SELECT 1 FROM rewards.ledger l
                    WHERE l.learner_id = p_learner_id
                      AND l.source_kind = CASE v_definition.criterion_kind
                            WHEN 'lessons_completed' THEN 'lesson_first_completed'
                            ELSE 'question_first_correct' END
                    LIMIT v_definition.threshold) t;
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
-- Switching a rule version (internal; an operator or a later staff function)
-- ----------------------------------------------------------------------------
-- ALWAYS switch through this function. Both updates happen inside this one
-- call, so no award is ever examined in a gap with NO live version. Awards running
-- concurrently see either the old version or the new one, never neither.
CREATE FUNCTION rewards.set_active_rule_version(p_code text, p_version integer)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM rewards.rules r WHERE r.code = p_code AND r.version = p_version) THEN
        RAISE EXCEPTION 'Unknown reward rule version' USING ERRCODE = '22023';
    END IF;
    -- Serialise switches of the same rule.
    PERFORM 1 FROM rewards.rules r WHERE r.code = p_code ORDER BY r.version FOR UPDATE;
    UPDATE rewards.rules r SET is_active = false
     WHERE r.code = p_code AND r.is_active AND r.version <> p_version;
    UPDATE rewards.rules r SET is_active = true
     WHERE r.code = p_code AND r.version = p_version AND NOT r.is_active;
    -- Operations examined while NO version was live were not paid. Forget those
    -- decisions so that reconciliation examines them again under this version.
    PERFORM set_config('rewards.reexamining', 'on', true);
    DELETE FROM rewards.processed_operations p WHERE p.outcome = 'no_active_rule';
    PERFORM set_config('rewards.reexamining', 'off', true);
END;
$$;

-- ----------------------------------------------------------------------------
-- Student API entry point (the push hook)
-- ----------------------------------------------------------------------------
-- The learner is ALWAYS app.current_actor_id(); there is no learner parameter
-- and no amount parameter.
--
-- The caller is inside the push transaction and HOLDS THE LEARNER'S SYNC LOCK,
-- so this must never queue behind another holder of the rewards lock
-- (reconcile, the worker, an erasure — or a hostile session squatting on the
-- advisory key). It waits at most 200 ms and then answers 'deferred': the
-- learning operation commits unrewarded and reconciliation examines it later.
CREATE FUNCTION rewards.award_for_operation(p_op_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    RETURN rewards.apply_operation(v_actor, p_op_id, 200);
END;
$$;

-- ----------------------------------------------------------------------------
-- Reconciliation: examine accepted operations that were never examined
-- ----------------------------------------------------------------------------
-- This is what makes the ledger self-healing: if the push hook was switched
-- off, failed, or timed out, the learning operation still committed and is
-- found here later, oldest first. Bounded per call.
CREATE FUNCTION rewards.reconcile_learner_internal(p_learner_id uuid, p_limit integer,
                                                   p_wait_ms integer DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
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

    IF p_wait_ms IS NULL THEN
        PERFORM rewards.lock_learner(p_learner_id);
    ELSIF NOT rewards.try_lock_learner(p_learner_id, p_wait_ms) THEN
        RETURN jsonb_build_object('examined', 0, 'gold', 0, 'more', true,
                                  'balance_corrected', false, 'skipped', true);
    END IF;

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
SET search_path = pg_catalog, pg_temp
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

-- For the worker (EXECUTE granted to edu_worker in the next migration):
-- reconcile learners that have unexamined operations.
--
-- A function cannot commit, so every learner lock taken here is held until the
-- CALLER commits. The contract for the worker is therefore: ONE CALL PER
-- TRANSACTION, small batches (default 1 learner, at most 20), commit, repeat
-- while "learners" > 0. A learner whose lock is busy is SKIPPED, never waited
-- for, and the push path waits at most 200 ms for a lock, so a slow batch can
-- delay a learner's Gold but not their sync. Learners are taken in id order.
CREATE FUNCTION rewards.reconcile_batch(p_max_learners integer DEFAULT 1,
                                        p_max_ops_per_learner integer DEFAULT 200)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_max integer := LEAST(GREATEST(COALESCE(p_max_learners, 1), 1), 20);
    v_learner record;
    v_result jsonb;
    v_learners integer := 0;
    v_skipped integer := 0;
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
            ORDER BY r.learner_id
            LIMIT v_max
        ) pending
        ORDER BY pending.learner_id
    LOOP
        v_result := rewards.reconcile_learner_internal(v_learner.learner_id, p_max_ops_per_learner, 0);
        IF COALESCE((v_result ->> 'skipped')::boolean, false) THEN
            v_skipped := v_skipped + 1;
            CONTINUE;
        END IF;
        v_learners := v_learners + 1;
        v_examined := v_examined + (v_result ->> 'examined')::integer;
        v_gold := v_gold + (v_result ->> 'gold')::integer;
    END LOOP;
    RETURN jsonb_build_object('learners', v_learners, 'examined', v_examined, 'gold', v_gold,
                              'skipped', v_skipped);
END;
$$;

-- ----------------------------------------------------------------------------
-- Internal reversal (EXECUTE granted to NOBODY)
-- ----------------------------------------------------------------------------
-- A correction never edits history: it appends the single reversal of one
-- award. The reversed source key stays taken, so the same thing cannot be
-- earned again afterwards. Staff reach it only through
-- rewards.staff_reverse_entry (next migration), which checks the role and
-- writes the audit event.
CREATE FUNCTION rewards.reverse_entry(p_ledger_id uuid, p_reason_code text,
                                      p_actor_id uuid DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
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
        reverses_ledger_id, accepted_at, accepted_day, reason_code, actor_id)
    VALUES (
        v_original.learner_id, 'reversal', -v_original.amount, v_original.rule_code,
        v_original.rule_version, 'reversal', p_ledger_id, v_now, rewards.haiti_day(v_now),
        p_reason_code, p_actor_id)
    RETURNING id INTO v_id;  -- a second reversal of the same row violates ledger_exactly_once
    RETURN v_id;
END;
$$;

-- ----------------------------------------------------------------------------
-- Erasure hook (plan §3; EXECUTE granted to NOBODY — the account orchestrator
-- calls it as owner)
-- ----------------------------------------------------------------------------
-- Removes every rewards row of one learner and KEEPS THE LEARNER'S REWARDS LOCK
-- UNTIL THE CALLER COMMITS (it is a transaction-scoped advisory lock), so no
-- award or reconcile for that learner can run in between.
--
-- CONTRACT for the account orchestrator, all in ONE transaction:
--   1. SELECT rewards.erase_learner(<id>);            -- takes the lock
--   2. remove the learner's app.sync_receipts (and the other learning rows);
--   3. delete app.learner_profiles (rewards foreign keys are RESTRICT);
--   4. COMMIT.
-- A reconcile that was waiting on the lock then finds no receipt and recreates
-- nothing. If receipts are left behind after the commit, reconciliation WILL
-- faithfully re-derive the rewards from them — that is what receipts are for.
CREATE FUNCTION rewards.erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_awards bigint;
    v_ledger bigint;
    v_processed bigint;
    v_forfeited bigint;
    v_pending bigint;
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
    WITH gone AS (DELETE FROM rewards.forfeited_sources WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_forfeited FROM gone;
    WITH gone AS (DELETE FROM rewards.pending_completions WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_pending FROM gone;
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
            'processed_operations', v_processed, 'forfeited_sources', v_forfeited,
            'pending_completions', v_pending, 'activity_days', v_days,
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
-- NOT granted here: apply_operation, try_award_event, set_active_rule_version,
-- reconcile_learner_internal, try_lock_learner,
-- rebuild_balance, rebuild_streak, reverse_entry, erase_learner, lock_learner
-- and the trigger functions (nobody); reconcile_batch (the worker, in the
-- next migration, which needs the roles of the staff lane's B1).
