-- Word of the Day: what a learner can read, through the student API role.
-- Missing translation -> French fallback; nothing assigned -> zero rows;
-- draft / in-review / rejected / future content is invisible; two accounts get
-- the same word and reading writes nothing anywhere.
BEGIN;
SELECT * FROM no_plan();
-- Never straddle Haiti midnight: if the date changes within 5 seconds, wait for it.
DO $$ BEGIN
    PERFORM pg_sleep(GREATEST(0, 5 - EXTRACT(epoch FROM
        vocab.haiti_day_start(vocab.haiti_date(clock_timestamp()) + 1) - clock_timestamp()))::int
        * CASE WHEN vocab.haiti_day_start(vocab.haiti_date(clock_timestamp()) + 1) - clock_timestamp() < interval '5 seconds' THEN 1 ELSE 0 END);
END $$;

-- (TRUNCATE is refused by a trigger; switched off for this fixture only, inside the rolled-back transaction.)
ALTER TABLE vocab.daily_assignments DISABLE TRIGGER no_truncate;
ALTER TABLE vocab.word_revisions DISABLE TRIGGER no_truncate;
ALTER TABLE vocab.reviews DISABLE TRIGGER no_truncate;
TRUNCATE vocab.daily_assignments, vocab.audio_assets, vocab.reviews, vocab.word_revisions, vocab.words, vocab.sources;
ALTER TABLE vocab.daily_assignments ENABLE TRIGGER no_truncate;
ALTER TABLE vocab.word_revisions ENABLE TRIGGER no_truncate;
ALTER TABLE vocab.reviews ENABLE TRIGGER no_truncate;
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
SET CONSTRAINTS ALL IMMEDIATE;

-- Run one statement AS THE STUDENT API ROLE with the given actor, then switch
-- back. Returns the first column of the first row as text, or 'ERROR:<sqlstate>'.
GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
CREATE FUNCTION pg_temp.as_api(p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    EXECUTE 'SET LOCAL ROLE edu_api';
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE;
    END;
    EXECUTE 'RESET ROLE';
    PERFORM set_config('edu.actor_id', '', true);
    RETURN v_out;
END;
$fn$;
\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''

CREATE TEMP TABLE ids (k text PRIMARY KEY, v uuid NOT NULL);
CREATE FUNCTION pg_temp.id(p_k text) RETURNS uuid LANGUAGE sql AS $fn$ SELECT v FROM ids WHERE k = p_k $fn$;
CREATE FUNCTION pg_temp.today() RETURNS date LANGUAGE sql AS $fn$ SELECT vocab.haiti_date(clock_timestamp()) $fn$;
CREATE FUNCTION pg_temp.revision(p_key text, p_word uuid, p_locale text, p_term text, p_source uuid, p_outcome text DEFAULT 'approved')
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE v_rev uuid;
BEGIN
    PERFORM set_config('edu.actor_id', 'a0000000-0000-4000-8000-000000000003', true);
    v_rev := vocab.create_draft(p_word, p_locale, p_term, 'pro-' || p_term, 'noun',
                                'Définition synthétique : ' || p_term, 'Exemple synthétique : ' || p_term, 'glose ' || p_term, p_source);
    INSERT INTO ids VALUES (p_key, v_rev);
    IF p_key = 'one_fr1' THEN
        PERFORM vocab.set_audio(v_rev, 'vocab/test/one-fr-1.m4a', 20480, sha256('synthetic test bytes'), 'audio/mp4', 1200,
                                'e1000000-0000-4000-8000-000000000003');
    END IF;
    IF p_outcome <> 'draft' THEN
        PERFORM vocab.submit_revision(v_rev);
        IF p_outcome <> 'in_review' THEN
            PERFORM set_config('edu.actor_id', 'a0000000-0000-4000-8000-000000000004', true);
            PERFORM vocab.review_revision(v_rev, p_outcome);
        END IF;
    END IF;
    PERFORM set_config('edu.actor_id', '', true);
END;
$fn$;

INSERT INTO vocab.sources (id, source_title, licence, created_by) VALUES
  ('e1000000-0000-4000-8000-000000000001', 'Synthetic test source (word one, French)', 'synthetic-test-only', :EDITOR),
  ('e1000000-0000-4000-8000-000000000002', 'Synthetic test source (word one, Creole)', 'synthetic-test-only', :EDITOR),
  ('e1000000-0000-4000-8000-000000000003', 'Synthetic test source (recording)', 'synthetic-test-only', :EDITOR),
  ('e1000000-0000-4000-8000-000000000004', 'Synthetic test source (word two)', 'synthetic-test-only', :EDITOR);
UPDATE vocab.sources SET rights_status = 'cleared';
INSERT INTO vocab.words (id, slug, created_by) VALUES
  ('f1000000-0000-4000-8000-000000000001', 'word-one', :EDITOR),   -- French + Creole + recording
  ('f1000000-0000-4000-8000-000000000002', 'word-two', :EDITOR);   -- French only
SELECT pg_temp.revision('one_fr1', 'f1000000-0000-4000-8000-000000000001', 'fr', 'UN-FR', 'e1000000-0000-4000-8000-000000000001');
SELECT pg_temp.revision('one_ht1', 'f1000000-0000-4000-8000-000000000001', 'ht', 'UN-HT', 'e1000000-0000-4000-8000-000000000002');
SELECT pg_temp.revision('two_fr1', 'f1000000-0000-4000-8000-000000000002', 'fr', 'DEUX-FR', 'e1000000-0000-4000-8000-000000000004');

-- ---- nothing assigned --------------------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM vocab.daily_word('fr')$$), '0', 'NOTHING ASSIGNED: zero rows (the API turns this into 404, never an invented word)');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM vocab.daily_word('ht')$$), '0', 'nothing assigned in Creole either');
SELECT is(pg_temp.as_api(NULL, $$SELECT count(*) FROM vocab.daily_word('fr')$$), 'ERROR:42501', 'no verified actor: refused');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM vocab.daily_word('en')$$), 'ERROR:22023', 'unsupported locale: refused');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM vocab.daily_word(NULL)$$), 'ERROR:22023', 'missing locale: refused');

