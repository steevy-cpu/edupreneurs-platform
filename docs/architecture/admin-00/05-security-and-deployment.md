# 5. Security and deployment

## 1. Architecture

```
Browser (admin SPA)  ──HTTPS──►  FastAPI /v1/staff/*  ──►  PostgreSQL (staff.* SECURITY DEFINER functions, own login, RLS)
  no secrets                       auth + MFA + role check        private schemas, never exposed to the browser
                                   audit write on every call      object storage via server-issued signed URLs
```
The SPA is static hosting on its own origin (`admin.…`) — **not** under the student API origin or the marketing site. CORS allows only that origin.

## 2. Authentication and sessions

* **Staff identities are distinct** from learner accounts (different Supabase project/role or at least an enforced `staff` claim + `staff_roles` row); a learner token never authorises a staff route and vice-versa.
* **MFA is mandatory** (TOTP; WebAuthn later) with single-use recovery codes. No MFA enrolled → no access to anything except enrolment.
* Short access tokens (≤ 15 min) in memory; refresh via an `HttpOnly; Secure; SameSite=Strict` cookie scoped to the admin API path; idle timeout 30 min, absolute 12 h **(proposals)**.
* **Step-up** (MFA within 5 min) for: release/rollback/withdraw, role grants, entitlement grants/revokes, feature-flag changes, policy changes, break-glass learner access.
* **Safe recovery:** lost MFA → admin-assisted reset requiring a **second admin** and a cooling-off notification to the user's other channel; the sole admin's recovery uses pre-generated offline codes held by the owner. Every step audited.
* Brute-force controls: per-identity and per-IP limits on the staff login only (the learner limiter stays off until NAT finding L-4 is solved — different system).

## 3. Authorisation

Role check in FastAPI **and** inside the `staff.*` database functions (defence in depth, as built in PR #4). Separation-of-duties rules in doc 2 are enforced in SQL, not in the UI. Deny by default: a route without a role row in doc 2 does not ship.

## 4. Web-specific protections

Strict CSP (no inline script, no `unsafe-eval`, only own origin + the API), `frame-ancestors 'none'`, `Referrer-Policy: no-referrer`, SRI for any third-party script (prefer none), dependency lockfile + audit in CI, no `dangerouslySetInnerHTML`, all user/staff text rendered as plain text, CSRF protection for cookie-authenticated refresh, no tokens in URLs or `localStorage`, download of generated files via signed URLs with `Content-Disposition: attachment`.

## 5. Audit

Every mutation writes an `app.audit_events` row **from the server** (the prototype wrote from the browser — never again): actor, role, action, target, request id, outcome, reason. Reads of individual learner data are audited too. The audit log is append-only (existing trigger design) and readable by admins; actors read their own. Retention is an owner decision.

## 6. Minors

Default views are aggregates with minimum group size K; K is a server-side constant with a database lower bound (lesson of finding LB-R2). Learner-level views are minimal, reason-gated, audited. No bulk learner export in Admin-00. No free-text student content in the console.

## 7. Environments and deployment

* `LOCAL` (synthetic data) → `STAGING` (synthetic + anonymised only) → `PRODUCTION`. The UI banner shows the environment; production requires a separate staff pool.
* Admin never points at the owner's shared local stack by default; the dev proxy refuses non-local URLs unless `ADMIN_ALLOW_REMOTE=1`.
* No public deployment, DNS record or CDN rule is created by this work.

## 8. Gates before ANY network exposure (from the correction plan "any staff surface reachable from a network")

1. Staff MFA implemented (not just designed) and recovery procedure rehearsed.
2. Content takedown route (L-B2-3) and last-admin fix (S13).
3. Deploy-time readiness assertion X-1 (refuse to start if an API role holds TEMP or the extension list differs).
4. PR #20 merged (temp-schema fix) and the hosted-platform checks for NF-1 (`supautils`) done.
5. Audit read API + alerting on role changes, releases and break-glass use.
6. Independent security review of the staff API and the SPA (implementer ≠ reviewer, as in the audit).
7. Penetration-style test of role boundaries (each role × each route).
