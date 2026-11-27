# Curriculum and examination migration readiness

**Status:** readiness assessment and pipeline design. **No content was imported, converted, approved or published.** No lesson is invented or labelled complete here.

## 1. What actually exists (and what is unknown)

**The honest answer to "how much content exists across 7AF–NS4" is: unknown until the owner runs a count on the legacy database.** Content lives in database rows, which were deliberately not read. The landing page claims "2760+ leçons, 125+ examens"; that figure is not in source and is unverified.

| Category | Where it lives in the prototype | Known from source | Unknown (needs owner-run count) |
|---|---|---|---|
| Subjects | `subjects` (grade as free text, optional Bac series) | Grades 7AF, 8AF, 9AF, NS1–NS4; subjects seen: Maths, Français, Anglais, Espagnol, Sciences expérimentales, Sciences sociales / Hist-Géo, Créole, Biologie-Géologie, Physique-Chimie (also Arts, Éducation physique in redirects) | Subjects per grade; which are populated |
| Lessons | `lessons`: HTML columns `objectif`, `introduction`, `contenu`, `exemples_exercices`, `activites_interactives`, `quiz_final`; `order_index`, `mois` | Workflow enum draft / in_review / approved / published / rejected exists | Count per grade, subject and **status**; how many were human-reviewed. **AI generation jobs auto-publish**, so "published" does not mean "reviewed" |
| Lesson quizzes | Generated per student at view time by `generate-quiz-final` | Not stored as a stable reviewed set | Whether any stored quiz sets exist |
| Lesson assets | Buckets `lesson-images`, `lesson-audio` (TTS), YouTube fields, `lesson_videos`, `banned_youtube_videos` | Public-read buckets | Counts, sizes, licences, broken links |
| Official exams | `official_exams` (tracks 9AF, NS4; series SMP/SES/SVT/LLA; types official/model/practice/rattrapage; `duration_minutes`, `pdf_url`) | Structure | Count per track, series, subject, year |
| Exam questions | `exam_exercises`: MCQ and open-ended; prompt/options/explanation as text + LaTeX blocks; `correct_answer`, `answer_json`, `explanation` | UI says practice covers "quelques questions… pas toutes" of an exam | How many exams have complete question sets and keys |
| Exam PDFs | Bucket `exam-documents`; two PDFs in `public/exams/` | Ingested by staff via `parse-exam-vision` (AI) | Rights (MENFP); completeness |
| Derived / AI material | StudyGram summaries, AI-generated lessons, audio, battle questions | Present | Provenance per item |
| E-books | `ebook-files`, `ebook-covers` | Present | Rights per title |

**In the rebuild:** one synthetic 9AF lesson on `main`; six **draft, unreviewed** 7AF mathematics lessons (fr + ht, 60 questions) in PR #41, not importable into the database yet.

### Owner-run inventory queries (counts only, no personal data)

The owner (or an operator they authorise) can run these on the legacy database; they return aggregates only:

```sql
-- lessons by grade, subject, workflow status
select s.grade_level, s.name, l.status, count(*) from lessons l join subjects s on s.id = l.subject_id group by 1,2,3 order by 1,2,3;
-- exams by track, series, type
select track, series, exam_type, count(*) from official_exams group by 1,2,3 order by 1,2,3;
-- exercises per exam, and how many have a key and an explanation
select exam_id, count(*) total, count(correct_answer) with_key, count(explanation) with_explanation from exam_exercises group by 1;
```