-- ---- today = word-two (French only); tomorrow = word-one (French + Creole) ---------------
INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via)
VALUES (pg_temp.today(), 'fr', 'f1000000-0000-4000-8000-000000000002', pg_temp.id('two_fr1'), 'auto');
INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via)
VALUES (pg_temp.today() + 1, 'fr', 'f1000000-0000-4000-8000-000000000001', pg_temp.id('one_fr1'), 'auto');
INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via)
VALUES (pg_temp.today() + 1, 'ht', 'f1000000-0000-4000-8000-000000000001', pg_temp.id('one_ht1'), 'auto');

SELECT is(pg_temp.as_api(:A::uuid, $$SELECT term || '|' || locale || '|' || requested_locale || '|' || is_fallback_locale FROM vocab.daily_word('fr')$$),
    'DEUX-FR|fr|fr|false', 'French request: today''s French word');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT term || '|' || locale || '|' || requested_locale || '|' || is_fallback_locale FROM vocab.daily_word('ht')$$),
    'DEUX-FR|fr|ht|true', 'MISSING TRANSLATION: a Creole request gets the French word, flagged as a fallback');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT haiti_date::text FROM vocab.daily_word('fr')$$), pg_temp.today()::text, 'haiti_date is the server''s Haiti date');
SELECT is((SELECT valid_until FROM vocab.daily_word_at('fr', now())), vocab.haiti_day_start(pg_temp.today() + 1), 'valid_until is the next Haiti midnight');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT word_revision_id::text || '|' || word_id::text || '|' || revision FROM vocab.daily_word('fr')$$),
    pg_temp.id('two_fr1')::text || '|f1000000-0000-4000-8000-000000000002|1', 'the ids identify the exact revision served');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT pronunciation || '|' || part_of_speech || '|' || definition || '|' || example || '|' || gloss FROM vocab.daily_word('fr')$$),
    'pro-DEUX-FR|noun|Définition synthétique : DEUX-FR|Exemple synthétique : DEUX-FR|glose DEUX-FR', 'all word fields are returned');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT COALESCE(audio_asset_id::text, 'none') FROM vocab.daily_word('fr')$$), 'none', 'no recording: audio is null');
