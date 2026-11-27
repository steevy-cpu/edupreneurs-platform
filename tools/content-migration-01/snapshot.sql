-- Execute on a read-only content-only role. Collect aggregates, never lesson text.
SELECT s.grade_level,s.series,count(DISTINCT s.id) subjects,count(l.id) lessons,
       count(l.id) FILTER (WHERE l.is_published AND l.workflow_status='published') published,
       sum(l.quiz_count) cached
FROM public.subjects s LEFT JOIN public.lessons l ON l.subject_id=s.id
GROUP BY 1,2 ORDER BY 1,2;

WITH counted AS (
  SELECT id,quiz_count,regexp_count(quiz_final,'<div[[:space:]]+class="quiz-question"[^>]*>',1,'i') AS markers
  FROM public.lessons
)
SELECT sum(markers) candidate_markers,count(*) FILTER(WHERE markers IS DISTINCT FROM quiz_count) differences
FROM counted;

SELECT e.grade_level,e.series,e.track,count(*) AS papers,
  count(*) FILTER (WHERE duration_minutes IS NULL OR duration_minutes NOT BETWEEN 5 AND 300) AS unusable_duration,
  count(*) FILTER (WHERE NOT EXISTS (
    SELECT FROM public.subjects s WHERE s.grade_level=e.grade_level AND s.series IS NOT DISTINCT FROM e.series AND s.slug=e.subject_slug
  )) AS missing_exact_subject FROM public.official_exams e GROUP BY 1,2,3 ORDER BY 1,2,3;
