# Content Migration-01 discovery and decision

**HOLD for a larger staging rehearsal.** This run mapped the identities of all 2,832 source lessons. Of six deliberately varied lessons inspected in full across the six authoring fields, zero could be converted end to end. The other 2,826 were not structurally tested. The fraction of the library that could convert after resolving locale, hierarchy and format decisions is unknown.

## Source and target

The connected Lovable project is `14710ec1-c1bf-40aa-b397-6fddd23c28b4`. Aggregate reads began at 2026-11-27 02:00:05 UTC. The owner supplied editor commit `3110f7971aad9abbdeb3e2965afd565f5b74b520`. The current editor reported `8749ddce155194e60a12830ac66a469520937c89`. The intervening diff did not change the educational schema. Neither editor commit identifies the live database contents. Opening and closing identity/metadata roots agreed for all eight categories. Separate database reads cannot establish transaction-wide content or object-byte stability.

The target is main `1094eb0822759d7bc28f3162285077f30ad38969`. The grade and exam readiness assessment and PR #48 describe parity gaps. PR #50 defines integration dependencies. PR #51 supplies proposed exam storage and scoring constraints. PR #41 is a separate mathematics pilot with unresolved independent validator findings. None confers approval on legacy material. Compared heads were [#48](https://github.com/steevy-cpu/edupreneurs-platform/pull/48) at `56f359d`, [#50](https://github.com/steevy-cpu/edupreneurs-platform/pull/50) at `8fdf3e4`, [#51](https://github.com/steevy-cpu/edupreneurs-platform/pull/51) at `9e36566` and [#41](https://github.com/steevy-cpu/edupreneurs-platform/pull/41) at `d33edb6`.

The native blocks and MCQ schemas under `packages/contracts/content` constrain the projection. The published catalog and lesson API serve published revisions in the requested locale. Native `contentStore.ts` keys saved lessons by lesson and locale, saves the revision and stores practice questions with the saved download. `contentAccess.ts` distinguishes an in-memory online read from a committed offline download. This migration produces private descriptors only. Inserting into a published catalog or manufacturing question identity across revisions could affect saved lessons and attempts. No continuity test with learner records was performed.

## Inventory and differences

[inventory-evidence.json](inventory-evidence.json) contains the per-grade and series counts, full identity-set sizes, metadata roots, sampled lesson IDs, exercise classifications and asset checks. All owner baseline headline counts reproduced. Grades 7AF, 8AF, 9AF, NS1, NS2, NS3 and NS4 respectively contain 204, 197, 191, 249, 245, 874 and 872 lessons. NS3 and NS4 each have LLA, SES, SMP and SVT. The other grades have no series. All 2,832 lessons were marked published in both source fields and had main content and quiz text. Of 140 subject records, series-specific subjects count separately.

* All 2,832 lacked a source reviewer. Only 44 had nonempty references, 2,674 had a content-validation timestamp and 2,677 had activity text. The lesson schema has no explicit locale or rights grant. A subject named Créole or Kreyòl does not establish the language of every section.
* There are 14,191 version rows including 2,832 current rows. The history contains title, slug, objective, introduction, main content and worked examples. It omits quiz, activity and audio history. Never reconstruct historical questions using current keys. The inspected checks found no orphan lesson/subject, duplicate lesson/ordinal version, repeated grade/subject/slug or duplicate full main-body digest groups. Translations and near-duplicates still require review.
* All 2,832 quiz fields had a recognizable candidate wrapper. Cached counts total 40,576. The reproducible whitespace-tolerant marker query in [snapshot.sql](snapshot.sql) counts 40,564, with ten lesson counts differing. An earlier pattern counted 40,563 with eleven differences. HTML marker counts depend on syntax. Only the 37 sampled items below passed full practice-template parsing. No whole quiz field was identified as a JSON document.
* 1,226 main bodies contain image markup, 306 contain table markup and one matched the iframe/SVG/math pattern. The separate lesson-assets table is empty. There are 255 video associations across 251 lessons, four lessons with audio URLs, and three published e-books. Static TypeScript in the pinned editor's `src/data/` covers math, languages, science, social science and activities, including backup/temporary modules. All 19 literal map keys recognized in the pinned static math module had an exact lesson slug match somewhere in the database. Grade, series, text and rights equivalence remain unresolved. Counting those entries as 19 additional lessons would double-count candidates. Static modules were inventoried as source, never executed or admitted to the count. Reconcile static IDs, grade, series, slug, normalized text hashes and rights before inclusion.
* The five buckets have 4,037 images, 381 audio objects, 131 exam documents, three book files and three covers. Literal path matching in the expected bucket found 3,039/3,084 main-body double-quoted image references, 16/16 lesson audio references, 127/128 paper PDFs, and 3/3 each for book files and covers. Missing literal matches require URL/encoding and origin review. Matches do not establish origin, bytes, MIME, licensing or safe rendering. No asset bytes were certified. The two similarly named tracked exam PDFs require crosswalk against storage by byte hash.
* The scoped census mapped every identity within each of subjects, lessons, lesson versions, exam papers, exercises, video associations, e-books and 4,555 storage objects. Row-set roots cover the named metadata projection only. Asset names and per-record content bodies remain outside this repository.

