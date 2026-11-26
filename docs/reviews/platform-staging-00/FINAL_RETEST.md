# Platform-Staging-00 independent security retest

**Request changes before integrating #39 with #33. All six findings from #36 are closed on the reviewed SHA.** The fresh disposable run passed all 17 original cases with expected-failure masking disabled. Two additional tests found blind spots in the same policy used for staging release, startup and readiness. An API login with table-maintenance or privilege-delegation rights still received a green policy result. Both grants were rolled back. [Independent run, including failures and cleanup](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45897169183/job/140173829614)

## Scope and provenance

Codex #1 reviewed the correction implemented by Codex #2. GitHub reported #39 at the requested SHA before testing. The QA branch starts at that exact commit and adds tests, a QA-only workflow change and this report. Production code, migration files and the original assertions in the candidate are the files exercised by the runner. [Correction #39 at ab8a8296e12d44510d0b2a596eac2fa36385861f](https://github.com/steevy-cpu/edupreneurs-platform/commit/ab8a8296e12d44510d0b2a596eac2fa36385861f) · [Independent QA tests at f606fbf33edae4684d52d78690f599be0421499a](https://github.com/steevy-cpu/edupreneurs-platform/commit/f606fbf33edae4684d52d78690f599be0421499a)

I retrieved both acceptance files at #36's GitHub head, compared their full contents with #39 and independently verified the Git blob IDs. The copies differ only in their repository paths. The original suite used `--runxfail` so previously expected failures counted as failures. [Original QA #36](https://github.com/steevy-cpu/edupreneurs-platform/pull/36) · [QA test run](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45897169183)

| #36 at cfac1ac803124d8863d7b9812893fa55234a092e | Copy at #39 | Identical Git blob |
|---|---|---|
| tests/unit/test_platform_staging_qa.py | tests/staging_acceptance/qa_unit.py | c48a6706dc9db726ec9e14b5ec644f8bd4e3fd49 |
| tests/integration/test_platform_staging_qa.py | tests/staging_acceptance/qa_database.py | 0e71d1ee8444bc30b8a435943c6f5f0a6de7012a |

## Test boundaries

The local sandbox denied the OrbStack socket. I used the Mac for network-free controls and a fresh GitHub-hosted VM for all live API, Auth, PostgreSQL and restore operations. The staging preflight derives its project name and four ports from the checkout path, rewrites the default Supabase config before startup, then verifies the Docker DB and Kong publications before reset and before integration fixtures consume the generated environment. Corruption tests use separate `drill_<uuid>` databases. The ordinary repository CI uses a different VM and a project name containing its own run ID and attempt. The string `mon-edupreneur` appeared only in fixture/config checks. No test contacted the owner's shared stack.

For the two process-level tests, the production launcher received its normal synthetic staging profile. A test adapter supplied the real FastAPI app backed by the verified local DB engine. The app ran the staging lifespan, privilege SQL and HTTP readiness handler. Each test checked the serving PID against the original launcher subprocess and issued real HTTP requests. This covers Uvicorn process selection and app startup. Hosted DNS, TLS and Supavisor were outside this experiment. [Worker tests](../../../tests/integration/test_staging_final_retest.py) · [Recording Auth tests](../../../tests/unit/test_staging_final_retest.py)

## Test results

GitHub checked out the PR merge ref at `cd860d7370edde8b183218f94be01526bc8e2357`. GitHub's comparison against the independent test commit reports zero changed files. The unmasked tests, ordinary smoke and cleanup each completed. The preflight is red solely on the two additional privilege assertions. [Disposable runner log](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45897169183/job/140173829614)

| Gate | Observed result |
|---|---|
| Original independent tests | **17 passed** under `pytest --runxfail`, including both corrupted-restore rejection cases. Previous result was 10 pass and 7 fail. |
| Units and recording adapters | **115 passed** on the runner, comprising 99 candidate cases and 16 independent recording cases. The Mac separately passed those same 99 and 16, plus the 12 network-free original cases unmasked. Counts overlap across invocations. |
| Real API/Auth/PostgreSQL integration | **87 passed**, comprising 85 candidate cases and two live launcher tests. Real tokens and database connections used the throwaway local Supabase services. |
| Database suite and migrations | **215 pgTAP assertions** across six files passed. Ordered manifest, append-only prefix, release plan and read-only audit passed. |
| Restore | Fresh logical restore reproduced source digests and ledger. The drill detected the default TEMP grant before repair and deliberate privilege/extension drift after repair. Corrupt version and changed migration name were independently rejected, with scratch DB removal asserted. |
| Process and HTTP | Both launcher/PID tests passed with a real socket. The separate Uvicorn factory smoke also returned healthy liveness and readiness. |
| Static, packaging and secrets | Locked installs, Ruff lint/format, strict mypy, fresh OpenAPI and production-only installation passed. Redacted Gitleaks reported **no leaks across 11 commits**, scanning from the shared base through the tested QA change. [Secret-scan job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45897169183/job/140173829215) |
| Extra web-role privilege checks | **2 failed** as policy assertions, after successful fixture setup and confirmation of the effective grants. Both transactions rolled back. Runner cleanup completed. [Regression tests](../../../tests/staging_acceptance/extra_acl_retest.py) |

The separate repository CI job passed both 215-assertion pgTAP runs, its combined 202 Python tests, mobile bundle checks and all 477 mobile tests across 32 suites. [Repository CI job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45897169156/job/140173829558)

## Disposition of the six original findings

