# Lane NOTIFY — notification outbox with a dummy adapter (Part A)

Branch `overnight/notify-security` · schema `notify` · migration
`20261124080100_notify_outbox.sql` · pgTAP `240–242` · flag
`EDU_NOTIFICATIONS_ENABLED` (default **off**).

**Nothing is sent to anyone.** There is no push provider, no e-mail, no SMS, no
device-token table and no network call in this lane. The only adapter is
`DummyLocalAdapter`, which appends to a bounded in-memory list. No process runs
the delivery pass: it is a library function exercised by tests.

Part B (rate limiting, logs, readiness, restore drill) is in
[`operations-drill.md`](operations-drill.md) and the second half of this file.

## What exists

| Object | Purpose |
|---|---|
| `notify.kinds` | Allow-list of kinds and their category. Seeded: `daily_word_available` (learning), `sync_reminder` (reminders), `entitlement_expiring` (account). No marketing category exists |
| `notify.policy` | One row: platform quiet hours (21:00–06:00), `max_attempts` 5, backoff base 60 s, cap 3600 s |
| `notify.preferences` | Per learner: `push_enabled` (default false), `muted_categories`, optional own quiet window |
| `notify.outbox` | One row per event per recipient: `kind`, `refs` (ids only), `channels`, `deliver_after`, `expires_at`, `dedupe_hash`, `state` |
| `notify.deliveries` | One row per (event, worker-delivered channel): `pending → leased → delivered / failed`, or `suppressed` / `expired` |
| `notify.delivery_attempts` | Append-only log, one row per attempt |

Rules enforced **in the database**:

- **Only server code creates a notification.** `notify.enqueue` is executable by
  nobody but the owner; `edu_api` has no INSERT/UPDATE/DELETE anywhere in the
  schema. Producers call `enqueue` from their own definer functions.
- **Ids only, no free text.** `refs` must satisfy `notify.refs_are_ids`: at most
  four entries, keys from a fixed list (`word_id`, `lesson_id`, `unit_id`,
  `course_id`, `subject_id`, `grant_id`), values canonical lower-case UUIDs. Every
  other text column is an allow-list; the dedupe key is stored only as SHA-256.
  A structure test fails if a new text column is added.
- **Dedupe.** `UNIQUE (recipient_id, kind, dedupe_hash)`; `enqueue` is idempotent
  and returns the existing id.
- **Push is opt-in** (no preferences row = off; consent unknown = not granted,
  PO-04) and preferences are read **at delivery time**, so a learner who opts out
  stops already-queued pushes.
