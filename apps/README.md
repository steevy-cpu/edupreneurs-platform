# apps/ — client applications

| Folder | Status | What it is |
|---|---|---|
| `apps/student-native/` | **Mobile-01 implemented** (logic tested; not yet run on a device) | Edupreneurs student app, React Native (Expo): sign-in, saved lessons, offline practice, sync |
| `apps/lite-web/` | reserved, not started | Tiny HTML-first experience for older mobile browsers |
| `apps/staff-web/` | reserved, not started | Editor / reviewer dashboard |

Clients talk to `services/api` using the contract in `packages/contracts/openapi.json`,
and to Supabase Auth for sign-in only. They never query the database directly.
