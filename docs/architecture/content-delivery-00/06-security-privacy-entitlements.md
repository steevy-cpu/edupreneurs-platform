# 6. Security, privacy and entitlement considerations

## 1. Trust boundaries (unchanged principles)

* The phone never talks to PostgreSQL. Only authenticated FastAPI endpoints (existing rule; the slice adds none).
* Object storage is private; clients receive short-lived signed URLs from FastAPI after an authorisation decision.
* No service-role credential, bucket secret or signing key ever reaches the app or the admin web.

## 2. Threats and controls

| Threat | Control |
|---|---|
| Tampered or truncated download | Streaming SHA-256 and length against the manifest; structural validation; atomic activation (**partly implemented**: structural validation today; hashes need doc 4 §A) |
| Man-in-the-middle / captive portal HTML | TLS; response must parse and validate as the requested lesson+locale (**tested**: HTML body, wrong lesson, wrong locale, empty blocks, bad ids) |
| Hostile content rendering | All strings are plain text, never markup (contract rule). The reader draws text only; math `source` never reaches a web view. Unknown block types degrade to text. |
| Stale / withdrawn content on phones | Catalog `withdrawn` flag + Withdrawn lifecycle state (doc 3); takedown route is an open audit item (L-B2-3) |
| Account A sees account B's data | Content is public and shared; **student work is per-account database**; licensed books per-account directories; the memory cache is cleared on sign-out. **Tested:** a second account sees no answers, completion or preferences from an online-read lesson. |
| Signed-URL sharing | TTL 5–10 min; not bound to content titles; issuance is audited (user id, resource id, outcome — no content) |
| Enumeration of lessons | Already: unknown/draft/withdrawn all return the same 404. Keep for new endpoints. |
| Storage exhaustion / abuse | Plan-time space check; per-request limits (≤ 200 items); rate limiter once PO-10 is decided (it must stay off until the NAT finding L-4 is fixed) |

## 3. Minors and privacy

* No new personal data is stored. Download/read events, if collected for the admin dashboard, are **aggregate counters by
  resource and day, no student id** (preferred) or pseudonymous with a documented purpose; this is an **owner/legal decision**
  (PO-04 class) and is therefore **not built**.
* A learner's reading history is a behavioural record of a child. Server-side, "who read what online" is **not logged** by this
  design beyond the existing practice answers; access logs for signed URLs hold user id only for entitlement audit and expire.
* Erasure: local removal never touches the server; server erasure stays governed by the account-lifecycle design (S3 is open and
  blocks that flag). Nothing in content delivery stores identity in object keys.

## 4. The practice / controlled-exam boundary

Today `GET /v1/lessons/{id}` returns **every question's `answer_key` and `explanation`** to the phone (the *offline practice*
contract, `assessment_mode: "offline_practice"`). That is intentional for practice and is what makes local feedback possible. It
is **unacceptable for any supervised or high-stakes assessment**, because a rooted phone or a proxy reads the key.

| | Practice | Controlled / supervised |
|---|---|---|
| Key on device | yes | **never** |
| Download | allowed | **not allowed** |
| Feedback | immediate, provisional | after close, server-computed |
| Scoring | server re-scores on sync | server only |
| Time limit / attempts | none | server-enforced |
| Delivery | lesson-like pack | session API (doc 4 §D), online only |

Rule for the roadmap: **no exam item is added to a delivery manifest unless its class is `practice`**; the class is a column on
the exam resource, set by an editor and a reviewer. Past national exam papers (permitted ones) are *practice* by default; any paper
the owner wants for assessment is *controlled*. Owner must confirm the list.

## 5. Rights and entitlements (books, papers, media)

* Every non-original resource has a `rights` record (license, territory, validity, who may access). No record → not deliverable.
* Authorisation happens in `POST /v1/downloads/plan` and `POST /v1/library/{id}/access` using the entitlement read model
  (PR #10, currently flagged off, no paywall). While entitlements are off, delivery must behave exactly as today (free).
* **Honest limit:** app-private storage and signed URLs stop casual copying and sharing of links; they do **not** stop a determined
  user from extracting a file they are entitled to. If a publisher requires DRM, that is a separate, larger project and must be
  stated in the contract with them. Do not market the download as "protected".
* A revoked entitlement or withdrawn right: the library shows the title as unavailable and the app removes the local file at next
  catalog refresh (books only); progress and bookmarks are kept.

## 6. Decisions needed from the owner

1. Which exams are *practice* and which *controlled* (ADR-8).
2. Whether aggregate download/read counters may be collected, and at what granularity.
3. Withdrawn-content policy (hard vs soft, doc 3).
4. DRM expectation for any licensed book.
5. Wi-Fi-only default for bulk downloads and the default storage budget.
