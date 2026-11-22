# services/worker — reserved, intentionally empty

Future home of background workers (pack builder, content pipelines, and later
the Jude and lesson-generation agents). **Not implemented in Foundation-01.**

When it is built it must use its OWN database role with its own narrow grants —
never the student API's `edu_api` role, and never `postgres`/`service_role`.
The `app.background_jobs` table already exists for it; the student API has no access to that table.