## Six real lesson samples

| Sample | Whole lesson | Projected fields | Practice MCQs | Examples of blockers |
|---|---|---|---:|---|
| 9AF Créole text-bearing | Quarantined | Objective | 10 | Rich emphasis and class semantics |
| 9AF mathematics | Quarantined | Activity text only | 0 | Unclosed markup and unsupported quiz |
| NS3 Kreyòl with imagery | Quarantined | None | 15 | Long text, malformed sections, image representation |
| 8AF Créole interactive | Quarantined | Activity text only | 0 | Unclosed markup and unsupported quiz |
| NS4 Kreyòl with table | Quarantined | None | 12 | Unsupported sections and long text |
| 7AF social science | Quarantined | None | 0 | Unsafe text, long sections, unsupported quiz |

All six also lack independently established locale. Three real field projections and 37 real practice items passed the constraints of the two pinned schemas in memory. Every accepted practice template included distinct choices, a stored choice matching the displayed answer label, and an explanation. This checks representation and internal agreement. A teacher still needs to verify the answers. Activity text projections demonstrate presentation only. No interactive behavior was converted. CI repeats schema checks on synthetic output and length-only shape twins. It has no access to live source samples.

## ExamHub mapping

All 128 papers and 2,284 exercise descriptors were paged through the metadata adapter. Every exercise resolved to a source paper. No paper resolved by exact grade, series and subject slug against the curriculum subject table. Preserve the original subject, slug, series, session, track, year, PDF reference, source versions, exercise number and original points until an independent subject crosswalk is approved. PR #51 requires a supported duration and a French title; locale is unknown on the source. 34 papers lack a usable duration. Do not default duration or fabricate a French title.

| Track | Papers | Exercises | With answers | With explanations | Human marking/self-review candidates | Quarantined MCQs |
|---|---:|---:|---:|---:|---:|---:|
| 9AF | 85 | 1,566 | 116 | 74 | 1,074 | 492 |
| NS4 | 43 | 718 | 0 | 1 | 663 | 55 |

All 2,284 have a prompt. Zero qualified for reviewed auto-grading and zero required PDF-only classification for a missing prompt. Across 547 MCQs, only 110 had stored answer text and 18 had structured options. There are zero structured answer keys. The other six stored answers belong to open items. The 1,737 open items are candidates for review. Keep original marks as source metadata; PR #51 requires zero automatic points for open items. No score or learner payload was generated. The sealed-key comparison in the prototype exercises owner acceptance and an independent reviewer receipt only with synthetic data.

Paired sample: a 2023 9AF Spanish paper carries a duration of 120 minutes, eight MCQs and eleven open items. A 2022 NS4 LLA Spanish paper has seventeen open items and no duration. Neither sample had a stored answer. Both remain excluded from an ExamHub import.

## Coverage and release decision

| Measure | Established in this run |
|---|---|
| Source inventory | 2,832/2,832 lesson identities mapped; 128/128 paper and 2,284/2,284 exercise metadata descriptors inspected |
| Structural conversion | 0/6 whole sampled lessons; 2,826 untested. One synthetic complete lesson exercised planning, simulation and reconciliation |
| Asset integrity | 0/4,555 object byte streams verified; literal-reference counts above |
| Language | 0/2,832 lessons with a source-declared locale; French and Haitian Creole coverage unresolved |
| Human review | 0/2,832 with a populated reviewer; 0 owner-accepted educator approvals established |
| Publication readiness | 0 lessons and 0 exams cleared. Unknown rights remain unresolved |

A larger rehearsal requires a captured consistent snapshot, independently reviewed grade/series/subject/unit and locale crosswalks, a bounded byte-verification adapter, a reviewed conversion policy for images/tables/formulas/activities and documented handling of historical question IDs. Obtain Claude #1's independent code review and human acceptance of the sample field-by-field diffs before widening extraction. Content, native, exam and licensing reviewers must address their respective blockers. Account and historical-attempt migration remain separate assignments.

The T7 was mounted but outside the session's writable roots. Private source processing took place in memory. No bodies or keys were sent to the CI runner or written to local storage. No import, student access, production write, feature activation, publication or deployment occurred.
