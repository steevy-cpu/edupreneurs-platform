> Public version: exploitable weaknesses are described as class + impact + fix; reproductions are in the private report.

# Domains fix verification — rewards, word of the day, content format v2, entitlements

Reviewer qa5 (independent) · integration tree `origin/overnight/integration-2026-11-24` @ `34a2e6d` ·
stack `edu-fv-qa5` (Postgres 127.0.0.1:57722), `make db-reset` before starting · 2026-11-25.
Probe scripts are kept with the private report.
local Auth tokens); all SQL "as the API" ran on a real `edu_api_login` connection.

(Sections are written as work progresses; the verdict table is at the end.)

## 1. Gold / rewards

### What was run and seen

**Duplicates (r1_dupes.py, HTTP push, flag on, seed lesson):**
- first correct answer → 1 row `q:<lesson>:addition` 5 Gold; same op id same payload → `replayed`, no row;
  same op id different payload → `conflict op_id_reused_with_different_payload`, no row; new op id same answer →
  no row; Creole revision of the same question → no row; wrong → right → right again on another question → one row;
  completions FR, HT, FR again in one batch → one `l:` row (20) + one achievement (10).
- newer revision of the seed lesson with the **same** question keys (r3 N1): 5 answers + completion → ledger
  unchanged 55 → 55. A newer revision whose keys were renamed (`q1`, `q2`…) pays again (documented L4 behaviour).
- two devices of the same learner pushing the same answer in parallel with different op ids → one row.
- Every processed operation accounted for; `balance = sum(ledger)` and zero duplicated source keys after each step.

**Server computes every amount:** push models are `extra="forbid"`: `payload.gold` → op `rejected invalid_payload`;
`op.amount` and envelope `gold` → 422. As `edu_api_login` with an actor: INSERT ledger, UPDATE balances,
`apply_operation`, `try_award_event`, `set_active_rule_version`, `reconcile_batch`, `staff_adjust` → all 42501.
`award_for_operation(<A's op>)` with actor B → `no_award` (indistinguishable from unknown). The trigger
`validate_ledger_entry` forces amount = rule amount even for owner-side inserts (not re-attacked; read).

**Concurrency (r2_conc.py §C):** 6 rounds × (2 learners × (4 pushes of the identical batch with the same op ids +
2 pushes of 10 answers with new op ids)), 72 pushes, while a worker connection looped `reconcile_batch(5,50)` (392×),
the owner looped `rebuild_balance` + `rebuild_streak` (159×) and `erase_learner(B)` (63×): 72/72 HTTP 200, 456
invariant samples, **0 violations**, 0 errors, 0 duplicate keys; final ledgers exactly 7 rows / 55 Gold per learner
(5 questions + completion + achievement); 0 unexamined after a final reconcile.

**M1 time budget:** with the learner's rewards lock held by another session:
10-op push **220 ms** (all accepted, one `rewards_award_deferred` line, rest of batch skipped), a second push of the
same learner 215 ms. After release, `reconcile_batch` as `edu_worker_login` examined 11 ops, 55 Gold; a second call 0;
replaying the whole batch afterwards changed nothing.
**M1 residual (r2 §M1b/M1c):** any wait inside the reward step that is *not* the advisory lock still costs the full
connection `statement_timeout` (5 s) once per push while the push holds the learner's sync row lock:
owner `LOCK TABLE rewards.processed_operations|balances|rules IN ACCESS EXCLUSIVE MODE` → push 200 in **5018 / 5014 /
5015 ms**; owner row lock `SELECT … FROM rewards.balances WHERE learner_id=A FOR UPDATE` → push **5032 ms**. Learning
committed in every case. All rewards writers in the code take the advisory lock first, so in practice the holders
are DDL (a later migration adding an index/column on `rewards.*`, `CREATE INDEX` without CONCURRENTLY,
`VACUUM FULL`) or manual owner sessions. See new finding QA5-R1.

