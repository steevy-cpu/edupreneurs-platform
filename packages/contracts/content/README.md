# Content contracts

Machine-readable shape of what a lesson and a practice question may contain,
the rules that JSON Schema cannot express, and the test vectors that the server
and the phone must both pass.

Status: content **format 1** is what learners are served today. Content
**format 2** is a contract with validators and vectors only — nothing serves it
yet, and what it must contain is an open product decision (PO-08).

| File | Defines | Format |
|---|---|---|
| `lesson-blocks.schema.json` | Lesson body: `heading`, `paragraph`, `example`, `callout` | 1 (unchanged) |
| `question-mcq.schema.json` | Multiple-choice question, scoring rule `mcq-v1` | 1 (unchanged) |
| `lesson-blocks.v2.schema.json` | Lesson body: the four blocks above plus `math`, `image`, `list`, `table`, `audio` | 2 |
| `question-true-false.schema.json` | True/false question, scoring rule `true-false-v1` | 2 |
| `question-numeric.schema.json` | Numeric question, scoring rule `numeric-v1` | 2 |
| `question-short-text.schema.json` | Short-text question, scoring rule `short-text-v1` | 2 |
| `pack-manifest.v1.schema.json`, `pack-lesson.v1.schema.json` | Pack manifest and the lesson object stored in a pack | 1 and 2 |
| `vectors/*.json` | Shared test vectors (layout below) | — |

Reference implementation in Python, standard library only:
`services/api/src/edu_api/content/`. It is tested against every vector **and**
against the JSON Schema files, so the two cannot drift apart
(`tests/unit/test_content_v2_vectors.py`).

## Two layers of validation

1. **Structural** (`layer: "schema"`): the JSON Schema file. Unknown block types
   and unknown properties are rejected; every string, list and number is bounded.
2. **Semantic** (`layer: "semantic"`): the rules below, checked only on a
   structurally valid document. Each rule has a stable code.

Conventions that an implementation must share:

- String lengths are counted in **Unicode code points** (not UTF-8 bytes, not
  UTF-16 units — in JavaScript use `[...text].length`).
- Patterns are ECMA-262 regular expressions evaluated in Unicode mode; `$`
  matches only at the very end, so a value followed by a line feed (`"intro\n"`)
  is refused (vectors `x-key-trailing-line-feed`, `mcq-*-trailing-line-feed`).
- Integers are written without fraction or exponent (`18432`, never `18432.0`).
  An integral float (`10.0`, `1e2`) is **not** an integer and canonical JSON has
  no trailing line feed: a client that cannot see the difference after parsing
  (JavaScript) must compare the canonical re-serialisation with the bytes it
  received (vectors `canonical-json.json`).
- "Plain text" fields (alt texts, captions, list items, table cells, audio
  titles, units, accepted answers, and the lesson title in a pack) reject C0
  control characters, U+007F, a `<` directly followed by a letter, `/`, `!` or
  `?` (`x < 3` and `3<5` are fine), and every invisible or direction-changing
  character: C1 controls U+0080–U+009F, U+200B–U+200F, U+2028–U+202E, U+2060,
  U+2066–U+2069, U+FEFF and lone surrogates (vectors `plain-text.json`).
  The four format-1 block types and `mcq` questions keep their format-1 rules
  unchanged, also inside a format-2 lesson (owner decision).
- **Rendering rule.** Every string of a lesson or a question is plain text and
  is never interpreted as markup by any client; a math `source` is never passed
  to an HTML engine or a web view.

## Format 2 blocks

| Block | Required | Optional | Limits |
|---|---|---|---|
| `math` | `key`, `notation` = `edu-math-1`, `source`, `alt` | `asset` (pre-rendered image) | source ≤ 400, alt ≤ 300 |
| `image` | `key`, `asset`, `alt` | `caption` ≤ 200 | ≤ 200 000 bytes, ≤ 1600 × 1600 px, webp / png / jpeg |
| `list` | `key`, `style` (`bullet` / `number`), `items` | — | 1–30 items, each ≤ 500, flat |
| `table` | `key`, `caption`, `columns`, `rows` | `row_headers` | 2–4 columns, 1–20 rows, header ≤ 24, cell ≤ 80 |
| `audio` | `key`, `asset`, `duration_ms`, `title`, `transcript.block_keys` | — | ≤ 2 000 000 bytes, ≤ 600 000 ms, mp4 (AAC) / mpeg |

An asset is referenced by the lower-case hexadecimal SHA-256 of its bytes, never
by URL. Audio never plays by itself: there is no `autoplay` property and unknown
properties are rejected.

### Semantic rules for a lesson body

| Code | Rule |
|---|---|
| `keys.unique` | Every block key appears once in the lesson. (Format 1 never checked this; a format-1 document with duplicate keys stays valid *as format 1*.) |
| `math.*` | The `edu-math-1` grammar, next section. |
| `table.row_width` | Every row has exactly one cell per column. |
| `table.width_budget` | For each column take its longest unbreakable word (header and cells, split on U+0020 only, counted in code points). The sum over the columns is at most `36 − 2 × columns` (32 / 30 / 28 for 2 / 3 / 4 columns). |
| `audio.transcript` | Every key in `transcript.block_keys` names a block of the same lesson that carries text (anything except `audio` and `image`). |
| `assets.consistent` | The same SHA-256 always comes with the same mime type, byte size and intrinsic size. |
| `assets.image_budget` | Distinct images of one lesson, pre-rendered formulas included, weigh at most 1 000 000 bytes together. |

