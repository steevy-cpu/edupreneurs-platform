# 4. API design notes

Machine-readable draft: [openapi/social-v1.draft.yaml](openapi/social-v1.draft.yaml)
(OpenAPI 3.1 — 44 paths, 50 operations). This page explains the behaviour a
schema cannot. It follows `docs/API_CONTRACT.md`; only the differences and
additions are described.

The draft is **not** merged into `packages/contracts/openapi.json`. That file
is generated from the running application and CI fails if it is out of date;
it will gain the social routes when they exist (Social-02).

## Route map

| Area | Routes | Milestone |
|---|---|---|
| My status, profile, settings, rules | `GET /v1/social/me` · `PATCH /me/profile` · `GET,PATCH /me/settings` · `POST /me/guidelines-acceptance` · `GET /me/submissions` · `GET /guidelines` | Social-02 |
| Community discovery and membership | `GET /communities` · `POST /communities/join` · `GET /communities/{id}` · `POST /communities/{id}/leave` · `GET /communities/{id}/members` · `PUT /communities/{id}/join-requests/{user_id}` | Social-02 |
| Feeds | `GET /feed` · `GET /communities/{id}/feed` · `GET /updates` | Social-02 |
| Posts | `POST /communities/{id}/posts` · `GET,DELETE /posts/{id}` | Social-02 |
| Comments | `GET,POST /posts/{id}/comments` · `DELETE /comments/{id}` | Social-02 |
| Reactions | `PUT,DELETE /posts/{id}/reaction` · `PUT,DELETE /comments/{id}/reaction` | Social-02 |
| Reports and blocks | `POST /reports` · `GET /blocks` · `PUT,DELETE /blocks/{user_id}` | Social-02 |
| Notifications | `GET /notifications` · `POST /notifications/read` | Social-02 |
| Moderation | `GET /moderation/queue` · `POST /moderation/queue/claim` · `GET /moderation/items/{id}` · `POST …/decision` · `POST …/escalation` · `GET /moderation/users/{id}` · `POST …/sanctions` · `DELETE /moderation/sanctions/{id}` · `GET /moderation/metrics` | Social-02 (metrics: Social-03) |
| Administration | `POST /admin/enrollments` · `POST /admin/communities` · `PUT …/status` · `POST …/invites` · `PATCH /admin/config` · `POST /admin/users/{id}/erasure` | Social-02 (erasure: Social-03) |
| Guardianship | `GET /guardianship/learners` · `PATCH …/settings` · `DELETE …/consent` | Social-04 |

All paths are under `/v1/social`. Versioning rule (same as today): additive
changes stay in `v1`; anything that breaks an installed app needs `/v2/social`.

## Authentication

Unchanged from the learning API: the Supabase Auth access token, verified with
the public key; identity only from the token; anonymous sessions and project
keys refused.

Additions for the social module:

| Rule | Why |
|---|---|
| A valid token is **not enough**. Every request also checks the caller's social standing in the database (`social.actor_access`) | A suspension, a withdrawn consent or a removed staff role must work immediately. The token stays valid for up to an hour, so the token alone cannot be trusted for this (`docs/SECURITY.md` item 2) |
| Moderation and admin routes require a multi-factor session (`aal` claim = `aal2`) and an active row in `social.staff_roles` | Staff accounts can read children's unpublished text |
| Moderation and admin routes are served from pool C (`edu_social_mod_login`); member routes from pool B | A routing or logic bug cannot give a learner moderation powers |
| When `EDU_SOCIAL_ENABLED` is false the router is not mounted: every `/v1/social/*` path is the ordinary `404 not_found` | Zero behaviour change until the switch is turned on |

## Authorization

Decided in the database and repeated in the API (defence in depth). The order
of checks for any write:

1. Token valid → `401 unauthenticated` otherwise.
2. Request shape valid, unknown fields rejected → `422 validation_error`.
3. Local text screen (posts, comments, names) → `422 content_not_allowed`.
4. Database function: safe-retry lookup **first** (a retry of something already
   accepted returns the original answer even if the person has since been muted).
5. Standing and capability (`write_denial`): enrolled → active → not suspended →
   member → submissions open → community open → rules accepted → not muted →
   capability enabled → posting allowed.
6. Limits (waiting-for-review cap, daily cap) → `429`.
7. Store as `pending_review`, queue for review → `202`.

Reads are filtered by row-level security; the API additionally names the
community and status in its `WHERE` clauses.

