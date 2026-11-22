# packages/contracts — shared, machine-readable contracts

| File | What it defines | Kept honest by |
|---|---|---|
| `openapi.json` | Every API endpoint, request and response (OpenAPI 3.1). Generate TypeScript clients from this. | `make openapi` regenerates it; a test and CI fail if it is stale |
| `content/lesson-blocks.schema.json` | Shape of a lesson body (`lesson_revisions.blocks`) | Test validates the seeded lessons against it |
| `content/question-mcq.schema.json` | Shape of a multiple-choice question and its answer key | Test validates the seeded questions against it |

Sync operation payloads (`practice_answer`, `lesson_completed`) are described inside
`openapi.json` (`PracticeAnswerPayload`, `LessonCompletedPayload` are documented in
`docs/API_CONTRACT.md`; the envelope is `PushRequest`).