(Column names follow the prototype's documentation and must be confirmed against the live schema before running.)

## 2. Import pipeline (deterministic, validated, reversible)

One-way: legacy export → staging area → new platform **as drafts**. Never writes to the legacy database.

```
export (operator, read-only)  →  snapshot files + SHA-256 manifest
   →  normalise (pure functions)  →  validate  →  load as DRAFT  →  human review  →  approve  →  pack/publish
```

| Stage | Rule |
|---|---|
| **Export** | Operator-run, read-only credentials, isolated shell. Output: JSON lines per table + asset files, with a SHA-256 manifest. Content tables only: no user tables in this job |
| **Identity of items** | Every imported course, lesson, question, exam and asset keeps `legacy_id` (and legacy slug). New ids are deterministic (UUIDv5 of namespace + legacy id), so a re-run produces the same ids: idempotent |
| **Normalise** | HTML → structured blocks by a pure, versioned converter. Anything the converter cannot represent (table, embedded widget, unknown tag) becomes an **exception record**, never silently dropped or flattened |
| **Validate: structure** | Schema validation of blocks and questions (contracts in `packages/contracts/content/`) |
| **Validate: language** | Declared locale present; French content is not labelled Creole; duplicate-text check between locales (as in the content-pilot validator) |
| **Validate: mathematics** | Displayed arithmetic checked where the validator can read it; everything else listed for the reviewer (content-pilot, PR #41) |
| **Validate: assets** | Every referenced asset exists in the manifest, hash matches, type and size within limits; no hot-links to public legacy buckets or YouTube without a decision |
| **Validate: rights** | Each item carries a source record: origin (AI-generated / author / MENFP / third party), licence status, attribution. Third-party or unknown rights block publication |
| **Load** | Into `lesson_revisions` / exam tables with status **draft**; `editorial_reviews` empty. Legacy "published" maps to **draft** in the new platform unless a human approval record exists (OD-2) |
| **Approve** | Existing editorial rule: approval by a qualified reviewer (and native speaker for Creole); only approved revisions enter a pack |
| **Report** | Per run: imported, skipped, exceptions by reason, asset mismatches. The report is the acceptance artefact |
| **Rollback** | Each run has an `import_batch`; a batch can be withdrawn; packs are versioned |

**What this pipeline will not do:** mark anything approved; translate French into Creole; generate missing lessons; fix wrong content. Missing lessons are reported as missing.

## 3. ExamHub: rules to preserve, and what changes

| Rule in the prototype | In the new platform |
|---|---|
| Tracks 9AF and NS4, series, exam types | Kept as data |
| Modes practice / timed / review | Kept. **Timed is enforced by the server clock**; the client timer is display only |
| Online exam | Timed (graded) attempts are **online-only**. Offline practice is a separate, clearly labelled mode whose results never count as an exam score |
| MCQ auto-scoring | Server-side. Keys and explanations are **not** delivered with questions; the explanation is returned after an answer is submitted (practice) or after the attempt is finished (timed) |
| Open-ended questions graded by AI (`exam-tutor`) | **Not in the first slice.** Open answers are stored and shown with the model answer for self-review; AI grading waits for the Jude gates (cost, safety, provider terms). Flagged as a parity gap (OD-9) |
| Gold for exercises and completion bonus | Not granted by the client. Hooks into the server-side ledger (#12) when that merges |
| PDFs of official papers | Only with confirmed rights; delivered as assets with integrity hashes |

### First integrated workflow (implemented as a separate PR; see backlog item S-1)

```
GET  /v1/exams                         catalog (filters: track, series, subject, type)
GET  /v1/exams/{exam_id}               exam detail: metadata + question count, no questions
POST /v1/exams/{exam_id}/attempts      start (mode: practice | timed) → attempt + questions WITHOUT keys
POST /v1/exam-attempts/{id}/answers    submit one answer → practice: verdict + explanation; timed: recorded only
POST /v1/exam-attempts/{id}/finish     server scores → result with per-question verdicts and explanations
GET  /v1/exam-attempts                 history for the signed-in learner
GET  /v1/exam-attempts/{id}            one attempt (own only)
```

Invariants: the answer key never appears in a response before the learner has answered (practice) or finished (timed); a learner sees only their own attempts (RLS); a timed attempt cannot accept answers after `started_at + duration`; scoring is a pure server function; everything is behind a default-off flag and uses synthetic fixtures.

## 4. Readiness verdict

| Area | Ready? | Blocking item |
|---|---|---|
| Lesson delivery engine | Yes (merged) | — |
| Lesson format for real content | No | Format v2 (#7/#18): maths, images, tables |
| Real curriculum content | **No** | Inventory count; rights; HTML converter; review capacity. 6 draft 7AF lessons exist; **0 approved** |
| Exam engine | First slice only (after S-1) | Import, open-ended policy, PDFs |
| Exam content | **No** | Inventory; MENFP rights; key completeness |
| Review capacity | **No** | Named mathematics/subject teachers and a native Creole reviewer |

The largest single risk to "complete curriculum 7AF–NS4 in v1" is not engineering: it is that the legacy lessons are largely AI-generated and auto-published, and the new platform will not call them approved without human review. That is a volume-of-review problem the owner must size (OD-2, OD-3).
