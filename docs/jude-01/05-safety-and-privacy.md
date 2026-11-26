# 5. Safety and privacy

> Any launch to real learners needs policy and legal review beyond this
> document. What follows is the engineering baseline and its tests.

## Safety policy (as implemented)

| Area | Rule | Mechanism | Tested |
|---|---|---|---|
| Age-appropriate help | School learning only, suitable for a child | System prompt §3; output check for unsuitable content | structure only |
| Personal information | Jude never asks for it. Removed before retrieval and before any provider call: e-mail addresses, links, phone numbers, and a name or home place given in an explicit self-introduction. **Nothing else** — see the limits below | `minimise_personal_details`; notice `personal_info_removed` | yes, with the misses pinned |
| Unsafe or unsuitable requests | Fixed refusal, no model call | `screen_student_message` → `declined` | yes |
| Manipulating instructions | Fixed reply, no model call; lesson text can never reach an instruction position; leaked prompt is rejected | screen + trust boundary + canary | yes |
| Sensitive personal disclosures | See "Immediate safety concerns" | | yes |
| Requests unrelated to education | Nothing relevant in the lesson → fixed "not in this lesson" reply, no model call | retrieval threshold | yes |
| Controlled-exam answers | No hints, no answer explanations, no question context in a controlled assessment | `assessment_mode` on the lesson; fixed reply | yes |
| Other learners' data | Never read; the request cannot name a learner | token subject + RLS + no learner field | yes |

### Immediate safety concerns

If a message suggests the student may be in danger, hurt, abused or thinking of
self-harm **in wording the phrase list recognises**, Jude does **not** tutor and
does **not** call a model. It returns a fixed message (French and Haitian
Creole). **Neither the phrase list nor the message has been reviewed by a
child-safeguarding professional or a native speaker**
(`safety.TEMPLATES_REVIEW_STATUS = "unreviewed"`), and no student-facing route
can be built until the owner records that review
(`build_student_facing_router`). The message:

- thanks the student and says they should not stay alone with it;
- tells them to talk now to a trusted adult — a parent, a teacher, a relative;
- tells them, if in danger right now, to call emergency services or go to an adult who can help;
- says plainly that Jude is a lesson helper and **cannot call anyone or send help**.

It contains no phone number: a test fails if a digit appears. Verified local
contacts are an owner decision ([10](10-open-decisions.md)), not something to guess.

This reply is given even without consent, entitlement or budget and while the
kill switch is on (it is local, fixed text). Nothing about the event is stored
or logged and nobody is notified — Jude has no channel to do so, and says so.
Whether a safeguarding escalation path should exist is an open owner decision.

If the screen misses a message and the model itself flags it
(`status: safety_support`), the model's wording is discarded and the same
fixed message is shown.

### Avoiding excessive refusal

The screen matches **phrases, in the first person where that matters**, not
topic words. Tests pin that these pass untouched: why Romeo kills himself at the
end of the play; sexual reproduction in flowering plants; the reproductive
system; deaths in the war of independence; the health dangers of drugs; how the
atomic bomb ended the war; "who killed Dessalines?"; a student calling
themselves bad at maths. Numbers in mathematics are not mistaken for phone
numbers.

### Honest limits of the screen

- It is a short list of phrases in three languages. It will miss indirect,
  misspelled or unusual wording — six realistic misses are pinned as expected
  failures in `test_security_corrections.py` — and all of it needs review by
  native Haitian Creole speakers and by a child-safeguarding professional.
- A sentence in quotation marks that is explicitly attributed to a text or a
  character is treated as a literature question. That exemption is narrow, and
  it can be wrong in both directions.
- **Personal details:** removal is pattern matching, not name recognition. A
  name outside a self-introduction, a nickname, a school, a teacher's or
  relative's name, or a description that identifies the child is sent as
  written. Whether such text may go to a third-party model at all is an open
  legal decision ([12](12-security-corrections.md), S-4).
- It is not a classifier and has not been evaluated on real messages (there are
  none, by design).
- The Creole fixed messages were written for this milestone and have **not**
  been reviewed by a native-speaking editor.
- Launch needs, in addition: a model-based safety classifier evaluated on
  consented data, a reviewed policy, and legal advice on duties toward minors
  in Haiti.

## Privacy by design

### What exists where

| Data | Where it is | For how long |
|---|---|---|
| The student's message | In memory for the request; sent (redacted) to the provider once live | Not stored by Edupreneurs. Provider retention is a contract term to settle before any live call. |
| The model's answer | In memory; returned to the caller | Not stored |
| Usage row: learner id, request key, day/month, amounts, token counts, model, price version, prompt version, lesson revision id, outcome code, attempts, timestamps | Usage ledger | Owner's retention rule; `purge_older_than` implements it |
| Counters per learner per day/month | Usage ledger | Deleted on erasure |
| Global monthly totals | Usage ledger | Kept (no personal data) |

There is no transcript store, and none can appear by accident:

- `UsageRecord` and the SQL tables have no column that could hold text; a test
  pins the exact field list, and adding a field is therefore a visible decision.
- In SQL the only free-text ledger columns are constrained by `CHECK` to code
  shapes; a test tries to insert a sentence into `outcome` and is refused.
- No hash of the message is stored either (a short question is guessable from its hash).
- A consequence worth knowing: a repeated idempotency key cannot replay the
  answer, because the answer was never kept. The client keeps the answer it received.

### Logging

The tutor logs one line per request: an outcome code and a duration. No
learner id, no lesson text, no question, no answer. Exceptions are logged by
type only — an exception message can carry request text. Tests run requests
containing a marker string through success and four failure paths, including an
adapter that raises an error containing the whole prompt, and assert the marker
appears in no log record and no stored row. A static test forbids
`logger.exception`, `exc_info` and content-bearing arguments in the package.

### Minimum data to the provider

The prompt contains the retrieved lesson passages, the lesson title and
language, the intent, the (redacted) message, and for an answer explanation the
chosen option and whether it was right. It contains **no** learner id, name,
grade, school, location, history or real lesson identifier; tests assert this.

### Interfaces

| Requirement | Interface | Default / state |
|---|---|---|
| Consent eligibility | `ConsentGate.tutor_consent → granted / denied / unknown` | `DenyByDefaultConsent` returns `unknown`; only `granted` passes |
| Who may use Jude | `EntitlementGate.may_use_tutor` | `DenyByDefaultEntitlements` returns `False` |
| Per-learner isolation | token subject; `Database.transaction(learner_id)`; `tutor.*` functions read `app.current_actor_id()` | built, tested (incl. forged reservation on PostgreSQL) |
| Account deletion | `LearnerDataEraser.erase_learner` | built in both stores; to be called by the erasure orchestrator (#5) |
| Usage retention | `UsageRetention.purge_older_than(cutoff)` | built; cutoff is an owner decision |
| Audit of privileged operations | every kill-switch change, erasure and purge writes an audit row (who, what, when; not *whose* data) | built; to move to `app.audit_events` with the staff boundary (#4) |

### Kept disabled rather than invented

Consent wording and record, the entitlement rule, the retention period, the
provider and its data-processing terms are unresolved. So: `enabled` is false,
the provider is the mock, live calls are unauthorised, both gates deny, and the
SQL policy row starts paused with every limit at zero.