**Why `36 − 2n` (readability at 320 dp).** A 320 dp wide screen with 16 dp page
margins leaves 288 dp. Each column needs 16 dp of cell padding. A 14 sp glyph is
budgeted at 8 dp. `floor((288 − 16n) / 8) = 36 − 2n` characters that can never be
broken across lines. The renderer wraps cell text at spaces, never splits a word
and never scrolls a table sideways; a table that satisfies the rule therefore
always fits. The numbers are a conservative budget, to be re-measured on the
reference device when a renderer exists.

### The notation `edu-math-1`

A small whitelisted subset of LaTeX mathematics, stored as plain text. It is
data, not markup that is executed: no macros, no definitions, no environments,
no colours, no links, no HTML. The mandatory `alt` says the formula in words.

```
formula := item+                         spaces between items are ignored
item    := atom script*                  at most one ^ and one _ per atom
script  := (^ | _) (group | letter | digit | symbol command)
group   := { item+ }                     nesting depth at most 4
                                         (the index [...] of a root is one level too)
atom    := character | group | command

characters   A-Z a-z 0-9 + - * / = < > ( ) [ ] | , . ; : ! '
escapes      \%  \{  \}  \,
symbols      \times \div \cdot \pm \le \ge \ne \approx \equiv \pi \infty
             \alpha \beta \gamma \delta \theta \lambda \mu \Delta
             \circ \angle \triangle \parallel \perp
             \in \notin \cup \cap \subset \emptyset
             \sin \cos \tan \log \ln \ldots \to \Rightarrow \Leftrightarrow \quad
structures   \frac{a}{b}  \sqrt{a}  \sqrt[n]{a}  \overline{a}  \vec{a}
             \mathbb{X}   with X one of N Z D Q R
             \text{...}   plain words; the only place for accented letters
                          (U+00C0–U+017F except U+00D7 and U+00F7)
```

**No markup.** A source never contains `<` directly followed by a letter, `/`,
`!` or `?` — bare or inside `\text{...}`; authors write `a < b` with a space
(structural layer, vectors `schema-markup-*`). A renderer must never pass a
`source` to an HTML engine or a web view.

A command name is the longest run of ASCII letters after the backslash.
Validation scans left to right and stops at the **first** error:

