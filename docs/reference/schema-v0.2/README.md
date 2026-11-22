# Mon Edupreneur 2.0 — Schema v0.2 bundle

This is a **proposed** first-release PostgreSQL schema, not a live or tested deployment.

- **`SCHEMA_DESIGN.md`** — design rationale, full 22-table data dictionary, trust boundaries and test plan.
- **`migrations/0001_core_schema.sql`** — private `app` schema and tables, indexes, RLS enabled, publication/immutability guards.
- **`migrations/0002_api_role_and_policies.sql`** — API role privileges and actor-scoped row security.
- **`diagrams/*.mmd`** — three editable Mermaid ERDs.
- **`diagrams/Mon-Edupreneur-Schema-v0.2.drawio`** — multi-page diagrams.net/draw.io ERD.
- **`tests/schema_introspection.sql`** — safe read-only introspection after applying migrations.

## How to use

1. Review `SCHEMA_DESIGN.md` and diagrams with the founders and curriculum reviewers.
2. Create an Edupreneur-owned **development** Supabase project (not the Lovable database).
3. Have Fable translate these ordered SQL drafts into timestamped Supabase CLI migrations.
4. Test locally with `supabase db reset`; run structural, permission and replay tests in a disposable environment.
5. Create least-privileged API login credentials **outside** source control and verify connection pooling preserves transaction-scoped actor isolation.
6. Use staging exclusively until all security, durability and account separation tests pass.

**Never run these drafts against a live database before review and test.** No production, admin or user credentials belong in these files.
