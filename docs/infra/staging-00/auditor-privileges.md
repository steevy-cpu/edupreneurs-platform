# Migration auditor: exact privilege contract

The release audit and plan connect as `edu_staging_auditor`, a metadata-only login. It exists to read the migration ledger versions, nothing else. `scripts/staging_verify.py::check_session` refuses to run (and `ValueError("excessive audit login privileges")` is raised) when the connected role holds anything beyond the contract below. The web-login policy (`services/api/src/edu_api/db/staging_security.sql`) is a separate check and is unchanged by this document.

## Allowed

* `CONNECT` on the database, **without** grant option.
* `USAGE` on `supabase_migrations`, **without** grant option.
* `SELECT(version)` on `supabase_migrations.schema_migrations` (no other column, no grant option).

## Rejected (effective, i.e. direct, inherited through membership, PUBLIC, or ownership)

| Privilege | Check |
|---|---|
| Superuser, bypass-RLS, create-DB/role, replication | role flags |
| Any role membership | `pg_auth_members` |
| Database `CREATE`, `TEMP` | `has_database_privilege(..., 'CREATE,TEMP,CONNECT WITH GRANT OPTION')` |
| Database `CONNECT WITH GRANT OPTION` | same call (a comma list means "any of") |
| `CREATE` in **any** namespace | every row of `pg_namespace` through `has_schema_privilege(..., 'CREATE')` |
| `USAGE WITH GRANT OPTION` on `supabase_migrations` and on any other namespace | `has_schema_privilege(..., 'USAGE WITH GRANT OPTION')` |
| `USAGE` on `app`, `auth` | `has_schema_privilege` |
| Writes, `REFERENCES`, `TRIGGER`, `MAINTAIN`, column insert/update on the ledger; any column read other than `version`; `SELECT` grant option on any ledger column | table and column checks |

The earlier check denied `CREATE` only on `supabase_migrations`, and checked grant options only on ledger columns. An auditor holding `CREATE` on any other schema, ownership of a schema, `CONNECT WITH GRANT OPTION`, or `USAGE WITH GRANT OPTION` was admitted (PR #45, `FINAL_GATE_42.md`).

## PostgreSQL semantics verified (PostgreSQL 17.12, disposable scratch instance)

* A freshly created role holds `CREATE` in **no** namespace: `pg_catalog`, `information_schema`, `pg_toast`, the per-session `pg_temp_N` / `pg_toast_temp_N` schemas and `public` (PG15+ default) all return false. **The policy therefore needs no system-schema exception**; any `CREATE` is a violation.
* `PUBLIC` cannot receive a grant option (`grant options can only be granted to roles`). A "PUBLIC WITH GRANT OPTION" state cannot exist. A *base* privilege granted to PUBLIC is, however, effective for every role, and `has_*_privilege` includes it.
* Grant options are inherited through role membership; an owner always holds them. Ownership of a schema or database therefore makes `CREATE` / grant-option checks true.
* In a comma-separated privilege list the result is true if **any** listed privilege is held.
* The database default gives PUBLIC `TEMP`; the migration `20261125100000_revoke_temp_from_api_roles.sql` revokes it, which is why the contract forbids `TEMP`.

## Regression cases

`tests/integration/test_staging_auditor_privileges.py` (disposable database, rolled-back fixtures; 14 cases):

* the version-only auditor is still admitted (control);
* each rejected state, first proving the privilege is effective for the auditor through `has_*_privilege`: schema CREATE on `supabase_migrations`, on another schema (direct, via PUBLIC, `public` via PUBLIC, via ownership, inherited), `CONNECT WITH GRANT OPTION` (direct, inherited), migration-schema `USAGE WITH GRANT OPTION` (direct, inherited), and `USAGE WITH GRANT OPTION` on another schema;
* PostgreSQL itself forbids PUBLIC grant options;
* a fresh auditor holds `CREATE` in no namespace (so no exception is needed).

Existing auditor cases in `tests/integration/test_staging_readiness.py` and the independent QA cases are unchanged.

Limits: this verifies privileges visible to the connected role in one database. It does not prove provider-level controls (hosted role provisioning, network policy, TLS), which stay hosted-acceptance gates.
