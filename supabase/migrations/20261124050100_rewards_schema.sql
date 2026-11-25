-- Mon Edupreneur 2.0 — rewards: Gold ledger, balances, streak days, achievements
--
-- Overnight mission 2026-11-24, lane REWARDS (Platform-00 M-10, decision PO-09).
--
-- PRINCIPLES
--   * The device never reports points. Gold exists only as rows of
--     rewards.ledger, and every award row is tied to a sync operation the
--     server already ACCEPTED (app.sync_receipts) and to the server-written
--     fact behind it (app.practice_attempts / app.lesson_progress).
--   * The ledger is append-only. A correction is a NEW `reversal` row.
--   * Balances and streaks are derived caches that can be rebuilt from the
--     ledger / the activity days at any time.
--   * Nothing is created in schema `app`, and app.sync_apply_operation is not
--     touched. The only links to `app` are a foreign key to
--     app.learner_profiles and read-only look-ups made by definer functions.
--
-- NO FOREIGN KEY TO THE LEARNING TABLES, ON PURPOSE: app.sync_receipts,
-- app.practice_attempts and app.lesson_progress are validated by the insert
-- trigger below instead. A foreign key would (a) block the receipt compaction
-- that Platform-00 already has in its backlog and (b) make every
-- `TRUNCATE app.sync_receipts, ...` used by the verified test-suite fail.
--
-- BLOCKED_BY_OWNER (PO-09): every amount, cap and achievement in this file is
-- a SYNTHETIC PLACEHOLDER using Platform-00's recommended defaults. They are
-- rows in rewards.rules, not code: the owner's decision becomes a new rule
-- version, never an edit of history.

CREATE SCHEMA rewards;
REVOKE ALL ON SCHEMA rewards FROM PUBLIC;
REVOKE ALL ON SCHEMA rewards FROM anon, authenticated;
COMMENT ON SCHEMA rewards IS
    'Private. Server-authoritative Gold ledger, streaks and achievements. Reached only through FastAPI; never expose this schema in the Supabase Data API.';

-- ============================================================================
-- Product day
-- ============================================================================
-- "A day" is the America/Port-au-Prince calendar date of the instant the
-- SERVER accepted the operation. Never the phone's clock.
CREATE FUNCTION rewards.haiti_day(p_instant timestamptz)
RETURNS date
LANGUAGE sql STABLE PARALLEL SAFE
SET search_path = pg_catalog, pg_temp
AS $$ SELECT (p_instant AT TIME ZONE 'America/Port-au-Prince')::date $$;

