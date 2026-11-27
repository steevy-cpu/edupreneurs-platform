-- Metadata-only eligibility. No correct answers or student tables are read out.
WITH mapped AS (
  SELECT e.grade_level, x.id, x.exam_id, x.exercise_number, x.points, x.exercise_type,
         CASE WHEN x.points IS NULL OR x.points NOT BETWEEN 0 AND 100 OR x.exercise_number IS NULL OR x.exercise_number < 1 THEN 'quarantined'
              WHEN NULLIF(btrim(x.question_text),'') IS NULL THEN 'pdf_only_or_insufficient'
              WHEN x.exercise_type IN ('open_ended','open-ended') THEN 'human_marked_or_self_review'
              ELSE 'quarantined' END AS mode
  FROM public.exam_exercises x JOIN public.official_exams e ON e.id=x.exam_id
)
SELECT grade_level, mode, count(*) AS n FROM mapped GROUP BY 1,2 ORDER BY 1,2;
