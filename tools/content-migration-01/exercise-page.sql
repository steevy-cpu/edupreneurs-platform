-- Bind $1 to NULL or the last exercise UUID. Output has no keys or answer text.
SELECT x.id,x.exam_id,x.exercise_number,x.points,x.exercise_type,
       coalesce(btrim(x.question_text),'')<>'' AS has_prompt,
       (coalesce(btrim(x.correct_answer),'')<>'' OR x.answer_json IS NOT NULL) AS has_answer,
       (coalesce(btrim(x.explanation),'')<>'' OR x.explanation_blocks IS NOT NULL) AS has_explanation,
       encode(sha256(convert_to(jsonb_build_array(x.question_text,x.prompt_blocks,x.options,x.options_json,x.correct_answer,
         x.answer_json,x.explanation,x.explanation_blocks,x.concept,x.concept_tags,x.difficulty)::text,'UTF8')),'hex') AS private_content_fingerprint
FROM public.exam_exercises x WHERE ($1::uuid IS NULL OR x.id>$1::uuid)
ORDER BY x.id LIMIT 100;
