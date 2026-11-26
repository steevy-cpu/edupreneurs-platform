# Final independent staging gate for PR #42

**Ready to integrate #42 into #39 for the web-login correction. Hold staging promotion.** The two findings from #40 are closed on `1375e5f33e33ddad1a2c64bf4266a6d2d9242083`. The separate migration auditor still has a gap between its documented privileges and its release checks.

## Candidate and execution

GitHub reported the requested head before testing. The parent PR #39 was at `ab8a8296e12d44510d0b2a596eac2fa36385861f`. I started a fresh attempt of the disposable preflight and checked the job log. Actions checked out `43bfbd7d4ccad639762a6644afb0e5c61e8ba005`. GitHub's comparison with the pinned head contained **zero changed files**. I also ran the static checks and 12 standalone acceptance cases in a separate local worktree at the head itself. [Review candidate](https://github.com/steevy-cpu/edupreneurs-platform/pull/42) · [Independent preflight job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45901474294/job/140194396334) · [Checkout comparison](https://github.com/steevy-cpu/edupreneurs-platform/compare/1375e5f33e33ddad1a2c64bf4266a6d2d9242083...43bfbd7d4ccad639762a6644afb0e5c61e8ba005)

| Gate | Result |
| --- | --- |
| Original acceptance evidence | **19/19 passed** with `--runxfail`. The two #36 files match the original Git blobs `c48a6706dc9db726ec9e14b5ec644f8bd4e3fd49` and `0e71d1ee8444bc30b8a435943c6f5f0a6de7012a`. The #40 follow-up matches `3725ec967ccc9b8e1920c95059f74530618482b9`. The separate 12 local passes overlap this count. |
| Effective rights | Direct, inherited and PUBLIC table-maintenance rights were detected. Tests checked whole-table and column delegation, profile-column insertion, database connection, schema usage and function execution. The version-only auditor was admitted. Direct, inherited, PUBLIC and column-level excess ledger privileges were rejected in the exercised cases. |
| Readiness and startup | With excess maintenance or delegable read access, readiness returned 503, liveness returned 200 and startup refused the web identity. After revocation, startup succeeded, the real web login read the catalog, its required profile-column right remained, and readiness returned 200. The separate required-catalog-read revocation and recovery test also passed. |
| Database, API and Auth | **215 pgTAP assertions in six files**, **95 integration tests** and **99 unit tests** passed. The integration suite exercised Auth, learner isolation, catalog, sync and staging policy against the runner's fresh Supabase stack. |
| Restore and migration security | The migration manifest, plan and release audit passed. The synthetic restore verified row-content digests, ledger and role policy. Both corrupted scratch restores were rejected. Uvicorn HTTP probes passed and the runner logged stack teardown. |
| Static and package checks | Ruff lint and formatting, mypy, OpenAPI freshness and the production dependency/package smoke check passed. |

## Open release finding

**Medium — the migration auditor's own privilege check covers only part of its allowed scope.** The runbook gives this metadata-only login connection, migration-schema usage and version-column read access, and forbids CREATE. In `check_session`, the schema CREATE denial covers only `supabase_migrations`. The function also checks grant options on ledger columns but omits the auditor's database CONNECT and migration-schema USAGE grant options. The separate `SECURITY_SQL` delegation checks name the web login. Consequently, passing the release audit does not establish that the auditor lacks those additional rights. This is a source finding. The runner results above establish the covered web-login and ledger cases. [Auditor contract](../../../docs/infra/staging-00/environment.md) · [Auditor predicate](../../../scripts/staging_verify.py) · [Web-login predicate](../../../services/api/src/edu_api/db/staging_security.sql)

Before staging promotion, check effective schema CREATE across namespaces for the auditor, and reject grant options on its two required connection and namespace privileges. Cover each case separately in the disposable auditor matrix, alongside a passing version-only control, and rerun both plan and audit. No hosted Render or managed Supabase acceptance was performed. TLS, provider configuration and hosted restore acceptance remain release gates.