**Recovery after failure (r2 §R):** `REVOKE EXECUTE … award_for_operation FROM edu_api` → 11-op push 200 in 49 ms,
all accepted, 10 attempts stored, 0 Gold, 11 unexamined. Re-grant; two `reconcile_batch` calls in parallel → one
examined 11 (55 Gold), the other `skipped: 1`; replay + new completion → unchanged 55. Exactly once.

**Flag OFF:** code diff vs `origin/main` is the `on_accepted=… if settings.rewards_enabled else None` argument and one
`if on_accepted is not None` line; with `None` the loop is the original. Responses for push / replay / conflict /
rejected / 422 compared flag off vs on: identical status, header set and body after masking op ids, server-generated
attempt ids, timestamps and request ids.

**Streaks / Haiti day (r3 §S):** `rewards.haiti_day` on explicit instants: 2026-03-08 04:59:59Z → 03-07, 05:00Z → 03-08
(winter UTC−5), DST start 07:00Z → 03-08, 2026-03-09 03:59:59Z → 03-08, 04:00Z → 03-09 (summer UTC−4); 2026-11-01
03:59:59Z → 10-31, 04:00Z → 11-01; 2026-11-02 04:59:59Z → 11-01, 05:00Z → 11-02. `rebuild_streak` over active days
03-07/08/09, 10-31, 11-01, 11-02, 11-04 → longest 3 ending 11-02, current run 1 from 11-04 (non-punitive, no loss field).

**New rules:**
- Evidence (r1 E1/E2): bare completion of a fresh lesson → `awaiting_evidence`, 0 Gold; one **wrong** answer in that
  lesson → completion paid (20 + 10 achievement). Works as documented; the bar is one scored answer of any
  correctness (owner decision, PO-09).
- Caps (r3 K1–K3): test version with day cap 10 → 2 awarded, third `capped_day` and recorded in `forfeited_sources`;
  same question re-sent with a new op id and via the Creole revision → `forfeited` ×2; after switching back to v1
  (cap 300) the same question is still never paid. Caps are now final per source key (binds modified clients).
- `no_active_rule` (r3 NA1–NA3): rule switched off → 2 correct answers `no_active_rule`; `set_active_rule_version`
  → reconcile examined 2, 10 Gold, exactly once.
- Rule-version switch race (r4_race.py): an examination that sees no live version and commits **after** a concurrent
  `set_active_rule_version` switch-on is left `no_active_rule` permanently (the switch's DELETE cannot see the
  uncommitted row and takes no lock that the examination holds). Observed: T1 (`edu_api_login`, actor A)
  `award_for_operation` → `no_active_rule`, T2 switch-on committed in 2 ms, T1 commit → processed row
  `no_active_rule`, `reconcile_batch` examined 0, no Gold for that op; a later *new* op of the same answer is paid.
  See new finding QA5-R2.

### Original findings, one by one
- security **M1** — advisory-lock stall fixed (220 ms once, rest of batch skipped, reconcile heals once); residual
  for non-advisory waits = QA5-R1 (5 s once per push, operator/DDL-triggered). PASS for the finding as reported.
- security **M2** — evidence rule present, default on, tested both ways; the evidence is one scored answer of any
  correctness, so a script still earns completion Gold by answering one question wrong. PASS (as designed; bar is an
  owner call).
- security **L1** — caps final per source key (`forfeited`) — PASS.
- security **L2** — erasure: `account.erase_learner` calls the registered `rewards` hook and deletes receipts/attempts/
  profile in the same transaction (read: `20261124020500_account_review_fixes.sql:266-452`, hook order table
  `account.erasure_hooks`); `rewards.erase_learner` holds the learner lock until commit. PASS by reading; the race
  test is the lane's own, I did not re-run an orchestrator-plus-summary race.
- security **L3** — ledger cursor now `{"v":2,"a":<account tag>,"t":<µs>,"i":<entry id>}`, no global seq
  (`rewards/cursor.py:5-52`). PASS.
