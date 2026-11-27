-- Conservative candidate path matches only. Never fetch external URLs or infer hash/rights.
WITH refs AS (
 SELECT 'lesson_body_img' kind,'lesson-images' bucket,(m)[1] link FROM public.lessons CROSS JOIN LATERAL regexp_matches(contenu,'<img[^>]*[[:space:]]src="([^"]+)"','gi') m
 UNION ALL SELECT 'lesson_audio','lesson-audio',v FROM public.lessons CROSS JOIN LATERAL unnest(ARRAY[audio_objectif_url,audio_introduction_url,audio_contenu_url,audio_exemples_url]) v WHERE nullif(btrim(v),'') IS NOT NULL
 UNION ALL SELECT 'paper_pdf','exam-documents',pdf_url FROM public.official_exams WHERE nullif(btrim(pdf_url),'') IS NOT NULL
 UNION ALL SELECT 'ebook_file','ebook-files',file_url FROM public.ebooks WHERE is_published
 UNION ALL SELECT 'ebook_cover','ebook-covers',cover_url FROM public.ebooks WHERE is_published
), normalized AS (
 SELECT *,substring(split_part(split_part(link,'?',1),'#',1) FROM '/storage/v1/object/public/[^/]+/(.+)$') path
 FROM refs
)
SELECT kind, count(*) references_seen,count(*) FILTER(WHERE path IS NOT NULL AND strpos(link,'/storage/v1/object/public/'||bucket||'/')>0 AND EXISTS(
 SELECT FROM storage.objects o WHERE o.bucket_id=normalized.bucket AND o.name=normalized.path)) literal_path_matches
FROM normalized GROUP BY kind ORDER BY kind;
