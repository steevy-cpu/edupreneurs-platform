# Admin-01 — web dashboard prototype

Status: **draft, synthetic, not deployed.** Implements milestone **AD-1** of
[Admin-00](../architecture/admin-00/06-roadmap-and-ui-plan.md): shell, navigation, environment banner, role-aware menu, metric tiles with
definitions and freshness, fixture API only, no real URL.

| Doc | Content |
|---|---|
| [01-architecture.md](01-architecture.md) | Structure, data adapter, decisions, deviations from the Lovable prototype |
| [02-security.md](02-security.md) | What the browser contains, CSP, role-preview vs real authorization, what was not built |
| [03-testing-and-verification.md](03-testing-and-verification.md) | Exact commands, counts, what is and is not verified |
| [04-backend-dependencies-and-admin-02.md](04-backend-dependencies-and-admin-02.md) | Backend still required, suggested Admin-02 sequence |
| `screenshots/` | Real Chrome renders of the production build (desktop, tablet, narrow) |

## What you can do locally

`cd apps/admin-web && npm ci && npm run dev`, then open http://127.0.0.1:5174. Use the dashed **“Aperçu de rôle”** selector to switch
synthetic personas (not a login). Try: Chloé approves Anne's revision → David publishes it → Hélène cannot publish her own; the admin cannot
edit anyone's draft; the support role cannot even open Contenu.

## Scope kept

Only `apps/admin-web/` and `docs/admin-01/` changed. Nothing under `apps/student-native/`, `services/api/`, `supabase/`, no migration, no
database, no deployment, no hosted service, Lovable untouched.
