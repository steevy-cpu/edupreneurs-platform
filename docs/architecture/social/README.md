# Social-00 — Community architecture and database design

**Status: design only.** Nothing in this folder runs. No migration was applied,
no endpoint was added, no mobile screen changed, nothing was deployed. Every
file added by this branch lives under `docs/architecture/social/`.

Date: 2026-11-24 · Branch: `social-00` (from `main`) · Scope: design for review.

## The design in one page

Edupreneurs learners are in grades 7AF to NS4, and many are minors. So the
community module is designed as a **supervised classroom noticeboard**, not as
a social network.

1. **Nothing a learner writes is seen by anyone else until a moderator approves
   it.** This is not just an API rule: the database itself refuses to publish a
   post unless an approval by a *different* person exists for exactly that text.
2. **Text only, to start.** No photos, no video, no private messages, no
   followers, no public profiles, no search for people. Each of those is a
   separate later decision with its own safety review.
3. **Closed groups with verified members.** There are no public communities. A
   learner joins a class group with a code, and a teacher or staff member must
   confirm them. Younger (7AF–9AF) and older (NS1–NS4) learners are never mixed.
4. **Social data and learning data cannot reach each other.** The module has its
   own database schema (`social`), its own database roles and its own connection
   pools. It has no permission to read lessons progress, scores or attempts, and
   the learning API has no permission to read social data. Tests will prove both.
5. **Built for weak networks.** Small text pages, a feed you page through, one
   small "anything new?" call when the screen opens — and no always-on
   connection. Posts written offline wait in a *separate* queue that can never
   delay or block lesson sync.
6. **Safety tools from day one:** report, block, automatic hiding of reported
   content, a moderation queue with deadlines, warnings/mutes/suspensions, an
   audit trail that cannot be edited, and an escalation path for serious cases.
7. **No learner text is sent to any outside AI or moderation company.** The
   automatic check is a simple rule-based filter that runs inside our own API.
   Jude is not part of conversations in this design.
8. **It ships switched off.** A global switch and a per-community switch both
   default to "closed"; the routes are not even mounted unless a setting is on.

## Deliverables

| # | Deliverable | File |
|---|---|---|
| 1 | Architecture decision record | [01-architecture-decision-record.md](01-architecture-decision-record.md) |
| 2 | Database ERD and table dictionary | [02-database-erd-and-table-dictionary.md](02-database-erd-and-table-dictionary.md) |
| 3 | Proposed SQL migration files, **not executed** | [03-sql-migration-plan.md](03-sql-migration-plan.md), [migrations/proposed/](migrations/proposed/), [migrations/future/](migrations/future/) |
| 4 | OpenAPI draft | [openapi/social-v1.draft.yaml](openapi/social-v1.draft.yaml), [04-api-design.md](04-api-design.md) |
| 5 | Role and permission matrix | [05-roles-and-permissions.md](05-roles-and-permissions.md) |
| 6 | Moderation workflow and threat model | [06-moderation-workflow-and-threat-model.md](06-moderation-workflow-and-threat-model.md) |
| 7 | Low-bandwidth and scaling strategy | [07-low-bandwidth-and-scaling.md](07-low-bandwidth-and-scaling.md) |
| 8 | Automated test specification | [08-test-specification.md](08-test-specification.md) |
| 9 | Phased implementation roadmap | [09-roadmap.md](09-roadmap.md) |
| 10 | Risks, unanswered decisions, recommendations | [10-risks-and-open-decisions.md](10-risks-and-open-decisions.md) |
| + | App Store / Google Play review and legal questions | [11-store-policy-and-legal-review.md](11-store-policy-and-legal-review.md) |

Suggested reading order for a first review: this page → 10 (the decisions only
you can make) → 01 → 06 → 09. The rest is reference.

## What was checked, and what was not

The instruction was not to execute the migrations, so they were **not run
against any database** — not the local one either. What was done instead:

