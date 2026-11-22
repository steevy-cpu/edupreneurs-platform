# apps/ — reserved, intentionally empty

Client applications will live here. **Nothing is scaffolded yet** (out of scope for Foundation-01).

| Folder (future) | What it will be |
|---|---|
| `apps/student-native/` | React Native student app: UI, local SQLite, offline outbox |
| `apps/lite-web/` | Tiny HTML-first experience for older mobile browsers |
| `apps/staff-web/` | Editor / reviewer dashboard |

They will talk to `services/api` using the contract in `packages/contracts/openapi.json`,
and to Supabase Auth for sign-in only. They never query the database directly.
