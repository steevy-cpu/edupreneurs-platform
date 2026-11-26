# Platform-Staging-00

**Release boundary.** This is a specification and a disposable rehearsal for a single synthetic staging tenant. Cloud accounts, spending, live credentials, domain registration, real learner data and a hosted deployment require a later owner decision. The review started at main `4abb2e241c9909aee7c191d05b70307f851eb154`.

[Environment inventory](environment.md) · [Deployment, restore and rollback checklist](runbook.md) · [Evidence and limitations](verification.md) · [Inactive Render example](examples/render.staging.yaml.example)

## Audit of current main

| Area | What exists and how it affects staging |
|---|---|
| FastAPI | The application factory serves unauthenticated `/health` and `/ready`, and token-protected `/v1` identity, published catalog, lesson and offline sync routes. The original readiness query was `SELECT 1`. The staging profile also checks the serving login and effective database security on every probe. A separate privileged-metadata gate verifies the ledger before a release and after restoration. |
| Identity | Supabase Auth issues asymmetric access tokens. The API fetches public JWKS, verifies signature, issuer, audience and user token claims, and sets the actor inside each SQL transaction. Known cached signing keys can survive a temporary JWKS refresh failure. Use a synthetic sign-in and key-rotation smoke check alongside readiness. |
| PostgreSQL | PG17, private `app` schema, 22 RLS-protected tables and definer functions for writes. The API authenticates as `edu_api_login`, inheriting `edu_api`. The owner, local seed users and Supabase service credentials have no place in the Render web process. Data API exposure is separately configured at Supabase. |
| Migration sequence | `20261121000100` core schema, `00200` integrity guards, `00300` API grants/policies, `00400` sync functions (the last three share the first migration’s date), then `20261125100000` database TEMP revocation from PR #20. The ordered SHA-256 manifest names each full version. Seed SQL and generated login credentials are local-only. |
| CI and isolation | Existing CI runs lint, types, contract freshness, API/Auth tests, pgTAP twice and mobile verification in a runner VM. Its project is already named per run. The new workflow adds an independent restore drill, immutable migration comparison, secret scan and HTTP smoke. The default local configuration still names the owner’s project. Previously, the reset printed a warning and proceeded. The Make targets and Python fixtures now verify the disposable identity first. |
| Prior work | Inspected `codex/platform-stabilization@b86ad991e7ba2e327876e131442bef4543632ff6` and its parent `8320c72`. Retained its ideas of checkout-bound tests, post-restore TEMP checks and a reviewed extension list. Its staff/worker login requirements and integrated schemas belong to a different baseline. Main reserves the worker directory and implements only the student API login. [Platform gap matrix](../../architecture/platform-00/02-gap-matrix.md) · [Existing security model](../../SECURITY.md) |

## Service and trust boundaries

| From | To | Authority and transport |
|---|---|---|
| Synthetic client | Staging Supabase Auth | Staging project URL and public client identifier. Invite-only test accounts, limited redirects, independently rotated asymmetric signing keys. No service key in clients. |
| Synthetic client | Render FastAPI | HTTPS bearer access token, staging issuer/audience and actor verification for each protected request. An open health endpoint conveys no identity. |
| Render FastAPI | Supabase JWKS and PostgreSQL | Public key retrieval over HTTPS. Database access uses a unique custom login, TLS certificate/hostname verification and one bounded SQLAlchemy pool. Only the DB route requires a server-side password. |
| Release operator | Staging database | A separate metadata reader runs a read-only plan and audit. The migration owner and restore operator are held outside the service. The project ref is independently recorded by the owner and compared with the dashboard and both endpoints. |
| Future workers | Narrow backend contracts | Dedicated non-web processes and separate DB or service identities. Require short-lived, audience-scoped service credentials or narrowly scoped DB grants per task. An internal network address alone confers no authorization. |

The example has one paid-size web process with no disk, auto-deploy disabled, no preview environments, migration commands, scheduled tasks or worker. No root Blueprint or deploy hook is added. Render terminates HTTPS and supplies `PORT`. The explicit staging launcher starts one Uvicorn instance bound to that port. It disables access logging and proxy-header trust and emits reviewed event names without log arguments, exceptions, learner IDs, answer text, query strings or tokens. Check Render edge log retention/access separately. [Render Blueprint reference](https://render.com/docs/blueprint-spec) · [Health checks](https://render.com/docs/health-checks)

## Capacity, location and cost assumptions

Start the hosted trial, if approved, with one Render Virginia web instance at 0.5 CPU/512 MB and one dedicated Supabase project in US East (Northern Virginia). Co-location reduces API-to-database round trips. Haiti-to-Virginia latency depends on carrier routing, radio conditions and time of day. Measure DNS/TLS, sign-in, lesson fetch and sync p50/p95 from at least two Haitian networks. No latency, concurrency or throughput figure here is a measured capacity claim. [Render regions](https://render.com/docs/regions) · [Compute plans](https://render.com/docs/compute-plans)

One process allows 32 concurrent connections/tasks at Uvicorn and **four** SQL pool slots (3 + 1). Budget eight web SQL slots while two deployments overlap, plus Auth, metadata reader, migrations and admin headroom. Keep-alive is 5 seconds, drain 20 seconds, pool wait 5 seconds, DB connect 3 seconds, statement 5 seconds, driver command 7 seconds and readiness 3 seconds. Keep-alive does not cap the duration of a request. Watch resident memory, pool wait, 503s, DB connections and retry/idempotency behavior before increasing limits. Raise capacity only after synthetic load tests.

For budgeting, reserve **USD 10–20/month** for one always-on web instance as an internal allowance and **USD 25/month baseline** for a single Supabase Pro organization/project assuming its included compute credit applies. Indicative combined allowance **USD 35–45/month**, before workspace/seat fees, taxes, egress, builds, additional compute, PITR, logs or off-site backups. It is an estimate, not an approved quote. Obtain actual project-specific prices and spend limits before purchase. The plan here allocates zero to models, GPUs, object storage and workers. [Render pricing](https://render.com/pricing) · [Supabase pricing](https://supabase.com/pricing)

## Future integration contracts

- **Admin-02** will require separate staff identity, server-side role checks, fresh MFA on sensitive actions, read/write audit and its own database role. Browser role previews carry no authority.
- **Jude** stays disabled with no route, provider secret or worker. A later server-side broker may hold a scoped OpenRouter key, enforce quotas, redact input/logs and account for spend. A future Runpod experiment gets separate credentials, egress and shutdown limits.
- **Packs** may use R2 after procurement. Separate environment buckets, immutable versioned objects, integrity-checked manifests and time-limited access are required. Keep storage credentials server-side and rehearse object recovery independently of SQL.
- **Analytics and monitoring** begin with aggregate counters, queue/pool latency and readiness transitions. Approve aggregation thresholds and retention first. Keep staff audit events access-controlled and separate from infrastructure logs. No student-level analytics export, tracing payloads or external monitoring vendor is enabled.
