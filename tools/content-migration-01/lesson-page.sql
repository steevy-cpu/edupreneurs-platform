-- Bind $1 to NULL on the first page, then the last UUID. Stay on a read-only consistent snapshot.
-- These bodies are PRIVATE. Do not log the result or copy it into Git or CI.
SELECT l.id,l.subject_id,l.grade_level,l.title,l.slug,l.order_index,l.updated_at,l.is_published,l.workflow_status,
       l.objectif,l.introduction,l.contenu,l.exemples_exercices,l.activites_interactives,l.quiz_final,
       l.reviewed_by IS NOT NULL AS has_source_reviewer,l.scheduled_publish_at,l.quiz_count,l.activities_count,
       l.needs_quiz_regeneration,l.needs_activities_regeneration,l.last_content_validated_at,l.last_activities_validated_at,
       encode(sha256(convert_to(coalesce(l.validation_details_json::text,''),'UTF8')),'hex') AS validation_fingerprint,
       l.mois,l."references",l.youtube_url,l.suggested_videos,l.audio_objectif_url,l.audio_introduction_url,
       l.audio_contenu_url,l.audio_exemples_url,s.grade_level AS subject_grade,s.series AS subject_series, v.source_revision
FROM public.lessons l JOIN public.subjects s ON s.id=l.subject_id
LEFT JOIN LATERAL (
  SELECT CASE WHEN count(*)=1 THEN max(version_number) END AS source_revision
  FROM public.lesson_versions WHERE lesson_id=l.id AND is_current
) v ON true
WHERE ($1::uuid IS NULL OR l.id>$1::uuid)
ORDER BY l.id LIMIT 50;
