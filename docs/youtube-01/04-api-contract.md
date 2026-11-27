# 4. API contract

Machine-readable contract: `packages/contracts/openapi.json` (schemas `LessonVideosResponse`, `VideoCard`); generated mobile types: `apps/student-native/src/core/api/schema.d.ts`. The change is strictly additive: no existing path or schema changed.

## `GET /v1/lessons/{lesson_id}/videos?locale=fr|ht`

Bearer token required. Read-only. Never contacts YouTube and never uses a provider key.

| Status | When |
|---|---|
| 200 | Lesson is published in `locale`. `videos` may be empty |
| 401 | Missing or invalid token |
| 404 | Feature off (`EDU_VIDEOS_ENABLED=false`), or the lesson is unknown, inactive or not published in this language |
| 422 | Malformed id or unsupported locale |
| 503 | Database or auth key service unavailable |

```json
{
  "lesson_id": "b0000000-0000-4000-8000-000000000005",
  "locale": "fr",
  "requires_network": true,
  "videos": [
    {
      "link_id": "…uuid…",
      "provider": "youtube",
      "video_id": "okVideo0001",
      "title": "Titre tel que publié sur YouTube",
      "channel_title": "Nom de la chaîne",
      "channel_url": "https://www.youtube.com/channel/UC…",
      "duration_seconds": 300,
      "start_seconds": 42,
      "purpose": "explanation",
      "audio_language": "fr",
      "made_for_kids": false,
      "thumbnail_url": "https://i.ytimg.com/vi/okVideo0001/hqdefault.jpg",
      "embed_url": "https://www.youtube.com/embed/okVideo0001",
      "watch_url": "https://www.youtube.com/watch?v=okVideo0001&t=42s",
      "metadata_checked_at": "2026-11-26T12:00:00Z"
    }
  ]
}
```

Guarantees:

* Every URL is built by the server from a validated 11-character id (`edu_api/videos/ids.py`); stored text never becomes a URL.
* Only approved, presentable, freshly checked videos appear (row-level security; see `03-…`).
* No reviewer identity, note, staff reason, legacy reference or provider secret is in the response; the database role cannot even read those columns.
* The response is identical for every learner (lesson content, not personal data).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `EDU_VIDEOS_ENABLED` | `false` | Learner endpoint on/off |
| `EDU_YOUTUBE_API_KEY` | unset | Server-side key for the metadata refresh only; restrict it to the YouTube Data API v3 and this server |
| `EDU_YOUTUBE_LIVE_CALLS_AUTHORIZED` | `false` | Second switch; without it no provider call is made even if a key is set |

## Rollback

Set `EDU_VIDEOS_ENABLED=false` (immediate; the app hides video cards on 404). The migration is additive; the drop statement is in its header.
