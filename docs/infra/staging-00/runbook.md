# Release, restore and rollback

## Rehearse locally or in CI

Use a fresh worktree reserved for tests, with Docker on a local Unix socket and enough space for the Supabase PG17 images and a second logical database. Commands below affect that disposable checkout only. Do not use an owner checkout with an existing `.env` or signing key.

```sh
npm ci
uv sync --locked
uv run python scripts/staging_verify.py manifest
uv run python scripts/disposable.py configure
make start
make db-reset
uv run python scripts/staging_verify.py plan --environment local
uv run python scripts/staging_verify.py audit --environment local
uv run python scripts/restore_drill.py --environment local
make test-db
uv run pytest
make stop
```

Configuration derives the project ID and port lane from the absolute worktree path. Keep the resulting local changes to `supabase/config.toml` out of commits. A port collision must fail startup. Choose a different disposable worktree if it occurs. Reset requires the named DB and gateway containers to own the expected ports. Effective URLs must agree with those ports, credentials must name the proper database roles, and file/process conflicts fail verification. Stop preserves disposable data. CI uses the same identity check before its optional no-backup cleanup.

The guarded targets are the supported interface. An owner with direct Docker or database administration privileges can invoke upstream tools independently of this repository. Raw `supabase db reset`, linked CLI operations, `pg_restore --clean` against a service database and copied owner environment files are outside this procedure.

## Before considering a hosted deployment

1. **Record the release.** Capture candidate SHA, last-known-good SHA, dependency locks, Python patch, migration hashes, CI results, responsible operator, rollback decision-maker and proposed window. Review any schema addition against the previous application version. The append-only CI gate rejects edits, removals and insertions before existing versions. A read-only ledger plan reports the pending suffix and rejects gaps or unknown versions. On a genuinely new database lacking a ledger, use the separately reviewed bootstrap procedure before this check.
2. **Confirm identity and spend authorization.** Obtain separate owner approval for provisioning. Record the dedicated staging ref, region, Render service ID, Supabase organization and expected billing. Compare them with the independent release record. Restrict staff access, disable public signup, restrict redirect URLs and allow only synthetic accounts. Keep the `app` schema out of Supabase Data API exposed schemas. Review DB ingress, TLS CA, signing algorithm, key rotation and backup retention.
3. **Apply reviewed schema separately.** A migration operator targets the recorded staging project, with a verified backup and an agreed restore point. Apply only the reviewed forward migration suffix under the expected owner (`postgres` owns the app definer functions). Never apply `supabase/seed.sql` or copy a local login password into staging. If necessary create synthetic content via an audited fixture procedure approved for that environment. The Render build and start commands have no migration step.
4. **Provision distinct roles.** Give `edu_api_login` LOGIN, INHERIT and only `edu_api` membership without admin option, no ownership, TEMP, schema CREATE, superuser, role/DB creation, replication or BYPASSRLS. Set its random password in the database and Render secret store. Check lock and statement timeouts using the selected connection mode. Grant the separate metadata reader access to read the migration version column and standard catalogs. Do not grant the web role migration-owner or Auth-admin access. See the [inventory](environment.md).
5. **Run gates before admitting traffic.** In the staging release shell set the independent project ref and inject secrets from the manager. Run the two commands below. Compare the applied version list, ACLs and provider extension inventory with the release. A managed extension outside the list blocks staging until its purpose, schema, owner, version and grants have been independently reviewed. Avoid removing provider-managed extensions as an automatic repair.

```sh
uv run python scripts/staging_verify.py plan --environment staging
uv run python scripts/staging_verify.py audit --environment staging
```

6. **Build and smoke test.** After separate deploy approval, manually select the reviewed SHA using the inactive example. Set `/ready` as the health path. Startup validates the project, effective login and DB policy. `/health` checks process liveness and `/ready` rechecks database policy. Neither route asserts Auth availability or proves a backup exists. Fetch the pinned public JWKS over HTTPS and check its expected key ID/algorithm. Sign in with a synthetic user, verify `/v1/me`, published-only catalog, same-operation retry and account isolation. Use a staging test account to verify access controls rather than production identity or data.
7. **Observe before wider use.** Record deployment ID, response status, pool saturation, memory, sync retries and p95 from Haiti. Inspect service and edge log samples for personal data and secrets. Exercise graceful shutdown and previous-build rollback on staging. A failed identity check, missing migration, unexpected extension, TEMP grant, public exposure or failed restore keeps traffic closed.

## Backup verification and restoration

For the first hosted trial propose **RPO 24 hours** with daily backups and **RTO four hours**. These are targets pending a timed hosted restore. Record the backup ID/timestamp, encryption, access list, retention, checksum for downloaded archives and the actual elapsed restore time. A passing backup job or a listed archive alone is insufficient.

The automated drill starts with the verified disposable source. It takes a custom-format logical dump of `app`, `auth` and `supabase_migrations`, checks its SHA-256, and restores into a randomly named fresh database under `template0`. Each table’s row count and deterministic row-content digest are compared with the source alongside the migration ledger. The target initially has the ordinary database TEMP default. The drill requires that failure, reapplies the checked-in PR #20 database ACL correction there, and then checks effective privileges. It also checks a direct login grant and an unreviewed benign extension independently. Restore failures stop the job. The scratch database and local archive are removed. The test uses a shared *disposable cluster* so cluster roles already exist. Quiesce writers for a comparable backup fingerprint.

For a hosted restore, isolate the restored project from all clients and workers. Re-establish custom roles/memberships, rotate passwords, check exposed schemas, compare extensions, verify TLS, issuer and backups, run the read-only audit, then validate the least-privilege `/ready` probe and a synthetic authorized request. Require explicit approval for remediation. A complete migration ledger does not prove that TEMP, RLS, role grants or extension policy survived restoration.

The drill does not back up provider control-plane settings, cluster role passwords, JWT signing keys, Auth email/redirect settings, Render secrets or object bytes. The provider may manage physical backups. Rehearse a separate project restore on the selected plan and rebind its own identity before accepting the hosted RPO/RTO. Future object storage needs a separate object-version and hash restore drill. [Supabase backup scope](https://supabase.com/docs/guides/platform/backups)

## Rollback decision

- **Application-only regression.** Stop promotion, retain sanitized failure evidence, select the last-known-good Render deploy and restore the matching service configuration from the secret manager by version. Confirm its schema compatibility first. Re-run readiness and synthetic Auth/catalog/sync checks before reopening traffic. Record both deployment IDs. [Render rollback behavior](https://render.com/docs/rollbacks)
- **Incompatible or unsafe database change.** Close ingress and stop writers. Keep a snapshot of the failed state. Prefer a reviewed forward correction where data remains intact. Otherwise restore to a separate isolated staging project at the chosen point. Inventory writes since that point and reconcile or replay approved synthetic operations. Revalidate roles, passwords, TEMP, extensions, migrations and duplicate sync handling before repointing the whole environment. A Render rollback does not revert database migrations.
- **Suspected credential disclosure or project mix-up.** Remove traffic, revoke/rotate affected credentials, identify the projects contacted and review provider access logs with the owner. Keep tokens, DSNs and student data out of incident tickets. Resume only after independent confirmation of source, destination and restore point.
