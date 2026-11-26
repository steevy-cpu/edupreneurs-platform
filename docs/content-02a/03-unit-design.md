# 3. Unit design — “Les nombres entiers naturels : lire, calculer, diviser”

**Proposed pilot (not owner-approved): 7AF mathematics.** Six short lessons, each readable in about 5-8 minutes, each with one idea and a built-in practice set.

## Why this unit

* It is the part of 7e année “Nombres et calculs” that **both** official documents contain (see the conflict table in the source register).
* It is **beginner-friendly** and a prerequisite for fractions and decimals (Content-02B) and for 8e année algebra (S1 explicitly leads from “opérations à trous” to unknowns).
* It makes **offline practice meaningful**: every exercise has a single mechanically checkable answer, which suits the existing `mcq-v1` contract.

## Progression

| # | Lesson | One idea | Builds on |
|---|---|---|---|
| 1 | Lire, écrire et comparer des nombres entiers | Place value decides a digit’s worth; compare by length, then left to right | — |
| 2 | Additionner et soustraire | Column method with carrying/exchanging; mental rounding; check with the inverse | 1 |
| 3 | Multiplier et diviser | Repeated addition; division with remainder; `dividende = diviseur × quotient + reste` | 2 |
| 4 | Multiplier et diviser par 10, 100, 1 000 | Place value shifts; unit conversions m↔cm, km↔m | 1, 3 |
| 5 | Multiples et diviseurs | “Division that comes out even”; listing divisors | 3 |
| 6 | Les critères de divisibilité | Decide divisibility from digits, then verify by division | 3, 5 |

## Design choices (and why)

* **One lesson = one screen of ideas.** Each lesson is 10-13 blocks of v1 types only (`heading`, `paragraph`, `example`, `callout`); about 2.0-2.6 KB of lesson text per language (plus about 1.7-2.6 KB of questions).
* **Fixed block skeleton, stable keys.** Every lesson starts with `objectifs` then `intro` (a concrete situation) and ends with `piege` (a common error) and `retenir` (a summary). Keys such as `exemple-addition` are identical in French and Creole and never change meaning, so reading position and future revisions stay aligned.
* **Worked examples before practice**, one step per line, each arithmetic result verified by the tool.
* **Common mistakes named explicitly** (`piege`): comparing only the last digit, subtracting the large from the small, dividing by 0, “just add a zero”, adding digits for divisibility by 3/9 incorrectly.
* **Plain text only.** No images, no maths markup (format v2 is not approved). Numbers use a no-break space inside digit groups (`2 450`) so a number never splits across lines on a 320 dp screen.
* **Everyday Haitian contexts** with neutral, clearly fictional quantities (a stadium, mangoes in baskets, notebooks in parcels, a school, a truck of maize). No prices, brands, politics or real people.
* **Practice: five multiple-choice questions per lesson.** Distractors are *diagnostic*: they reproduce the typical error (forgetting to carry, mixing quotient and remainder, confusing 10× with +10, looking at only the last digit).
* **Practice is formative.** Answer keys ship with the lesson (the existing offline-practice contract). They must **never** be reused as a controlled exam item (see Content-Delivery-00 doc 6 §4).

## Two languages

French and Haitian Creole are **independent drafts**, not one derived from the other by a program. They are tied together only by stable identifiers (lesson slug/uuid, block keys, question keys, choice ids, correct choice) and by the **numbers**: the validator refuses a Creole text whose numbers differ from the French. Creole mathematical vocabulary used (e.g. *adisyon, soustraksyon, miltiplikasyon, divizyon, kosyan, rès, divizè, miltip, divizib, kritè divizibilite, santèn, dizèn, inite*) is **unreviewed**: a native-speaker educator may prefer other terms. Every Creole string is a draft.

## Known limits of the design (honest list)

* Multiple choice cannot assess working. Free-response or step-by-step questions need a contract that does not exist yet (`question-mcq` only).
* No pictures: place value, columns and the balance of operations are text-only; a graduated half-line (an S1 item) is not possible in v1.
* Column arithmetic is described in words; on a narrow screen a true column layout is not available.
* The sample sizes (6 lessons, 30 questions) are far below a school year; this is a pilot to test the **workflow**, not a course.
* No pilot with real students has taken place. Difficulty and timing are the author’s estimate, not measurements.
