# Evaluation results (tables)

**Dataset:** 158 references (105 real / 53 fake).


## RQ1 - Does the hierarchy improve verification?

| Strategy | Resolution rate | Resolved | Unresolved | False-accusation rate |
|---|---|---|---|---|
| DOI-only | 74.7% | 118 | 40 | 1.9% |
| DOI+URL | 83.5% | 132 | 26 | 1.9% |
| Full (DOI+URL+rev) | 89.9% | 142 | 16 | 1.9% |

Full hierarchy resolves 15.2% more references than DOI-only.


## RQ2 - How often via DOI / URL / reverse lookup?

| Tier | Verified refs | Share |
|---|---|---|
| doi | 96 | 82.8% |
| url | 10 | 8.6% |
| reverse | 10 | 8.6% |

## RQ3 - How accurately are different errors identified?

Overall match to expected verdict: **94.9%**.

| Error type | n | Routed as expected | Rate |
|---|---|---|---|
| fabricated_doi | 7 | 7 | 100.0% |
| fabricated_fakedoi | 6 | 6 | 100.0% |
| fabricated_nodoi | 6 | 6 | 100.0% |
| lookalike_title | 6 | 6 | 100.0% |
| metadata_mismatch | 7 | 7 | 100.0% |
| none | 105 | 98 | 93.3% |
| url_dead | 4 | 4 | 100.0% |
| url_metadata_mismatch | 4 | 4 | 100.0% |
| wrong_authors | 7 | 7 | 100.0% |
| wrong_year | 6 | 5 | 83.3% |

## RQ4 - Query reduction from DOI-first

- OpenAlex queries, retrieval-first: **158** (one per reference)
- OpenAlex queries, DOI-first: **10** (only the 10 reverse-tier refs)
- Reduction: **93.7%** (148 queries saved)


## RQ5 - Estimated time saved vs retrieval-first

- Retrieval-first (est.): 222.6 s
- DOI-first (est.): 112.2 s
- Saved: **110.4 s (49.6% faster)**

_Latency-model estimate; run_timing.py yields measured wall-clock._