SELECT is((SELECT string_agg(k, ',' ORDER BY k) FROM vocab.daily_word_at('fr', now()) d, jsonb_object_keys(to_jsonb(d)) k),
    'audio_asset_id,audio_byte_size,audio_duration_ms,audio_mime_type,audio_sha256,definition,example,gloss,haiti_date,is_fallback_locale,locale,part_of_speech,pronunciation,requested_locale,revision,term,valid_until,word_id,word_revision_id',
    'the row exposes exactly these columns: no author, reviewer, source, licence or storage key');

-- ---- cross-account: same word, nothing personal, nothing written ------------------------------
CREATE TEMP TABLE counts_before AS
SELECT (SELECT count(*) FROM vocab.daily_assignments) + (SELECT count(*) FROM vocab.word_revisions) + (SELECT count(*) FROM vocab.words)
     + (SELECT count(*) FROM vocab.reviews) + (SELECT count(*) FROM vocab.audio_assets) + (SELECT count(*) FROM vocab.sources) AS vocab_rows,
       (SELECT count(*) FROM app.audit_events) AS audit_rows;
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT md5(d::text) FROM vocab.daily_word('fr') d$$),
          pg_temp.as_api(:B::uuid, $$SELECT md5(d::text) FROM vocab.daily_word('fr') d$$),
    'CROSS-ACCOUNT: student A and student B receive the identical row');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT md5(d::text) FROM vocab.daily_word('ht') d$$),
          pg_temp.as_api(:EDITOR::uuid, $$SELECT md5(d::text) FROM vocab.daily_word('ht') d$$),
    'a staff account reading as a learner receives the same row as a student');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT position('a0000000' in d::text) FROM vocab.daily_word('fr') d$$), '0', 'the row contains no account identifier at all');
SELECT is((SELECT (SELECT count(*) FROM vocab.daily_assignments) + (SELECT count(*) FROM vocab.word_revisions) + (SELECT count(*) FROM vocab.words)
                + (SELECT count(*) FROM vocab.reviews) + (SELECT count(*) FROM vocab.audio_assets) + (SELECT count(*) FROM vocab.sources)),
          (SELECT vocab_rows FROM counts_before), 'READING WRITES NOTHING in vocab (no view/history row)');
SELECT is((SELECT count(*) FROM app.audit_events), (SELECT audit_rows FROM counts_before), 'reading writes no audit row');
SELECT is((SELECT (SELECT count(*) FROM app.practice_attempts) + (SELECT count(*) FROM app.lesson_progress) + (SELECT count(*) FROM app.account_change_feed)
                + (SELECT count(*) FROM app.sync_receipts) + (SELECT count(*) FROM app.account_sync_state))::int, 0,
    'reading creates no progress, no mastery, no change-feed entry, no sync state');

-- ---- FUTURE content is invisible ---------------------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT position('UN-' in d::text) FROM vocab.daily_word('fr') d$$), '0', 'FUTURE: tomorrow''s word does not appear in today''s answer');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT position('UN-' in d::text) FROM vocab.daily_word('ht') d$$), '0', 'FUTURE: nor in the Creole answer (which falls back to TODAY''s French, not to tomorrow''s Creole)');
SELECT is((SELECT term FROM vocab.daily_word_at('fr', vocab.haiti_day_start(pg_temp.today() + 1))), 'UN-FR',
    '(owner-only clock seam: tomorrow''s word is recorded and becomes visible exactly at Haiti midnight)');
SELECT is((SELECT term FROM vocab.daily_word_at('fr', vocab.haiti_day_start(pg_temp.today() + 1) - interval '1 second')), 'DEUX-FR',
    '(one second before midnight it is still today''s word)');

