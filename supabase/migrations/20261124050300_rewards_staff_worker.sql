-- Mon Edupreneur 2.0 — rewards: worker and staff entry points
--
-- Needs the shared platform interface of the staff lane (B1, migration
-- 20261124010000): roles edu_staff / edu_worker, staff.require_role,
-- ops.audit_write. Nothing is added to schemas app, ops or staff.
--
--   edu_worker  may run the bounded batch reconciliation. Nothing else.
--   edu_staff   may, as an ACTIVE ADMIN only, reverse one award or book one
--               small adjustment. Both append ledger rows (never edit one),
--               both write an audit event in the same transaction, and the
--               reason is a CODE from a fixed list, never free text.
--
-- BLOCKED_BY_OWNER (PO-09): whether staff may credit Gold at all, the bounds
-- (100 per adjustment, 300 credited per learner per Haiti day) and the list of
-- reason codes are synthetic placeholders. No HTTP route calls these yet.
--
-- Audit details carry only ids, numbers and enum codes (ruling R-03, item 3).

GRANT USAGE ON SCHEMA rewards TO edu_worker, edu_staff;

-- The reasons a staff correction may give. One list for both actions.
CREATE FUNCTION rewards.is_correction_reason(p_reason_code text)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT COALESCE(p_reason_code = ANY (ARRAY[
        'duplicate_award', 'content_error', 'scoring_error', 'abuse_confirmed',
        'support_goodwill', 'test_correction']), false)
$$;

CREATE FUNCTION rewards.staff_reverse_entry(p_ledger_id uuid, p_reason_code text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('admin');  -- raises 42501 otherwise
    v_id uuid;
    v_row record;
BEGIN
    IF p_ledger_id IS NULL OR NOT rewards.is_correction_reason(p_reason_code) THEN
        RAISE EXCEPTION 'A ledger id and a known reason code are required' USING ERRCODE = '22023';
    END IF;
    -- 22023 if it is not an existing award; 23505 if it was already reversed.
    v_id := rewards.reverse_entry(p_ledger_id, p_reason_code, v_actor);
    SELECT l.learner_id, l.amount INTO v_row FROM rewards.ledger l WHERE l.id = v_id;

    PERFORM ops.audit_write(
        'rewards_ledger.reverse', 'rewards_ledger', v_id, 'allowed',
        jsonb_build_object(
            'learner_id', v_row.learner_id::text,
            'reversed_ledger_id', p_ledger_id::text,
            'amount', v_row.amount,
            'reason_code', p_reason_code));

    RETURN jsonb_build_object(
        'ledger_id', v_id, 'amount', v_row.amount,
        'balance', (SELECT b.balance FROM rewards.balances b WHERE b.learner_id = v_row.learner_id));
END;
$$;

-- p_adjustment_id is chosen by the caller ONCE per intended adjustment and
-- reused on every retry: the same id with the same content is a replay (no
-- second row, no second audit event); with different content it is refused.
CREATE FUNCTION rewards.staff_adjust(p_learner_id uuid, p_amount integer,
                                     p_reason_code text, p_adjustment_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    c_max_per_adjustment CONSTANT integer := 100;
    c_max_credit_per_day CONSTANT integer := 300;
    v_actor uuid := staff.require_role('admin');  -- raises 42501 otherwise
    v_now timestamptz := now();
    v_day date := rewards.haiti_day(v_now);
    v_existing record;
    v_balance bigint;
    v_id uuid;
BEGIN
    IF p_learner_id IS NULL OR p_adjustment_id IS NULL OR p_amount IS NULL
       OR p_amount = 0 OR abs(p_amount) > c_max_per_adjustment
       OR NOT rewards.is_correction_reason(p_reason_code) THEN
        RAISE EXCEPTION 'Adjustment refused: amount out of bounds or unknown reason code'
            USING ERRCODE = '22023';
    END IF;
    IF v_actor = p_learner_id THEN
        RAISE EXCEPTION 'Staff cannot adjust their own Gold' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.learner_profiles p WHERE p.user_id = p_learner_id) THEN
        RAISE EXCEPTION 'Adjustment refused: no such learner' USING ERRCODE = '22023';
    END IF;

    PERFORM rewards.lock_learner(p_learner_id);

    SELECT l.id, l.learner_id, l.amount, l.reason_code INTO v_existing
    FROM rewards.ledger l WHERE l.adjustment_id = p_adjustment_id;
    IF FOUND THEN
        IF v_existing.learner_id = p_learner_id AND v_existing.amount = p_amount
           AND v_existing.reason_code = p_reason_code THEN
            RETURN jsonb_build_object(
                'ledger_id', v_existing.id, 'amount', v_existing.amount, 'replayed', true,
                'balance', (SELECT b.balance FROM rewards.balances b WHERE b.learner_id = p_learner_id));
        END IF;
        RAISE EXCEPTION 'Adjustment id was already used for a different adjustment'
            USING ERRCODE = '22023';
    END IF;

    SELECT COALESCE((SELECT b.balance FROM rewards.balances b WHERE b.learner_id = p_learner_id), 0)
      INTO v_balance;
    IF v_balance + p_amount < 0 THEN
        RAISE EXCEPTION 'Adjustment refused: the balance cannot go below zero' USING ERRCODE = '22023';
    END IF;
    IF p_amount > 0 AND p_amount + (
        SELECT COALESCE(sum(l.amount), 0) FROM rewards.ledger l
        WHERE l.learner_id = p_learner_id AND l.entry_kind = 'adjustment'
          AND l.amount > 0 AND l.accepted_day = v_day
    ) > c_max_credit_per_day THEN
        RAISE EXCEPTION 'Adjustment refused: daily credit limit for this learner reached'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO rewards.ledger (
        learner_id, entry_kind, amount, source_kind, adjustment_id, actor_id, reason_code,
        accepted_at, accepted_day)
    VALUES (p_learner_id, 'adjustment', p_amount, 'adjustment', p_adjustment_id, v_actor,
            p_reason_code, v_now, v_day)
    RETURNING id INTO v_id;

    PERFORM ops.audit_write(
        'rewards_ledger.adjust', 'rewards_ledger', v_id, 'allowed',
        jsonb_build_object(
            'learner_id', p_learner_id::text,
            'adjustment_id', p_adjustment_id::text,
            'amount', p_amount,
            'reason_code', p_reason_code));

    RETURN jsonb_build_object('ledger_id', v_id, 'amount', p_amount, 'replayed', false,
                              'balance', v_balance + p_amount);
END;
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA rewards FROM PUBLIC, anon, authenticated;
-- REVOKE ... ON ALL FUNCTIONS above does not touch grants to named roles made
-- by the previous migration (edu_api keeps its three functions).
GRANT EXECUTE ON FUNCTION rewards.reconcile_batch(integer, integer) TO edu_worker;
GRANT EXECUTE ON FUNCTION rewards.staff_reverse_entry(uuid, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION rewards.staff_adjust(uuid, integer, text, uuid) TO edu_staff;
-- edu_worker and edu_staff get NO table privilege in rewards, and edu_api
-- gets nothing new.
