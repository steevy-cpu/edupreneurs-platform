-- Mon Edupreneur 2.0 — `billing` schema: the entitlement GRANT model (Platform-00 M-08)
--
-- NO LIVE PAYMENTS. This migration creates a model, not a paywall:
--   * nothing in schema `app` is created, altered or granted (overnight plan §3);
--   * the catalogue, lesson and sync code paths do not read this schema;
--   * no plan, price or provider row is inserted here — every plan that exists
--     tonight is synthetic test data created by a test (BLOCKED_BY_OWNER PO-01,
--     PO-05, PO-06, PO-07).
--
-- The `billing` schema is PRIVATE, exactly like `app`: it is never listed in the
-- Supabase Data API "exposed schemas", and `PUBLIC`, `anon`, `authenticated`,
-- `authenticator` and `service_role` hold nothing in it.
--
-- SHAPE (Platform-00 doc 04 §4.2)
--   providers                who may send payment events (none registered here)
--   plans, plan_prices       what could be bought: scope, duration, price per currency
--   orders                   one attempt to pay: plan, amount expected, provider, state
--   provider_events          every provider message, raw, unique by (provider, event id)
--   refunds                  one row per refunded order
--   entitlements             ONE ROW PER GRANT. Never edited. Extending = a new row.
--   entitlement_revocations  revocation is a NEW record, never an edit of the grant
--
-- MONEY is always an integer number of minor units plus an ISO-4217 currency
-- code. There is no floating-point or `numeric` amount anywhere.
--
-- Functions, grants to the student API role and the staff seam are in the next
-- migration (20261124070200_billing_functions.sql).

CREATE SCHEMA billing;
REVOKE ALL ON SCHEMA billing FROM PUBLIC;
REVOKE ALL ON SCHEMA billing FROM anon, authenticated, service_role;
COMMENT ON SCHEMA billing IS
    'Private entitlement grants, orders and provider events. Reached only through FastAPI; never expose this schema in the Supabase Data API.';

-- ============================================================================
-- Providers
-- ============================================================================
-- A provider must be registered AND enabled before billing.create_order() or
-- billing.apply_provider_event() will accept it. This migration registers none:
-- in a hosted environment the simulated provider therefore does not exist.
CREATE TABLE billing.providers (
    code text PRIMARY KEY CHECK (code ~ '^[a-z][a-z0-9_]{1,30}$'),
    -- true  = an in-process simulation that moves no money (local/test only);
    -- false = a real payment provider (none is integrated).
    is_simulated boolean NOT NULL,
    is_enabled boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- Plans (data, not code)
-- ============================================================================
-- scope_kind: 'all' | 'grade' | 'course'. Modelled from day one (doc 05 risk
-- "entitlement scope too coarse or too fine") even if only 'all' is ever sold.
CREATE TABLE billing.plans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9][a-z0-9_-]{2,59}$'),
    scope_kind text NOT NULL CHECK (scope_kind IN ('all', 'grade', 'course')),
    scope_grade_id uuid REFERENCES app.grades(id) ON DELETE RESTRICT,
    scope_course_id uuid REFERENCES app.courses(id) ON DELETE RESTRICT,
    duration_days integer NOT NULL CHECK (duration_days BETWEEN 1 AND 3660),
    -- BLOCKED_BY_OWNER (PO-01, PO-05): no real plan or price has been decided.
    -- A synthetic plan can only ever be ordered through a simulated provider,
    -- and a real provider can never fulfil a synthetic plan (billing.create_order).
    is_synthetic boolean NOT NULL DEFAULT true,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT plans_scope_shape CHECK (
        (scope_kind = 'all' AND scope_grade_id IS NULL AND scope_course_id IS NULL)
        OR (scope_kind = 'grade' AND scope_grade_id IS NOT NULL AND scope_course_id IS NULL)
        OR (scope_kind = 'course' AND scope_grade_id IS NULL AND scope_course_id IS NOT NULL)
    )
);

CREATE TABLE billing.plan_prices (
    plan_id uuid NOT NULL REFERENCES billing.plans(id) ON DELETE RESTRICT,
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    amount_minor bigint NOT NULL CHECK (amount_minor > 0),
    PRIMARY KEY (plan_id, currency)
);

-- ============================================================================
-- Orders
-- ============================================================================
-- Written only by billing.create_order() (price snapshot taken on the server)
-- and billing.apply_provider_event() (state). learner_id becomes NULL only when
-- the learner is erased; the financial skeleton is kept without the person.
CREATE TABLE billing.orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learner_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    plan_id uuid NOT NULL REFERENCES billing.plans(id) ON DELETE RESTRICT,
    provider text NOT NULL REFERENCES billing.providers(code) ON DELETE RESTRICT,
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    amount_expected_minor bigint NOT NULL CHECK (amount_expected_minor > 0),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'failed', 'refunded')),
    idempotency_key text NOT NULL UNIQUE CHECK (char_length(idempotency_key) BETWEEN 8 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    erased_at timestamptz,
    CONSTRAINT orders_learner_or_erased CHECK (learner_id IS NOT NULL OR erased_at IS NOT NULL)
);