**Uniform "not found".** These all return the same `404` with the same body and
timing-insensitive code path: unknown id, content not yet approved, content
removed, community the caller is not in, author who blocked the caller or was
blocked by them. Otherwise ids could be used to probe what exists.

## Request limits

| Limit | Value | Where enforced |
|---|---|---|
| Body on the wire / after gzip | 20 KB / 128 KB (existing middleware) | API |
| Post text / comment text / report note / display name | 2000 / 1000 / 500 / 40 characters | API and `CHECK` |
| Posts per day · waiting for review | 5 · 3 | Database (`social.config`) |
| Comments per day · waiting for review | 30 · 10 | Database |
| Reactions per day | 200 | Database |
| Reports per day | 20 | Database |
| Join attempts per hour (failures count) | 5 | Database |
| Display-name change requests per day | 3 | Database |
| Communities per person · blocks per person | 10 · 200 | Database |
| Feed page · other lists | 10 default, 20 max · 20 default, 50 max | API |
| `GET /updates` | at most every 120 s per account (earlier calls get the cached answer) | API |
| Per-IP and per-account request rate for **all** routes | to be chosen with the gateway (prerequisite P-2 in the roadmap) | Gateway |

"Day" is a fixed UTC window. `429` responses carry `Retry-After` in seconds.
The app must show a calm, translated message ("Tu as atteint la limite pour
aujourd'hui") and must **not** auto-retry.

## Cursor pagination

Same style as `edu_api.sync.cursor`: a URL-safe base64 string the client treats
as opaque. Contents (for implementers only):

| List | Cursor holds | Order |
|---|---|---|
| Feeds | format version, account tag, last `publish_seq` seen | `publish_seq` descending |
| Comments | format version, account tag, last `publish_seq` seen | ascending |
| My submissions | format version, account tag, `(submitted_at, id)` | descending |
| Notifications | format version, account tag, last id | descending |
| Updates | format version, account tag, last `change_seq` | ascending |

- The account tag (first 16 hex characters of SHA-256 of the user id) makes a
  cursor from another account on a shared phone fail cleanly with
  `410 social_cursor_invalid` instead of producing a confusing page.
- A cursor is not a credential and is not signed. Editing it can only change
  which of the caller's *own visible* rows are returned.
- Keyset pagination ("after this marker") is used instead of page numbers so
  that new posts arriving while the learner scrolls never cause duplicates or gaps.
- `next_cursor: null` means the end. There is no total count (it would cost a
  full scan and adds nothing for the learner).

## Safe retries

| Operation | Mechanism | Result of a repeat |
|---|---|---|
| Submit post / comment | `client_op_id` in the body; unique with the author | `202`, same id, `replayed: true` |
| Same `client_op_id`, different text | digest comparison | `409 idempotency_conflict`, nothing written |
| Set / clear reaction | `PUT` / `DELETE` | Same final state |
| Report | unique per reporter and subject | `202`, same `report_id`, `replayed: true` |
| Block / unblock, leave, mark read, accept rules, delete own content | keyed by subject | `204` again |
| Join | unique membership | `202`, `replayed: true`; **the attempt still counts** toward the hourly limit |
| Moderator decision | item must be `claimed` by the caller | Second call → `409 item_not_claimed` (the first one resolved it) |

Rules for the app: generate `client_op_id` when the learner taps *send*, store
it with the draft, and reuse it for every retry — including after an app
restart. On `500`, `503` or a network error: retry later with the same id. On
`4xx` other than `401` and `429`: do not retry; show the state.

## Validation

1. **Shape** — strict models, unknown fields rejected, ids must be UUIDs.
2. **Normalisation** — Unicode NFC; strip control characters, zero-width
   characters and direction-override characters (used to hide words); collapse
   runs of whitespace; trim. If nothing is left → `empty_after_cleanup`.
3. **Hard rules (refuse now)** — phone numbers, e-mail addresses, links and
   domain names, social-media handles; these are how a stranger moves a child to
   another app. The response says *which rule* so the learner can fix the text,
   and never echoes the text.
4. **Soft rules (accept and flag)** — word lists in French and Haitian Creole,
   repeated-character and all-capitals patterns, names of other apps. Flags are
   stored for the moderator and raise the item's priority. They are never shown to the author.
5. **Digest** — SHA-256 of the canonical JSON of `(community or post id, kind,
   locale, normalised text)`, using the existing canonicalisation module's conventions.

The screen's version string is stored with each row (`screening_version`), so
old decisions can be understood after the rules change.

## Moderation status in responses

| What the learner did | HTTP | Body | What the app shows |
|---|---|---|---|
| Sent a post or comment | `202` | `{id, status: "pending_review", replayed}` | "Envoyé — en attente de validation" |
| Looks at their submissions | `200` | each item with `status` and, if refused, `moderation_reason_code` | Waiting / Published / Not accepted + a fixed explanation and "Modifier et renvoyer" |
| Opens a feed | `200` | only `published` items | — |
| Asked for a new display name | `200` | `display_name_status: "pending_review"` | Old name stays until approval |

`moderation_reason_code` is one of a short fixed list (doc 06). It is a code,
not a sentence: the app translates it, so a moderator can never send free text to a child.

## Response models

Defined in the OpenAPI file. Design rules:

- **Small.** Feed items carry a 280-character excerpt, the author's public
  profile (id, name, avatar key, badge) and three numbers. No nested comments,
  no reaction lists, no image URLs.
- **No internal fields.** Screening flags, digests, reporter identity, internal
  notes and other people's states are not in any member-facing model.
- **`author` may be `null`** (account erased). The app shows "Compte supprimé".
- **Timestamps** are ISO-8601 UTC from the server. The phone's clock is never trusted.
- **Stable enums.** New enum values may be added in `v1`; the app must treat an
  unknown value as "other" rather than crash.

## Errors

Same single shape as today:

```json
{"error": {"code": "social_muted", "message": "Posting is temporarily disabled for this account.",
           "request_id": "2f8e4400fa554a9b8d8403045f8b5ae6"}}
```

New codes introduced by this module:

| HTTP | `code` | Meaning | What the app does |
|---|---|---|---|
| 403 | `social_not_enrolled` | No social enrolment | Hide the community entry points |
| 403 | `social_not_active` | Consent pending or withdrawn, or enrolment paused/closed | Explain; no retry |
| 403 | `social_suspended` | Suspension or ban in force | Show until when (from `GET /me`) |
| 403 | `social_muted` | May read, not write | Disable composing, show until when |
| 403 | `guidelines_not_accepted` | Rules (new version) not accepted yet | Show the rules, then retry once |
| 403 | `submissions_closed` | Global switch is off | "La communauté est en lecture seule pour le moment" |
| 403 | `community_read_only` | Community frozen or not open | Same, for that community |
| 403 | `capability_disabled` | Switched off in safety settings (by learner, adult or staff) | Explain who can change it |
| 403 | `posting_restricted` | Only teachers post here / announcements | Hide the compose button |
| 403 | `settings_locked` | A locked setting cannot be loosened by the learner | Explain |
| 403 | `not_allowed` | E.g. reacting to or reporting one's own content | Nothing |
| 403 | `forbidden`, `self_moderation_forbidden` | Staff rule violated | Staff console message |
| 404 | `content_not_found`, `community_not_found`, `user_not_found`, `invite_invalid`, `item_not_found` | Unknown **or** not visible | Remove from local cache |
| 409 | `idempotency_conflict` | Same `client_op_id`, different text | Client bug; mark failed |
| 409 | `invalid_state`, `item_not_claimed`, `limit_reached`, `cannot_block_staff`, `guidelines_outdated`, `blocked_by_evidence_hold` | The action does not fit the current state | Refresh and show |
| 410 | `social_cursor_invalid` | Cursor unusable | Drop it, reload first page |
| 422 | `content_not_allowed` | The local screen refused the text; `details[].type` names the rule | Help the learner fix it |
| 429 | `rate_limited`, `pending_limit_reached` | Limit reached; `Retry-After` set | Calm message, no auto-retry |

Existing codes keep their meaning: `401 unauthenticated`, `413
payload_too_large`, `422 validation_error`, `500 internal_error`,
`503 dependency_unavailable`.

Mapping from database results: a function's `result` string *is* the API error
code; the API holds one table from code to HTTP status. Raised database errors
map as today (`42501` → 403 `forbidden`, `23514` → 409 `invalid_state`,
`40P01` → one automatic retry, anything else → 500 without details).

## Caching headers

| Response | Headers |
|---|---|
| Any authorised read | `Cache-Control: private, no-store` — nothing may be stored by a shared proxy |
| First feed page, communities, `me`, guidelines | plus `ETag`; the app sends `If-None-Match` and usually receives a body-less `304` |
| Responses over ~1 KB | `Content-Encoding: gzip` (response compression is not enabled in the API today; adding it is part of Social-02 and benefits the catalog too) |

The `ETag` is derived from the caller's id and the highest `change_seq` in
scope, so it is cheap to compute and never the same for two accounts.
