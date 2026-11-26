# 2. Roles and permissions

Authorization is **server-enforced** in FastAPI (and, below it, in the SECURITY DEFINER `staff.*` functions). The web app hides what a role
cannot do; hiding is convenience, never security.

## Existing roles (`app.staff_roles`, check constraint) and proposed additions

| Role | State | Purpose |
|---|---|---|
| `editor` | exists | Create and edit own draft revisions, attach sources, submit |
| `reviewer` | exists | Review submitted revisions (cannot review own) |
| `publisher` | exists | Build packs, release, roll back |
| `admin` | exists | Role administration, entitlements grants, schedule, everything below by exception |
| `analyst` | **proposed** | Read aggregated analytics only |
| `support` | **proposed** | Minimal learner lookup, notification resend, entitlement *view* |

Adding `analyst`/`support` edits the frozen baseline constraint → **explicit owner approval and a reviewed migration** (not done here).
A person may hold several roles; effective permission is the union **minus** the separation rules below.

## Matrix (✔ allowed · ◐ limited · — denied)

| Capability | editor | reviewer | publisher | analyst | support | admin |
|---|---|---|---|---|---|---|
| Create / edit **own** draft revision | ✔ | — | — | — | — | — ¹ |
| Attach / detach sources, rights record | ✔ (own) | ◐ read | — | — | — | — ¹ |
| Submit revision | ✔ (own) | — | — | — | — | — ¹ |
| Review / approve / request changes | — | ✔ (not own) | — | — | — | — |
| Build pack, release, roll back, withdraw | — | — | ✔ | — | — | ✔ |
| Word of the Day: draft/edit | ✔ | — | — | — | — | — |
| Word of the Day: review/approve | — | ✔ (not own) | — | — | — | — |
| Word of the Day: schedule, retire | — | — | ✔ | — | — | ✔ |
| Aggregated analytics | ◐ own content | ◐ | ◐ | ✔ | — | ✔ |
| Learner lookup (minimal view, reason required) | — | — | — | — | ✔ | ✔ |
| View answers / profile text of a learner | — | — | — | — | — | ◐ (break-glass, reason + second approver) |
| Grant / revoke entitlement | — | — | — | — | ◐ view | ✔ |
| Grant / revoke staff roles | — | — | — | — | — | ✔ (last-admin protected) |
| Audit log (read) | own actions | own actions | own actions | — | own actions | ✔ all |
| Reward rules, leaderboard policy, feature flags | — | — | — | — | — | ✔ (step-up) |
| Jude AI config / budgets | — | — | — | — | — | ✔ |
| Announcements / notifications | — | — | ◐ draft | — | ◐ | ✔ |

¹ **Admin does not edit or approve other people's drafts** — existing, verified rule (audit M-B2-1, fixed in #4/33aa2e2): an admin could not
previously be a back door to unreviewed content. An admin who needs to author content takes the `editor` role and is then bound by it.

## Separation of duties (enforced server-side; each already exists or is a required test)

1. Reviewer ≠ author of the revision (exists).
2. A submitted revision is frozen; changes need a new revision (exists).
3. Author ≠ publisher for the same revision (**to add**, or documented as owner choice for a very small team).
4. The last usable admin cannot be revoked — including when accounts are banned/deleted (open finding S13).
5. Sensitive actions (release, rollback, withdraw, role change, entitlement grant, flag change) require **step-up** (fresh MFA within 5 minutes).
6. No staff action can be performed by the worker/service identities through the web; they are different database logins.

## Minors and data minimisation

Default analytics are **aggregates with a minimum group size K** (reuse the leaderboard lesson: K ≥ 5; owner decides the value). Individual
learner views exist only for `support`/`admin`, show the least data that solves the ticket, and write an audit row **including reads**.
Exports of learner-level data are not part of Admin-00.
