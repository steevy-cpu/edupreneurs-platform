# Correction plan for the open findings of PR #21 (final verification, 2026-11-25)

Companion to [`FINAL_AUDIT.md`](FINAL_AUDIT.md). It orders the work, names the owner decisions that
gate it, and says what "done" means for each item. **No item here enables a learner-facing feature,
deploys anything, or touches the owner's shared database.** Everything is implemented on isolated
branches and stacks, as separate draft PRs stacked on the lane PR they correct.

## Working rules for every item

1. **Implementer ≠ reviewer.** One agent writes the fix; a different agent re-runs the *original*
   reproduction and tries new bypasses (the audit's lesson: three "fixed" items were only partly fixed).
2. **A regression test that fails before the change and passes after**, stated in the PR.
3. **Isolated stack per worktree** (own Docker project and ports) and, for mobile tests, only the
   hardened harness (PR #20 / #15) — never the shared `mon-edupreneur` stack.
4. **Gate:** `make lint && make typecheck && uv run python scripts/export_openapi.py --check &&
   make db-reset && make test-db && uv run pytest -q && make test-db` (+ `EDU_REWARDS_ENABLED=true
   uv run pytest -q` when rewards code is touched; mobile `tsc` ×2 + `jest` for app changes).
5. **Flags stay off.** A flag is switched on only after its row in the "enablement gates" table below.
6. After any "keep both sides" merge resolution: run the duplicate-registration check (item X-2).

## Wave 0 — landing the hardening (owner review, no new engineering)

| # | Item | Notes |
|---|---|---|
| 0-1 | Review and merge PR #20 into `main` | Closes S1 (temp-schema shadowing) and S4 (shared-stack truncation) on `main`. See the PR #20 verdict. |
| 0-2 | Re-point #15 / #4 after #20 | #15 and #4 carry the same changes as #20 in their own trees; after #20 merges, rebase-free reconciliation by merging `main` into them (no history rewrite). |

## Wave 1 — fixes that need no owner decision (small; parallelisable)

| # | Finding | Fix | Done when | Size |
|---|---|---|---|---|
| 1-1 | **LB-R1** leaderboard refresh resurrects a withdrawn learner at REPEATABLE READ / SERIALIZABLE (#19) | `refresh_snapshot` refuses any isolation level other than READ COMMITTED (or locks and re-reads the membership rows it scores) | two-connection test at RR and SERIALIZABLE reproduces before and passes after, including the frozen-week case | S |
| 1-2 | **LB-R2** `min_cohort_size` can be set to 1, restoring the small-cohort leak | hard lower bound in the CHECK (value is the owner's; propose 5, raise-only through a documented migration) | cohorts of size bound−1 and bound tested; setting 1 is refused | S |
| 1-3 | **LB-R4** cohorts flag enforced only in the service layer | pass the flag into the SQL read (or a separate function) so a direct database call cannot return the cohort block | direct call as `edu_api_login` returns no cohort block with the flag off | S |
| 1-4 | **S6 / QA5-C1** content body gate misses nested values and nested asset references | recursive walk in SQL over an allow-list of keys and value types; asset-hash discovery covers nested references; the staff API runs the Python validators at submit **and** approval (defence in depth) | the reviewer's nested-media-link and non-string-text bodies are refused; rights check sees nested assets; all existing vectors pass | M |
| 1-5 | **S12 / QA5-C3, C2** invisible-character rule is a hand list; markup split across adjacent `\text{}` pieces | refuse whole Unicode categories (Cc, Cf, Co, Cs, Cn) plus Hangul fillers and tag characters in **new v2 fields** (validators, JSON schemas, vectors, `content.is_locale_text_map`); apply the markup rule to the *rendered* math text | new vectors for each class; schema and validator agree; v1 block types untouched (owner decision, see Wave 2) | M |
| 1-6 | **NF-2** follow-through | PR #18 merged; add attach/detach routes only through the author-checked functions | route test: non-author gets 403 | S |
| 1-7 | **S13 / L-B2-4** last-admin check ignores banned/deleted accounts | join `auth.users` in `revoke_role` | zero-usable-admin case refused | S |
| 1-8 | **S11 / QA5-V1** any service login can blank today's word by holding the day's advisory key | return 503 + `Retry-After` instead of 404 when the key is busy; do not grant the advisory-lock functions to the logins | test with a held key; learner sees a retryable error, never a missing word | S |
| 1-9 | **Rewards** `FOR SHARE` on every award | switch to `FOR KEY SHARE`; measure | two-connection race test still passes | S |
| 1-10 | Operational: restore procedure | the TEMP revoke is a database-level privilege and is **not carried by a plain `pg_dump -Fc` restore into a new database** (verified on PR #20's stack). Document and automate a post-restore assertion | runbook step + a check script that fails if any API role holds TEMP | S |
| X-1 | Deploy-time readiness assertions | refuse to start the API/worker when an API role holds TEMP or when the installed-extension list differs from an allow-list (also the only available mitigation for NF-1 until the hosted behaviour is known) | assertion script + test | S |
| X-2 | Merge-conflict class | one test asserting every `include_router` is unique and every route path+method registers once; the same for duplicated settings fields | fails on the three historic duplicates | S |

## Wave 2 — gated by owner decisions

### 2-A Account erasure (S3, M-3; the audit's highest open privacy risk)

**Decision needed first (PO-04 + legal):** how an erased learner's Auth account is removed, and whether
a minimal, time-limited tombstone of the erased user id may be kept.

*Problem:* after `account.erase_learner`, a still-valid access token can still call the API; the API
creates a profile on every authenticated request, so the learner reappears (in 8 tables, via sync,
onboarding or export). The Auth user cannot be deleted first because foreign keys to `auth.users`
are `RESTRICT`, and verification is local (a ban does not invalidate an existing JWT).

*Recommended design (needs the decision):*
1. Executor order: **tombstone → revoke Auth sessions / ban → erase → delete Auth user → purge the
   tombstone after the maximum token lifetime.** The tombstone is a single row (user id, timestamp)
   retained only for that window; retention is the owner's decision.
2. The API refuses requests whose token subject is tombstoned (401), before any profile creation;
   profile first-contact creation is refused for tombstoned ids.
3. The worker path stays bound to an open deletion request; add the cooling-off period and a reason
   code on the staff path (both open in the identity review).
4. Wire erasure to a worker job and a staff-admin route (today it exists as database functions only).

*Independent of the decision (can start in Wave 1 as separate PRs):*
- extend the postcondition to sweep text/jsonb/`uuid[]` columns and unlogged tables (L-3);
- a CI test that every schema with a foreign key into `app.learner_profiles` is registered in
  `account.erasure_hooks` and that an unregistered one fails erasure closed;
- an "erase a learner who has rows in every schema" end-to-end test on the integration tree.

*Verification:* the reviewer re-runs the original H-1/M-3 sequence **through the API** (token replay
after erasure must give 401 and recreate nothing, in all 8 tables), plus the cross-lane row sweep.

*Plan B (also an owner decision):* if the hosted platform does not allow `postgres` to set
`session_replication_role` (unverified), replace trigger suspension with a reviewed change to the
append-only trigger function (an erasure marker honoured only for the owner). That edits the frozen
baseline and therefore needs explicit approval. **Hosted verification is a prerequisite either way.**

### 2-B Content format v2 (shippability)

Not shippable until the reviewer's six preconditions exist. Beyond 1-4 and 1-5:

| # | Item | Gate |
|---|---|---|
| 2-B1 | Activation gate: a release can become current only with a recorded manifest row, and `/v1` delivery refuses `content_format > 1` | none (implement in the staff release function; owner-only SQL can still bypass — documented) |
| 2-B2 | Format-aware delivery (`Edu-Content-Formats`, `negotiate`), with a test that a client without the header never receives format 2 | PO-08 |
| 2-B3 | `app` migration for new question kinds + server scoring wired to the versioned rules | edits the frozen baseline → explicit owner approval |
| 2-B4 | One format-character policy (bidi overrides, zero-width, U+2028/2029, BOM) for lesson text, vocabulary and notes; NFC normalisation *before* validation; whether v1 block types are tightened | editorial/owner decision |
| 2-B5 | Plain-text rendering rule written into the contract; remaining low findings (L2, L4, L6–L8 of the content review) | PO-08 |

### 2-C Leaderboard policy (before any flag)

| # | Decision | Engineering after the decision |
|---|---|---|
| 2-C1 | Who may consent for a minor; whether real children ever see a rank; pseudonym policy (PO-04) | consent record + audit of opt-in/opt-out (LB-8); only then the opt-in routes |
| 2-C2 | Refresh policy: fixed batched schedule, never immediately after a single consent event; optionally banded sizes (LB-R3) | scheduler job + test that no refresh is triggered by a consent write |
| 2-C3 | The value of K and its floor | wired in 1-2 |
| 2-C4 | Class/school cohorts (PO-13) | cohort page and staff routes — **not built; do not build before 2-C1** |

## Wave 3 — onboarding and the native app

| # | Finding | Fix | Verification |
|---|---|---|---|
| 3-1 | **D2** at font scale 2.0 the next step opens still scrolled | reset scroll (or remount) on step change | emulator at 1.0 / 1.3 / 2.0, fr and ht |
| 3-2 | **D1** chip labels touch the border when wrapping | smaller radius / padding when the label wraps | emulator |
| 3-3 | **"7AF" note, diagnosed by source reading:** Accueil's notice (`homeNoSelection`) says *class and subject* and shows until **both** exist; onboarding sets the class and deliberately clears the subject, so the notice stays. Not a data-flow defect (my audit text said "class… needs investigation"; this corrects it) | when the class is known say "Choisis ta matière" (with a button to Apprendre); consider a subject step or a default when a catalogue is downloaded | emulator + a component test; confirm both fr and ht copy |
| 3-4 | Offline Profil shows "Tout est synchronisé" beside "Serveur injoignable"; no feedback after a manual sync that gets a 503 | one status model for the sync line; visible result of a manual sync | component tests + emulator |
| 3-5 | Haitian Creole: ≈106 draft strings (incl. "Men lis klas yo abitye.") | native-speaker/educator review | signed-off string table |
| 3-6 | The overnight native fixes (stale "word of the day" label, device-clock handling, sync spacing, grade prefill, stale streak) were **never re-reviewed** | independent source re-review | report |
| 3-7 | Flags-on validation: Word of the Day freshness, Gold pending vs confirmed, leaderboard preview, account switching | run the app on an emulator against the integration backend (API from the corrected candidate, flags on, on an isolated stack) | screenshots + notes |
| 3-8 | Physical-device pass | a real low-RAM Android phone (API 24-class), including large text and a real offline session | recorded test notes |
| 3-9 | Flags-off equivalence of the production bundle | rebuild on the final commit and re-inspect | bundle check |

## Enablement gates (what must be true before any learner-facing flag is switched on)

| Flag | Gate |
|---|---|
| `EDU_PROFILE_EDIT_ENABLED`, `EDU_ONBOARDING_ENABLED` | 3-1…3-4, 3-6; Creole review (3-5); device pass (3-8) |
| `EDU_ACCOUNT_LIFECYCLE_ENABLED` | **2-A complete and re-verified**, PO-04 decided |
| `EDU_DAILY_WORD_ENABLED` | rights decisions; 1-8; content review of the first real words; Creole review |
| `EDU_REWARDS_ENABLED` | PO-09 decided; 1-9 |
| `EDU_LEADERBOARD_ENABLED` / `…_COHORTS_ENABLED` | 1-1, 1-2, 1-3, 2-C1, 2-C2 and a fresh independent privacy re-review of the finished feature |
| `EDU_ENTITLEMENTS_ENABLED` | PO-01/05/06/07; the low entitlement findings |
| `EDU_NOTIFICATIONS_ENABLED`, `EDU_RATE_LIMIT_ENABLED` | PO-10; the app must refresh tokens before expiry (NAT finding L-4); a gateway limiter |
| any staff surface reachable from a network | staff MFA (design → implementation), a content takedown route, X-1 |

## Platform items outside the code

| Item | Action |
|---|---|
| **NF-1** Supabase `supautils` lets service logins run privileged-extension DDL | verify on the hosted project; raise with Supabase; X-1 as the interim guard |
| Hosted `session_replication_role` for the erasure function | verify on the hosted project (prerequisite of 2-A) |
| Scheduled work (reconcile, daily-word fill, leaderboard refresh, notification delivery) | a worker deployment and schedules do not exist; design them with the owner |

## Suggested order

1. Merge PR #20 (Wave 0).
2. Wave 1 in parallel, each as a small stacked draft PR; independent re-review of 1-1, 1-2, 1-4, 1-5 (the privacy- and content-critical ones).
3. Owner decisions for 2-A, 2-C1/2-C2 (they gate the most valuable remaining work).
4. 2-A, then 2-C; 2-B in parallel once PO-08 is decided.
5. Wave 3 with an integrated emulator run, then a real-device pass; only then discuss enabling any flag, one at a time.
