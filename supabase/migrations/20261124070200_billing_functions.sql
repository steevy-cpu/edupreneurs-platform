-- Mon Edupreneur 2.0 — `billing` functions, guards, policies and grants
--
-- WHO CAN DO WHAT after this migration
--   edu_api (the student API)   USAGE on the schema; SELECT on a few columns of
--                               its OWN grants and their revocations (RLS);
--                               EXECUTE on billing.is_entitled(). Nothing else.
--   everyone else               nothing. Every function that can create, extend
--                               or revoke a grant, create an order or apply a
--                               provider event has EXECUTE granted to NOBODY.
--
-- "No client request can create or extend a grant" (Platform-06 gate) is
-- therefore a privilege fact, not an API convention: the role the student API
-- logs in with cannot write any billing table and cannot call any billing
-- function that writes.
--
-- All functions follow the overnight plan §3 pattern: owned by postgres,
-- SECURITY DEFINER where they must see or write rows, SET search_path = '',
-- schema-qualified SQL, bounded inputs, no dynamic SQL, and the acting person is
-- always app.current_actor_id() — never a parameter.

-- ============================================================================
-- >>> STAFF SEAM — the ONLY two places that know how staff are recognised and
-- >>> how an audit record is written. The staff lane's shared interface
-- >>> (staff.require_role / ops.audit_write) does not exist in this database
-- >>> yet. When it is merged, a follow-up migration in this lane's block
-- >>> replaces the two BODIES below with
-- >>>     RETURN staff.require_role(VARIADIC p_roles);
-- >>>     PERFORM ops.audit_write(p_action, p_target_kind, p_target_id, p_outcome, p_details);
-- >>> and grants EXECUTE on the billing.staff_* functions to edu_staff.
-- >>> Nothing else in this file changes.
-- ============================================================================

-- Seam 1 of 2: returns the verified actor if they hold one of the roles, else
-- raises 42501. Same contract as staff.require_role(VARIADIC text[]).
CREATE FUNCTION billing._require_staff(VARIADIC p_roles text[])
RETURNS uuid
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    IF p_roles IS NULL OR cardinality(p_roles) = 0 OR NOT EXISTS (
        SELECT 1 FROM app.staff_roles s
        WHERE s.user_id = v_actor AND s.is_active AND s.role = ANY (p_roles)
    ) THEN
        RAISE EXCEPTION 'Staff role required' USING ERRCODE = '42501';
    END IF;
    RETURN v_actor;
END;
$$;

-- Seam 2 of 2: one audit record. Same parameters as ops.audit_write(). Until
-- that exists, this writes app.audit_events directly as the function owner
-- (the existing append-only trigger on that table still applies).
CREATE FUNCTION billing._audit(
    p_action text,
    p_target_kind text,
    p_target_id uuid,
    p_outcome text,
    p_details jsonb DEFAULT '{}'::jsonb
)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_kind text;
BEGIN
    v_kind := CASE
        WHEN v_actor IS NULL THEN 'system'
        WHEN EXISTS (SELECT 1 FROM app.staff_roles s WHERE s.user_id = v_actor AND s.is_active) THEN 'staff'
        ELSE 'user'
    END;
    INSERT INTO app.audit_events (actor_id, actor_kind, action, target_kind, target_id, outcome, details)
    VALUES (v_actor, v_kind, p_action, p_target_kind, p_target_id, p_outcome,
            COALESCE(p_details, '{}'::jsonb));
END;
$$;
-- <<< END OF STAFF SEAM