- **Quiet hours** are evaluated in `America/Port-au-Prince` including daylight
  saving. The platform window always applies; a learner's own window is *added*
  to it (a learner can lengthen quiet time, never shorten the platform's). A push
  falling in quiet hours is put off to the end of the window without spending an
  attempt.
- **Retry:** exponential backoff `base × 2^(attempt−1)` capped at
  `backoff_cap_seconds`; after `max_attempts` the delivery is `failed` for good.
  A lease that runs out (worker died) is logged as `lease_lost` and retried; a
  late report with the old lease token returns `stale` and writes nothing.
- **In-app list** = the outbox rows themselves (pull only). Muting a category
  suppresses its push, not its in-app row.

## Functions and who may execute them

| Function | EXECUTE today | Intended caller |
|---|---|---|
| `notify.set_preferences(boolean, text[], time, time) → void` | `edu_api` | Student API; actor from `app.current_actor_id()` |
| `notify.enqueue(p_recipient uuid, p_kind text, p_refs jsonb, p_dedupe_key text, p_channels text[] = '{in_app}', p_deliver_after timestamptz = now, p_expires_at timestamptz = null) → uuid` | **nobody** | Other schemas' definer functions (run as owner; need no grant) |
| `notify.claim_due(p_channel text, p_limit int = 20, p_lease_seconds int = 60) → setof notify.claimed` | **nobody** — awaiting `edu_worker` | Delivery worker |
| `notify.record_attempt(p_outbox_id uuid, p_channel text, p_lease_token uuid, p_outcome text, p_error_code text = null) → text` | **nobody** — awaiting `edu_worker` | Delivery worker |
| `notify.erase_learner(p_user_id uuid) → jsonb` | **nobody** | `account` erasure orchestrator (as owner) |
| `notify._claim_due_at`, `notify._record_attempt_at`, `notify._settle` | nobody, **never to be granted** | Internal; the `_at` twins take an explicit clock for tests |
| `notify.quiet_until`, `notify.window_end`, `notify.refs_are_ids` | nobody | Internal helpers |

**Seam, in one place.** The staff lane's roles do not exist in this branch. When
they are merged, a second migration in this block (`20261124080200_…`) adds
exactly the three statements quoted under `SEAM(notify-worker-role)` at the end
of the migration, the expectation marked with the same tag in
`240_notify_structure.sql` gains two pairs, and `owner_engine` in
`tests/notify_fixtures.py` switches to `EDU_WORKER_DATABASE_URL`. No Python in
`edu_api/notify/` changes. `ops.audit_write` is not called anywhere yet (it does
not exist here): erasure and preference changes are not audited — see gaps.

## API contract (only when `EDU_NOTIFICATIONS_ENABLED=true`)

With the flag off the three routes are **not mounted** (404, absent from
`/openapi.json`, no extra database pool). `packages/contracts/openapi.json` and
the mobile `schema.d.ts` are therefore unchanged — see deviations.

All routes need the learner's access token; the learner is taken from the token.
Errors use the standard shape.

### `GET /v1/me/notification-preferences` → 200
```json
{"push_enabled": false, "muted_categories": [], "quiet_hours": null,
 "platform_quiet_hours": {"start": "21:00", "end": "06:00"},
 "time_zone": "America/Port-au-Prince",
 "categories": ["account", "learning", "reminders"], "updated_at": null}
```
Writes nothing. `updated_at` is `null` until the first save.

### `PUT /v1/me/notification-preferences` → 200 (same shape)
Body, all three fields required, unknown fields rejected (422):
```json
{"push_enabled": true, "muted_categories": ["reminders"],
 "quiet_hours": {"start": "20:00", "end": "07:30"}}
```
`quiet_hours` may be `null`; times are `HH:MM` wall-clock in `time_zone`; the
window may wrap midnight; `start` ≠ `end`. Full replacement, safe to repeat.
Creates the caller's learner profile on first contact, like `GET /v1/me`.

### `GET /v1/notifications?cursor=&limit=` → 200
```json
{"items": [{"id": "…", "kind": "daily_word_available", "category": "learning",
            "refs": {"word_id": "…"}, "available_at": "…", "expires_at": null}],
 "next_cursor": null}
```
Newest first (`available_at` desc). `limit` 1–50, default 20. `next_cursor` gets
**older** items; to see new ones, ask again without a cursor. Only the caller's
own rows whose channel policy includes `in_app`, that are due and not expired.
No title, no body: the app renders the words from `kind` + `refs`.

| HTTP | `code` | When |
|---|---|---|
| 401 | `unauthenticated` | as everywhere |
| 404 | `not_found` | flag off |
| 422 | `validation_error` | bad body / `limit` / over-long cursor |
| 422 | `notification_cursor_invalid` | cursor unreadable or from another account → restart without a cursor |
| 503 | `notifications_unavailable` (`Retry-After: 30`) | any database trouble on these routes. **Not** a reason to stop syncing |

## Python (`services/api/src/edu_api/notify/`)

- `adapter.py` — `build_push_payload` returns exactly
  `{"v": 1, "id": <outbox id>, "kind": <kind>, "refs": {…uuid}}`;
  `assert_content_free` rejects anything else (also called by the sink). Age is
  unknown to the platform, so every recipient is treated as a minor: there is no
  code path that adds a title or body. `DummyLocalAdapter` records in memory.
- `worker.py` — `deliver_due(port, adapter)`: one pass, at-least-once, an adapter
  crash or timeout becomes a retry. `SqlOutboxPort(engine)` is the seam.
- `service.py`, `schemas.py`, `cursor.py`, `routers/notifications.py` — the
  learner routes, on their **own 2-connection pool** (`app.state.notify_db`,
  2 s statement timeout) so a slow `notify` cannot starve lessons and sync.

## Tests (Part A)

| File | Assertions / tests | Covers |
|---|---|---|
| `supabase/tests/240_notify_structure.sql` | 42 | tables, RLS on all, no text columns, grants, EXECUTE lists, search_path, Data API roles |
| `supabase/tests/241_notify_outbox.sql` | 89 | client cannot enqueue/claim/report/erase; dedupe; bounded inputs; no-free-text constraints; preferences; isolation; erasure |
| `supabase/tests/242_notify_delivery.sql` | 105 | quiet hours across Haiti midnight and both DST changes; opt-in/opt-out; lease; backoff; cap; terminal failure; expiry |
| `tests/unit/test_notify_payload_and_cursor.py` | 20 | content-free payload, dummy sink, no network import, worker pass, cursor, strict body |
| `tests/integration/test_notify_api.py` | 13 | flag off = 404; contract; auth; preferences; list; pagination; arbitrary SQL as the API role |
| `tests/integration/test_notify_delivery.py` | 7 | dummy delivery through real functions; opt-out; quiet hours on the real clock; retries to terminal; 8 concurrent passes; erasure |
| `tests/integration/test_notify_isolation.py` | 5 | learning works with `notify` unreachable and with every notify table locked; `/ready`; Data API |

## Decisions taken without the owner (all reversible, all behind the flag)

| Decision | Chosen | Status |
|---|---|---|
| Quiet hours | 21:00–06:00 Haiti time, platform-wide floor | `BLOCKED_BY_OWNER` PO-10 — synthetic |
| Which messages exist | three service kinds from the brief; no marketing | `BLOCKED_BY_OWNER` PO-10 |
| Push default | off; the learner's own switch turns it on | `BLOCKED_BY_OWNER` PO-04/PO-10 — whether a minor's own switch is sufficient consent is not decided. Nothing is sent either way |
| May a learner shorten the platform quiet window | no (own window only adds) | `BLOCKED_BY_OWNER` PO-10 |
| Retry bounds | 5 attempts, 60 s base, 1 h cap | engineering default |
| Wording of notifications (fr/ht) | none stored server-side; app renders | Creole wording pending native-speaker review (plan §7) |

## Deviations from the brief

1. **Routes are mounted only when the flag is on, so the committed OpenAPI file
   and mobile types do not contain them.** The existing
   `test_openapi_contract` pins the exact set of paths of the default app and
   may not be edited; mounting the routes unconditionally would break it. The
   contract above and `test_contract_of_the_flagged_routes` stand in until the
   director decides how flagged routes enter the shared contract.
2. **No `notify.push_tokens` table** (Platform-00 doc 04 lists one). The brief
   forbids device tokens tonight; the table belongs with the first real channel.
3. **Extra table `notify.delivery_attempts`, `notify.kinds`, `notify.policy`.**
   The brief names three tables; the attempt log is separate from the per-channel
   state so that retry state is one row and history is append-only.
4. **Foreign keys to `app.learner_profiles`** (not `auth.users`). Nothing is
   created in `app`; the 209 baseline assertions are unchanged.
5. **`edu_api` gained privileges in `notify`** (USAGE, SELECT on four tables,
   EXECUTE on `set_preferences`). Its privileges in `app` are untouched.

## Known gaps

- No worker process, no schedule, no real channel, no device tokens.
- No audit event on preference change or erasure (`ops.audit_write` not present).
- No "read/unread" state and no way to dismiss an in-app item.
- No retention job: outbox rows and attempt logs grow until `erase_learner`.
- `deliver_after` further than 90 days ahead is refused by `enqueue`.
- Delivery is at-least-once (a crash between adapter success and the report
  repeats the push); the payload carries the notification id for de-duplication
  on the device, which no client implements yet.
- The in-app list and preferences are not part of offline sync; the app must
  cache them itself.
- Quiet hours use one product time zone; a learner abroad gets Haiti hours.
