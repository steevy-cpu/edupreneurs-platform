# 3. Retrieval design

## What may be retrieved

Only content of **one approved lesson revision** that the learner can already
read: its blocks and, when the request names one, a practice question of that
revision. `SqlLessonSource` runs the same query as `GET /v1/lessons/{id}` inside
`Database.transaction(learner_id)`, so PostgreSQL's row-level security is the
filter. Drafts, revisions in review, rejected revisions, approved revisions that
are not in a current pack, withdrawn lessons and unknown ids are all simply
absent — the tutor cannot distinguish them and returns one answer
(`tutor_lesson_unavailable`) for all of them.

Not retrieved in Jude-01: other lessons, other learners' data, the web, the
learner's own progress (see "Designed, not built" below).

## Stable references

Every passage carries a `LessonReference` created by the server:

| Field | Meaning |
|---|---|
| `lesson_id` | `app.lessons.id` |
| `lesson_revision_id` | `app.lesson_revisions.id` — the immutable revision |
| `locale` | `fr` or `ht` (a revision has exactly one) |
| `kind` | `block` or `question` |
| `key` | the block `key`, or the `question_key` |

If the client pins `lesson_revision_id` and a newer revision has replaced it,
the tutor answers `tutor_lesson_revision_not_current` instead of silently citing
block keys from a revision the learner is not looking at.

## Pipeline

```
approved lesson ─▶ passages (one per block) ─▶ Ranker ─▶ relevant top-k
                                                    │
        + the block in focus, the question asked about
        + the section heading above each chosen passage
                                                    ▼
                  size bound (max_context_chars) ─▶ lesson order ─▶ ids P1..Pn
```

1. **Passages.** One per block. An example block is its title and steps, one per
   line. Unknown block types (a later content format) are skipped, not guessed.
2. **Query.** The learner's words after screening and redaction; if there are
   none, the prompt of the practice question they asked about.
3. **Ranking.** `Bm25Ranker`: BM25 over accent-folded, stop-word-filtered,
   prefix-stemmed words. A passage is *relevant* only if it covers at least 34%
   of the question's informative (IDF) weight, so sharing one common word or the
   digit 5 is not enough.
4. **Nothing relevant → no answer.** If the learner asked something in their own
   words and no passage is relevant, retrieval returns nothing and the service
   replies with the fixed "not in this lesson" message **without calling a
   model**. A block in focus does not rescue an unrelated question.
5. **Explicit pointers are always context.** The block in focus and the named
   practice question are included; each chosen passage brings its section heading.
6. **Bound.** Passages are kept in priority order until `max_context_chars`
   (default 6000) is reached, then restored to lesson order. `truncated` records
   that something was dropped.
7. **Opaque ids.** The model sees `P1`, `P2`, … and never a real identifier.

### Practice questions and the answer

- The answer key (`correct_choice_id`) is never put in a prompt.
- The reviewed explanation, which gives the answer away, is included only for
  `explain_answer` or from `support_level` 3. A first hint cannot leak it.
- Whether the learner's choice was right is decided by the server from the
  reviewed key and passed to the model as a fact.

## Lexical versus semantic: what was measured

`uv run python -m edu_api.tutor.evaluation` (synthetic lesson, 12 questions per
language, 6 unrelated questions). Output of the run on this branch:

| Ranker | Dataset | Cases | Hit@1 | Hit@3 | MRR |
|---|---|---:|---:|---:|---:|
| `bm25-v1` | fr question / fr lesson | 12 | 0.92 | 1.00 | 0.96 |
| `bm25-v1` | ht question / ht lesson | 12 | 0.92 | 0.92 | 0.94 |
| `bm25-v1` | ht question / fr lesson | 12 | 0.33 | 0.33 | 0.33 |
| `char3-tfidf-v1` | fr question / fr lesson | 12 | 0.75 | 1.00 | 0.88 |
| `char3-tfidf-v1` | ht question / ht lesson | 12 | 0.83 | 0.92 | 0.90 |
| `char3-tfidf-v1` | ht question / fr lesson | 12 | 0.58 | 0.58 | 0.58 |
| `rrf(bm25-v1+char3-tfidf-v1)` | fr question / fr lesson | 12 | 0.75 | 1.00 | 0.88 |
| `rrf(bm25-v1+char3-tfidf-v1)` | ht question / ht lesson | 12 | 0.83 | 0.92 | 0.90 |
| `rrf(bm25-v1+char3-tfidf-v1)` | ht question / fr lesson | 12 | 0.58 | 0.58 | 0.58 |

Unrelated questions wrongly matched: 0 of 6 for all three rankers.

**What this shows**

- When the question is in the language of the lesson, plain BM25 finds a correct
  block in the top three for 92–100% of the questions and wrongly matches none
  of the unrelated ones. For a corpus of a dozen blocks this is enough.
- Character trigrams and the fused ranker are *worse* at rank 1 in the same
  language. They are not the default.
- **Cross-language is the weakness.** A Creole question against a French lesson
  finds the right block a third of the time with BM25. A test pins this number
  so nobody assumes otherwise.

**What this does not show**

- **No semantic embedding model was evaluated.** None is authorised or available
  offline in this milestone, so that row is absent rather than invented. The
  character-trigram ranker is a fuzzy-matching stand-in, not an embedding.
- The data is synthetic, small and written by the same author as the lesson.
  Real student phrasing will be messier. Treat the numbers as a regression
  alarm and a baseline to beat.

**Decision for Jude-01:** lexical BM25, no vector database. Embeddings are worth
evaluating for exactly one case — questions in a different language from the
lesson — and there are cheaper first answers to that case:

1. The app already has both revisions; send the request with the `locale` of the
   lesson the learner is reading and let `response_locale` choose the answer
   language. The headline example ("Pourquoi on soustrait 5 des deux côtés ?"
   on a French lesson, answered in Creole) works today for that reason.
2. Use the sibling revision in the learner's language for *ranking* and map the
   hit back by block key (keys are shared across locales in the seed content;
   this needs an editorial rule that they always are).
3. Only then: embeddings.

## Adding embeddings later

Implement `Ranker` (`name`, `rank(query, passages) -> list[ScoredPassage]`) and
pass it to `build_tutor_service(ranker=...)`. `HybridRanker` already fuses any
set of rankers. Because a lesson is a few dozen passages, vectors can be
computed when a revision is approved and stored beside it (revisions are
immutable, so they never go stale); a brute-force cosine over one lesson needs
no index and no vector database. The tutoring contract does not change.

## Designed, not built

- **Learner state.** "Which questions of this lesson did I get wrong?" would be
  a `LearnerStateSource` reading `app.practice_attempts` under the learner's own
  RLS. Not built: the request already carries the one answer being explained,
  and reading history adds a privacy surface that needs the consent decision first.
- **Related concepts across lessons** (prerequisites). Needs an editorial
  relation between lessons that does not exist yet.
- **Content format v2** (#7: formulas, tables, images). `parse_blocks` must be
  taught each new block type; until then unknown types are skipped.