| Check | Result | How to repeat |
|---|---|---|
| SQL syntax of all 8 files, including every PL/pgSQL function body | parses cleanly with the real PostgreSQL parser (`pglast` 8.9, PostgreSQL 17 grammar) | see below |
| Cross-references | every table, column and function named in a `GRANT` exists with the same signature; no reference to an undefined `social.*` object; **0** mentions of the `app` schema | see below |
| OpenAPI draft | valid OpenAPI 3.1 (44 paths, 50 operations, 39 schemas), unique operation ids | see below |
| ER diagrams | the three Mermaid diagrams in doc 02 parse with the Mermaid 11 library | open doc 02 on GitHub: it renders them |
| Existing code | untouched: `git diff --stat main...social-00` lists only `docs/architecture/social/` | `git diff --stat main...social-00` |

```bash
# from the repository root; nothing is installed into the project
uv run --no-project --with 'pglast>=7' python - <<'EOF'
import glob
from pglast import parse_sql, parse_plpgsql
for f in sorted(glob.glob("docs/architecture/social/migrations/*/*.sql")):
    src = open(f).read()
    for raw in parse_sql(src):
        if type(raw.stmt).__name__ == "CreateFunctionStmt" and any(
            o.defname == "language" and o.arg.sval == "plpgsql" for o in raw.stmt.options):
            end = raw.stmt_location + raw.stmt_len if raw.stmt_len else len(src)
            parse_plpgsql(src[raw.stmt_location:end])
    print("ok", f)
EOF
uv run --no-project --with openapi-spec-validator --with pyyaml python -c "
import yaml; from openapi_spec_validator import validate
validate(yaml.safe_load(open('docs/architecture/social/openapi/social-v1.draft.yaml'))); print('valid')"
```

**Not verified, and must not be assumed:** that the SQL *behaves* as described.
A parser checks grammar, not meaning. A wrong column type, a lock that
deadlocks, a policy that is too slow — none of that is caught until the files
are applied to a throwaway local database and the tests in
[08-test-specification.md](08-test-specification.md) are written and run. That
is the whole purpose of milestone Social-01.

## Words used in these documents

| Term | Meaning here |
|---|---|
| **Schema** | A named folder of tables inside one database. `app` holds learning data; `social` would hold community data. |
| **Role** | A database account with a fixed set of permissions. The API connects as a role; what that role cannot do, the API cannot do, even if it has a bug. |
| **RLS (row-level security)** | A rule stored in the database that filters *which rows* a role sees — e.g. "only posts in communities you belong to". It applies even if the API forgets a `WHERE`. |
| **SECURITY DEFINER function** | A database function that runs with its owner's permissions. Used as a narrow door: the API role cannot write tables, it can only call the function, and the function enforces the rules. |
| **Pre-moderation** | A human approves content *before* anyone else can see it. (Post-moderation = publish first, review later. Not used here.) |
| **UGC** | User-generated content: anything a user writes — posts, comments, and also display names. |
| **Idempotent / safe retry** | Sending the same request twice has the same effect as sending it once. Essential when the network drops the answer. |
| **Cursor / keyset pagination** | "Give me the 10 posts after this marker" instead of "page 3". Stays correct when new posts arrive, and stays fast as the table grows. |
| **Outbox** | The queue on the phone that holds actions done offline until they can be sent. |
| **Tombstone** | A small "this item is gone" marker, so a phone that cached the item knows to delete it. |
| **Evidence hold** | A lock that stops automatic deletion of a piece of content while a serious case is open. |
| **Kill switch** | A setting that turns a feature off immediately without a deploy. |
| **MFA / `aal2`** | Multi-factor sign-in. Supabase Auth marks such sessions with the claim `aal: "aal2"`. |
| **CSAM / CSAE** | Child sexual abuse material / child sexual abuse and exploitation — the terms the app stores and laws use. |
