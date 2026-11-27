# Environment and identity inventory

| Environment | Identity anchor | Allowed tooling |
|---|---|---|
| LOCAL | Dedicated worktree, deterministic Supabase project ID and ports, verified Docker bindings, local synthetic Auth and DB logins. Existing hosted CI has a narrowly matched runner-ID exception. | Local setup, pgTAP, pytest and rehearsal only on the verified stack. The default `mon-edupreneur` configuration fails destructive preflight. |
| STAGING | Separate project/ref, Auth signing keys, database password, accounts, backups, secrets and Render service. Record the approved ref independently of connection strings. Readiness checks inspect the actual login. | Explicit staging launcher, metadata plan and audit. The app profile never migrates, provisions or seeds. |
| PRODUCTION | Future separate account/project, identities, secrets and deployment approval. | The staging launcher, local tests, restore drill and release verifier refuse this selection. A production deployment profile has not been defined. |

## Render web process

| Variable | Handling and default |
|---|---|
| `EDU_ENVIRONMENT` | Must be `staging`, matching the launcher's required argument. |
| `EDU_STAGING_PROJECT_REF` | Required, exact approved 20-character Supabase ref. Non-secret identity anchor. Pin it separately in the release record. A person replacing the pin and both endpoints together can defeat a self-consistency check. |
| `EDU_DATABASE_URL` | Secret. `postgresql+asyncpg` DSN, database `postgres`, explicit port 5432, URL-encoded random per-project password. Direct username `edu_api_login` at `db.<ref>.supabase.co`; session pooler username `edu_api_login.<ref>` on the reviewed Virginia aws-0/1 Supavisor host. The policy rejects query overrides and port 6543. |
| `EDU_DB_CA_FILE` | Optional path to mounted provider CA file. Default uses system CAs, always verifies certificate and hostname in staging. Obtain CA material from the project console. |
| `EDU_AUTH_ISSUER`, `EDU_AUTH_JWKS_URL` | Exact HTTPS project issuer ending in `/auth/v1`, and that issuer plus `/.well-known/jwks.json`. Both must match the pin. |
| `EDU_AUTH_AUDIENCE`, `EDU_AUTH_ALGORITHMS` | `authenticated`, default JSON list `["ES256"]`. API additionally supports RS256 for separately reviewed asymmetric key rotation. |
| `EDU_AUTH_LEEWAY_S`, `EDU_AUTH_JWKS_CACHE_TTL_S`, `EDU_AUTH_JWKS_MIN_REFRESH_INTERVAL_S` | Defaults 30 / 600 / 30 seconds. Public key caching and clock allowance. |
| `EDU_DB_POOL_SIZE`, `EDU_DB_MAX_OVERFLOW`, `EDU_DB_POOL_TIMEOUT_S` | Template 3 / 1 / default 5 seconds. One pool per process. |
| `EDU_DB_CONNECT_TIMEOUT_S`, `EDU_DB_STATEMENT_TIMEOUT_MS`, `EDU_DB_DISABLE_STATEMENT_CACHE` | Defaults 3 seconds / 5000 ms / false. Direct or session pooling only. Rehearse prepared statements and startup settings on hosted Supavisor. |
| `EDU_SYNC_MAX_OPS`, `EDU_MAX_WIRE_BODY_BYTES`, `EDU_MAX_DECODED_BODY_BYTES` | Defaults 50 operations / 20480 wire bytes / 131072 decoded bytes. |
| `EDU_PULL_DEFAULT_LIMIT`, `EDU_PULL_MAX_LIMIT` | Defaults 100 / 200 feed rows. |
| `WEB_CONCURRENCY` | Template sets 1. The launcher explicitly starts one worker, including on plans with a higher platform default. |
| `PORT`, `UV_VERSION` | Port supplied by Render. Template pins uv 0.11.3, repository Python line 3.13 and `uv.lock`. Verify the resolved Python patch and OS image in the release record. |

## Operator-only material

`STAGING_AUDIT_DATABASE_URL` uses `postgresql`, verified TLS and a distinct `edu_staging_auditor` login for the same project. Give it CONNECT, USAGE on `supabase_migrations`, SELECT(version) on its ledger and catalog visibility only. Give it no parent-role membership, no CREATE in **any** namespace, no TEMP, no USAGE on app/auth, and no grant option on CONNECT or on any schema USAGE (see `auditor-privileges.md`). The rehearsal runs this exact metadata query as that role. Keep it outside the web service. Run the gate in an isolated release shell with the matching staging configuration. The migration owner needs a separate short-lived operator session. Restore and rotate custom login passwords independently after a backup restore.

Keep `LOCAL_ADMIN_DATABASE_URL`, `LOCAL_API_DB_PASSWORD`, `LOCAL_SUPABASE_URL`, local publishable/secret keys, legacy JWT fixtures and `supabase/signing_keys.json` inside the selected test worktree. Keep `.env`, dumps, Render deploy hooks, account tokens and private keys out of Git, CI artifacts, client builds and service logs. The staging CI consumes repository contents and synthetic secrets generated on its own runner. The web process needs no Supabase admin key, signing private key, OpenRouter token, Runpod key or storage key.

Use the project console’s connection panel to confirm IPv4/IPv6 reachability and Supavisor session hostname. Direct IPv6 support from the selected Render service and the hosted CA chain remain acceptance checks. A different region, hostname convention or pooler mode needs a separately reviewed profile. [Supabase connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres)
