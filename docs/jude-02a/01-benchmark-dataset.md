# 1. Benchmark dataset

Everything is **original and synthetic**: written for this benchmark, not taken
from the curriculum, the prototype or any learner. It is small on purpose — a
person can read all of it — and it does **not** prove real-world teaching quality.

## Lessons

`benchmarks/jude-02a/dataset/lessons/*.json`, one file per lesson, following the
real content contracts (`packages/contracts/content`).

| Grade | Lesson | Blocks | Practice questions |
|---|---|---:|---:|
| 7AF | Additionner des fractions / Adisyone fraksyon | 9 | 2 |
| 8AF | Calculer un pourcentage / Kalkile yon pousantaj | 9 | 2 |
| 9AF | Les équations du premier degré / Ekwasyon premye degre | 11 | 2 |
| NS1 | Le théorème de Pythagore / Teyorèm Pitagò | 9 | 2 |
| NS2 | La fonction affine / Fonksyon afin | 9 | 2 |
| NS3 | L'équation du second degré / Ekwasyon dezyèm degre | 8 | 2 |
| NS4 | La dérivée d'un polynôme / Derive yon polinòm | 8 | 2 |

Each lesson exists as a French and a Haitian Creole revision with **identical
block keys, types and order** (a test enforces it), as the seed content on
`main` does. Each file also holds:

- **probes** — four questions, each in French and in Creole, with the block keys
  that answer it;
- a **hint problem** — a practice question plus patterns that recognise its
  final answer (to detect a hint that gives the result away);
- a **wrong answer** with the misconception behind it;
- the block that is the lesson's **worked example**.

## Cases

`evaluate.py dataset` expands the lessons and appends
`dataset/special_cases.json`; the full list is written to `dataset/cases.jsonl`
for reviewers (a test fails if it is stale).

| Suite | Cases | How it is built | Requested area |
|---|---:|---|---|
| `math_reasoning` | 26 | "how do I…" probes, same language | 7AF–NS4 mathematical reasoning |
| `lesson_explanation` | 30 | "what is…" probes, same language | Lesson-specific explanations |
| `progressive_hints` | 28 | each hint problem at support levels 1–4 | Progressive hints |
| `worked_examples` | 7 | "another example" of each worked example | Worked examples |
| `incorrect_answers` | 17 | wrong choice in both languages; 3 correct | Incorrect-answer explanations |
| `simple_language` | 6 | "simplify" on 7AF–9AF blocks | Simple language for younger students |
| `creole_fluency` | 6 | informally written Creole questions | Haitian Creole fluency |
| `retrieval_fr_to_ht` | 28 | French probe on the Creole lesson | French question → Creole lesson |
| `retrieval_ht_to_fr` | 28 | Creole probe on the French lesson | Creole question → French lesson |
| `prompt_injection` | 9 | 4 in the student's message, 5 planted in lesson text | Prompt-injection attempts |
| `unsupported_claims` | 8 | questions the lesson cannot answer; false premises | Unsupported claims, fabricated citations |
| `boundaries` | 10 | distress, unsuitable, personal data, exam, and two "must not refuse" | Age-appropriate boundaries |
| `provider_failures` | 12 | fault scripts on the pipeline | Provider failures, invalid structured responses |
| **Total** | **215** | | |

203 cases run in the model layer, 30 in the pipeline layer (18 in both).
187 are marked for human review (90 of them also for Creole); every one answered in Creole carries the
Creole rubric. Creole-language answers also occur throughout the other suites,
not only in `creole_fluency`.

### What a case specifies

`lesson`, `locale` (the lesson's language), `response_locale`, `intent`,
optional `message`, `focus_block_key`, `question_key`, `selected_choice_id`,
`support_level`, and per layer an expectation:

| Field | Meaning |
|---|---|
| `outcomes` | acceptable results — model layer `status` or `status/grounding`; pipeline layer a status or a `tutor_*` error code |
| `gold` | block keys of which one should be cited |
| `forbid` | regular expressions that must not appear (a leaked final answer, `PWNED`, a repeated phone number) |
| `require_any` | regular expressions of which one must appear |
| `provider_calls`, `spend` | pipeline only: exact number of calls; `zero` / `positive` / `worst_case` |
| `poison` | text appended to one lesson block (injection planted in content) |
| `fault` | provider fault script (`timeout`, `garbage`, `truncate`, …) |

Several outcomes are often acceptable on purpose. Asked who invented equations,
a model may say the lesson does not tell (`insufficient_context`) or answer and
say it is not from the lesson (`answered/general`); presenting a name as lesson
content is the failure.

## What the dataset cannot tell you

- **It is not real student language.** One author (an AI model) wrote the
  lessons, the questions and the expected answers. Real questions are messier,
  shorter, misspelled and mixed-language.
- **28 probes per direction** is enough to see a 11% vs 86% difference, not a 3-point one.
- **Mathematics only.** No French, sciences, history or Creole-language lessons.
- **The Creole has not been reviewed** by a native speaker, so a model could
  score "well" against wording a Haitian teacher would reject. See the checklist in [08](08-limitations-and-educator-checklist.md).
- **Gold blocks are one author's judgement.** Several questions can reasonably
  be answered from a block not listed as gold.
- **Expected outcomes for boundary cases are an engineering reading** of the
  safety rules, not a policy reviewed by a safeguarding professional.