- integration **M3** — dating rule documented (lane doc "Dating rule"); behaviour unchanged (by design). PASS (docs).
- integration **L2** — still open as documented (rule chosen at examination time). Confirmed open.
- integration **L3** — `no_active_rule` not final, healed by `set_active_rule_version` — PASS, except QA5-R2 race.
- integration **L4** — documented; behaviour reconfirmed (renamed keys pay again, same keys do not). PASS (docs).
- integration **L5** — open as documented (not built). Not re-measured.
- integration **L6** — open as documented (no Cache-Control / as_of). Not re-measured.

### New findings (rewards)

**QA5-R1 — LOW — reward step still has no statement/lock budget for non-advisory waits.**
Location `services/api/src/edu_api/rewards/hook.py:49-51@34a2e6d`, `supabase/migrations/20261124050200_rewards_functions.sql:491-509@34a2e6d`.
Evidence above (5014–5032 ms pushes with an ACCESS EXCLUSIVE lock on a rewards table or a row lock on the
learner's balance row). Bounded to once per push (was N × 5 s), but a routine future migration on `rewards.*`
(e.g. `CREATE INDEX` on `rewards.ledger`) turns every push of every active learner into a ≥5 s request for the length
of the migration, each holding a pooled connection and the learner's sync row lock. Smallest fix: inside the
savepoint run `SET LOCAL lock_timeout = '200ms'` and `SET LOCAL statement_timeout = '500ms'` before the award (and
restore the outer values after RELEASE, since SET LOCAL survives a released savepoint), plus a test with an
ACCESS EXCLUSIVE lock on `rewards.processed_operations`.

**QA5-R2 — LOW — `no_active_rule` decisions written concurrently with a switch-on are never re-examined.**
Location `supabase/migrations/20261124050200_rewards_functions.sql:457-482@34a2e6d` (`set_active_rule_version`
deletes only committed `no_active_rule` rows) and `:226-229` (`try_award_event` reads `rules` without a lock).
Impact: an honest learner whose push was in flight during an operator's switch-on
silently loses that Gold; the window is one push transaction long. Smallest fix: do not write a
`processed_operations` row for `no_active_rule` (let reconcile retry), or have `try_award_event` read the rule
`FOR SHARE` so the switch's `FOR UPDATE` waits for in-flight examinations.

## 2. Word of the day

Fix under test: `supabase/migrations/20261124040400_vocab_review_fixes.sql@34a2e6d` (per-date exclusive advisory lock
taken by `guard_daily_assignment` on an accepted UPDATE/DELETE; learner read `vocab.daily_word_at` takes the shared
side with `pg_try_advisory_xact_lock_shared` and serves nothing if it cannot; `TRUNCATE` statement triggers;
`vocab._clock()` seam honoured only when `session_user = 'postgres'`). Probes `v1_vocab.py`, `v2.py`, `v3.py`; the app
was built with `daily_word_enabled=True` and the staff pool (`staff_database_url` = `edu_staff_login`), real tokens
for the seed editor and reviewer; for the probe the reviewer was additionally granted `publisher` and the editor
`reviewer` (removed afterwards).

**Editorial rules over HTTP `/v1/staff/vocab`:** rights cleared by an editor → 403; by a publisher → 200. Review of an
unsubmitted draft → 409 "Only a submitted word revision can be reviewed"; submit by a non-author → 403; author who
also holds `reviewer` approving own → 409 "Author cannot review own word"; learner → 403; a different reviewer → 200.
Edit of an approved revision → 409 immutable; audio added to an approved revision → 409 immutable. Scheduling a word
with no approved, rights-cleared French revision → 409; scheduling by an editor → 403.

**Opened day (real clock):** publisher `PUT /schedule/<today>` and `DELETE /schedule/<today>` → 409 "already opened";
retire of today's word → `rows: 0`, learner still gets the same revision id. Over `edu_staff_login`, a session that
sets `vocab.test_clock` to 2020 still gets the real clock (`vocab._clock()` itself is not executable: 42501;
`schedule_word(today)` refused). Owner `TRUNCATE vocab.daily_assignments` and `… CASCADE` → refused
"This table cannot be truncated" (F2 fixed).

**F1 mechanism (owner clock seam):** owner session with `vocab.test_clock` = 23:30 the previous evening updated
today's French row (accepted, exclusive key taken), then `SET CONSTRAINTS ALL IMMEDIATE`, transaction left open:
learner `GET /v1/daily-word` → **404 in 3 ms** (no old word, no wait); after rollback → 200 with the original word.
Since the guard refuses UPDATE/DELETE of an opened or frozen day *before* taking the lock, the exclusive key of day
D can only be taken before D's freeze; readers of D only exist after D opens, so no reader can see D's old word and
later a new one. The lane's tests `test_plain_commit_after_midnight_is_refused`,
`test_change_held_open_across_midnight_is_never_seen_as_a_changed_word`,
`test_refused_attempt_on_an_opened_day_does_not_hide_its_word`, `test_truncate_is_refused_even_for_the_owner`
(`tests/integration/test_vocab_schedule.py:337-420`) and `supabase/tests/165_vocab_guard_clock.sql` cover F1–F3
behaviourally through the seam (F3 fixed). I did not re-run them in isolation (they are part of the suites below).

**Availability probe:**
- Normal staff work: 60 schedule/unschedule calls on days today+2…today+6 (0.73 s) while 4 learner loops read
  today's word: **475 reads, 0 non-200**, one term. Editors/publishers changing other days never blank today.
- A publisher withdrawing the rights of today's source → learner 404 immediately; restoring → the same revision id
  returns (NOTE N1 of the original review, by design; it is the one *normal* staff action that hides today's word).
- Any raw database session on one of the three login roles can make today's word unavailable for as long as it keeps a transaction open (lock-based class; learner read answered 404 without waiting). Integrity holds. See QA5-V1.

### New findings (word of the day)

**QA5-V1 — LOW — today's word can be suppressed by any login role holding an advisory key; the outage is reported to
learners as "no word today".** Location `20261124040400_vocab_review_fixes.sql:181-183@34a2e6d`
(`pg_try_advisory_xact_lock_shared` → `RETURN` nothing) and `routers/daily_word.py` (404 mapping). Impact: availability only (integrity
holds); requires a SQL session (credential leak / injection), but the API's own login suffices. Also, a legitimate
lock wait is indistinguishable from "no word" (404 with `no-store`). Smallest fix: return a distinct outcome when
the shared lock is unavailable (503 `daily_word_busy` + `Retry-After: 1`); revoke `EXECUTE` on
`pg_advisory_*lock*` from `edu_api`/`edu_worker` if no other lane needs them (rewards/sync use them inside definer
functions, which run as the owner), and bound `idle_in_transaction_session_timeout` / `transaction_timeout` for the
login roles.

**QA5-V2 — NOTE — `/v1/staff/vocab/*` are not behind `daily_word_enabled`.** With the flag off and the staff pool
configured, `GET /v1/staff/vocab/review-queue` as the reviewer → 200 (staff routes are gated by the staff side:
503 `staff_unavailable` when unconfigured). Probably intended (staff prepare content before launch); state it in the
lane doc because RULES say new routes answer the standard 404 while their flag is off.

## 3. Content format v2

Probes `c1_content.py` (validators + `lesson-blocks.v2.schema.json` via `jsonschema`, starting from the vector
`v2-every-new-block-type`), `c2_h1.py`, and SQL on `content.blocks_accountable` / `content.block_asset_hashes` /
baseline `app.lesson_revisions` as the owner inside rolled-back transactions.

- **H1** — `_verify_lesson_object` now requires `required_format(blocks, kinds) == lesson.content_format`, unknown
  kinds are refused, a lesson's format may not exceed the manifest's (`pack.py:701-765@34a2e6d`); vectors
  `v-format-1-pack-with-numeric-question`, `v-format-1-lesson-with-numeric-question-in-format-2-pack`,
  `v-lesson-declares-more-than-it-needs`, `v-format-1-lesson-with-format-2-block`, `v-format-1-pack-lists-format-2-lesson`
  are verifier-side. `required_format(…, ["bogus"])` raises `ValueError` (caught upstream by the kind check).
  No fresh bypass found by reading; my attempt to mutate a manifest directly did not locate one in the vectors
  (vectors hold pack descriptions), so the schema-side `if/then` was not independently re-attacked. PASS (by reading
  + lane vectors run in the suite).
- **H2** — hash binding fixed: the function takes `bytea`, computes `sha256(p_manifest)` / `octet_length` itself
  (`20261124030200…sql:112-124`). Body gate only partly fixed: `content.blocks_accountable` checks **top-level**
  keys per block type and a top-level `asset.sha256`, nothing nested. Several nested, non-contract shapes (media references and non-string text values below the top level of a block) are accepted as accountable.
  `content.block_asset_hashes` does not see nested references, so it escapes the attachment/rights gate —
  the same class as original H2(c). The baseline table accepts all four bodies (owner INSERT succeeded, rolled back),
  and `staff.create_revision` / `update_revision` (`20261124010200_staff_editorial.sql:74-90`) check only that
  `blocks` is a 1–200-element array under 256 KiB, so an `edu_staff_login` session with an editor actor can author
  them; the HTTP staff editorial API cannot (its pydantic `Block` model is format-1 and strict). End-to-end
  (`record_release_manifest` → `ready` → `staff.release_pack` → `/v1/lessons`) was NOT run for lack of time; the
  component results above are the evidence. FAIL (partial fix). See QA5-C1.
- **M1** — raw-source markup now refused (`<img …>`, `\text{<img …>}` → `math.text` / schema). Fresh bypass class: markup split across adjacent text runs passes validator and schema;
  the *rendered* text is element-shaped once the runs are concatenated. Only matters for a renderer that emits text runs
  into HTML unescaped, which the README's rendering rule forbids. PASS with residual QA5-C2.
- **M2** — root index, scripts, `\frac`, `\overline`/`\vec` and plain groups all count: depth 4 accepted, 5/6/39
  refused (`math.depth`) for every construct and a 5-way mix; 100 000-deep braces, 50 000 nested `\sqrt[`, 100 000
  `x^`, 200 000 backslashes → error codes in < 1 ms, no `RecursionError`; 1 000 000 `(` → valid in 331 ms when
  called directly (length is capped at 400 by the schema layer). PASS.
- **M3** — `verify_pack` recomputes totals and refuses duplicate lesson ids, revision ids, question ids and question
  positions, lesson title plain text (`pack.py:684-705`); vectors `v-totals-*`, `v-lesson-listed-twice`,
  `v-*-twice`, `v-title-*`. PASS (by reading + vectors).
- **M4** — the listed classes are refused (U+202E → "invisible or direction-changing characters are not allowed" in
  alt and list item). Fresh bypass: the class is a hand-picked list; these invisible / format characters pass the
  validator **and** the schema in alt text and list items: U+061C ARABIC LETTER MARK (a bidi mark), U+00AD soft
  hyphen, U+034F, U+180E, U+2061–U+2064 invisible operators, U+206A–U+206F, U+FE0F variation selector, U+E0041
  tag characters (invisible "ASCII smuggling"), U+3164 Hangul filler, U+FFF9 interlinear annotation, U+1D173
  musical formatting. FAIL (partial). See QA5-C3.
- **`/v1/catalog`, `/v1/lessons`:** routers and sync service carry no content-lane change
  (`git diff origin/main` empty for `routers/catalog.py`; baseline migrations, seed, `supabase/tests/0*`, conftest,
  helpers byte-identical). Through HTTP nothing new can be authored (staff editorial model is format-1). There is
  still no activation gate on content format (`staff.release_pack` / `switch_current_pack` never consult
  `content.release_required_format` or `content.pack_manifests`), so a format-2-shaped body written through a raw
  staff SQL session could be released and served verbatim by `/v1/lessons` (not run end-to-end). Condition of the
  original review ("before any format-2 content ships, an activation gate must exist") still unmet.

### New findings (content)

**QA5-C1 — MEDIUM — the H2 body gate does not look below the top level of a block.** Location
`supabase/migrations/20261124030200_content_manifest_bytes_and_body_gate.sql:42-77@34a2e6d` (`blocks_accountable`),
`content.block_asset_hashes`. Evidence above. Impact: media references in non-contract nested shapes (and non-string
text values) pass the gate and escape the attachment/rights check, for a release finalised from SQL-authored bodies.
Precondition: an `edu_staff_login` session with editor + reviewer + publisher actors (or the owner). Smallest fix:
validate the full shape in SQL (every value type per property: strings for text fields, arrays of strings for
`items`/`steps`/`columns`, arrays of arrays of strings for `rows`, `asset` objects with exactly the contract keys) —
or, better, have the staff API run `validate_blocks` at submit/approval and make `record_release_manifest` callable
only by the build step after `verify_pack`; add negative pgTAP cases for each nested shape above.

**QA5-C2 — LOW — math markup rule is per-source, not per-rendered-text.** `content/math_notation.py:66,252` and
schema `$defs.math.source`. Markup split across adjacent `\text{}` runs renders as element-shaped text. Fix: apply the no-markup rule to
the concatenation of `\text{}` runs and literals (or refuse `<` as the last character of a `\text{}` run), plus a
vector; keep the README rule that `source` never reaches an HTML engine.

**QA5-C3 — LOW — invisible-character rule misses Unicode format characters.** `content/issues.py:28-30` and
`$defs.noInvisible` in both v2 schemas. Fix: refuse general categories Cf, Cc, Co, Cs, Cn (ECMA `\p{Cf}` etc. with the
`u` flag) plus the Hangul fillers U+115F, U+1160, U+3164, U+FFA0, instead of a hand list; add vectors for U+061C,
U+00AD, U+2061, U+E0041.

## 4. Entitlements

Probe `e1_ent.py`; app built with `entitlements_enabled=True` and the staff pool; the seed reviewer was granted
`admin` for the probe (removed afterwards).

- **M1** — `POST /v1/staff/billing/grants` with `idempotency_key` `order:<uuid>`, `order:<uuid minus one char>`,
  `order::<uuid>` → **422**; owner `billing.grant_entitlement(…, 'gift', …, 'order:<uuid>')` → 22023 "This
  idempotency key prefix is reserved". `ORDER:<uuid>`, `Order:<uuid>`, `x.order:<uuid>` → 200, but the unique index is
  on the exact text (`entitlements_idempotency_key_key … btree (idempotency_key)`) and purchase keys are lower-case
  `'order:' || uuid` (`billing_functions.sql:657`), so these cannot collide. Staff sources exclude `purchase`
  (SQL `:345` and `StaffGrantSource`). PASS. (Still open, documented: `apply_provider_event` raises instead of
  storing a rejected event if a collision ever happened.)
- **L1** — reproduced, open as documented: grant → revoke → same key with `reason_code: trial` → `200
  replayed: true`, same entitlement id; learner `GET /v1/entitlements` shows no active grant.
- **L2, L3, L4** — open as documented in `docs/overnight-2026-11-24/lanes/entitlements.md:110-117`; not re-run.
- **No paywall:** `/v1/catalog?locale=fr`, `/v1/lessons/<seed>?locale=fr|ht`, a push and a pull compared between
  (a) flag off, (b) flag on, (c) flag on with `REVOKE USAGE ON SCHEMA billing FROM edu_api` (restored afterwards):
  identical status and body after masking server-generated ids/timestamps (the pull differed only in the new
  attempt's `entity_id`). With billing unreachable `/v1/entitlements` → 503 `entitlements_unavailable`.
  Catalogue/lesson/sync code has no reference to billing.
- **Simulated provider:** no route mentions provider messages (`routers/entitlements.py:6`, `staff_billing.py:7`);
  no module outside `billing/mock_provider.py` imports `MockProvider` (services and scripts searched); EXECUTE on
  `billing.apply_provider_event` held by `postgres` only; `billing.providers` has 0 rows; the constructor refuses
  any environment other than `local`/`test` (caller-supplied string, documented N-note). PASS.

## Verdict table (all on `34a2e6d`)

| ID | Original defect | Reproduction result (this review) | Fix assessment | Remaining exploit / regression path | Test coverage | Verdict |
|---|---|---|---|---|---|---|
| RW-sec H1 | definer search_path `''` | not re-attacked; all rewards functions read `pg_catalog, pg_temp` (migration text) | fixed | — | structure test 180 (in suite) | NOT_VERIFIED (read only) |
| RW-sec M1 | push stalls N×5 s on busy rewards lock | squatted advisory key: 10-op push 220 ms, 2nd push 215 ms, all accepted; reconcile once (55 Gold), replay unchanged | fixed for the advisory lock (200 ms try-lock, skip rest of batch) | any non-advisory wait (DDL / ACCESS EXCLUSIVE / row lock on `balances`) still 5.0 s once per push (QA5-R1) | `test_a_busy_rewards_lock_cannot_stall_a_push` (advisory case only) | PASS (residual QA5-R1) |
| RW-sec M2 | Gold without evidence of learning | bare completion → `awaiting_evidence`; one *wrong* answer releases 20+10 | as designed (PO-09 parameter, default on) | a script answers one question wrongly to earn completion Gold | lane tests both settings | PASS |
| RW-sec L1 | caps only bind honest clients | day cap 10: 3rd answer `capped_day`, re-sent/new op/Creole → `forfeited`, never paid even after cap raised | fixed (forfeited_sources) | — | lane tests | PASS |
| RW-sec L2 | erasure undone by summary | read: orchestrator calls rewards hook then deletes receipts in one tx; erase holds lock | fixed by contract | orchestrator+summary race not re-run by me | lane test | PASS (by reading) |
| RW-sec L3 | cursor leaks global seq | cursor v2 = account tag + µs + entry id | fixed | — | unit test | PASS |
| RW-int M3 | late rows / reversals vs closed periods | dating rule documented; behaviour unchanged | documented | leaderboard must snapshot | — | PASS (docs) |
| RW-int L2 | rule chosen at examination time | open as documented | not built | — | — | open (confirmed) |
| RW-int L3 | `no_active_rule` final | off → 2× `no_active_rule`; `set_active_rule_version` → reconcile 2 ops / 10 Gold once | fixed | switch-on racing an in-flight examination leaves it final (QA5-R2, reproduced) | lane test (no race test) | PASS (residual QA5-R2) |
| RW-int L4 | source key depends on editorial discipline | same keys in newer revision: 55→55; renamed keys pay again | documented | content tooling must keep keys | lane tests | PASS (docs) |
| RW-int L5 | read path at volume | not re-measured; open as documented | not built | — | — | open (documented) |
| RW-int L6 | thin provisional contract | not re-measured; open as documented | not built | — | — | open (documented) |
| RW dupes/amounts/concurrency/flag-off/streaks | (task items) | all 9 duplicate scenarios one row each; 72-push storm with reconcile/rebuild/erase: 456 samples, 0 violations; extra fields rejected; API login 42501 on every write/internal fn; flag off ≡ on responses; Haiti-day edges correct | — | — | lane + my probes | PASS |
| WOTD F1 | reschedule committed after day opened | owner-clock simulation: open change → learner 404 in 3 ms, never old→new; staff login cannot use seam; today refused over HTTP | fixed (integrity) | availability: any login holding the date key blanks today (404) — QA5-V1 | 4 integration tests + pgTAP 165 | PASS (residual QA5-V1) |
| WOTD F2 | owner TRUNCATE | TRUNCATE and TRUNCATE CASCADE refused for owner | fixed | owner can still disable triggers (out of scope) | `test_truncate_is_refused_even_for_the_owner` | PASS |
| WOTD F3 | no commit-time tests | tests exist and use `vocab._clock()` seam | fixed | — | `test_vocab_schedule.py:337-420`, pgTAP 165 | PASS |
| WOTD editorial | approval by a different reviewer | HTTP: own approval 409, unsubmitted 409, non-author submit 403, learner 403, other reviewer 200; approved/audio immutable; unapproved word cannot be scheduled | holds | — | lane tests | PASS |
| CT H1 | format-1 pack with format-2 kind | read verifier: exact `required_format` per lesson; lane vectors verifier-side | fixed | schema `if/then` not independently attacked | `vectors/pack-verify.json` | PASS (by reading) |
| CT H2 | record_release_manifest trusts hash/bodies | hash computed from bytes (fixed); `blocks_accountable` = true and `block_asset_hashes` empty for nested asset/URL/object-text shapes | partial | nested media escapes rights gate (QA5-C1); no format activation gate | pgTAP 140/142 (top-level only) | FAIL |
| CT M1 | markup in math source | raw markup refused; markup split across text runs passes | fixed for raw source | rendered-run concatenation (QA5-C2) | math vectors | PASS (residual QA5-C2) |
| CT M2 | depth bypass / RecursionError | depth 5 refused for every construct; huge inputs <1 ms, no exception | fixed | — | math vectors | PASS |
| CT M3 | totals / duplicates | read + vectors | fixed | — | pack-verify vectors | PASS (by reading) |
| CT M4 | invisible / bidi chars | listed set refused; U+061C, U+00AD, U+2061–4, U+206A–F, U+FE0F, U+E0041, U+3164 … accepted (validator and schema) | partial | QA5-C3 | plain-text vectors (listed set only) | FAIL |
| CT delivery | `/v1/catalog`, `/v1/lessons` unchanged | no diff; HTTP authoring is format-1 only | holds over HTTP | raw staff SQL body + `staff.release_pack` has no format gate (not run end-to-end) | — | PASS (HTTP) |
| EN M1 | staff key collides with purchase key | `order:` keys 422 / 22023; case variants accepted but unique index is exact text | fixed | `apply_provider_event` still raises on collision (documented) | pgTAP 222 + HTTP test | PASS |
| EN L1 | replay of revoked grant says granted | reproduced: 200 `replayed: true`, learner has nothing | open | as documented | — | open (confirmed) |
| EN L2–L4 | plan snapshot / erasure / refund-before-pay | documented open; not re-run | open | as documented | — | open (documented, NOT_VERIFIED by run) |
| EN no-paywall | catalogue/lesson/sync identical | off vs on vs billing USAGE revoked: identical (masked); entitlements 503 | holds | — | lane tests | PASS |
| EN simulated provider | no apply outside local/test | no route, no importer, EXECUTE owner-only, 0 providers, constructor env guard | holds | — | lane tests | PASS |

## Suites

All counts after `make db-reset`.

| Command (after `make db-reset`, `34a2e6d`) | Result |
|---|---|
| `make test-db` before pytest | 42 files, **3025** tests, PASS |
| `uv run pytest -q` (flag off) | **1754 passed** (104 s) |
| `EDU_REWARDS_ENABLED=true uv run pytest -q` | **1754 passed** (113 s) |
| `make test-db` after both pytest runs | 42 files, 3025 tests, PASS |

Baseline files (four `20261121*` migrations, `seed.sql`, `supabase/tests/0*.sql`, `tests/conftest.py`,
`tests/helpers.py`): `git diff origin/main` empty.

## Overall verdict

Gold ledger: exactly-once, server-computed amounts and concurrency hold under every scenario run; M1 fixed for the
advisory lock, with two LOW residuals (QA5-R1, QA5-R2). Word of the day: the owner guarantee holds (F1–F3 fixed);
availability residual QA5-V1 (LOW). Content v2: **H2 and M4 are only partly fixed** (QA5-C1 MEDIUM, QA5-C3 LOW);
H1, M2, M3 hold; M1 holds with a rendering-level residual (QA5-C2). Entitlements: M1 fixed, L1 reproduced and still
open, the no-paywall guarantee and the simulated-provider confinement hold.

## Not examined

The rewards H1 search-path fix was read, not re-attacked. No end-to-end run of `record_release_manifest` →
`release_pack` → `/v1/lessons` with a nested-shape body (component-level evidence only). JSON-schema `if/then` for
H1 was not attacked on its own. Entitlements L2–L4 were not re-run. Lane tests were not mutation-tested. Not
examined: native app, load beyond about 70 concurrent pushes, a real midnight, lint/typecheck/OpenAPI checks.
