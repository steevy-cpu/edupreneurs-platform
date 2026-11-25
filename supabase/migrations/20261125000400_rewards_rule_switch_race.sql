-- Mon Edupreneur 2.0 - rewards: close the rule-switch race (final verification QA5-R2)
--
-- A push whose rule check ran while the rule was off could commit its
-- 'no_active_rule' decision just AFTER rewards.set_active_rule_version had
-- switched the rule on and deleted the then-visible 'no_active_rule' rows; the
-- stale decision was never freed and never healed. try_award_event now takes a
-- SHARE lock on the rule's rows before reading them (set_active_rule_version
-- already takes them FOR UPDATE), so the two are strictly ordered.
-- Same signature, owner, search_path and grants (CREATE OR REPLACE keeps them).

CREATE OR REPLACE FUNCTION rewards.try_award_event(
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

    -- Rule-switch race (QA5-R2): rewards.set_active_rule_version locks every
    -- version of the rule FOR UPDATE, forgets 'no_active_rule' decisions and
    -- commits. Taking the matching SHARE lock here, BEFORE the rule is read and
    -- until this transaction ends, orders the two: either the switch is
    -- finished (and committed) before the rule is read, so the new version is
    -- seen; or the switch waits for this transaction and its DELETE then sees
    -- a 'no_active_rule' decision recorded by it. Never a stale final decision.
    PERFORM 1 FROM rewards.rules r WHERE r.code = p_event ORDER BY r.version FOR SHARE;

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
