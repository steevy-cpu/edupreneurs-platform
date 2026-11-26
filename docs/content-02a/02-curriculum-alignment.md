# 2. Curriculum alignment — what the pilot covers, what it does not

**Status: proposed, not validated by an educator or the ministry.** “Direct / partial / context” describes how closely a lesson matches an item **as the author read it**. It is **not** an official alignment and **no official adoption is claimed**. Sources are described in `01-source-register.md`. *(Revised after independent QA, PR #34: topic names are now paraphrased rather than quoted, lesson 1's S2 relation is partial, and the claim of agreement between S1 and S2 is qualified.)*

## Matrix (S1 = 2024 programme, S2 = 2019 minimal-competencies programme)

| Lesson | S1 (2024), unit “Nombres et calculs”, 7e année | Relation | S2 (2019), PDF locator | Relation |
|---|---|---|---|---|
| 1. Lire, écrire et comparer des nombres entiers | printed p. 38: reading/writing/representing naturals, then ordering/comparing them | **partial** (naturals only; no graduated half-line, fractions or decimals) | PDF p. 9, 2.6.1: comparing and ordering naturals | **partial** (reading and writing up to 999 999 goes beyond it) |
| 2. Additionner et soustraire | printed p. 38: meaning of operations; carrying them out mentally, by hand, with an instrument | **partial** (no calculator work) | PDF p. 6, 2.1.1: mental and written arithmetic on naturals | direct (topic); the lesson's method is its own |
| 3. Multiplier et diviser | same + quotient, multiples and divisors | **partial** (one-digit multipliers; small division with remainder) | PDF p. 6, 2.1.1 | direct (topic); remainder vocabulary is not prescribed there |
| 4. Multiplier et diviser par 10, 100, 1 000 | printed p. 38: scaling a decimal by powers of ten in both directions (exact operations on naturals are a precursor) | **partial** (naturals only; decimals and 0,1… deferred) | PDF p. 6, Mesures 1.1.2 (unit conversion) | **context only** (no direct S2 item found) |
| 5. Multiples et diviseurs | printed p. 38: quotient, multiples and divisors of integers | direct (small positive numbers; no primes/GCD/LCM, which S1 puts in 9e) | PDF p. 9, 2.5 (divisibility tests) | **context only** (no explicit requirement to list all divisors) |
| 6. Critères de divisibilité | printed p. 38: divisibility criteria for the six divisors the lesson teaches | **direct** (same list of divisors) | PDF p. 9, 2.5.1 (same six, plus 11) | partial (11 not covered) |

The same references are stored per lesson in `pilot.json` (`curriculum_refs`) and checked by the validator (each must name a source in the register).

## S1 7e-année items **not** covered by this pilot (→ Content-02B)

* Read/write/represent **fractions and decimals**; convert decimal ↔ fraction; order them; place on a graduated half-line.
* **Equivalent fractions** (7e, printed p. 38). Adding/subtracting fractions is listed under **8e** in S1 (printed p. 40) but reported by QA in 7AF in S2: settle the placement before scoping 02B.
* **Multiplying/dividing decimals** by 10, 100, 1 000, 0,1, 0,01, 0,001.
* **Fraction of a quantity**; problems with fractions or decimals (7e, printed p. 39).
* **Calculation with an instrument** (calculator), and a regular mental-calculation ritual beyond the examples given.
* The other 7e-année units of S1 (algebra of letters is 8e; geometry, measures, data/proportionality are separate units).

## Topics the two programmes disagree about (not taught in the pilot)

Priority of operations and chains of operations, and powers of natural numbers: **S1 puts them in 8e année (printed pp. 39-40), S2 in 7e**. They are excluded until an educator or the ministry decides (see register §“Conflict”).

## What this matrix does **not** show

* It does not show alignment with the 1989 programmes (not located).
* It does not show that a student who finishes these six lessons has met any official objective. Official objectives are broader and are assessed in class.
* “Direct” does not mean “identical wording or depth”: it means the topic name matches. The topics were chosen because both documents place them in 7e année **by topic name**; they do not agree on every detail, and **the pilot makes no claim that the two documents agree on everything it teaches**.