| Finding | Decision | Evidence |
|---|---|---|
| QA-2 · high · writable migration ledger | Closed | The real version-only role passed the full audit. A direct column UPDATE failed the full gate. Direct table UPDATE, PUBLIC column INSERT, PUBLIC table DELETE, direct column REFERENCES and inherited table TRUNCATE each caused rejection at the common plan/audit privilege check. Tests confirmed the effective privilege in the auditor session before the negative assertion. The inherited fixture is also subject to the explicit no-membership rule. |
| QA-5 · high · standalone Auth password helpers | Closed | Both dev-login and token rejected each of eight recording cases. These covered another checkout's project, the shared identifier, a gateway port mismatch, inherited conflicting URL, mixed-case issuer, wrong DB or gateway interface and an absent Auth listener. Every rejection preceded HTTP dispatch. Only the absent-listener case reached the two synthetic TCP probes. |
| QA-1 · medium · Docker publication ownership | Closed | The guard matched the expected project containers, internal ports, published ports and serving IPv4 interface for both DB and gateway. Loopback and IPv4 wildcard covered the target; IPv6-only and unrelated interfaces failed. Ownership of both publications was checked before the first socket probe. A wildcard publication does not establish host firewall isolation. |
| QA-6 · medium · environment key case | Closed | Mixed-case settings were rejected before resolving the target. Generated dotenv and effective settings agreed, and conflicting canonical overrides were refused. The standalone helper recording matrix independently confirmed zero HTTP calls. |
| QA-3 · medium · readiness after loss of catalog access | Closed | With the real API login a healthy `/ready` returned 200. Removing SELECT on `app.courses` from its group role yielded 503 with only the database-unavailable status, while `/health` stayed 200. Restoring the grant returned readiness to 200. |
| QA-4 · medium · worker count | Closed | The unchanged original probes observed exactly one configured Uvicorn worker for WEB_CONCURRENCY=1 and 2. Both real HTTP process tests served from the launcher PID, completed startup through the local staging database policy and returned healthy readiness. |

## New findings and correction gates

**R1 · Medium · PostgreSQL 17 MAINTAIN passes for the web login.** Starting with a green baseline, the independent test added only MAINTAIN on the synthetic catalog table to the web login. PostgreSQL confirmed the effective permission. Every staging policy predicate still returned true. This authority permits operations that can lock tables or disrupt availability. The exercise only inspected effective permissions. Add MAINTAIN to the disallowed API table privileges and keep the rollback-only test. The dedicated migration-auditor guard already checks MAINTAIN on its ledger. [Staging policy](../../../services/api/src/edu_api/db/staging_security.sql) · [PostgreSQL 17 privilege definitions](https://www.postgresql.org/docs/17/ddl-priv.html)

**R2 · Medium · The web login may delegate catalog SELECT while the policy stays green.** A separate rolled-back transaction gave the web login SELECT WITH GRANT OPTION on the same table. PostgreSQL confirmed the grant option and every policy predicate again passed. A web login needs read access to this catalog. It has no operational reason to grant that access to another principal. Other controls such as schema access and row-level security still apply to a recipient. Check effective grant options on allowed API relation/column privileges, including the one intended column INSERT, separately from possession of those privileges. Keep the positive baseline and this negative case. No delegation was performed. [Staging checks](../../../services/api/src/edu_api/db/staging_security.sql) · [Independent evidence](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45897169183/job/140173829614)

These are observed false greens in the SQL shared by the release audit, startup and readiness. The test did not send an HTTP readiness request under each surplus grant. After correcting the shared predicate, independently rerun both negative tests, the version-only reader, the 17 unmasked assertions and the full staging preflight. Land the corrected stack before main integration so the earlier #33 implementation cannot be promoted alone.

## Integration with main

GitHub main was `1094eb0822759d7bc28f3162285077f30ad38969` (Admin-01, #27). The common ancestor with #39 is `4abb2e241c9909aee7c191d05b70307f851eb154`. Main had eight unique commits and #39 had ten, nine of them from #33. A local three-way `git merge-tree --write-tree` produced tree `54b89f435a62e4e24548ff7c257965f3934352ea` with no conflicts and without changing a branch. The combined tree matches the candidate for Supabase, backend, scripts, tests, root dependency locks, Makefile and staging workflow. Main's intervening changes were confined to the admin app, its workflow and documentation. [Main reviewed](https://github.com/steevy-cpu/edupreneurs-platform/commit/1094eb0822759d7bc28f3162285077f30ad38969)

All five migrations, including the final TEMP revocation, match current main byte for byte and in order. The manifest command also passed with current main supplied as its base. The only root dependency declaration change across the staging stack is making python-dotenv a direct Python dependency with corresponding lock metadata. Root Node locks are unchanged. The admin app has its own lockfile. Recheck the merge tree and append-only manifest if main or the candidate advances.

## Hosted acceptance still required

The template explicitly configures three pooled connections and one overflow slot per process. A single worker therefore has a four-connection web budget, or eight during a two-instance overlap. The underlying Settings defaults allow five plus five if both template overrides are omitted. Review the effective deployed settings and reserve separate capacity for Auth, the release auditor and operators. Local tests exercise SQLAlchemy rollback, liveness/readiness and transaction-local identity. Provider pool quotas, prepared statements on the hosted session pooler, CA/hostname verification against the real certificate chain, Render startup and drain behavior, recovery from a provider-native backup and latency from Haiti remain unverified. Cloud acceptance requires a separate owner decision. [Staging template](../../infra/staging-00/examples/render.staging.yaml.example) · [Operator runbook](../../infra/staging-00/runbook.md)