-- ============================================================================
-- Rules (data, not code)
-- ============================================================================
CREATE TABLE rewards.rules (
    code text NOT NULL CHECK (code ~ '^[a-z0-9_]{3,60}$'),
    version integer NOT NULL CHECK (version > 0),
    event_kind text NOT NULL
        CHECK (event_kind IN ('question_first_correct', 'lesson_first_completed', 'achievement')),
    -- Gold per award. Bounded so that a typo cannot mint a fortune.
    amount integer NOT NULL CHECK (amount BETWEEN 1 AND 1000),
    -- Most Gold this rule may give ONE learner for ONE lesson (all time).
    per_lesson_cap integer CHECK (per_lesson_cap IS NULL OR per_lesson_cap >= amount),
    -- Most Gold this rule may give ONE learner on ONE Haiti calendar day.
    per_day_cap integer CHECK (per_day_cap IS NULL OR per_day_cap >= amount),
    is_active boolean NOT NULL DEFAULT false,
    decision_status text NOT NULL DEFAULT 'BLOCKED_BY_OWNER:PO-09'
        CHECK (char_length(decision_status) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (code, version),
    -- The two learning events are looked up by their own name.
    CHECK (event_kind = 'achievement' OR code = event_kind),
    CHECK (event_kind <> 'achievement' OR (per_lesson_cap IS NULL AND per_day_cap IS NULL))
);
-- At most one live version of a rule.
CREATE UNIQUE INDEX rules_one_active_version ON rewards.rules (code) WHERE is_active;

-- ============================================================================
-- Achievements (definitions)
-- ============================================================================
CREATE TABLE rewards.achievement_definitions (
    code text PRIMARY KEY CHECK (code ~ '^[a-z0-9_]{3,60}$'),
    criterion_kind text NOT NULL
        CHECK (criterion_kind IN ('lessons_completed', 'questions_correct', 'streak_days')),
    threshold integer NOT NULL CHECK (threshold BETWEEN 1 AND 100000),
    -- Optional one-off Gold bonus: the code of an 'achievement' rule.
    bonus_rule_code text CHECK (bonus_rule_code IS NULL OR bonus_rule_code ~ '^[a-z0-9_]{3,60}$'),
    -- Draft wording (French + Haitian Creole), pending educator / native-speaker review.
    titles jsonb NOT NULL CHECK (jsonb_typeof(titles) = 'object' AND titles ? 'fr'),
    sort_order smallint NOT NULL DEFAULT 100,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- The ledger
-- ============================================================================
CREATE TABLE rewards.ledger (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Monotonic insertion order; used only for stable paging.
    seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    entry_kind text NOT NULL CHECK (entry_kind IN ('award', 'reversal')),
    amount integer NOT NULL CHECK (amount <> 0 AND amount BETWEEN -1000 AND 1000),
    rule_code text NOT NULL,
    rule_version integer NOT NULL,
    source_kind text NOT NULL CHECK (source_kind IN
        ('question_first_correct', 'lesson_first_completed', 'achievement', 'reversal')),
    -- The accepted sync operation that earned this row (awards only).
    source_op_id uuid,
    lesson_id uuid,
    question_key text,
    achievement_code text,
    reverses_ledger_id uuid REFERENCES rewards.ledger(id),
    -- THE EXACTLY-ONCE KEY. It names WHAT was rewarded, not which operation
    -- carried it, so a replay, a new op id, another device, another locale or a
    -- newer revision of the same question all collide on the same value:
    --   q:<lesson id>:<question key>   first correct answer to a question
    --   l:<lesson id>                  first completion of a lesson
    --   a:<achievement code>           one-off achievement bonus
    --   r:<ledger id>                  the (single) reversal of a row
    -- It is GENERATED from the structured columns, so no writer — not even a
    -- privileged one — can supply a look-alike key by hand.
    source_key text GENERATED ALWAYS AS (
        CASE source_kind
            WHEN 'question_first_correct' THEN 'q:' || lesson_id::text || ':' || question_key
            WHEN 'lesson_first_completed' THEN 'l:' || lesson_id::text
            WHEN 'achievement' THEN 'a:' || achievement_code
            WHEN 'reversal' THEN 'r:' || reverses_ledger_id::text
        END
    ) STORED NOT NULL,
    -- Instant the server accepted the earning operation, and its Haiti date.
    accepted_at timestamptz NOT NULL,
    accepted_day date NOT NULL,
    reason text CHECK (reason IS NULL OR char_length(reason) BETWEEN 3 AND 300),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ledger_exactly_once UNIQUE (learner_id, source_key),
    CONSTRAINT ledger_rule_fkey FOREIGN KEY (rule_code, rule_version)
        REFERENCES rewards.rules(code, version) ON DELETE RESTRICT,
    CONSTRAINT ledger_day_is_haiti_day
        CHECK (accepted_day = (accepted_at AT TIME ZONE 'America/Port-au-Prince')::date),
    CONSTRAINT ledger_shape CHECK (
        (source_kind = 'question_first_correct' AND entry_kind = 'award' AND amount > 0
            AND source_op_id IS NOT NULL AND lesson_id IS NOT NULL AND question_key IS NOT NULL
            AND achievement_code IS NULL AND reverses_ledger_id IS NULL AND reason IS NULL)
        OR (source_kind = 'lesson_first_completed' AND entry_kind = 'award' AND amount > 0
            AND source_op_id IS NOT NULL AND lesson_id IS NOT NULL AND question_key IS NULL
            AND achievement_code IS NULL AND reverses_ledger_id IS NULL AND reason IS NULL)
        OR (source_kind = 'achievement' AND entry_kind = 'award' AND amount > 0
            AND source_op_id IS NOT NULL AND lesson_id IS NULL AND question_key IS NULL
            AND achievement_code IS NOT NULL AND reverses_ledger_id IS NULL AND reason IS NULL)
        OR (source_kind = 'reversal' AND entry_kind = 'reversal' AND amount < 0
            AND reverses_ledger_id IS NOT NULL AND reason IS NOT NULL)
    )
);
CREATE INDEX idx_ledger_learner_seq ON rewards.ledger (learner_id, seq DESC);
CREATE INDEX idx_ledger_caps_lesson ON rewards.ledger (learner_id, rule_code, lesson_id)
    WHERE entry_kind = 'award';
CREATE INDEX idx_ledger_caps_day ON rewards.ledger (learner_id, accepted_day, rule_code)
    WHERE entry_kind = 'award';
-- For period aggregates (the leaderboard lane reads through its own functions).
CREATE INDEX idx_ledger_day ON rewards.ledger (accepted_day, learner_id) INCLUDE (amount);
CREATE INDEX idx_ledger_rule ON rewards.ledger (rule_code, rule_version);
CREATE INDEX idx_ledger_reverses ON rewards.ledger (reverses_ledger_id)
    WHERE reverses_ledger_id IS NOT NULL;

-- ============================================================================
-- Derived caches
-- ============================================================================
-- balance = sum(ledger.amount). Maintained by a trigger on the ledger, so it
-- is correct for EVERY insert path, and rebuildable by rewards.rebuild_balance.
CREATE TABLE rewards.balances (
    learner_id uuid PRIMARY KEY REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    balance bigint NOT NULL DEFAULT 0 CHECK (balance >= 0),
    -- Sum of the positive rows only (what was ever earned, before reversals).
    lifetime_earned bigint NOT NULL DEFAULT 0 CHECK (lifetime_earned >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (lifetime_earned >= balance)
);

-- One row per accepted operation the rewards engine has looked at, whatever it
-- decided. This is what lets reconciliation find "accepted but never examined"
-- operations without re-reading every wrong answer forever, and what makes a
-- cap decision final (an operation refused by a cap is not re-judged later).
CREATE TABLE rewards.processed_operations (
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    op_id uuid NOT NULL,
    outcome text NOT NULL CHECK (outcome IN
        ('awarded', 'duplicate', 'capped_lesson', 'capped_day', 'not_eligible', 'no_active_rule')),
    -- Gold credited because of this operation (event + achievement bonuses).
    gold integer NOT NULL DEFAULT 0 CHECK (gold >= 0),
    accepted_day date NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (learner_id, op_id)
);

-- Haiti calendar days on which the server accepted at least one learning
-- operation from the learner (right or wrong answer, any completion).
CREATE TABLE rewards.activity_days (
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    day date NOT NULL,
    first_op_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (learner_id, day)
);

-- Derived from activity_days. NON-PUNITIVE BY DESIGN: there is no "lost",
-- "broken" or "frozen" column. A run that ended simply stops being the latest.
CREATE TABLE rewards.streak_state (
    learner_id uuid PRIMARY KEY REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    -- The most recent run of consecutive days (it may have ended in the past).
    latest_run_days integer NOT NULL CHECK (latest_run_days > 0),
    latest_run_start date NOT NULL,
    last_active_day date NOT NULL,
    longest_run_days integer NOT NULL CHECK (longest_run_days > 0),
    longest_run_end date NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (latest_run_start = last_active_day - (latest_run_days - 1)),
    CHECK (longest_run_days >= latest_run_days)
);

CREATE TABLE rewards.achievement_awards (
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    achievement_code text NOT NULL REFERENCES rewards.achievement_definitions(code) ON DELETE RESTRICT,
    -- The accepted operation whose processing crossed the threshold.
    source_op_id uuid NOT NULL,
    -- The bonus row, when the achievement carries Gold.
    ledger_id uuid UNIQUE REFERENCES rewards.ledger(id),
    awarded_at timestamptz NOT NULL,
    awarded_day date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (learner_id, achievement_code),
    CHECK (awarded_day = (awarded_at AT TIME ZONE 'America/Port-au-Prince')::date)
);
CREATE INDEX idx_achievement_awards_code ON rewards.achievement_awards (achievement_code);

-- ============================================================================
-- Guards
-- ============================================================================
-- Rule versions are history: the economics of a version never change. Only the
-- on/off switch (and the note about the owner's decision) may be edited.
CREATE FUNCTION rewards.protect_rule_version()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NEW.code IS DISTINCT FROM OLD.code OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.event_kind IS DISTINCT FROM OLD.event_kind OR NEW.amount IS DISTINCT FROM OLD.amount
       OR NEW.per_lesson_cap IS DISTINCT FROM OLD.per_lesson_cap
       OR NEW.per_day_cap IS DISTINCT FROM OLD.per_day_cap
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'A reward rule version is immutable; add a new version instead'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_rule_version BEFORE UPDATE ON rewards.rules
    FOR EACH ROW EXECUTE FUNCTION rewards.protect_rule_version();

-- Every ledger row is checked against server-written facts, whoever inserts
-- it. SECURITY DEFINER for the same reason as the app guards: the check must
-- see every relevant row regardless of the caller's row-level security.
CREATE FUNCTION rewards.validate_ledger_entry()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_rule record;
    v_receipt record;
    v_original record;
BEGIN
    NEW.created_at := now();

    IF NEW.source_kind = 'reversal' THEN
        SELECT l.learner_id, l.entry_kind, l.amount, l.rule_code, l.rule_version INTO v_original
        FROM rewards.ledger l WHERE l.id = NEW.reverses_ledger_id;
        IF NOT FOUND OR v_original.learner_id <> NEW.learner_id
           OR v_original.entry_kind <> 'award' OR NEW.amount <> -v_original.amount
           OR NEW.rule_code <> v_original.rule_code
           OR NEW.rule_version <> v_original.rule_version THEN
            RAISE EXCEPTION 'A reversal must exactly negate one award of the same learner'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    -- The amount is never the writer's choice: it is the rule version's amount.
    SELECT r.amount, r.event_kind INTO v_rule
    FROM rewards.rules r WHERE r.code = NEW.rule_code AND r.version = NEW.rule_version;
    IF NOT FOUND OR v_rule.event_kind <> NEW.source_kind OR v_rule.amount <> NEW.amount THEN
        RAISE EXCEPTION 'Ledger amount and kind must match the reward rule version'
            USING ERRCODE = '23514';
    END IF;

    -- Tied to an operation the server accepted from THIS learner.
    SELECT r.op_kind, r.result_code, r.result, r.created_at INTO v_receipt
    FROM app.sync_receipts r
    WHERE r.learner_id = NEW.learner_id AND r.op_id = NEW.source_op_id;
    IF NOT FOUND OR v_receipt.result_code <> 'accepted'
       OR NEW.accepted_at <> v_receipt.created_at THEN
        RAISE EXCEPTION 'A reward needs an accepted sync operation of the same learner'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.source_kind = 'question_first_correct' THEN
        IF v_receipt.op_kind <> 'practice_answer' OR NOT EXISTS (
            SELECT 1
            FROM app.practice_attempts a
            JOIN app.question_revisions q ON q.id = a.question_revision_id
            JOIN app.lesson_revisions lr ON lr.id = a.lesson_revision_id
            WHERE a.learner_id = NEW.learner_id AND a.op_id = NEW.source_op_id
              AND a.score = 1 AND q.question_key = NEW.question_key
              AND lr.lesson_id = NEW.lesson_id
        ) THEN
            RAISE EXCEPTION 'A question reward needs a server-scored correct attempt for that question'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.source_kind = 'lesson_first_completed' THEN
        IF v_receipt.op_kind <> 'lesson_completed'
           OR (v_receipt.result ->> 'lesson_id') IS DISTINCT FROM NEW.lesson_id::text
           OR NOT EXISTS (
            SELECT 1 FROM app.lesson_progress lp
            WHERE lp.learner_id = NEW.learner_id AND lp.lesson_id = NEW.lesson_id
              AND lp.completed_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'A lesson reward needs a server-recorded completion of that lesson'
                USING ERRCODE = '23514';
        END IF;
    ELSE -- achievement
        IF NOT EXISTS (
            SELECT 1 FROM rewards.achievement_definitions d
            WHERE d.code = NEW.achievement_code AND d.bonus_rule_code = NEW.rule_code
        ) THEN
            RAISE EXCEPTION 'An achievement bonus must use the rule named by its definition'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER validate_ledger_entry BEFORE INSERT ON rewards.ledger
    FOR EACH ROW EXECUTE FUNCTION rewards.validate_ledger_entry();

-- The balance follows the ledger in the same statement.
CREATE FUNCTION rewards.apply_ledger_entry_to_balance()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    -- UPDATE first: a reversal (negative amount) always has a row to update,
    -- and must never travel through the INSERT arm, whose proposed row would
    -- be rejected by the "balance >= 0" check before the conflict is seen.
    UPDATE rewards.balances b
       SET balance = b.balance + NEW.amount,
           lifetime_earned = b.lifetime_earned + GREATEST(NEW.amount, 0),
           updated_at = now()
     WHERE b.learner_id = NEW.learner_id;
    IF NOT FOUND THEN
        INSERT INTO rewards.balances AS b (learner_id, balance, lifetime_earned)
        VALUES (NEW.learner_id, NEW.amount, GREATEST(NEW.amount, 0))
        ON CONFLICT (learner_id) DO UPDATE
            SET balance = b.balance + EXCLUDED.balance,
                lifetime_earned = b.lifetime_earned + EXCLUDED.lifetime_earned,
                updated_at = now();
    END IF;
    RETURN NULL;
END;
$$;
CREATE TRIGGER apply_ledger_entry_to_balance AFTER INSERT ON rewards.ledger
    FOR EACH ROW EXECUTE FUNCTION rewards.apply_ledger_entry_to_balance();

-- Append-only history. The ONE exception is the erasure hook
-- (rewards.erase_learner), which announces the learner it is erasing in a
-- transaction-local setting; rows of any other learner stay undeletable even
-- then. UPDATE is never possible. (No role but the owner holds DELETE at all.)
CREATE FUNCTION rewards.prevent_history_change()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND NULLIF(current_setting('rewards.erasing_learner', true), '') = OLD.learner_id::text THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Reward history is append-only and cannot be updated or deleted'
        USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER no_edit_ledger BEFORE UPDATE OR DELETE ON rewards.ledger
    FOR EACH ROW EXECUTE FUNCTION rewards.prevent_history_change();
CREATE TRIGGER no_edit_achievement_awards BEFORE UPDATE OR DELETE ON rewards.achievement_awards
    FOR EACH ROW EXECUTE FUNCTION rewards.prevent_history_change();
CREATE TRIGGER no_edit_processed_operations BEFORE UPDATE OR DELETE ON rewards.processed_operations
    FOR EACH ROW EXECUTE FUNCTION rewards.prevent_history_change();

-- ============================================================================
-- Row-level security and grants: the student API reads its OWN rows, writes none
-- ============================================================================
ALTER TABLE rewards.rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE rewards.achievement_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE rewards.ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE rewards.balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE rewards.processed_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE rewards.activity_days ENABLE ROW LEVEL SECURITY;
ALTER TABLE rewards.streak_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE rewards.achievement_awards ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA rewards FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA rewards FROM PUBLIC, anon, authenticated;

GRANT USAGE ON SCHEMA rewards TO edu_api;
GRANT SELECT ON rewards.ledger, rewards.balances, rewards.streak_state,
    rewards.achievement_awards, rewards.achievement_definitions TO edu_api;
-- Deliberately NO grant on rewards.rules, rewards.processed_operations and
-- rewards.activity_days: the student API has no use for them.

CREATE POLICY ledger_select_own ON rewards.ledger
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY balances_select_own ON rewards.balances
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY streak_select_own ON rewards.streak_state
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY achievement_awards_select_own ON rewards.achievement_awards
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
CREATE POLICY achievement_definitions_read ON rewards.achievement_definitions
    FOR SELECT TO edu_api USING (is_active);

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA rewards FROM PUBLIC, anon, authenticated;

-- ============================================================================
-- Reference data — SYNTHETIC PLACEHOLDERS, BLOCKED_BY_OWNER (PO-09)
-- ============================================================================
-- Platform-00's recommendation: Gold for the FIRST correct answer to a question
-- and the FIRST completion of a lesson. Nothing for wrong answers, repeats,
-- rejected operations, exams, or opening things.
INSERT INTO rewards.rules (code, version, event_kind, amount, per_lesson_cap, per_day_cap, is_active) VALUES
    ('question_first_correct', 1, 'question_first_correct', 5, 100, 300, true),
    ('lesson_first_completed', 1, 'lesson_first_completed', 20, 20, 200, true),
    ('achievement_first_lesson', 1, 'achievement', 10, NULL, NULL, true),
    ('achievement_ten_correct', 1, 'achievement', 15, NULL, NULL, true);

INSERT INTO rewards.achievement_definitions (code, criterion_kind, threshold, bonus_rule_code, titles, sort_order) VALUES
    ('first_correct_answer', 'questions_correct', 1, NULL,
     '{"fr": "Première bonne réponse", "ht": "Premye bon repons"}', 10),
    ('first_lesson_completed', 'lessons_completed', 1, 'achievement_first_lesson',
     '{"fr": "Première leçon terminée", "ht": "Premye leson fini"}', 20),
    ('ten_correct_answers', 'questions_correct', 10, 'achievement_ten_correct',
     '{"fr": "Dix bonnes réponses", "ht": "Dis bon repons"}', 30),
    ('three_day_streak', 'streak_days', 3, NULL,
     '{"fr": "Trois jours d''étude de suite", "ht": "Twa jou etid youn apre lòt"}', 40);
