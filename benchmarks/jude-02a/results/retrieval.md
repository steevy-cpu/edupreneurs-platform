# Jude-02A retrieval benchmark

Synthetic lessons and questions; see docs/jude-02a/03-cross-language-retrieval.md.

| Strategy | Direction | Cases | Hit@1 | Hit@3 | MRR | Gold in context |
|---|---|---:|---:|---:|---:|---:|
| A. bm25 (Jude-01 baseline) | fr question / fr lesson | 28 | 0.50 | 0.71 | 0.61 | 0.75 |
| A. bm25 (Jude-01 baseline) | fr question / ht lesson | 28 | 0.11 | 0.11 | 0.11 | 0.11 |
| A. bm25 (Jude-01 baseline) | ht question / fr lesson | 28 | 0.11 | 0.11 | 0.11 | 0.11 |
| A. bm25 (Jude-01 baseline) | ht question / ht lesson | 28 | 0.54 | 0.68 | 0.60 | 0.68 |
| B. char-trigram tf-idf (Jude-01) | fr question / fr lesson | 28 | 0.36 | 0.79 | 0.56 | 0.82 |
| B. char-trigram tf-idf (Jude-01) | fr question / ht lesson | 28 | 0.39 | 0.46 | 0.44 | 0.50 |
| B. char-trigram tf-idf (Jude-01) | ht question / fr lesson | 28 | 0.32 | 0.43 | 0.38 | 0.46 |
| B. char-trigram tf-idf (Jude-01) | ht question / ht lesson | 28 | 0.39 | 0.79 | 0.58 | 0.82 |
| C. sections + bm25 | fr question / fr lesson | 28 | 0.50 | 0.79 | 0.66 | 0.82 |
| C. sections + bm25 | fr question / ht lesson | 28 | 0.11 | 0.11 | 0.11 | 0.11 |
| C. sections + bm25 | ht question / fr lesson | 28 | 0.11 | 0.11 | 0.11 | 0.11 |
| C. sections + bm25 | ht question / ht lesson | 28 | 0.54 | 0.82 | 0.68 | 0.82 |
| D. sections + glossary | fr question / fr lesson | 28 | 0.50 | 0.79 | 0.66 | 0.82 |
| D. sections + glossary | fr question / ht lesson | 28 | 0.50 | 0.71 | 0.62 | 0.75 |
| D. sections + glossary | ht question / fr lesson | 28 | 0.39 | 0.61 | 0.50 | 0.61 |
| D. sections + glossary | ht question / ht lesson | 28 | 0.54 | 0.82 | 0.68 | 0.82 |
| D'. sections + glossary without the lesson's own topic terms | fr question / fr lesson | 28 | 0.50 | 0.79 | 0.66 | 0.82 |
| D'. sections + glossary without the lesson's own topic terms | fr question / ht lesson | 28 | 0.39 | 0.50 | 0.45 | 0.50 |
| D'. sections + glossary without the lesson's own topic terms | ht question / fr lesson | 28 | 0.36 | 0.46 | 0.41 | 0.46 |
| D'. sections + glossary without the lesson's own topic terms | ht question / ht lesson | 28 | 0.54 | 0.82 | 0.68 | 0.82 |
| E. sections + sibling block keys | fr question / fr lesson | 28 | 0.50 | 0.79 | 0.66 | 0.82 |
| E. sections + sibling block keys | fr question / ht lesson | 28 | 0.50 | 0.79 | 0.66 | 0.82 |
| E. sections + sibling block keys | ht question / fr lesson | 28 | 0.54 | 0.82 | 0.68 | 0.82 |
| E. sections + sibling block keys | ht question / ht lesson | 28 | 0.54 | 0.82 | 0.68 | 0.82 |
| F. sections + sibling block keys + glossary | fr question / fr lesson | 28 | 0.54 | 0.86 | 0.71 | 0.89 |
| F. sections + sibling block keys + glossary | fr question / ht lesson | 28 | 0.54 | 0.86 | 0.71 | 0.89 |
| F. sections + sibling block keys + glossary | ht question / fr lesson | 28 | 0.50 | 0.82 | 0.66 | 0.82 |
| F. sections + sibling block keys + glossary | ht question / ht lesson | 28 | 0.50 | 0.82 | 0.66 | 0.82 |
| G. sections + sibling block keys + two-term rule | fr question / fr lesson | 28 | 0.54 | 0.82 | 0.69 | 0.86 |
| G. sections + sibling block keys + two-term rule | fr question / ht lesson | 28 | 0.54 | 0.82 | 0.69 | 0.86 |
| G. sections + sibling block keys + two-term rule | ht question / fr lesson | 28 | 0.54 | 0.86 | 0.70 | 0.86 |
| G. sections + sibling block keys + two-term rule | ht question / ht lesson | 28 | 0.54 | 0.86 | 0.70 | 0.86 |

Unrelated questions wrongly matched (lower is better):

| Strategy | fr→fr | fr→ht | ht→fr | ht→ht |
|---|---:|---:|---:|---:|
| A. bm25 (Jude-01 baseline) | 0/42 | 0/42 | 0/42 | 0/42 |
| B. char-trigram tf-idf (Jude-01) | 2/42 | 0/42 | 2/42 | 8/42 |
| C. sections + bm25 | 0/42 | 0/42 | 0/42 | 0/42 |
| D. sections + glossary | 0/42 | 0/42 | 0/42 | 0/42 |
| D'. sections + glossary without the lesson's own topic terms | 0/42 | 0/42 | 0/42 | 0/42 |
| E. sections + sibling block keys | 0/42 | 0/42 | 0/42 | 0/42 |
| F. sections + sibling block keys + glossary | 0/42 | 0/42 | 0/42 | 0/42 |
| G. sections + sibling block keys + two-term rule | 0/42 | 0/42 | 0/42 | 0/42 |

Informally written Creole questions on the Creole lesson (gold block in context):

| Strategy | Found |
|---|---:|
| A. bm25 (Jude-01 baseline) | 3/6 |
| B. char-trigram tf-idf (Jude-01) | 5/6 |
| C. sections + bm25 | 4/6 |
| D. sections + glossary | 4/6 |
| D'. sections + glossary without the lesson's own topic terms | 4/6 |
| E. sections + sibling block keys | 4/6 |
| F. sections + sibling block keys + glossary | 5/6 |
| G. sections + sibling block keys + two-term rule | 4/6 |

Same questions after one sentence of ordinary talk (all four directions pooled):

| Strategy | Gold in context, plain | Gold in context, padded | Unrelated matched | Padded unrelated matched |
|---|---:|---:|---:|---:|
| A. bm25 (Jude-01 baseline) | 0.41 (n=112) | 0.05 (n=336) | 0/168 | 0/168 |
| B. char-trigram tf-idf (Jude-01) | 0.65 (n=112) | 0.48 (n=336) | 4/168 | 2/168 |
| C. sections + bm25 | 0.46 (n=112) | 0.05 (n=336) | 0/168 | 0/168 |
| D. sections + glossary | 0.75 (n=112) | 0.08 (n=336) | 0/168 | 0/168 |
| D'. sections + glossary without the lesson's own topic terms | 0.65 (n=112) | 0.05 (n=336) | 0/168 | 0/168 |
| E. sections + sibling block keys | 0.82 (n=112) | 0.10 (n=336) | 0/168 | 0/168 |
| F. sections + sibling block keys + glossary | 0.86 (n=112) | 0.11 (n=336) | 0/168 | 0/168 |
| G. sections + sibling block keys + two-term rule | 0.86 (n=112) | 0.70 (n=336) | 0/168 | 0/168 |
