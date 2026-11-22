-- Mon Edupreneur 2.0 — deterministic SYNTHETIC seed data (local development only)
--
-- Loaded automatically by `supabase db reset` after the migrations.
-- Everything here is invented for testing: no real student, staff member,
-- school, or third-party text. Emails use the reserved `.test` domain.
--
-- NO PASSWORDS: the four accounts are created without a usable password.
-- scripts/dev_token.py (and the test-suite) assigns a fresh random password
-- through the LOCAL Auth admin API when a login is needed. Nothing secret is
-- stored in this file.
--
-- The content is seeded THROUGH the real editorial workflow
-- (draft -> review -> approve -> pack -> activate -> current pointer), so the
-- integrity triggers validate the seed itself. Nothing is bypassed.
--
-- Fixed identifiers (also used by tests and docs):
--   student A   a0000000-0000-4000-8000-000000000001   student.a@edupreneur.test
--   student B   a0000000-0000-4000-8000-000000000002   student.b@edupreneur.test
--   editor      a0000000-0000-4000-8000-000000000003   editor@edupreneur.test
--   reviewer    a0000000-0000-4000-8000-000000000004   reviewer@edupreneur.test
--   lesson      b0000000-0000-4000-8000-000000000005
--   revision fr c0000000-0000-4000-8000-000000000001   questions d0000000-0000-4000-8000-00000000010{1..5}
--   revision ht c0000000-0000-4000-8000-000000000002   questions d0000000-0000-4000-8000-00000000020{1..5}

-- ---------------------------------------------------------------------------
-- Auth accounts (Supabase Auth owns auth.users; we only add synthetic rows)
-- ---------------------------------------------------------------------------
INSERT INTO auth.users (
    instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
    raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
    confirmation_token, recovery_token, email_change_token_new, email_change)
SELECT
    '00000000-0000-0000-0000-000000000000', u.id, 'authenticated', 'authenticated', u.email,
    '', -- no usable password; see header
    now(), '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb, now(), now(),
    '', '', '', ''
FROM (VALUES
    ('a0000000-0000-4000-8000-000000000001'::uuid, 'student.a@edupreneur.test'),
    ('a0000000-0000-4000-8000-000000000002'::uuid, 'student.b@edupreneur.test'),
    ('a0000000-0000-4000-8000-000000000003'::uuid, 'editor@edupreneur.test'),
    ('a0000000-0000-4000-8000-000000000004'::uuid, 'reviewer@edupreneur.test')
) AS u(id, email);