-- ============================================================================
-- Guards (triggers): history cannot be rewritten, even by the owner by mistake
-- ============================================================================
-- The ONLY sanctioned exception is billing.erase_learner(), which sets the
-- transaction-local marker `billing.erasing`. The marker gives nothing to a
-- role without write privileges (and no role but the owner has any).
CREATE FUNCTION billing.guard_grant_history()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('billing.erasing', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Entitlement history is append-only: grants and revocations are never edited or deleted';
END;
$$;
CREATE TRIGGER no_edit_entitlements BEFORE UPDATE OR DELETE ON billing.entitlements
    FOR EACH ROW EXECUTE FUNCTION billing.guard_grant_history();
CREATE TRIGGER no_edit_revocations BEFORE UPDATE OR DELETE ON billing.entitlement_revocations
    FOR EACH ROW EXECUTE FUNCTION billing.guard_grant_history();

-- A provider event is written once. Erasure may blank its raw payload (which
-- can carry personal data such as a payer's phone number) and nothing else.
CREATE FUNCTION billing.guard_provider_event()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND current_setting('billing.erasing', true) = 'on'
       AND NEW.payload = '{}'::jsonb AND NEW.payload_erased_at IS NOT NULL
       AND (to_jsonb(NEW) - 'payload' - 'payload_erased_at')
           = (to_jsonb(OLD) - 'payload' - 'payload_erased_at') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Provider events are append-only';
END;
$$;
CREATE TRIGGER no_edit_provider_events BEFORE UPDATE OR DELETE ON billing.provider_events
    FOR EACH ROW EXECUTE FUNCTION billing.guard_provider_event();

CREATE FUNCTION billing.guard_refund()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'Refund records are append-only';
END;
$$;
CREATE TRIGGER no_edit_refunds BEFORE UPDATE OR DELETE ON billing.refunds
    FOR EACH ROW EXECUTE FUNCTION billing.guard_refund();

-- An order's money facts never change; its state only moves forward; the
-- learner link can only be removed, and only by erasure.
CREATE FUNCTION billing.guard_order()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Orders are never deleted';
    END IF;
    IF NEW.id <> OLD.id OR NEW.plan_id <> OLD.plan_id OR NEW.provider <> OLD.provider
       OR NEW.currency <> OLD.currency OR NEW.amount_expected_minor <> OLD.amount_expected_minor
       OR NEW.idempotency_key <> OLD.idempotency_key OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'The plan, provider, amount and currency of an order cannot change';
    END IF;
    IF NEW.learner_id IS DISTINCT FROM OLD.learner_id
       AND NOT (NEW.learner_id IS NULL AND current_setting('billing.erasing', true) = 'on') THEN
        RAISE EXCEPTION 'The learner of an order cannot change';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
           (OLD.status = 'pending' AND NEW.status IN ('paid', 'failed', 'refunded'))
        OR (OLD.status = 'failed' AND NEW.status IN ('paid', 'refunded'))
        OR (OLD.status = 'paid' AND NEW.status = 'refunded')) THEN
        RAISE EXCEPTION 'Order status cannot move from % to %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_order BEFORE UPDATE OR DELETE ON billing.orders
    FOR EACH ROW EXECUTE FUNCTION billing.guard_order();

-- ============================================================================
-- Reading: "is this learner entitled to scope X at time T?"
-- ============================================================================
-- Scope matching:
--   a grant for 'all'      covers every request;
--   a grant for a grade    covers that grade and every course of that grade;
--   a grant for a course   covers that course only.
-- A request for 'all' is satisfied only by an 'all' grant.
-- Internal (EXECUTE: nobody). The time is a parameter so that the boundary
-- (starts_at <= t < ends_at) can be tested exactly.
CREATE FUNCTION billing.learner_is_entitled_at(
    p_learner_id uuid,
    p_scope_kind text,
    p_scope_id uuid,
    p_at timestamptz
)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT p_learner_id IS NOT NULL AND p_at IS NOT NULL AND COALESCE(
        (p_scope_kind = 'all' AND p_scope_id IS NULL)
        OR (p_scope_kind IN ('grade', 'course') AND p_scope_id IS NOT NULL), false)
    AND EXISTS (
        SELECT 1
        FROM billing.entitlements e
        WHERE e.learner_id = p_learner_id
          AND e.starts_at <= p_at AND p_at < e.ends_at
          AND NOT EXISTS (
              SELECT 1 FROM billing.entitlement_revocations r
              WHERE r.entitlement_id = e.id AND r.revoked_at <= p_at)
          AND (
              e.scope_kind = 'all'
              OR (p_scope_kind = 'grade' AND e.scope_kind = 'grade' AND e.scope_grade_id = p_scope_id)
              OR (p_scope_kind = 'course' AND e.scope_kind = 'course' AND e.scope_course_id = p_scope_id)
              OR (p_scope_kind = 'course' AND e.scope_kind = 'grade' AND e.scope_grade_id = (
                      SELECT c.grade_id FROM app.courses c WHERE c.id = p_scope_id))
          )
    )
$$;

-- The caller's own answer, now, by the server clock. There is no learner
-- parameter: a caller can only ever ask about themselves. Read-only.
-- NOTE: nothing calls this to lock content. No paywall exists (PO-01).
CREATE FUNCTION billing.is_entitled(p_scope_kind text DEFAULT 'all', p_scope_id uuid DEFAULT NULL)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT billing.learner_is_entitled_at(app.current_actor_id(), p_scope_kind, p_scope_id, now())
$$;

-- ============================================================================
-- Core writers (internal; EXECUTE: nobody)
-- ============================================================================
-- Creates ONE grant, exactly once per idempotency key.
--   same key + same request      -> the ORIGINAL grant, replayed = true, no new row
--   same key + different request -> status 'conflict', nothing written
-- "Same request" = same learner, scope, source, order and duration.
CREATE FUNCTION billing.grant_entitlement(
    p_learner_id uuid,
    p_scope_kind text,
    p_scope_id uuid,
    p_starts_at timestamptz,
    p_ends_at timestamptz,
    p_source text,
    p_source_ref text,
    p_idempotency_key text,
    p_granted_by uuid,
    p_plan_id uuid DEFAULT NULL,
    p_order_id uuid DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_grade uuid;
    v_course uuid;
    v_id uuid;
    v_existing record;
BEGIN
    IF p_learner_id IS NULL OR p_scope_kind IS NULL OR p_starts_at IS NULL OR p_ends_at IS NULL
       OR p_source IS NULL OR p_idempotency_key IS NULL
       OR char_length(p_idempotency_key) NOT BETWEEN 8 AND 200
       OR (p_source_ref IS NOT NULL AND char_length(p_source_ref) NOT BETWEEN 1 AND 200) THEN
        RAISE EXCEPTION 'Malformed entitlement grant arguments' USING ERRCODE = '22023';
    END IF;
    IF p_source NOT IN ('purchase', 'gift', 'promo', 'school_licence', 'trial', 'staff_grant', 'migration') THEN
        RAISE EXCEPTION 'Unknown entitlement source' USING ERRCODE = '22023';
    END IF;
    IF (p_source = 'purchase') <> (p_order_id IS NOT NULL) THEN
        RAISE EXCEPTION 'A purchase grant needs an order, and only a purchase has one' USING ERRCODE = '22023';
    END IF;
    IF p_scope_kind NOT IN ('all', 'grade', 'course') OR (p_scope_kind = 'all') <> (p_scope_id IS NULL) THEN
        RAISE EXCEPTION 'Malformed entitlement scope' USING ERRCODE = '22023';
    END IF;
    IF p_ends_at <= p_starts_at OR p_ends_at - p_starts_at > make_interval(hours => 3660 * 24)
       OR p_starts_at < now() - interval '24 hours' OR p_starts_at > now() + make_interval(hours => 366 * 24) THEN
        RAISE EXCEPTION 'Entitlement period out of bounds' USING ERRCODE = '22023';
    END IF;
    IF p_scope_kind = 'grade' THEN
        v_grade := p_scope_id;
        IF NOT EXISTS (SELECT 1 FROM app.grades g WHERE g.id = v_grade) THEN
            RAISE EXCEPTION 'Unknown grade' USING ERRCODE = '22023';
        END IF;
    ELSIF p_scope_kind = 'course' THEN
        v_course := p_scope_id;
        IF NOT EXISTS (SELECT 1 FROM app.courses c WHERE c.id = v_course) THEN
            RAISE EXCEPTION 'Unknown course' USING ERRCODE = '22023';
        END IF;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id = p_learner_id) THEN
        RAISE EXCEPTION 'Unknown learner' USING ERRCODE = '22023';
    END IF;

    INSERT INTO billing.entitlements (
        learner_id, scope_kind, scope_grade_id, scope_course_id, starts_at, ends_at,
        source, source_ref, plan_id, order_id, idempotency_key, granted_by)
    VALUES (
        p_learner_id, p_scope_kind, v_grade, v_course, p_starts_at, p_ends_at,
        p_source, p_source_ref, p_plan_id, p_order_id, p_idempotency_key, p_granted_by)
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id INTO v_id;

    IF v_id IS NOT NULL THEN
        RETURN jsonb_build_object(
            'status', 'granted', 'replayed', false, 'entitlement_id', v_id,
            'starts_at', p_starts_at, 'ends_at', p_ends_at);
    END IF;

    SELECT e.* INTO v_existing FROM billing.entitlements e WHERE e.idempotency_key = p_idempotency_key;
    IF v_existing.learner_id = p_learner_id
       AND v_existing.scope_kind = p_scope_kind
       AND v_existing.scope_grade_id IS NOT DISTINCT FROM v_grade
       AND v_existing.scope_course_id IS NOT DISTINCT FROM v_course
       AND v_existing.source = p_source
       AND v_existing.order_id IS NOT DISTINCT FROM p_order_id
       AND extract(epoch FROM (v_existing.ends_at - v_existing.starts_at))
           = extract(epoch FROM (p_ends_at - p_starts_at)) THEN
        RETURN jsonb_build_object(
            'status', 'granted', 'replayed', true, 'entitlement_id', v_existing.id,
            'starts_at', v_existing.starts_at, 'ends_at', v_existing.ends_at);
    END IF;
    RETURN jsonb_build_object(
        'status', 'conflict', 'replayed', false,
        'code', 'idempotency_key_reused_with_different_grant');
END;
$$;

-- Records ONE revocation for a grant. Revoking an already revoked grant changes
-- nothing and reports the original revocation. The grant row is never touched.
CREATE FUNCTION billing.revoke_entitlement(
    p_entitlement_id uuid,
    p_reason_code text,
    p_revoked_by uuid,
    p_source_ref text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_id uuid;
    v_existing record;
BEGIN
    IF p_entitlement_id IS NULL OR p_reason_code IS NULL
       OR p_reason_code NOT IN ('staff_revoke', 'refund')
       OR (p_source_ref IS NOT NULL AND char_length(p_source_ref) NOT BETWEEN 1 AND 200) THEN
        RAISE EXCEPTION 'Malformed entitlement revocation arguments' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM billing.entitlements e WHERE e.id = p_entitlement_id) THEN
        RAISE EXCEPTION 'Unknown entitlement' USING ERRCODE = 'P0002';
    END IF;

    INSERT INTO billing.entitlement_revocations (entitlement_id, reason_code, source_ref, revoked_by)
    VALUES (p_entitlement_id, p_reason_code, p_source_ref, p_revoked_by)
    ON CONFLICT (entitlement_id) DO NOTHING
    RETURNING id INTO v_id;

    IF v_id IS NOT NULL THEN
        RETURN jsonb_build_object(
            'status', 'revoked', 'replayed', false, 'entitlement_id', p_entitlement_id,
            'revocation_id', v_id, 'revoked_at', now());
    END IF;
    SELECT r.id, r.revoked_at INTO v_existing
    FROM billing.entitlement_revocations r WHERE r.entitlement_id = p_entitlement_id;
    RETURN jsonb_build_object(
        'status', 'revoked', 'replayed', true, 'entitlement_id', p_entitlement_id,
        'revocation_id', v_existing.id, 'revoked_at', v_existing.revoked_at);
END;
$$;

-- ============================================================================
-- Staff actions (role `admin`, audited). EXECUTE: NOBODY until the staff
-- boundary is merged — see the STAFF SEAM above.
-- ============================================================================
-- A staff grant lasts p_duration_days x 24 hours from p_starts_at (default: now,
-- server clock). 'purchase' is not a staff source: a purchase grant can only
-- come from a verified provider event. An admin cannot grant to themselves.
CREATE FUNCTION billing.staff_grant_entitlement(
    p_learner_id uuid,
    p_scope_kind text,
    p_scope_id uuid,
    p_duration_days integer,
    p_source text,
    p_reason text,
    p_idempotency_key text,
    p_starts_at timestamptz DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := billing._require_staff('admin');
    v_starts timestamptz := COALESCE(p_starts_at, now());
    v_outcome jsonb;
BEGIN
    IF p_learner_id IS NULL OR p_duration_days IS NULL OR p_duration_days NOT BETWEEN 1 AND 366
       OR p_reason IS NULL OR char_length(btrim(p_reason)) NOT BETWEEN 3 AND 500 THEN
        RAISE EXCEPTION 'Malformed staff grant arguments' USING ERRCODE = '22023';
    END IF;
    IF p_source IS NULL OR p_source NOT IN ('gift', 'promo', 'school_licence', 'trial', 'staff_grant', 'migration') THEN
        RAISE EXCEPTION 'Staff cannot grant with this source' USING ERRCODE = '22023';
    END IF;
    IF p_learner_id = v_actor THEN
        RAISE EXCEPTION 'Staff cannot grant an entitlement to themselves' USING ERRCODE = '42501';
    END IF;

    v_outcome := billing.grant_entitlement(
        p_learner_id, p_scope_kind, p_scope_id,
        v_starts, v_starts + make_interval(hours => p_duration_days * 24),
        p_source, NULL, p_idempotency_key, v_actor);

    PERFORM billing._audit(
        'billing.entitlement.grant', 'billing_entitlement',
        (v_outcome ->> 'entitlement_id')::uuid,
        CASE WHEN v_outcome ->> 'status' = 'granted' THEN 'allowed' ELSE 'denied' END,
        jsonb_build_object(
            'status', v_outcome ->> 'status',
            'replayed', (v_outcome ->> 'replayed')::boolean,
            'learner_id', p_learner_id,
            'scope_kind', p_scope_kind,
            'scope_id', p_scope_id,
            'duration_days', p_duration_days,
            'source', p_source,
            'reason', btrim(p_reason)));
    RETURN v_outcome;
END;
$$;

CREATE FUNCTION billing.staff_revoke_entitlement(p_entitlement_id uuid, p_reason text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := billing._require_staff('admin');
    v_outcome jsonb;
BEGIN
    IF p_entitlement_id IS NULL OR p_reason IS NULL
       OR char_length(btrim(p_reason)) NOT BETWEEN 3 AND 500 THEN
        RAISE EXCEPTION 'Malformed staff revocation arguments' USING ERRCODE = '22023';
    END IF;
    v_outcome := billing.revoke_entitlement(p_entitlement_id, 'staff_revoke', v_actor);
    PERFORM billing._audit(
        'billing.entitlement.revoke', 'billing_entitlement', p_entitlement_id, 'allowed',
        jsonb_build_object(
            'replayed', (v_outcome ->> 'replayed')::boolean,
            'reason', btrim(p_reason)));
    RETURN v_outcome;
END;
$$;

-- Every grant of one learner, with its state now, for a support screen.
CREATE FUNCTION billing.staff_list_entitlements(p_learner_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := billing._require_staff('admin');
    v_rows jsonb;
BEGIN
    IF p_learner_id IS NULL THEN
        RAISE EXCEPTION 'Malformed staff list arguments' USING ERRCODE = '22023';
    END IF;
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'id', e.id,
               'scope_kind', e.scope_kind,
               'scope_id', COALESCE(e.scope_grade_id, e.scope_course_id),
               'starts_at', e.starts_at,
               'ends_at', e.ends_at,
               'source', e.source,
               'order_id', e.order_id,
               'granted_by', e.granted_by,
               'created_at', e.created_at,
               'revoked_at', r.revoked_at,
               'revocation_reason', r.reason_code,
               'state', CASE
                   WHEN r.id IS NOT NULL THEN 'revoked'
                   WHEN now() < e.starts_at THEN 'scheduled'
                   WHEN now() >= e.ends_at THEN 'expired'
                   ELSE 'active' END)
               ORDER BY e.created_at, e.id), '[]'::jsonb)
      INTO v_rows
    FROM billing.entitlements e
    LEFT JOIN billing.entitlement_revocations r ON r.entitlement_id = e.id
    WHERE e.learner_id = p_learner_id;

    PERFORM billing._audit(
        'billing.entitlement.list', 'learner', p_learner_id, 'allowed',
        jsonb_build_object('count', jsonb_array_length(v_rows)));
    RETURN v_rows;
END;
$$;

-- ============================================================================
-- Orders and provider events (EXECUTE: NOBODY — checkout is BLOCKED_BY_OWNER
-- PO-06; only the simulated provider's tests reach these, as the local owner)
-- ============================================================================
-- An order for the CALLER (app.current_actor_id()). The amount is copied from
-- billing.plan_prices here, on the server; the client never states a price.
CREATE FUNCTION billing.create_order(
    p_plan_code text,
    p_currency text,
    p_provider text,
    p_idempotency_key text
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_plan record;
    v_provider record;
    v_amount bigint;
    v_id uuid;
    v_existing record;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    IF p_plan_code IS NULL OR p_currency IS NULL OR p_provider IS NULL OR p_idempotency_key IS NULL
       OR p_currency !~ '^[A-Z]{3}$' OR char_length(p_plan_code) > 60 OR char_length(p_provider) > 31
       OR char_length(p_idempotency_key) NOT BETWEEN 8 AND 200 THEN
        RAISE EXCEPTION 'Malformed order arguments' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id = v_actor) THEN
        RAISE EXCEPTION 'Unknown learner' USING ERRCODE = '42501';
    END IF;
    SELECT pr.code, pr.is_simulated INTO v_provider
    FROM billing.providers pr WHERE pr.code = p_provider AND pr.is_enabled;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Payment provider is not enabled' USING ERRCODE = '42501';
    END IF;
    SELECT p.id, p.code, p.is_synthetic INTO v_plan
    FROM billing.plans p WHERE p.code = p_plan_code AND p.is_active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown plan' USING ERRCODE = '22023';
    END IF;
    -- Synthetic prices can never be charged by a real provider, and a
    -- simulated provider can never "pay" for a real plan.
    IF v_plan.is_synthetic <> v_provider.is_simulated THEN
        RAISE EXCEPTION 'Synthetic plans and simulated providers only go together' USING ERRCODE = '42501';
    END IF;
    SELECT pp.amount_minor INTO v_amount
    FROM billing.plan_prices pp WHERE pp.plan_id = v_plan.id AND pp.currency = p_currency;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Plan has no price in this currency' USING ERRCODE = '22023';
    END IF;

    INSERT INTO billing.orders (learner_id, plan_id, provider, currency, amount_expected_minor, idempotency_key)
    VALUES (v_actor, v_plan.id, p_provider, p_currency, v_amount, p_idempotency_key)
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id INTO v_id;

    IF v_id IS NOT NULL THEN
        RETURN jsonb_build_object(
            'status', 'created', 'replayed', false, 'order_id', v_id, 'plan_code', v_plan.code,
            'amount_expected_minor', v_amount, 'currency', p_currency);
    END IF;
    SELECT o.id, o.learner_id, o.plan_id, o.provider, o.currency, o.amount_expected_minor
      INTO v_existing
    FROM billing.orders o WHERE o.idempotency_key = p_idempotency_key;
    IF v_existing.learner_id IS NOT DISTINCT FROM v_actor AND v_existing.plan_id = v_plan.id
       AND v_existing.provider = p_provider AND v_existing.currency = p_currency THEN
        RETURN jsonb_build_object(
            'status', 'created', 'replayed', true, 'order_id', v_existing.id, 'plan_code', v_plan.code,
            'amount_expected_minor', v_existing.amount_expected_minor, 'currency', v_existing.currency);
    END IF;
    RETURN jsonb_build_object(
        'status', 'conflict', 'replayed', false,
        'code', 'idempotency_key_reused_with_different_order');
END;
$$;

-- Applies ONE provider message, exactly once.
--
-- TRUST: the caller attests that the message is authentic (its signature was
-- verified before this call). That is why EXECUTE is granted to nobody: the
-- student API role must never be able to reach this function.
--
-- Exactly-once: a per-event advisory lock serialises concurrent deliveries of
-- the same message; UNIQUE (provider, provider_event_id) is the backstop.
--   same id + same content      -> stored outcome, replayed = true, nothing changes
--   same id + different content -> 'conflict', nothing changes
-- Server-side verification: the order must exist for THIS provider, and the
-- amount, currency and (for a payment) plan in the message must equal what the
-- server recorded on the order. A mismatch is stored as 'rejected'.
-- Out-of-order safety: the order's state only moves forward (see guard_order):
--   refund before payment   -> order 'refunded'; a late payment message is ignored
--   stale failure after pay -> ignored
-- Every authentic message is stored raw with its outcome, including rejected
-- and ignored ones, so finance can reconcile.
CREATE FUNCTION billing.apply_provider_event(
    p_provider text,
    p_provider_event_id text,
    p_event_type text,
    p_payload jsonb
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_digest bytea;
    v_existing record;
    v_order record;
    v_plan record;
    v_order_id uuid;
    v_amount bigint;
    v_currency text;
    v_outcome text;
    v_code text;
    v_result jsonb := '{}'::jsonb;
    v_grant jsonb;
    v_entitlement_id uuid;
    v_event_id uuid;
    v_refunded boolean := false;
    v_now timestamptz := now();
BEGIN
    IF p_provider IS NULL OR p_provider_event_id IS NULL OR p_event_type IS NULL
       OR p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object'
       OR char_length(p_provider_event_id) NOT BETWEEN 1 AND 200
       OR char_length(p_event_type) NOT BETWEEN 1 AND 80
       OR octet_length(p_payload::text) > 16384 THEN
        RAISE EXCEPTION 'Malformed provider event arguments' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM billing.providers pr WHERE pr.code = p_provider AND pr.is_enabled) THEN
        RAISE EXCEPTION 'Payment provider is not enabled' USING ERRCODE = '42501';
    END IF;

    v_digest := sha256(convert_to(p_payload::text, 'UTF8'));
    PERFORM pg_advisory_xact_lock(
        hashtextextended('billing.provider_event:' || p_provider || ':' || p_provider_event_id, 0));

    SELECT ev.event_type, ev.payload_sha256, ev.outcome, ev.outcome_code, ev.result INTO v_existing
    FROM billing.provider_events ev
    WHERE ev.provider = p_provider AND ev.provider_event_id = p_provider_event_id;
    IF FOUND THEN
        IF v_existing.payload_sha256 = v_digest AND v_existing.event_type = p_event_type THEN
            RETURN jsonb_build_object(
                'status', v_existing.outcome, 'code', v_existing.outcome_code,
                'replayed', true, 'result', v_existing.result);
        END IF;
        RETURN jsonb_build_object(
            'status', 'conflict', 'code', 'event_id_reused_with_different_payload',
            'replayed', false, 'result', '{}'::jsonb);
    END IF;

    IF p_event_type NOT IN ('payment.succeeded', 'payment.failed', 'payment.refunded') THEN
        v_outcome := 'ignored';
        v_code := 'unsupported_event_type';
    ELSIF COALESCE(p_payload ->> 'order_id', '')
              !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
       OR jsonb_typeof(p_payload -> 'amount_minor') IS DISTINCT FROM 'number'
       OR COALESCE(p_payload ->> 'amount_minor', '') !~ '^[0-9]{1,15}$'
       OR COALESCE(p_payload ->> 'currency', '') !~ '^[A-Z]{3}$'
       OR (p_event_type = 'payment.succeeded'
           AND jsonb_typeof(p_payload -> 'plan_code') IS DISTINCT FROM 'string') THEN
        v_outcome := 'rejected';
        v_code := 'malformed_payload';
    ELSE
        v_order_id := (p_payload ->> 'order_id')::uuid;
        v_amount := (p_payload ->> 'amount_minor')::bigint;
        v_currency := p_payload ->> 'currency';

        SELECT o.id, o.learner_id, o.plan_id, o.currency, o.amount_expected_minor, o.status INTO v_order
        FROM billing.orders o
        WHERE o.id = v_order_id AND o.provider = p_provider
        FOR UPDATE;

        IF NOT FOUND THEN
            v_order_id := NULL;
            v_outcome := 'rejected';
            v_code := 'unknown_order';
        ELSE
            SELECT p.id, p.code, p.scope_kind, p.scope_grade_id, p.scope_course_id, p.duration_days
              INTO v_plan
            FROM billing.plans p WHERE p.id = v_order.plan_id;

            IF v_currency <> v_order.currency THEN
                v_outcome := 'rejected';
                v_code := 'currency_mismatch';
            ELSIF v_amount <> v_order.amount_expected_minor THEN
                v_outcome := 'rejected';
                v_code := 'amount_mismatch';
            ELSIF p_event_type = 'payment.succeeded' AND (p_payload ->> 'plan_code') <> v_plan.code THEN
                v_outcome := 'rejected';
                v_code := 'plan_mismatch';
            ELSIF v_order.status = 'refunded' THEN
                v_outcome := 'ignored';
                v_code := 'order_already_refunded';
            ELSIF p_event_type = 'payment.succeeded' THEN
                IF v_order.status = 'paid' THEN
                    v_outcome := 'ignored';
                    v_code := 'order_already_paid';
                ELSIF v_order.learner_id IS NULL THEN
                    v_outcome := 'ignored';
                    v_code := 'order_erased';
                ELSE
                    UPDATE billing.orders SET status = 'paid', updated_at = v_now WHERE id = v_order.id;
                    v_grant := billing.grant_entitlement(
                        v_order.learner_id, v_plan.scope_kind,
                        COALESCE(v_plan.scope_grade_id, v_plan.scope_course_id),
                        v_now, v_now + make_interval(hours => v_plan.duration_days * 24),
                        'purchase', left(p_provider || ':' || p_provider_event_id, 200),
                        'order:' || v_order.id::text, NULL, v_plan.id, v_order.id);
                    IF v_grant ->> 'status' <> 'granted' THEN
                        RAISE EXCEPTION 'Order % could not be granted', v_order.id USING ERRCODE = 'XX000';
                    END IF;
                    v_entitlement_id := (v_grant ->> 'entitlement_id')::uuid;
                    v_outcome := 'applied';
                    v_code := 'entitlement_granted';
                    v_result := jsonb_build_object(
                        'order_id', v_order.id, 'entitlement_id', v_entitlement_id,
                        'starts_at', v_grant -> 'starts_at', 'ends_at', v_grant -> 'ends_at');
                END IF;
            ELSIF p_event_type = 'payment.failed' THEN
                IF v_order.status = 'paid' THEN
                    v_outcome := 'ignored';
                    v_code := 'order_already_paid';
                ELSIF v_order.status = 'failed' THEN
                    v_outcome := 'ignored';
                    v_code := 'order_already_failed';
                ELSE
                    UPDATE billing.orders SET status = 'failed', updated_at = v_now WHERE id = v_order.id;
                    v_outcome := 'applied';
                    v_code := 'order_failed';
                    v_result := jsonb_build_object('order_id', v_order.id);
                END IF;
            ELSE -- payment.refunded, on a pending, failed or paid order
                UPDATE billing.orders SET status = 'refunded', updated_at = v_now WHERE id = v_order.id;
                SELECT e.id INTO v_entitlement_id FROM billing.entitlements e WHERE e.order_id = v_order.id;
                IF v_entitlement_id IS NOT NULL THEN
                    PERFORM billing.revoke_entitlement(
                        v_entitlement_id, 'refund', NULL,
                        left(p_provider || ':' || p_provider_event_id, 200));
                END IF;
                v_refunded := true;
                v_outcome := 'applied';
                v_code := 'order_refunded';
                v_result := jsonb_build_object(
                    'order_id', v_order.id, 'revoked_entitlement_id', v_entitlement_id);
            END IF;
        END IF;
    END IF;

    INSERT INTO billing.provider_events (
        provider, provider_event_id, event_type, payload, payload_sha256,
        order_id, outcome, outcome_code, result)
    VALUES (
        p_provider, p_provider_event_id, p_event_type, p_payload, v_digest,
        v_order_id, v_outcome, v_code, v_result)
    RETURNING id INTO v_event_id;

    IF v_refunded THEN
        INSERT INTO billing.refunds (order_id, provider_event_id, amount_minor, currency)
        VALUES (v_order.id, v_event_id, v_amount, v_currency);
    END IF;

    -- Access changes go to the audit trail (through the seam).
    IF v_code IN ('entitlement_granted', 'order_refunded') THEN
        PERFORM billing._audit(
            'billing.provider_event.' || v_code, 'billing_order', v_order.id, 'allowed',
            jsonb_build_object(
                'provider', p_provider, 'provider_event_row', v_event_id,
                'entitlement_id', v_entitlement_id));
    END IF;

    RETURN jsonb_build_object('status', v_outcome, 'code', v_code, 'replayed', false, 'result', v_result);
END;
$$;

-- ============================================================================
-- Erasure hook (overnight plan §3; EXECUTE: nobody — the `account` orchestrator
-- calls it as owner)
-- ============================================================================
-- * grants and their revocations of the learner are DELETED;
-- * orders keep their money facts but lose the learner (learner_id = NULL);
-- * the raw payload of every provider event of those orders is blanked.
-- What must be RETAINED for accounting, and for how long, is a legal decision
-- (BLOCKED_BY_OWNER PO-04); this default keeps no link to the person.
CREATE FUNCTION billing.erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_revocations integer;
    v_entitlements integer;
    v_events integer;
    v_orders integer;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'Malformed erasure arguments' USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('billing.erasing', 'on', true);

    DELETE FROM billing.entitlement_revocations r
    USING billing.entitlements e
    WHERE e.id = r.entitlement_id AND e.learner_id = p_user_id;
    GET DIAGNOSTICS v_revocations = ROW_COUNT;

    DELETE FROM billing.entitlements e WHERE e.learner_id = p_user_id;
    GET DIAGNOSTICS v_entitlements = ROW_COUNT;

    UPDATE billing.provider_events ev
       SET payload = '{}'::jsonb, payload_erased_at = now()
     WHERE ev.payload_erased_at IS NULL
       AND ev.order_id IN (SELECT o.id FROM billing.orders o WHERE o.learner_id = p_user_id);
    GET DIAGNOSTICS v_events = ROW_COUNT;

    UPDATE billing.orders o
       SET learner_id = NULL, erased_at = now(), updated_at = now()
     WHERE o.learner_id = p_user_id;
    GET DIAGNOSTICS v_orders = ROW_COUNT;

    PERFORM set_config('billing.erasing', '', true);
    RETURN jsonb_build_object(
        'schema', 'billing',
        'entitlements_deleted', v_entitlements,
        'revocations_deleted', v_revocations,
        'orders_anonymised', v_orders,
        'provider_event_payloads_blanked', v_events);
END;
$$;

-- ============================================================================
-- Policies and grants
-- ============================================================================
-- New functions are executable by PUBLIC by default; that default cannot be
-- changed per schema (see 20261121000300, change C10), so revoke explicitly.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA billing FROM PUBLIC, anon, authenticated, service_role;

GRANT USAGE ON SCHEMA billing TO edu_api;

-- The learner's own grants: the columns the app needs, nothing internal
-- (no idempotency key, no source reference, no staff id, no order id).
GRANT SELECT (id, learner_id, scope_kind, scope_grade_id, scope_course_id, starts_at, ends_at, source)
    ON billing.entitlements TO edu_api;
GRANT SELECT (entitlement_id, revoked_at) ON billing.entitlement_revocations TO edu_api;

CREATE POLICY entitlements_select_own ON billing.entitlements
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
-- A revocation is visible only if its grant is (the sub-query is itself
-- filtered by the policy above).
CREATE POLICY revocations_select_own ON billing.entitlement_revocations
    FOR SELECT TO edu_api
    USING (EXISTS (SELECT 1 FROM billing.entitlements e WHERE e.id = entitlement_revocations.entitlement_id));

-- Deliberately NO policy and NO grant on: providers, plans, plan_prices,
-- orders, provider_events, refunds. And no INSERT/UPDATE/DELETE anywhere.

GRANT EXECUTE ON FUNCTION billing.is_entitled(text, uuid) TO edu_api;
-- Every other billing function is callable by its owner only:
--   _require_staff, _audit                      the staff seam
--   learner_is_entitled_at                      internal reader
--   grant_entitlement, revoke_entitlement       internal writers
--   staff_grant_entitlement, staff_revoke_entitlement, staff_list_entitlements
--                                               awaiting the staff boundary (edu_staff)
--   create_order, apply_provider_event          awaiting PO-06 (checkout) and a webhook role
--   erase_learner                               called by the account-erasure orchestrator
