# Backend dependencies still required, and suggested Admin-02 sequence

## Backend still required (from Admin-00 doc 4 and what this prototype exposed)

| Need | Why the UI is blocked |
|---|---|
| **Staff identity, MFA (TOTP + recovery), sessions, step-up endpoint** | No real login exists; the role preview is a stand-in (AD-2) |
| `GET /v1/staff/metrics/{id}?from&to&group_by`, aggregate tables + worker, **server-side K-suppression** | All tiles read fixtures; M3, M8, M12, M18 need new queries; no worker is deployed |
| New events/sources: app opens (M4), downloads (M10, owner decision), online reads (M11), device sync (M13), exams (M14), Jude AI usage (M19), billing reconciliation (M20) | Honest unavailable states today |
| Catalogue tree read model, revision **diff**, pack build **preview**, asset upload | Tree, diff and manifest are computed client-side from fixtures |
| **Withdraw/takedown route** (L-B2-3) and **author ≠ publisher** rule in SQL | Shown in UI, not enforceable |
| Audit read API, support lookup, last-admin fix (S13), readiness script X-1 | Placeholders |
| `analyst`/`support` roles (owner approval + reviewed migration) | Shown as *proposed* |
| OpenAPI staff contract in `packages/contracts/openapi.json` | The adapter types are hand-written |

## Owner decisions still open
Value of K; whether analyst/support roles exist; audit retention; aggregate download/read counters; two-person threshold for money actions;
staff identity provider; SPA hosting; Creole content review.

## Suggested Admin-02 sequence
1. **Contract first:** agree the staff metrics and revision response shapes; generate a typed client; swap the mock adapter behind `AdminServices`
   (keep the fixture adapter for tests and demos).
2. **Staff auth + MFA (AD-2)** with an independent security review; replace the persona selector by the real session; keep a 403 test per role × route.
3. **Dashboard v1 (AD-4)** on aggregate tables: M1, M2, M3, M5–M8, M12, M15, M16, M18 — turn tiles from `fixture` to live one at a time.
4. **Content workflow (AD-3)** against real routes; add withdraw route, diff, pack preview; keep v1-only until format v2 is approved.
5. Admin & safety (AD-5): audit viewer, support lookup, ops view.
6. Later modules in Admin-00 order (Word of the Day/Gold, library, payments, Jude AI).
7. Add a CI job limited to `apps/admin-web/**` running `npm run verify` (proposal; not added in this PR).