INSERT INTO auth.identities (
    provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
SELECT u.id::text, u.id,
       jsonb_build_object('sub', u.id::text, 'email', u.email, 'email_verified', true),
       'email', now(), now(), now()
FROM auth.users u
WHERE u.email LIKE '%@edupreneur.test';

-- ---------------------------------------------------------------------------
-- Staff roles: the editor writes, a DIFFERENT person reviews
-- ---------------------------------------------------------------------------
INSERT INTO app.staff_roles (user_id, role) VALUES
    ('a0000000-0000-4000-8000-000000000003', 'editor'),
    ('a0000000-0000-4000-8000-000000000004', 'reviewer');

-- ---------------------------------------------------------------------------
-- Curriculum: 9AF Mathematics -> one unit -> one lesson
-- ---------------------------------------------------------------------------
INSERT INTO app.grades (id, code, sort_order, labels) VALUES
    ('b0000000-0000-4000-8000-000000000001', '9AF', 3,
     '{"fr": "9e année fondamentale", "ht": "9èm ane fondamantal"}');

INSERT INTO app.subjects (id, slug, labels) VALUES
    ('b0000000-0000-4000-8000-000000000002', 'mathematiques',
     '{"fr": "Mathématiques", "ht": "Matematik"}');

INSERT INTO app.courses (id, grade_id, subject_id, slug, titles, visibility) VALUES
    ('b0000000-0000-4000-8000-000000000003',
     'b0000000-0000-4000-8000-000000000001',
     'b0000000-0000-4000-8000-000000000002',
     'mathematiques-9af',
     '{"fr": "Mathématiques 9e AF", "ht": "Matematik 9èm AF"}',
     'published');

INSERT INTO app.units (id, course_id, slug, position, titles) VALUES
    ('b0000000-0000-4000-8000-000000000004',
     'b0000000-0000-4000-8000-000000000003',
     'equations-premier-degre', 1,
     '{"fr": "Équations du premier degré", "ht": "Ekwasyon premye degre"}');

INSERT INTO app.lessons (id, unit_id, slug, position) VALUES
    ('b0000000-0000-4000-8000-000000000005',
     'b0000000-0000-4000-8000-000000000004',
     'resoudre-une-equation-simple', 1);

-- Learner profiles for the two students (the API would also create these on
-- first contact; seeding them gives the tests a known grade and locale).
INSERT INTO app.learner_profiles (user_id, grade_id, preferred_locale, display_name) VALUES
    ('a0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000001', 'fr', 'Élève A (synthétique)'),
    ('a0000000-0000-4000-8000-000000000002', 'b0000000-0000-4000-8000-000000000001', 'ht', 'Elèv B (sentetik)');

-- ---------------------------------------------------------------------------
-- Lesson revisions: French and Haitian Creole are independent revisions
-- (blocks follow packages/contracts/content/lesson-blocks.schema.json)
-- ---------------------------------------------------------------------------
INSERT INTO app.lesson_revisions (id, lesson_id, revision, locale, title, blocks, created_by) VALUES
('c0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000005', 1, 'fr',
 'Résoudre une équation simple',
 $json$[
  {"key": "intro", "type": "paragraph",
   "text": "Une équation est une égalité qui contient un nombre inconnu, souvent noté x. Résoudre l'équation, c'est trouver la valeur de x qui rend l'égalité vraie."},
  {"key": "regle-titre", "type": "heading", "text": "La règle de la balance"},
  {"key": "regle", "type": "paragraph",
   "text": "Une équation est comme une balance en équilibre. Si l'on fait la même opération des deux côtés, la balance reste en équilibre."},
  {"key": "exemple-1", "type": "example", "title": "Exemple",
   "steps": ["x + 3 = 10", "On retire 3 de chaque côté : x + 3 − 3 = 10 − 3", "x = 7"]},
  {"key": "exemple-2", "type": "example", "title": "Avec une multiplication",
   "steps": ["4x = 20", "On divise chaque côté par 4 : 4x ÷ 4 = 20 ÷ 4", "x = 5"]},
  {"key": "astuce", "type": "callout", "tone": "tip",
   "text": "Vérifie toujours ta réponse : remplace x par la valeur trouvée et regarde si l'égalité est vraie."}
 ]$json$::jsonb,
 'a0000000-0000-4000-8000-000000000003'),
('c0000000-0000-4000-8000-000000000002', 'b0000000-0000-4000-8000-000000000005', 1, 'ht',
 'Rezoud yon ekwasyon senp',
 $json$[
  {"key": "intro", "type": "paragraph",
   "text": "Yon ekwasyon se yon egalite ki gen yon nonb nou pa konnen, nou souvan rele l x. Rezoud ekwasyon an vle di jwenn valè x ki fè egalite a vre."},
  {"key": "regle-titre", "type": "heading", "text": "Règ balans lan"},
  {"key": "regle", "type": "paragraph",
   "text": "Yon ekwasyon tankou yon balans ki an ekilib. Si nou fè menm operasyon an nan de bò yo, balans lan rete an ekilib."},
  {"key": "exemple-1", "type": "example", "title": "Egzanp",
   "steps": ["x + 3 = 10", "Nou retire 3 nan chak bò: x + 3 − 3 = 10 − 3", "x = 7"]},
  {"key": "exemple-2", "type": "example", "title": "Ak yon miltiplikasyon",
   "steps": ["4x = 20", "Nou divize chak bò pa 4: 4x ÷ 4 = 20 ÷ 4", "x = 5"]},
  {"key": "astuce", "type": "callout", "tone": "tip",
   "text": "Toujou verifye repons ou: ranplase x ak valè ou jwenn nan epi gade si egalite a vre."}
 ]$json$::jsonb,
 'a0000000-0000-4000-8000-000000000003');

-- ---------------------------------------------------------------------------
-- Five multiple-choice practice questions per locale
-- (shape: packages/contracts/content/question-mcq.schema.json)
-- ---------------------------------------------------------------------------
INSERT INTO app.question_revisions
    (id, lesson_revision_id, question_key, position, kind, prompt, response_spec, answer_key, explanation)
VALUES
('d0000000-0000-4000-8000-000000000101', 'c0000000-0000-4000-8000-000000000001', 'addition', 1, 'mcq',
 '{"text": "Résous : x + 5 = 12"}',
 '{"choices": [{"id": "a", "text": "x = 5"}, {"id": "b", "text": "x = 7"}, {"id": "c", "text": "x = 12"}, {"id": "d", "text": "x = 17"}]}',
 '{"correct_choice_id": "b"}',
 '{"text": "On retire 5 de chaque côté : x = 12 − 5 = 7."}'),
('d0000000-0000-4000-8000-000000000102', 'c0000000-0000-4000-8000-000000000001', 'multiplication', 2, 'mcq',
 '{"text": "Résous : 3x = 18"}',
 '{"choices": [{"id": "a", "text": "x = 6"}, {"id": "b", "text": "x = 15"}, {"id": "c", "text": "x = 21"}, {"id": "d", "text": "x = 54"}]}',
 '{"correct_choice_id": "a"}',
 '{"text": "On divise chaque côté par 3 : x = 18 ÷ 3 = 6."}'),
('d0000000-0000-4000-8000-000000000103', 'c0000000-0000-4000-8000-000000000001', 'deux-etapes', 3, 'mcq',
 '{"text": "Résous : 2x + 3 = 11"}',
 '{"choices": [{"id": "a", "text": "x = 3"}, {"id": "b", "text": "x = 7"}, {"id": "c", "text": "x = 4"}, {"id": "d", "text": "x = 8"}]}',
 '{"correct_choice_id": "c"}',
 '{"text": "On retire 3 : 2x = 8. Puis on divise par 2 : x = 4."}'),
('d0000000-0000-4000-8000-000000000104', 'c0000000-0000-4000-8000-000000000001', 'soustraction', 4, 'mcq',
 '{"text": "Résous : x − 4 = 9"}',
 '{"choices": [{"id": "a", "text": "x = 5"}, {"id": "b", "text": "x = 36"}, {"id": "c", "text": "x = 9"}, {"id": "d", "text": "x = 13"}]}',
 '{"correct_choice_id": "d"}',
 '{"text": "On ajoute 4 de chaque côté : x = 9 + 4 = 13."}'),
('d0000000-0000-4000-8000-000000000105', 'c0000000-0000-4000-8000-000000000001', 'egal-zero', 5, 'mcq',
 '{"text": "Résous : 5x − 10 = 0"}',
 '{"choices": [{"id": "a", "text": "x = 0"}, {"id": "b", "text": "x = 2"}, {"id": "c", "text": "x = 5"}, {"id": "d", "text": "x = 50"}]}',
 '{"correct_choice_id": "b"}',
 '{"text": "On ajoute 10 : 5x = 10. Puis on divise par 5 : x = 2."}'),

('d0000000-0000-4000-8000-000000000201', 'c0000000-0000-4000-8000-000000000002', 'addition', 1, 'mcq',
 '{"text": "Rezoud: x + 5 = 12"}',
 '{"choices": [{"id": "a", "text": "x = 5"}, {"id": "b", "text": "x = 7"}, {"id": "c", "text": "x = 12"}, {"id": "d", "text": "x = 17"}]}',
 '{"correct_choice_id": "b"}',
 '{"text": "Nou retire 5 nan chak bò: x = 12 − 5 = 7."}'),
('d0000000-0000-4000-8000-000000000202', 'c0000000-0000-4000-8000-000000000002', 'multiplication', 2, 'mcq',
 '{"text": "Rezoud: 3x = 18"}',
 '{"choices": [{"id": "a", "text": "x = 6"}, {"id": "b", "text": "x = 15"}, {"id": "c", "text": "x = 21"}, {"id": "d", "text": "x = 54"}]}',
 '{"correct_choice_id": "a"}',
 '{"text": "Nou divize chak bò pa 3: x = 18 ÷ 3 = 6."}'),
('d0000000-0000-4000-8000-000000000203', 'c0000000-0000-4000-8000-000000000002', 'deux-etapes', 3, 'mcq',
 '{"text": "Rezoud: 2x + 3 = 11"}',
 '{"choices": [{"id": "a", "text": "x = 3"}, {"id": "b", "text": "x = 7"}, {"id": "c", "text": "x = 4"}, {"id": "d", "text": "x = 8"}]}',
 '{"correct_choice_id": "c"}',
 '{"text": "Nou retire 3: 2x = 8. Apre sa nou divize pa 2: x = 4."}'),
('d0000000-0000-4000-8000-000000000204', 'c0000000-0000-4000-8000-000000000002', 'soustraction', 4, 'mcq',
 '{"text": "Rezoud: x − 4 = 9"}',
 '{"choices": [{"id": "a", "text": "x = 5"}, {"id": "b", "text": "x = 36"}, {"id": "c", "text": "x = 9"}, {"id": "d", "text": "x = 13"}]}',
 '{"correct_choice_id": "d"}',
 '{"text": "Nou ajoute 4 nan chak bò: x = 9 + 4 = 13."}'),
('d0000000-0000-4000-8000-000000000205', 'c0000000-0000-4000-8000-000000000002', 'egal-zero', 5, 'mcq',
 '{"text": "Rezoud: 5x − 10 = 0"}',
 '{"choices": [{"id": "a", "text": "x = 0"}, {"id": "b", "text": "x = 2"}, {"id": "c", "text": "x = 5"}, {"id": "d", "text": "x = 50"}]}',
 '{"correct_choice_id": "b"}',
 '{"text": "Nou ajoute 10: 5x = 10. Apre sa nou divize pa 5: x = 2."}');

-- ---------------------------------------------------------------------------
-- Provenance: one original, rights-cleared source
-- ---------------------------------------------------------------------------
INSERT INTO app.content_sources (id, source_title, source_uri, rights_status, rights_notes, verified_at) VALUES
    ('e0000000-0000-4000-8000-000000000001',
     'Original synthetic fixture written for Mon Edupreneur 2.0 development',
     NULL, 'cleared',
     'Invented test content; not derived from any textbook, exam or third-party material.',
     now());

INSERT INTO app.lesson_revision_sources (lesson_revision_id, source_id) VALUES
    ('c0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000001'),
    ('c0000000-0000-4000-8000-000000000002', 'e0000000-0000-4000-8000-000000000001');

-- ---------------------------------------------------------------------------
-- Editorial workflow: submit -> independent review -> approve
-- ---------------------------------------------------------------------------
UPDATE app.lesson_revisions SET status = 'in_review'
 WHERE id IN ('c0000000-0000-4000-8000-000000000001', 'c0000000-0000-4000-8000-000000000002');

INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict, notes) VALUES
    ('c0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000004', 'approved', 'Synthetic fixture review (fr).'),
    ('c0000000-0000-4000-8000-000000000002', 'a0000000-0000-4000-8000-000000000004', 'approved', 'Synthetic fixture review (ht).');

