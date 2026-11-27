-- Read-only identity and hierarchy census. No learner or authorship fields.
WITH inventory AS (
SELECT 'subjects' AS source_table, id::text AS legacy_id, jsonb_build_array(id::text, grade_level, series, slug)::text AS metadata FROM public.subjects
UNION ALL
SELECT 'lessons' AS source_table, id::text AS legacy_id, jsonb_build_array(id::text, subject_id::text, grade_level, slug, updated_at::text, workflow_status)::text AS metadata FROM public.lessons
UNION ALL
SELECT 'lesson_versions' AS source_table, id::text AS legacy_id, jsonb_build_array(id::text, lesson_id::text, version_number::text, grade_level)::text AS metadata FROM public.lesson_versions
UNION ALL
SELECT 'official_exams' AS source_table, id::text AS legacy_id, jsonb_build_array(id::text, grade_level, series, track, subject_slug, year::text, version_number::text)::text AS metadata FROM public.official_exams
UNION ALL
SELECT 'exam_exercises' AS source_table, id::text AS legacy_id, jsonb_build_array(id::text, exam_id::text, exercise_number::text, exercise_type, points::text)::text AS metadata FROM public.exam_exercises
UNION ALL
SELECT 'lesson_videos' AS source_table, id::text AS legacy_id, jsonb_build_array(id::text, lesson_id::text, order_index::text)::text AS metadata FROM public.lesson_videos
UNION ALL
SELECT 'ebooks' AS source_table, id::text AS legacy_id, jsonb_build_array(id::text, language, is_published::text)::text AS metadata FROM public.ebooks
UNION ALL
SELECT 'storage.objects', id::text, jsonb_build_array(id,bucket_id,name,metadata->>'mimetype',metadata->>'size')::text FROM storage.objects WHERE bucket_id IN ('lesson-images','lesson-audio','exam-documents','ebook-files','ebook-covers')
), hashed AS (
  SELECT source_table, legacy_id, metadata, encode(sha256(convert_to('edupreneurs:legacy-v1/' || source_table || '/' || legacy_id, 'UTF8')),'hex') AS h FROM inventory
), mapped AS (
  SELECT *, (substr(h,1,12)||'8'||substr(h,14,3)||'8'||substr(h,18,15))::uuid AS native_id FROM hashed
)
SELECT source_table,count(*) AS rows,count(DISTINCT native_id) AS mapped_ids,
  encode(sha256(convert_to(string_agg(native_id::text || ':' || metadata, E'\n' ORDER BY legacy_id COLLATE "C"),'UTF8')),'hex') AS metadata_root
FROM mapped GROUP BY source_table ORDER BY source_table;
