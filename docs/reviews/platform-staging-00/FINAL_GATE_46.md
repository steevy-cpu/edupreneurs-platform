# Independent staging gate for PR #46

**HOLD for the documented version-only auditor contract.** The specific #45 schema and delegation defects are corrected. The release check still cannot establish its broader claim that the auditor can read only migration versions. Do not promote staging on this evidence.

GitHub head and T7 source both matched `1e42eaf0c72552a03bc6a2c053fd09cae5c92136`, based on #42 at `1375e5f33e33ddad1a2c64bf4266a6d2d9242083`. The correction changes the auditor predicate, adds integration coverage and documents its contract. It also carries forward the #45 report. The web-role SQL and migrations have no diff from the parent. [Change set](https://github.com/steevy-cpu/edupreneurs-platform/compare/1375e5f33e33ddad1a2c64bf4266a6d2d9242083...1e42eaf0c72552a03bc6a2c053fd09cae5c92136)

## Fresh independent runner

I requested a new disposable preflight run and inspected its step log. GitHub checked out merge ref `9399ab84b730cb9bbfc6e9bdafdd750a64e5f26d`. Its GitHub comparison to the pinned head contains zero file changes. The job configured its own checkout-bound Supabase stack, exercised it, and logged teardown. [Runner log](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45919585819/job/140253792701)

| Gate | Result |
| --- | --- |
| Known auditor boundaries | Version-only control admitted. Direct CREATE in migration and other schemas, CREATE from PUBLIC or membership, and schema ownership rejected. CONNECT and schema USAGE grant options rejected directly and through membership. Other-schema USAGE grant option rejected. The fixture established each effective privilege through PostgreSQL. The PUBLIC grant-option case checked that PostgreSQL itself refuses such a grant. |
| Limits of that result | New matrix calls plan mode. Full audit shares the same auditor predicate before the plan/full branch. A separate integration control admits the legitimate auditor on full audit. Membership fixtures prove effective privilege plus rejection, but membership alone is also forbidden. |
| Application and database | **99 unit tests, 109 integration tests, 215 pgTAP assertions across six files** passed. Integration included synthetic API/Auth, readiness, startup and catalog read recovery. |
| Historical acceptance | **19/19 passed unmasked** with `--runxfail`, including the two corrupt restore rejection cases. |
| Operations | Migration manifest, plan, full local audit, restored data digests, migration ledger, role drift, packaged policy, Ruff, formatting, mypy, OpenAPI and HTTP probes passed. Local release commands connect as the disposable operator. Hosted Render, TLS and managed-backup restoration remain unqualified. |

## Remaining finding

**High for release assurance — non-ledger relation privileges and ownership are outside the auditor predicate.** The contract calls the auditor metadata-only. The new namespace sweep covers CREATE and delegable USAGE. The relation/column checks are restricted to one relation, `supabase_migrations.schema_migrations`. Ordinary read or write privileges, or ownership, on a different relation in an already usable schema do not participate in that decision. The subsequent full-audit SQL evaluates the web roles. A green plan or audit therefore cannot attest to version-only access. This is a source-level coverage finding. No access to another relation's data or privilege escalation was attempted. [Auditor predicate](../../../scripts/staging_verify.py) · [Stated privilege contract](../../../docs/infra/staging-00/auditor-privileges.md) · [Web-role checks](../../../services/api/src/edu_api/db/staging_security.sql)

Before approval, define the application-owned objects and expected PostgreSQL catalog access. Compare the auditor's effective ownership and table/column rights with that inventory. Include other application-owned object classes such as sequences and executable routines in the policy decision or explicitly narrow the attestation and provide a separate release control for them. Add metadata-only rollback fixtures for an unrelated synthetic relation in the migration namespace, including ordinary column access and ownership, plus the legitimate version-only control. Assert rejection in both plan and full audit, then rerun the disposable preflight. No need to change the five installed migrations to test this.
