-- Mon Edupreneur 2.0 — notifications: hand the delivery functions to the worker role
--
-- Closes the seam left by 20261124080100 (SEAM(notify-worker-role)) now that the
-- staff lane's platform roles exist (20261124010000: edu_staff, edu_worker).
--
-- edu_worker may, in schema notify, do exactly three things — all through
-- SECURITY DEFINER functions, with no table privilege at all:
--   * notify.claim_due      lease deliveries that are due (preferences and quiet
--                           hours are applied inside the function, on the
--                           database clock — the worker cannot choose the time);
--   * notify.record_attempt report the outcome of a lease it holds;
--   * notify.enqueue        create a notification from a background job
--                           (a scheduled reminder, for example).
--
-- NOT granted, to anyone: the internal _claim_due_at / _record_attempt_at twins
-- (explicit clock), notify._settle, notify.erase_learner, and every table.
-- NOT granted to edu_api or edu_staff: enqueue, claim_due, record_attempt. A
-- learner request or a staff request still cannot create or deliver a
-- notification. STILL NOTHING IS SENT: no adapter but the in-memory dummy exists.

GRANT USAGE ON SCHEMA notify TO edu_worker;
GRANT EXECUTE ON FUNCTION notify.claim_due(text, integer, integer) TO edu_worker;
GRANT EXECUTE ON FUNCTION notify.record_attempt(uuid, text, uuid, text, text) TO edu_worker;
GRANT EXECUTE ON FUNCTION notify.enqueue(uuid, text, jsonb, text, text[], timestamptz, timestamptz)
    TO edu_worker;