-- ---- DRAFT / IN-REVIEW / REJECTED content is invisible; EDIT after assignment ------------------------
SELECT pg_temp.revision('two_fr_draft', 'f1000000-0000-4000-8000-000000000002', 'fr', 'BROUILLON', 'e1000000-0000-4000-8000-000000000004', 'draft');
SELECT pg_temp.revision('two_fr_in_review', 'f1000000-0000-4000-8000-000000000002', 'fr', 'EN-RELECTURE', 'e1000000-0000-4000-8000-000000000004', 'in_review');
SELECT pg_temp.revision('two_fr_rejected', 'f1000000-0000-4000-8000-000000000002', 'fr', 'REJETE', 'e1000000-0000-4000-8000-000000000004', 'rejected');
SELECT pg_temp.revision('two_ht_draft', 'f1000000-0000-4000-8000-000000000002', 'ht', 'BOUYON', 'e1000000-0000-4000-8000-000000000004', 'draft');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT term FROM vocab.daily_word('fr')$$), 'DEUX-FR', 'DRAFT / IN-REVIEW / REJECTED revisions of today''s word change nothing');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT term || '|' || is_fallback_locale FROM vocab.daily_word('ht')$$), 'DEUX-FR|true', 'a DRAFT translation is not served: still the French fallback');
SELECT pg_temp.revision('two_fr5', 'f1000000-0000-4000-8000-000000000002', 'fr', 'DEUX-FR-CORRIGE', 'e1000000-0000-4000-8000-000000000004');
SELECT pg_temp.revision('two_ht2', 'f1000000-0000-4000-8000-000000000002', 'ht', 'DE-HT', 'e1000000-0000-4000-8000-000000000004');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT term || '|' || word_revision_id FROM vocab.daily_word('fr')$$), 'DEUX-FR|' || pg_temp.id('two_fr1'),
    'EDITED AFTER ASSIGNMENT: a newer APPROVED revision does not change today''s word');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT term || '|' || is_fallback_locale FROM vocab.daily_word('ht')$$), 'DEUX-FR|true',
    'a translation approved during the day does not change today''s answer either');

-- ---- recording metadata; rights withdrawn ---------------------------------------------------------
CREATE FUNCTION pg_temp.tomorrow(p_locale text) RETURNS SETOF record LANGUAGE sql AS $fn$
    SELECT term, locale, is_fallback_locale, audio_mime_type, audio_byte_size, audio_duration_ms, audio_sha256
    FROM vocab.daily_word_at(p_locale, vocab.haiti_day_start(vocab.haiti_date(clock_timestamp()) + 1) + interval '12 hours') $fn$;
SELECT is((SELECT t::text FROM pg_temp.tomorrow('fr') AS t(term text, locale text, fb boolean, mime text, bytes integer, ms integer, sha text)),
    '(UN-FR,fr,f,audio/mp4,20480,1200,' || encode(sha256('synthetic test bytes'), 'hex') || ')',
    'a recording is described by type, size, duration and checksum');
SELECT is((SELECT t::text FROM pg_temp.tomorrow('ht') AS t(term text, locale text, fb boolean, mime text, bytes integer, ms integer, sha text)),
    '(UN-HT,ht,f,,,,)', 'the Creole revision is served in Creole, and has no recording of its own');
UPDATE vocab.sources SET rights_status = 'restricted' WHERE id = 'e1000000-0000-4000-8000-000000000003';
SELECT is((SELECT t::text FROM pg_temp.tomorrow('fr') AS t(term text, locale text, fb boolean, mime text, bytes integer, ms integer, sha text)),
    '(UN-FR,fr,f,,,,)', 'RIGHTS: a recording whose rights were withdrawn disappears; the word stays');
UPDATE vocab.sources SET rights_status = 'blocked' WHERE id = 'e1000000-0000-4000-8000-000000000002';
SELECT is((SELECT t::text FROM pg_temp.tomorrow('ht') AS t(term text, locale text, fb boolean, mime text, bytes integer, ms integer, sha text)),
    '(UN-FR,fr,t,,,,)', 'RIGHTS: a translation whose rights were withdrawn falls back to French');
UPDATE vocab.sources SET rights_status = 'blocked' WHERE id = 'e1000000-0000-4000-8000-000000000004';
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM vocab.daily_word('fr')$$), '0', 'RIGHTS: today''s word disappears for learners when its rights are withdrawn');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM vocab.daily_word('ht')$$), '0', 'and no other word is substituted');
SELECT is((SELECT word_revision_id FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today()), pg_temp.id('two_fr1'),
    'the schedule of record still says what today''s word was');
UPDATE vocab.sources SET rights_status = 'cleared' WHERE id = 'e1000000-0000-4000-8000-000000000004';
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT term FROM vocab.daily_word('fr')$$), 'DEUX-FR', 'rights cleared again: the same word is back');

SELECT * FROM finish();
ROLLBACK;
