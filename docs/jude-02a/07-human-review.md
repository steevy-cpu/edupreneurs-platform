# 7. Human review

Two things decide whether Jude is fit for a Haitian student and neither can be
scored by a program: **is this good teaching, and is this real Haitian Creole?**

## What exists

| Item | Where |
|---|---|
| Teaching-quality rubric — 6 criteria, 1–4 anchors, automatic-fail list | `benchmarks/jude-02a/rubrics/teaching-quality.md` |
| Haitian Creole rubric — 5 criteria, 1–4 anchors, three open questions | `benchmarks/jude-02a/rubrics/haitian-creole.md` |
| Review packet builder (blind) | `jude_eval/review.py`, `evaluate.py review` |
| Sample packet, score sheet and label key | `benchmarks/jude-02a/results/review-sample/` |

The sample packet contains the mock and one simulated profile, to show the
format. **Its replies are stitched lesson text; do not spend a reviewer's time on it.**

## What a reviewer sees

For each case: grade and lesson, the lesson's language and the language asked
for, the kind of help and support level, what the student wrote, **the passages
the model was given**, and each candidate's explanation, hint, check question
and what it says it relied on — under a letter, not a name. The letter → model
key is a separate file to keep from reviewers until scoring is finished.

The score sheet is a CSV with one empty row per case × candidate × criterion.

## Who reviews what

| Rubric | Reviewer | Minimum |
|---|---|---|
| Teaching quality | A teacher of that grade's mathematics in the Haitian system | 2 reviewers, scoring independently |
| Haitian Creole | A native speaker who teaches or has taught in Haiti | 2 reviewers, scoring independently |

The same person may do both if qualified. Nobody who worked on the prompt or
the model choice should score.

## How much

About 40 cases × the 2–3 leading models. `review.select_cases(per_suite=…)`
picks the first cases of each suite deterministically; for a real review prefer
4 per suite and all four hint levels of at least three problems, so reviewers
can judge progression.

## Using the scores

- Report each criterion's mean **and** the number of 1s and 2s; a mean hides the
  one reply that would embarrass the project.
- Report agreement between the two reviewers per criterion. Where they differ by
  2 or more, discuss and record why rather than averaging.
- Read every comment. The open answers on the Creole rubric (would you let a
  student read this unsupervised; which variety; which terms to change) are
  worth more than the numbers.
- The gates that use these scores are in [04](04-provider-comparison-methodology.md).

## Why not an automatic Creole score

A keyword or function-word count can tell French from Creole. It cannot tell
natural Creole from a word-for-word calque of French with Creole spellings —
the exact failure the public evidence suggests models are prone to
([04](04-provider-comparison-methodology.md)). A score built that way would
look objective and reward the wrong thing. Using another model as the judge
would hide the same weakness behind a second model. So the harness reports one
warning (reply looks like French) and stops there.
