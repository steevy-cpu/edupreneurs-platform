# ExamHub-01: first server-authoritative exam workflow

**Status: draft, feature flag off, synthetic fixtures only.** No real exam, answer key or student record was imported or read. Not merged, not deployed. Backend and contract only: no native screen is included (the mobile work is a separate item, E-2 in `docs/v1-parity/06-release-backlog.md` once that PR lands).

## What it covers

```
catalog -> exam selection -> question delivery -> answer submission -> scoring -> explanation -> progress/history
```

| Step | Endpoint |
|---|---|
| Catalog (filters: grade, subject, series, exam type) | `GET /v1/exams?locale=` |
| Exam detail (metadata only) | `GET /v1/exams/{exam_id}?locale=` |
| Start or resume; receive the questions **without keys** | `POST /v1/exams/{exam_id}/attempts` `{mode, locale}` |
| Submit one answer | `POST /v1/exam-attempts/{attempt_id}/answers` `{question_id, response}` |
| Finish: server scores, reveals keys and explanations | `POST /v1/exam-attempts/{attempt_id}/finish` |
| History | `GET /v1/exam-attempts[?exam_id=]` |
| One attempt, with whatever may be revealed so far | `GET /v1/exam-attempts/{attempt_id}` |

Contract: `packages/contracts/openapi.json` (strictly additive: no existing path or schema changed) and the regenerated mobile types `apps/student-native/src/core/api/schema.d.ts`.

## Why it differs from the web prototype

In the prototype (read in source, not run) the browser downloads the answer key with the questions, computes the score and the remaining time itself, and reports them to the database. Here:

| Rule | Where it is enforced |
|---|---|
| The API's database role **cannot select** `answer_key` or `explanation` | Column-level grants; `SELECT *` on questions is refused (pgTAP) |
| Keys leave the database only after the learner answered (practice) or the attempt closed (timed) | `app.exam_submit_answer`, `app.exam_attempt_review` |
| The client never sends a score, verdict or time | Request models forbid extra fields; scoring is in `app.exam_close_attempt` |
| A learner sees only their own attempts and answers | Row-level security + ownership checks in every function; another learner gets 404 |
| A timed attempt ends on the **server** clock | `expires_at = start + duration`; later answers are refused (`409 attempt_expired`) and never stored; only answers recorded before the deadline are scored |
| One open timed attempt per learner and exam | Partial unique index + advisory lock; starting again resumes |
| Only reviewed exams with cleared rights are visible | `status = 'published'` needs an approver other than the author, a source with `rights_status = 'cleared'`, at least one question and a valid key for every multiple-choice question |
| A published exam cannot change under a learner | Trigger on `exam_questions` |

## Modes

| | Practice | Timed |
|---|---|---|
| Time limit | none | exam `duration_minutes`, server clock |
| Feedback | after each answer (verdict, key, explanation); the first answer stands | nothing until finished: no verdict, points, key or explanation |
| Changing an answer | no | yes, until finished or expired |
| `counts_as_exam_score` | false | true |
| Network | online in this slice | online only |

**Offline practice is a separate feature** (lesson questions ship their keys for offline feedback and are labelled `offline_practice`). Nothing in ExamHub is delivered with keys, and a practice-mode result is never an exam score.

## Question kinds

* `mcq`: scored by the server from `answer_key.correct_choice_id`.
* `open`: the text (1–4000 characters) is stored, never auto-scored (`points = 0`, `is_correct = null`); the model answer is shown for self-review. AI grading, as in the prototype's `exam-tutor`, is **not** included (owner decision OD-9; depends on the Jude gates).

## Feature flag and rollback

* `EDU_EXAMS_ENABLED` (default `false`). While false every route answers `404`, as if absent, and no attempt can be created.
* The migration `20261127000100_examhub.sql` only **adds** four tables, five functions and two triggers; it alters nothing existing. Rollback: turn the flag off (immediate), and if required drop the four tables and the functions (statement in the migration header). No existing data depends on them.

## Client states (French and Haitian Creole)

The Creole strings are **drafts** and need review by a native speaker before use.

| API result | French | Kreyòl (draft) |
|---|---|---|
| `404` on any route with the flag off | (feature hidden) | (feature hidden) |
| `409 attempt_expired` | Le temps de cet examen est écoulé. Tes réponses envoyées à temps ont été comptées. | Tan egzamen sa a fini. Repons ou te voye alè yo konte. |
| `409 attempt_closed` | Cet examen est déjà terminé. | Egzamen sa a deja fini. |
| `409 already_answered` | Tu as déjà répondu à cette question. | Ou deja reponn kesyon sa a. |
| `422 validation_error` on an answer | Cette réponse n'est pas valide pour cette question. | Repons sa a pa bon pou kesyon sa a. |
| `resumed: true` | Tu reprends ton examen en cours. | W ap kontinye egzamen ou te kòmanse a. |
| `counts_as_exam_score: false` | Entraînement : ce résultat n'est pas une note d'examen. | Antrènman: rezilta sa a pa yon nòt egzamen. |
| Network lost during a timed attempt | Connexion perdue. Le temps continue sur le serveur. | Koneksyon an koupe. Tan an ap kontinye sou sèvè a. |

## Tests

| Suite | What it proves |
|---|---|
| `supabase/tests/070_examhub.sql` (52 assertions) | Publication guards, key columns unreadable by the API role, no direct writes, isolation, scoring, deadline, resume |
| `supabase/tests/010_structure.sql` (updated counts) | 26 tables, 38 foreign keys, 21 policies, 18 triggers; the API role may execute exactly six functions |
| `tests/integration/test_exams.py` (11 tests) | The same properties over HTTP with real tokens, the flag, validation, the Creole version, and the contract |

## Known limits

* Synthetic fixtures only. Importing real exams (E-1) needs the content inventory, rights confirmation and the import pipeline.
* An expired timed attempt is closed when the learner next answers, finishes or starts again; until then it reads as `in_progress` with a past `expires_at` (keys stay hidden). A background sweep can be added with the worker (#4).
* No Gold or streak is granted (the ledger is in unmerged PR #12).
* No PDF delivery, no open-answer grading, no per-question timing, no anti-cheating beyond server authority.
* Rate limiting is not part of this slice (platform prerequisite).
