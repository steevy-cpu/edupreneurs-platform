# Isolated verification and remaining gates

**Scope.** The candidate branches from `4abb2e241c9909aee7c191d05b70307f851eb154`. Testing used synthetic fixtures on ephemeral GitHub runner VMs with checkout-specific Supabase containers. The older stabilization checkout was inspected read-only at `b86ad991e7ba2e327876e131442bef4543632ff6`. No provider credentials or hosted projects participated.

| Check | Result |
|---|---|
| Dependency and static checks | Checked npm lock install, uv lock consistency, production-only non-editable install including the packaged security SQL, Ruff lint/format, strict mypy, and generated OpenAPI freshness |
| Unit isolation | 86 passed. Coverage includes remote and cross-project endpoints, DB role/port/path mismatches, shared project refusal, wrong Docker binding, remote daemon refusal, role selection, redacted event output and append-only ledger planning |
| Database | 215 pgTAP assertions across six files. Current migration ledger and the effective TEMP privilege on the API-facing roles verified |
| Backup and restoration | Fresh logical restore. Matching row counts/digests and applied versions. Detected restored default TEMP, a direct TEMP grant and an unreviewed extension. The disposable restored copy passed after the corrective ACL was applied |
| API/Auth | 79 integration tests, including the staging readiness policy over the actual low-privilege connection, fail-closed startup, and the separate metadata-only audit role |
| HTTP | Real Uvicorn process on loopback served the expected liveness and DB readiness JSON |
| Secret scanning | Pinned Gitleaks scanned the introduced Git history with redacted output. This covers its detectors and the reviewed range |
| Shared-stack refusal | The default checkout’s `scripts/disposable.py config` rejected `mon-edupreneur` before a Docker or DB call. The branch changes no existing migration, seed, mobile/Admin code or existing CI job |

Evidence for code commit `96d892f71233c46ecd393f5dbb8ee7f3a736f83b` from the [dedicated workflow](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45885201576) is attached to [draft PR #33](https://github.com/steevy-cpu/edupreneurs-platform/pull/33). The earlier [restore-fixture failure](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45884763888) exposed a table-dependent column privilege lookup during the metadata-reader work. The corrected assertion resolves the column by relation OID and attribute number. The PG17 test operator also needs explicit SET membership to assume the auditor role. That test grant exists only inside a rolled-back transaction. A [separate legacy CI attempt](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45885201577) encountered an occupied runner port 54322 during startup. The new staging job uses its own checkout-derived port lane.

## Outstanding hosted acceptance

- Verify actual Render egress, ingress policy, VM runtime, Python patch, instance memory and graceful rollouts. Measure RTT, load, error rates and sync retries from Haitian carrier networks.
- Verify hosted PG17, direct IPv6 or US-East session pooler support, TLS CA chain and hostname, login mapping, session settings, connection budget, Data API exposure and the managed extension inventory. Unexpected extensions or privileges fail closed.
- Complete staging project registration, separate secret custody, asymmetric signing-key rotation, authorized/withdrawn account smoke tests, and review provider-generated edge logs for personal data.
- Perform a provider backup restore into a **different staging project**, record achieved RTO/RPO and verify cluster roles, passwords, Auth settings and object storage separately. The CI drill restores selected database schemas and data within one disposable cluster. It cannot verify provider recovery, global roles or object bytes.
- Reconcile the exact quote, backup/PITR retention and any workspace fees with the owner before any provisioning. Archive sanitized evidence and name an operator for rollback.

The engineering verdict applies to the reviewed staging design and its disposable rehearsal. Hosted acceptance and authorization remain open.