| Code | Meaning |
|---|---|
| `math.syntax` | stray `\`, bare `%`, empty group, empty formula, bad `\mathbb` argument |
| `math.unknown_command` | command not on the whitelist |
| `math.missing_argument` | command without its `{...}` argument(s) |
| `math.unbalanced` | `{`, `}` or a root index `[` without its partner |
| `math.depth` | groups and root indices (`\sqrt[...]`) nested deeper than 4 — an index counts as one level |
| `math.script` | `^` or `_` without a base, doubled, after a space, or without a valid operand |
| `math.text` | non-ASCII character outside `\text{...}`, or `\ { ^ _ %` inside it |

Not in format 2 (recorded, not decided here): mathematics inside a paragraph, a
list item or a table cell; multi-line derivations; matrices.

## Format 2 question kinds and their scoring rules

A question is four JSON objects (`prompt`, `response_spec`, `answer_key`,
`explanation`), as for `mcq`. Every answer key names its rule in
`scoring_version`. The shape of the learner's response is `$defs/response` in
each schema. A result is either **scored** (score is the integer 0 or 1) or
**`invalid_response`** (nothing is scored, a code says why) — mirroring how the
server answers `invalid_choice` for `mcq` today.

These rules are a **contract and a reference implementation only**. They are not
wired into `app.sync_apply_operation`: the server keeps rejecting every kind
other than `mcq` with `unsupported_question_kind`. The stored column
`app.question_revisions.kind` accepts `numeric` and `short_text` but not yet
`true_false`.

### `true-false-v1`
Response `{"value": true | false}`. Score 1 when it equals `answer_key.correct`.
Anything else — the strings `"true"`/`"false"`, the numbers 0/1, extra
properties — is `invalid_response` / `not_a_boolean`.

### `numeric-v1`
Response `{"text": "<1–32 code points, as typed>"}`. The phone does not parse
the text into a number before sending it.

1. Delete every U+0009, U+0020, U+00A0, U+2009, U+202F (so `1 000` is 1000).
2. Replace U+2212 (minus sign) by `-`.
3. A decimal is `[+-]? digits{1,12} ( [.,] digits{1,6} )?`. When
   `response_spec.allow_fraction` is true, `[+-]? digits{1,12} / digits{1,12}`
   with a non-zero denominator is also a number. Nothing else is
   (`invalid_response` / `not_a_number`): no exponent, no leading or trailing
   separator, only ASCII digits. A comma is always the decimal separator.
4. Compare **exactly**: correct when `|response − value| ≤ tolerance`
   (inclusive). `value` and `tolerance` are canonical decimal strings. No binary
   floating point at any step — use scaled integers or rationals.

### `short-text-v1`
Response `{"text": "<1–200 code points, as typed>"}`; longer than
`response_spec.max_length` code points is `invalid_response` / `too_long`. The
response and every accepted answer go through the same normalisation:

1. Unicode NFC.
2. U+2019, U+2018 and U+02BC become U+0027 (apostrophe).
3. Each run of U+0009, U+000A, U+000D, U+0020, U+00A0, U+2009, U+202F becomes
   one U+0020; leading and trailing spaces are removed.
4. Unless `case_sensitive`: Unicode default lower-casing (locale-independent).
5. Unless `accent_sensitive`: U+0153 → `oe`, U+0152 → `OE`, U+00E6 → `ae`,
   U+00C6 → `AE`; then NFD, delete U+0300–U+036F, then NFC.

Empty after normalisation is `invalid_response` / `empty`. Correct when the
normalised response equals one normalised accepted answer. Punctuation is kept;
there is no fuzzy matching. Semantic rule `short_text.accepted_fits`: every
accepted answer is non-empty after normalisation and no longer than `max_length`.

## Format versions and old mobile builds

The negotiation rule is specified in
`docs/overnight-2026-11-24/lanes/content.md` and exercised by
`vectors/negotiation.json`. In one line: a client declares the formats it
renders in the header `Edu-Content-Formats`; no header means format 1 only; a
format-1 pack never contains a format-2 block or question; a format-2 body is
never sent to, or converted for, a format-1 client.

## Packs: what a verifier checks beyond the two schemas

`pack-manifest.v1.schema.json` and `pack-lesson.v1.schema.json` are the
structural layer. A verifier (reference: `edu_api.content.pack.verify_pack`;
vectors: `pack-verify.json`) additionally refuses, with these stable codes:

| Code | Rule |
|---|---|
| `manifest.structure` | not the schema's shape — including: a format-1 pack lists only format-1 lessons, a format-1 lesson lists only `mcq` questions, a lesson `title` is plain text (no control character, no `<` directly followed by a letter, `/`, `!` or `?`); also lessons not in ascending distinct positions, assets not sorted, an asset nobody references |
| `manifest.duplicate` | a `lesson_id` or `revision_id` listed twice; a question id twice in the pack; two questions of a lesson at the same position or out of order |
| `manifest.totals` | `totals` differs from what the two lists add up to (recomputed, never believed) |
| `lesson.content_format` | a lesson object's `content_format` is not exactly the smallest format that carries its blocks **and** its question kinds: "format 1" means only `heading`, `paragraph`, `example`, `callout` and only `mcq` |
| `lesson.blocks`, `lesson.questions`, `lesson.mismatch` | the body or a question is not valid for the declared format, or the object disagrees with its manifest entry |

A client that only knows format 1 must apply these rules too: it must never
trust the manifest's `content_format` alone.

## Test vectors

Every file is `{"vector_format": 1, "suite": ..., "description": ..., "cases": [...]}`
and every case has a unique `id`. All content is synthetic.

| File | A case is | Expected result |
|---|---|---|
| `lesson-blocks.json` | `document` (a lesson body) | `expect.format_1` and `expect.format_2`, each `{valid: true}`, `{valid: false, layer: "schema"}` or `{valid: false, layer: "semantic", rules: [sorted codes]}`; optional `required_format` |
| `math-notation.json` | `source` (wrap it as `[{key: "m", type: "math", notation: "edu-math-1", source, alt: "x"}]`) | `{valid: true}`, `{valid: false, layer: "schema"}` or `{valid: false, layer: "semantic", rule}` (first error) |
| `questions.json` | `kind`, `document` (the four JSON columns) | as for lesson bodies, with a single `expect` |
| `scoring.json` | `kind`, `response_spec`, `answer_key`, `response` | `{status: "scored", scoring_version, score, is_correct}` or `{status: "invalid_response", scoring_version, code}`; for short text also `normalised_response` |
| `negotiation.json` | `type` = `parse_header` / `negotiate` / `required_format` | `expect_formats` or `expect` |
| `pack-manifest.json` | a pack described as input, with its assets in base64 | the exact manifest bytes, hashes and sizes |
| `canonical-json.json` | `utf8`: the text of the bytes | `{canonical: true/false}` |
| `plain-text.json` | `text`, to be put in place of `"@TEXT@"` in each document of `targets` | `{valid: true}` or `{valid: false, layer: "schema"}`, for every target |
| `pack-verify.json` | a complete stored pack: every object by key with its exact bytes (`utf8`), and `manifest_key`; verify without a trusted hash | `{intact: true}` or `{error: code}` (first problem) |

`scoring.json`, `plain-text.json`, `canonical-json.json` and `pack-verify.json` are written with ASCII-only JSON escapes so that invisible
characters (no-break spaces, the minus sign, combining accents) are unambiguous.
An implementation passes when, for every case, it produces exactly the expected
result.
