# 1. Source register — what was verified, what is uncertain, and the rights

Research date: **2026-11-26**. Method: web search plus reading the PDFs listed below. Only **short factual references** (document, page, objective codes, and **paraphrased** topic names) are kept in this repository. **No curriculum text is reproduced**, because S1 is marked “Tous Droits Réservés” and S2’s rights are unstated. *(Correction round, after independent QA in PR #34: the descriptor locators and this register previously echoed some objective wording; they now paraphrase. Owner/legal review of any remaining official-title mention is still pending.)*

## Summary of what the research established

| Question | Finding | Confidence |
|---|---|---|
| Does an official 7AF mathematics curriculum exist? | **Yes, two documents, which do not agree on grade placement** (see below). | High (both PDFs read) |
| Which one is current? | The **2024 third-cycle programme (S1)** is the newer one and, per press reports of ministerial decision D-2(1)384 (9 Jan 2026), new third-cycle programmes are to be generalised **starting in 7AF in 2027-2028**. The 2019 “compétences minimales” programme (S2) was a measure for 2019-2020. | Medium: decision text not obtained; press does not name mathematics explicitly |
| Is S1 the final, validated text? | **Not established.** The publisher-hosted PDF calls itself a *définitive* version dated **28 July 2024** (PDF p. 2), yet the preamble page (PDF p. 3) still holds an unfinished drafting instruction that anticipates a future validation. It is hosted by a publisher, not the ministry, and **no signed ministry adoption record tying this exact version to a school year was found.** *Both facts were checked directly in the PDF during the correction round.* | Low–medium |
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

Printed pages **38–39** (PDF pp. 39–40), unit **“Nombres et calculs”**, 7e année. Three sub-goals; the **third continues onto printed p. 39**, where the 8e-année table also begins (all checked in the PDF during the correction round):

1. **Naturals, simple positive decimals and fractions** — read/write/represent them; convert decimal ↔ fraction; order/compare (including on a graduated half-line).
2. **Calculation with positive numbers** — meaning of operations; add/subtract/multiply/divide in three forms (mental, by hand, with an instrument); **quotient, multiples and divisors; divisibility criteria by 2, 3, 4, 5, 9, 10; equivalent fractions**; multiply/divide a decimal by 10, 100, 1 000, 0.1, 0.01, 0.001.
3. **Problem solving with numbers** — fraction of a quantity; problems with integers and simple fractions (printed p. 39).

The same document places **squares, powers of 10 and simple powers** at the start of the 8e-année table (printed p. 39), **chains of operations with priority rules** and the **explicit rows on adding/subtracting fractions** in 8e année (printed p. 40), and **prime numbers, prime factorisation, GCD/LCM in 9e année** (printed p. 41). Equivalent fractions appear in 7e année (printed p. 38).

## What exactly was verified in S2 (2019)

Algèbre items found in the 7AF monthly table (PDF pp. 4-9): sets (1.x), naturals 2.1 (operations), 2.2 (**priority rules, chains of operations**), 2.3 (**positive integer powers**), 2.4 (binary numeration), 2.5 (**divisibility by 2, 3, 4, 5, 9, 10, 11**), 2.6 (order), decimals 3.x, proportionality, statistics, geometry, measures. **Independent QA (PR #34) additionally reports that S2 covers fraction reading and equivalence (PDF p. 13) and fraction addition/subtraction (PDF p. 14); this register's earlier wording understated fractions in S2. That QA reading has not been re-checked by the author of this correction.** The foreword states it does **not** replace the objectives of the programmes valid since March 1989.

## Conflict between S1 and S2, and the pilot’s response

| Topic | S1 (2024) | S2 (2019) | Pilot |
|---|---|---|---|
| Operations on naturals | 7e | 7e | **Included** (lessons 2-3); S2 states no remainder vocabulary and the 2024 text names calculator work, which the pilot omits |
| Order / comparison of naturals | 7e | 7e | **Included** (lesson 1) |
| Multiples, divisors | 7e (explicit) | within 2.5 (divisibility tests); **no explicit requirement to list all divisors** | **Included** (lesson 5); S2 support is *contextual* only |
| Divisibility 2, 3, 4, 5, 9, 10 | 7e | 7e (also 11) | **Included** (lesson 6); 11 not covered |
| Priority of operations / chains | **8e** | **7e** | **Excluded** — placement disputed between the documents; owner/educator decision |
| Powers of a natural number | **8e** | **7e** | **Excluded** — same reason |
| Binary numeration | not found | 7e | Excluded |
| Equivalent fractions; fraction of a quantity | 7e (printed pp. 38-39) | fractions reported by QA (PDF pp. 13-14), not re-checked | **Excluded here → Content-02B** |
| Adding/subtracting fractions | **8e** (printed p. 40) | reported by QA in 7AF (PDF p. 14) | **Excluded** — placement disputed; settle before Content-02B |
| Decimals; reading and writing decimals | 7e | 7e (decimals 3.x) | **Excluded here → Content-02B** |

The pilot is limited to topics that **both documents place in 7e année at the level of topic names**; depth, vocabulary and method are the author's and **may differ from either document** (for lessons 4 and 5 the 2019 document gives contextual support only; lesson 6 omits divisibility by 11). It documents every gap and does **not** claim to “follow”, “implement” or be “adopted by” any official programme.

## Rights summary

* S1, S2: **not copied**; cited by locator only. Obtaining permission is a prerequisite for any future quotation or for embedding official objective wording in the product.
* All lesson text, examples and exercises were **written for this pilot with AI assistance**; no passage was copied from a textbook, the programmes, or any prototype lesson (the Lovable prototype was **not** consulted). The licence under which Edupreneurs will publish them is an **owner decision** (`licence_status: unassigned_owner_decision`).
* Third-party hosts (JPL, haiti-now, press) are cited as **where a copy was found**, not as rights holders.

## Open questions for the owner / ministry

1. Is S1 the validated, final programme? It calls itself a *définitive* version of 28 July 2024 but its preamble page is unfinished; ask the MENFP for the signed adoption record for this exact version and the text of decision D-2(1)384.
2. Do mathematics follow the 2027-2028 generalisation calendar for 7AF?
3. Which grade should carry priority of operations and powers (S1: 8e; S2: 7e)?
4. May Edupreneurs align its objective labels to the official wording, and under what licence?
