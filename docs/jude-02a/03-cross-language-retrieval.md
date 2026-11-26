# 3. Cross-language retrieval

Jude-01 reported that its lexical ranker finds the right block for 92–100% of
same-language questions and about a third of cross-language ones, on **one**
lesson. Jude-02A re-measures on seven lessons and benchmarks four deterministic
improvements. None needs a model, a network or a vector database.

Full tables: `benchmarks/jude-02a/results/retrieval.md` (`evaluate.py retrieval`).

## The metric that matters: "gold in context"

Rank metrics (Hit@1, Hit@3, MRR) are reported, but the number a learner feels
is whether a block that answers the question is among the passages Jude-01's
retriever would actually put in the prompt (top 4, plus its own rules). If not,
Jude answers "I cannot find this in the lesson" or answers from the wrong passage.

## Results (28 questions per direction; synthetic)

Gold in context:

| Strategy | fr→fr | fr→ht | ht→fr | ht→ht |
|---|---:|---:|---:|---:|
| A. BM25 — **Jude-01 baseline** | 0.75 | 0.11 | 0.11 | 0.68 |
| B. Character trigrams (Jude-01's comparison ranker) | 0.82 | 0.50 | 0.46 | 0.82 |
| C. Sections + BM25 | 0.82 | 0.11 | 0.11 | 0.82 |
| D. Sections + glossary | 0.82 | 0.75 | 0.61 | 0.82 |
| D′. Same, without the lesson's own topic terms | 0.82 | 0.50 | 0.46 | 0.82 |
| E. Sections + sibling block keys | 0.82 | 0.82 | 0.82 | 0.82 |
| F. Sections + sibling keys + glossary | 0.89 | 0.89 | 0.82 | 0.82 |
| **G. Sections + sibling keys + two-term rule** | **0.86** | **0.86** | **0.86** | **0.86** |

("fr→ht" = French question, Creole lesson.)

Unrelated questions wrongly matched, out of 42 per direction: 0 for every
strategy except B (trigrams: 2, 0, 2, 8).

The same questions after one sentence of ordinary talk ("J'ai peur d'échouer en
maths. …", "Mwen pa fò nan matematik ditou. …"), all directions pooled:

| Strategy | Plain (n=112) | Padded (n=336) | Unrelated matched | Padded unrelated matched |
|---|---:|---:|---:|---:|
| A. Jude-01 baseline | 0.41 | **0.05** | 0/168 | 0/168 |
| E. Sections + sibling keys | 0.82 | 0.10 | 0/168 | 0/168 |
| **G. + two-term rule** | **0.86** | **0.70** | 0/168 | 0/168 |

Informally written Creole (no technical vocabulary, contractions), 6 questions:
A 3/6, G 4/6, F 5/6, trigrams 5/6.

## The four improvements

### 1. Sections: a matched heading stands for its section

Questions often match a section's *heading* best ("À quoi sert la dérivée ?" is
almost the heading itself). Jude-01 adds the heading above a chosen block, but
when the heading is the hit it does not pull in the body under it — and a
context of headings only is treated as "nothing found". `SectionRanker` gives
every block under a matched heading 90% of the heading's score.
Effect: same-language 0.68–0.75 → 0.82.

### 2. Sibling block keys: use the other-language revision to find the block

A lesson exists as one revision per language, and on `main`'s seed content (and
in this benchmark) the two have the same block keys. `SiblingKeyRanker` ranks
the question against **both** revisions and maps the sibling's hits back by
key. No language detection is needed, and citations still point at the revision
the learner is reading — the sibling is used to find *which* block, never
quoted (a test asserts both).
Effect: cross-language 0.11 → 0.82, exactly the same-language figure.

It refuses to operate unless `verify_key_alignment` passes: same lesson,
different locale, identical keys, types and order.

### 3. Bilingual glossary

`GlossaryRanker` translates the question's words into the lesson's language
with 76 French↔Creole school-mathematics pairs (`dataset/glossary.fr-ht.json`)
before ranking. Effect: 0.11 → 0.61–0.75.

Two honest caveats, both measured:

- **It depends on having the lesson's own vocabulary.** With a lesson's topic
  terms removed (row D′) it falls to 0.46–0.50 — no better than character
  trigrams. A glossary has to be maintained per topic to be worth having.
- **The glossary was written by the author of the lessons**, from the lesson
  texts. That flatters it. It was not written from the questions, but an
  independent glossary would do worse.

It is not recommended as the primary method. It is the fallback for a lesson
that exists in only one language, and it adds a little on top of sibling keys (row F).

### 4. Two-term rule: do not punish a student for writing a full sentence

Jude-01 calls a passage relevant only if it covers 34% of the question's
informative weight. Every extra word dilutes that, so "J'ai peur d'échouer en
maths. Comment additionner deux fractions…" matches nothing. `TwoTermBm25Ranker`
keeps Jude-01's scoring and adds a second way to be relevant: the passage
matches two different non-numeric terms of four letters or more.
Effect on padded questions: 0.05–0.10 → 0.70, with no unrelated question matched.

## Recommendation

**G — sections + sibling block keys + two-term rule** as Jude's retrieval, with
the glossary as a fallback for single-language lessons. It is what the model
benchmark uses to build prompts.

**No vector database, and no embeddings yet.** The cross-language gap that
motivated them is closed by key mapping wherever both revisions exist. The
remaining 14% are mostly questions whose wording shares no content word with the
answering block ("Comment calculer rapidement 10 % d'un nombre ?" against a tip
that says "50 %… sa moitié; 10 %… divisée par 10") — that is where a semantic
method could help, and it should be shown to on this benchmark before it is adopted.

## Not done, and what it would take

| Item | State |
|---|---|
| Wiring G into the Jude service | **Not done.** The rankers live in `benchmarks/jude-02a/jude_eval/crosslang.py`. `LessonSource` must fetch the sibling revision under the same row-level security, and the service must build the ranker per request. A Jude-02B change with its own tests. |
| An editorial rule that both revisions keep the same block keys | **Needed.** Today it is a property of the seed data, not a guarantee. Without it, sibling mapping silently turns off for that lesson (alignment check fails → fall back to glossary). |
| Tuning the 34% / two-term / 90% numbers | Chosen once, not tuned, to avoid fitting 28 questions. Re-check on real questions. |
| False positives | 0 of 336 here, but the "unrelated" set is small and far from the lessons' topics. A near-topic unrelated set (another mathematics lesson's questions) is a missing test. |
| Embeddings | Not evaluated: no model authorised. |