UPDATE app.lesson_revisions
   SET status = 'approved', approved_by = 'a0000000-0000-4000-8000-000000000004', approved_at = now()
 WHERE id IN ('c0000000-0000-4000-8000-000000000001', 'c0000000-0000-4000-8000-000000000002');

-- ---------------------------------------------------------------------------
-- Publication: one pack per locale, activated and made current
-- (The manifest digest is a labelled placeholder: no object storage exists yet.)
-- ---------------------------------------------------------------------------
INSERT INTO app.pack_releases (id, pack_key, revision, locale, created_by) VALUES
    ('f0000000-0000-4000-8000-000000000001', 'math-9af', 1, 'fr', 'a0000000-0000-4000-8000-000000000003'),
    ('f0000000-0000-4000-8000-000000000002', 'math-9af', 1, 'ht', 'a0000000-0000-4000-8000-000000000003');

INSERT INTO app.pack_items (pack_release_id, lesson_revision_id, position) VALUES
    ('f0000000-0000-4000-8000-000000000001', 'c0000000-0000-4000-8000-000000000001', 1),
    ('f0000000-0000-4000-8000-000000000002', 'c0000000-0000-4000-8000-000000000002', 1);

UPDATE app.pack_releases
   SET status = 'ready',
       manifest_object_key = 'synthetic/packs/' || pack_key || '/' || locale || '/' || revision || '/manifest.json',
       manifest_sha256 = sha256(convert_to('synthetic-fixture-manifest:' || pack_key || ':' || locale || ':' || revision, 'UTF8')),
       compressed_bytes = 4096
 WHERE id IN ('f0000000-0000-4000-8000-000000000001', 'f0000000-0000-4000-8000-000000000002');

UPDATE app.pack_releases SET status = 'active'
 WHERE id IN ('f0000000-0000-4000-8000-000000000001', 'f0000000-0000-4000-8000-000000000002');

INSERT INTO app.pack_current (pack_key, locale, release_id) VALUES
    ('math-9af', 'fr', 'f0000000-0000-4000-8000-000000000001'),
    ('math-9af', 'ht', 'f0000000-0000-4000-8000-000000000002');
