# 1. Source register — what was verified, what is uncertain, and the rights

Research date: **2026-11-26**. Method: web search plus reading the PDFs listed below. Only **short factual references** (document, page, topic names, objective codes) are kept in this repository. **No curriculum text is reproduced**, because S1 is marked “Tous Droits Réservés” and S2’s rights are unstated.

## Summary of what the research established

| Question | Finding | Confidence |
|---|---|---|
| Does an official 7AF mathematics curriculum exist? | **Yes, two documents, which do not agree on grade placement** (see below). | High (both PDFs read) |
| Which one is current? | The **2024 third-cycle programme (S1)** is the newer one and, per press reports of ministerial decision D-2(1)384 (9 Jan 2026), new third-cycle programmes are to be generalised **starting in 7AF in 2027-2028**. The 2019 “compétences minimales” programme (S2) was a measure for 2019-2020. | Medium: decision text not obtained; press does not name mathematics explicitly |
| Is S1 the final, validated text? | **Unknown.** It is hosted by a publisher, not the ministry, and its own preamble still reads “Introduction politique à réaliser quand les programmes seront validés”. | Low |
| Is there an official 7AF curriculum **we may reproduce**? | No: S1 states all rights reserved; S2 states none. We reproduce nothing. | High |

## The register

| ID | Document | Issuer / host | Verification | Rights status | Used for |
|---|---|---|---|---|---|
| **S1** | Programme du 3e cycle (7e à 9e AF) — **Mathématiques**, 60 p., “Tous Droits Réservés – 2024-2025” | MENFP / DEF; PDF hosted by Éditions JPL (`editions-jpl.com/programmes-officiels-menfp-3e-cycle-fondamental`) | **Read** (table of contents; “Domaine des mathématiques”; unit “Nombres et calculs” 7e-9e année, printed pp. 35-42) | All rights reserved — **reference only** | Primary alignment target |
| **S2** | Programme à compétences minimales — 7ème AF (Nov. 2019), 82 p. | MENFP / DEF; copy hosted by `haiti-now.org` | **Read** (mathematics = PDF pp. 4-15) | Unknown — **reference only** | Cross-check; shows what was in 7AF in 2019 |
| **S3** | Décision ministérielle D-2(1)384, 9 Jan 2026 (generalisation of new 3rd-cycle programmes) | MENFP, via Le Placentin (12 Jan 2026) and Le National (14 Jan 2026) | **Secondary press reports only**; decision text not obtained | Not used | Context on timing |
| **S4** | Cadre d’orientation curriculaire (MENFP 2021) | MENFP; hosted by `mit-ayiti.net` | **Located, not read** | Unknown | Not used |
| **S5** | Séquences modèles de mathématiques 7e année (Projet Nectar / MENFP portal) | `menfp.reseau-canope.fr` | **Located, not read** | Not used | Candidate input for Content-02B (fractions) |
| **S6** | Programmes officiels du fondamental valides depuis mars 1989 | MENFP | **Not located** | Unknown | Nothing: **no alignment with the 1989 programmes is claimed** |

Full machine-readable entries (URLs, notes, statuses) are in `content/pilots/7af-math/pilot.json` (`sources`), and the validator rejects a lesson that cites a source not listed there.

## What exactly was verified in S1 (2024)

Printed page 38, unit **“Nombres et calculs”**, 7e année, three sub-goals:

1. *Maîtriser et représenter les nombres naturels, ainsi que les nombres décimaux et fractionnaires positifs dans des cas simples* — read/write/represent naturals, fractions, decimals; convert decimal ↔ fraction; order/compare.
2. *Maîtriser et effectuer des calculs avec des nombres positifs…* — meaning of operations; add/subtract/multiply/divide in three forms (mental, by hand, with an instrument); **quotient, multiples and divisors; divisibility criteria by 2, 3, 4, 5, 9, 10; equivalent fractions**; multiply/divide a decimal by 10, 100, 1 000, 0.1, 0.01, 0.001.
3. *Résoudre des problèmes avec les nombres* — fraction of a quantity; problems with integers and simple fractions.

The same document places **chains of operations with priority rules, squares, powers of 10 and simple powers in 8e année**, and **prime numbers, prime factorisation, GCD/LCM in 9e année**.

## What exactly was verified in S2 (2019)

Algèbre items found in the 7AF monthly table (PDF pp. 4-9): sets (1.x), naturals 2.1 (operations), 2.2 (**priority rules, chains of operations**), 2.3 (**positive integer powers**), 2.4 (binary numeration), 2.5 (**divisibility by 2, 3, 4, 5, 9, 10, 11**), 2.6 (order), decimals 3.x, proportionality, statistics, geometry, measures. The foreword states it does **not** replace the objectives of the programmes valid since March 1989.

## Conflict between S1 and S2, and the pilot’s response

| Topic | S1 (2024) | S2 (2019) | Pilot |
|---|---|---|---|
| Operations on naturals | 7e | 7e | **Included** (lessons 2-3) |
| Order / comparison of naturals | 7e | 7e | **Included** (lesson 1) |
| Multiples, divisors | 7e | (within 2.5) | **Included** (lesson 5) |
| Divisibility 2, 3, 4, 5, 9, 10 | 7e | 7e (also 11) | **Included** (lesson 6); 11 not covered |
| Priority of operations / chains | **8e** | **7e** | **Excluded** — placement disputed between the documents; owner/educator decision |
| Powers of a natural number | **8e** | **7e** | **Excluded** — same reason |
| Binary numeration | not found | 7e | Excluded |
| Fractions, decimals, fraction of a quantity | 7e | 7e (decimals) | **Excluded here → Content-02B** |

The pilot therefore teaches **only what both documents agree belongs in 7AF**, and documents every gap. It does **not** claim to “follow the official programme”.

## Rights summary

* S1, S2: **not copied**; cited by locator only. Obtaining permission is a prerequisite for any future quotation or for embedding official objective wording in the product.
* All lesson text, examples and exercises were **written for this pilot with AI assistance**; no passage was copied from a textbook, the programmes, or any prototype lesson (the Lovable prototype was **not** consulted). The licence under which Edupreneurs will publish them is an **owner decision** (`licence_status: unassigned_owner_decision`).
* Third-party hosts (JPL, haiti-now, press) are cited as **where a copy was found**, not as rights holders.

## Open questions for the owner / ministry

1. Is S1 the validated, final programme? (ask the MENFP for the signed version and the text of decision D-2(1)384.)
2. Do mathematics follow the 2027-2028 generalisation calendar for 7AF?
3. Which grade should carry priority of operations and powers (S1: 8e; S2: 7e)?
4. May Edupreneurs align its objective labels to the official wording, and under what licence?
