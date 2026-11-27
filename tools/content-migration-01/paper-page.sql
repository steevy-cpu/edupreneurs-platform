-- Private paper metadata. Query only educational fields.
SELECT id,title,grade_level,track,series,subject,subject_slug,year,session,version,version_number,
       exam_type,duration_minutes,pdf_url,total_points,total_exercises,is_model_exam,encode(sha256(convert_to(coalesce(reference_texts::text,''),'UTF8')),'hex') AS reference_texts_sha256
FROM public.official_exams WHERE ($1::uuid IS NULL OR id>$1::uuid) ORDER BY id LIMIT 50;
