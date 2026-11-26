# 2. Curriculum alignment — what the pilot covers, what it does not

**Status: proposed, not validated by an educator or the ministry.** “Direct / partial / context” describes how closely a lesson matches an item **as the author read it**. It is **not** an official alignment. Sources are described in `01-source-register.md`.

## Matrix (S1 = 2024 programme, S2 = 2019 minimal-competencies programme)

| Lesson | S1 (2024), unit “Nombres et calculs”, 7e année | Relation | S2 (2019), PDF locator | Relation |
|---|---|---|---|---|
| 1. Lire, écrire et comparer des nombres entiers | “Lire, écrire et représenter les nombres entiers naturels” ; “Classer (situer, ordonner, comparer)…” | **partial** (naturals only; no graduated half-line, fractions or decimals) | p. 9, Algèbre 2.6.1 “Comparer et ordonner des entiers naturels” | direct |
| 2. Additionner et soustraire | “Donner un sens aux opérations” ; “Savoir effectuer des opérations… (mental, à la main, instrumentée)” | **partial** (no calculator work) | p. 6, 2.1.1 | direct |
| 3. Multiplier et diviser | same + “Quotient, multiples et diviseurs” | **partial** (one-digit multipliers; small division with remainder) | p. 6, 2.1.1 | direct |
| 4. Multiplier et diviser par 10, 100, 1 000 | “Multiplier ou diviser un nombre décimal par 10 ; 100 ; 1 000 ; 0,1 ; 0,01 ; 0,001” | **partial** (naturals only; decimals and 0,1… deferred) | p. 6, Mesures 1.1.2 (unit conversion) | context (no direct S2 item found) |
| 5. Multiples et diviseurs | “Quotient, multiples et diviseurs de nombres entiers” | direct (small numbers; no primes/GCD/LCM, which S1 puts in 9e) | p. 9, 2.5 | context |
| 6. Critères de divisibilité | “critères de divisibilité par 2, 3, 4, 5, 9, 10” | **direct** (exact list) | p. 9, 2.5.1 (adds 11) | partial (11 not covered) |

The same references are stored per lesson in `pilot.json` (`curriculum_refs`) and checked by the validator (each must name a source in the register).

## S1 7e-année items **not** covered by this pilot (→ Content-02B)

* Read/write/represent **fractions and decimals**; convert decimal ↔ fraction; order them; place on a graduated half-line.
* **Equivalent fractions**; adding/subtracting fractions.
* **Multiplying/dividing decimals** by 10, 100, 1 000, 0,1, 0,01, 0,001.
* **Fraction of a quantity**; problems with fractions or decimals.
* **Calculation with an instrument** (calculator), and a regular mental-calculation ritual beyond the examples given.
* The other 7e-année units of S1 (algebra of letters is 8e; geometry, measures, data/proportionality are separate units).

## Topics the two programmes disagree about (not taught in the pilot)

Priority of operations and chains of operations, and powers of natural numbers: **S1 puts them in 8e année, S2 in 7e**. They are excluded until an educator or the ministry decides (see register §“Conflict”).

## What this matrix does **not** show

* It does not show alignment with the 1989 programmes (not located).
* It does not show that a student who finishes these six lessons has met any official objective. Official objectives are broader and are assessed in class.
* “Direct” does not mean “identical wording or depth”: it means the topic name matches.