-- ============================================================================
-- Provider events (raw, exactly-once)
-- ============================================================================
-- UNIQUE (provider, provider_event_id) is what makes a duplicated or replayed
-- message harmless: the second arrival finds the first row and returns its
-- stored outcome. `outcome` is decided once, when the row is written.
CREATE TABLE billing.provider_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL REFERENCES billing.providers(code) ON DELETE RESTRICT,
    provider_event_id text NOT NULL CHECK (char_length(provider_event_id) BETWEEN 1 AND 200),
    event_type text NOT NULL CHECK (char_length(event_type) BETWEEN 1 AND 80),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    payload_sha256 bytea NOT NULL CHECK (octet_length(payload_sha256) = 32),
    order_id uuid REFERENCES billing.orders(id) ON DELETE RESTRICT,
    outcome text NOT NULL CHECK (outcome IN ('applied', 'ignored', 'rejected')),
    outcome_code text NOT NULL CHECK (outcome_code ~ '^[a-z_]{3,60}$'),
    result jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(result) = 'object'),
    received_at timestamptz NOT NULL DEFAULT now(),
    payload_erased_at timestamptz,
    UNIQUE (provider, provider_event_id)
);

CREATE TABLE billing.refunds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL UNIQUE REFERENCES billing.orders(id) ON DELETE RESTRICT,
    provider_event_id uuid NOT NULL UNIQUE REFERENCES billing.provider_events(id) ON DELETE RESTRICT,
    amount_minor bigint NOT NULL CHECK (amount_minor > 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- Entitlements: one row per grant
-- ============================================================================
-- * Access = ANY grant that is active now. Overlapping grants are allowed.
-- * A grant is active when  starts_at <= t < ends_at  and it has no revocation
--   (half-open interval: at exactly ends_at the grant is over).
-- * idempotency_key is UNIQUE, so the same grant request can never produce two
--   rows; a purchase grant is additionally unique per order.
-- * granted_by has deliberately no foreign key (like app.audit_events.actor_id):
--   history must not block the deletion of a staff account.
CREATE TABLE billing.entitlements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    scope_kind text NOT NULL CHECK (scope_kind IN ('all', 'grade', 'course')),
    scope_grade_id uuid REFERENCES app.grades(id) ON DELETE RESTRICT,
    scope_course_id uuid REFERENCES app.courses(id) ON DELETE RESTRICT,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    source text NOT NULL CHECK (source IN (
        'purchase', 'gift', 'promo', 'school_licence', 'trial', 'staff_grant', 'migration')),
    source_ref text CHECK (source_ref IS NULL OR char_length(source_ref) BETWEEN 1 AND 200),
    plan_id uuid REFERENCES billing.plans(id) ON DELETE RESTRICT,
    order_id uuid REFERENCES billing.orders(id) ON DELETE RESTRICT,
    idempotency_key text NOT NULL UNIQUE CHECK (char_length(idempotency_key) BETWEEN 8 AND 200),
    granted_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT entitlements_scope_shape CHECK (
        (scope_kind = 'all' AND scope_grade_id IS NULL AND scope_course_id IS NULL)
        OR (scope_kind = 'grade' AND scope_grade_id IS NOT NULL AND scope_course_id IS NULL)
        OR (scope_kind = 'course' AND scope_grade_id IS NULL AND scope_course_id IS NOT NULL)
    ),
    CONSTRAINT entitlements_period CHECK (ends_at > starts_at),
    -- A 'purchase' grant always comes from an order, and nothing else does.
    CONSTRAINT entitlements_purchase_has_order CHECK ((source = 'purchase') = (order_id IS NOT NULL))
);

-- One grant per order, whatever idempotency key a caller invents.
CREATE UNIQUE INDEX entitlements_one_per_order ON billing.entitlements(order_id)
    WHERE order_id IS NOT NULL;

-- Revocation is a new record. One per grant: revoking twice changes nothing.
-- revoked_at is always the server clock at the moment of revocation.
CREATE TABLE billing.entitlement_revocations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entitlement_id uuid NOT NULL UNIQUE REFERENCES billing.entitlements(id) ON DELETE RESTRICT,
    revoked_at timestamptz NOT NULL DEFAULT now(),
    reason_code text NOT NULL CHECK (reason_code IN ('staff_revoke', 'refund')),
    source_ref text CHECK (source_ref IS NULL OR char_length(source_ref) BETWEEN 1 AND 200),
    revoked_by uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- Indexes (in addition to the PK / UNIQUE indexes above); every FK is covered
-- ============================================================================
CREATE INDEX idx_billing_plans_grade ON billing.plans(scope_grade_id) WHERE scope_grade_id IS NOT NULL;
CREATE INDEX idx_billing_plans_course ON billing.plans(scope_course_id) WHERE scope_course_id IS NOT NULL;
CREATE INDEX idx_billing_orders_learner ON billing.orders(learner_id, created_at DESC);
CREATE INDEX idx_billing_orders_plan ON billing.orders(plan_id);
CREATE INDEX idx_billing_orders_provider ON billing.orders(provider);
CREATE INDEX idx_billing_events_order ON billing.provider_events(order_id) WHERE order_id IS NOT NULL;
CREATE INDEX idx_billing_entitlements_learner ON billing.entitlements(learner_id, ends_at DESC);
CREATE INDEX idx_billing_entitlements_grade ON billing.entitlements(scope_grade_id) WHERE scope_grade_id IS NOT NULL;
CREATE INDEX idx_billing_entitlements_course ON billing.entitlements(scope_course_id) WHERE scope_course_id IS NOT NULL;
CREATE INDEX idx_billing_entitlements_plan ON billing.entitlements(plan_id) WHERE plan_id IS NOT NULL;

-- ============================================================================
-- Default deny: RLS on every table; nobody but the owner holds a privilege yet
-- ============================================================================
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'billing' LOOP
    EXECUTE format('ALTER TABLE billing.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA billing FROM PUBLIC, anon, authenticated, service_role;
