# Research notes: tool and library choices

This document records *why* each external service, library, and model was chosen for the
citation-verification component of the AI Literacy Checkpoint, and what evidence supports
its credibility. The guiding principle throughout is **fail toward "unverifiable," never
toward a false accusation** — because the tool's output can affect students, a low
false-positive rate matters more than catching every possible fake.

## Summary

| Component | Role in the pipeline | Why chosen |
|---|---|---|
| DOI content negotiation (`doi.org`) | Resolve a DOI to canonical metadata | Registry-backed, unique key; agency-agnostic (Crossref + DataCite) |
| OpenAlex REST API | No-DOI fallback search by title | Open, free, broad coverage comparable to proprietary databases |
| RapidFuzz | Fuzzy title / author comparison | Fast, MIT-licensed implementation of established edit-distance metrics |
| Google Gemini 2.5 Flash | Extract structured metadata from raw references | Cheap, fast, native schema-constrained (structured) output |
| Pydantic | Define and enforce the extraction schema | Standard typed-data validation; powers structured LLM output |
| LangChain (`langchain-google-genai`) | Orchestrate the model + schema | `with_structured_output` binds the Pydantic schema to the model |
| BeautifulSoup | Read embedded `citation_*` meta tags from web pages | Mature, lenient HTML parser |
| Requests | All HTTP calls | De-facto standard Python HTTP client |

---

## 1. Verification data sources

### 1.1 DOI resolution via content negotiation (`doi.org`)

A DOI is a *registered, unique identifier* — one DOI maps to exactly one work — which makes
it the strongest possible evidence for a citation. Rather than scraping a publisher's web
page, the tool resolves the DOI through `doi.org` content negotiation, requesting
`application/vnd.citationstyles.csl+json` and receiving clean, labelled CSL-JSON metadata
(or a 404 if the DOI does not exist).

**Why this over the Crossref REST API directly:** content negotiation through `doi.org` is
*registration-agency-agnostic*. It routes to whichever agency owns the DOI — Crossref for
most journal articles, DataCite for datasets, theses, and many preprints — so a valid
DataCite DOI is not falsely reported as "not found" the way a Crossref-only lookup would do.

**Credibility:** the DOI system and CSL-JSON are long-standing, standardised scholarly
infrastructure maintained by the International DOI Foundation, Crossref, and DataCite. This
is the canonical mechanism libraries and reference managers themselves rely on.

### 1.2 OpenAlex (no-DOI fallback)

When a reference has no DOI (books, older works, many humanities sources), the tool searches
OpenAlex by title and judges candidates on title *and* authors *and* year together. OpenAlex
was chosen as the workhorse for this branch for three reasons:

1. **Openness and reproducibility.** OpenAlex is released under a CC0 licence with a free,
   high-volume REST API, governed by the non-profit OurResearch (Priem, Piwowar, & Orr,
   2022). For a tool destined for a university curriculum, results must be auditable by
   anyone without a paywall — a property proprietary databases (Scopus, Web of Science)
   cannot offer.
2. **Coverage.** OpenAlex launched in 2022 as the open replacement for Microsoft Academic
   Graph (discontinued by Microsoft in 2021) and indexed over 200 million works at launch,
   growing monthly (Priem et al., 2022). Because roughly half of indexed works carry a DOI,
   it contains large numbers of works that have *no* DOI — exactly the population this branch
   must cover.
3. **Quality is competitive with the proprietary standards.** A reference-coverage analysis
   comparing OpenAlex to Web of Science and Scopus found OpenAlex's reference coverage
   broadly comparable to both (Reference Coverage Analysis of OpenAlex, 2024, arXiv:2401.16359),
   and open-access coverage studies report similarly strong results (Simard et al., 2024).

**Honest limitation (documented deliberately):** OpenAlex is more *inclusive* but less
*curated* than Scopus or Web of Science, so it may index venues that have not been vetted to
the same standard, and a minority of records have incomplete metadata. This is acceptable
here because the tool checks *existence and metadata agreement*, not journal prestige — and
because a "not found" result is reported as **unverifiable**, never as "fabricated." A real
but unindexed work (a regional-journal article, an old monograph) must not be flagged as
fake; preserving that distinction is the single most important design constraint of the
fallback branch.

---

## 2. Comparison: RapidFuzz and fuzzy matching

Titles must be compared *approximately*, not character-for-character, because legitimate
formatting differences (punctuation, dropped subtitles, transliteration) would otherwise
cause false mismatches. The tool uses RapidFuzz's `token_set_ratio` with a threshold of 85,
which sits inside the conventional 80–90 band for high-precision approximate matching.

**The credibility argument is about the algorithm, not the library.** RapidFuzz is an
*implementation* — a high-performance, MIT-licensed C++ library (with Python bindings) of
well-established string-similarity metrics, principally Levenshtein edit distance
(Levenshtein, 1966) and token-based variants. The scientific justification is that
normalized edit-distance matching is a standard, decades-old technique in *record linkage*
and entity resolution (Christen, 2012); RapidFuzz is cited only as the concrete, reproducible
tool used to compute it. It was preferred over the older FuzzyWuzzy library for speed and a
permissive licence.

This is also why the *threshold* (85) is defensible rather than arbitrary: it is reported in
the record-linkage literature as a conventional starting point, and it is validated empirically
by the project's own test suite (a clean match scores ~100; a different paper with a similar
title scores well below 50).

---

## 3. Comparison: LLM extraction vs. dedicated reference parsers

Turning a messy, multi-style reference string into structured fields is the hardest part of
the pipeline, because citation styles (APA, MLA, IEEE, Vancouver, Chicago...) reorder fields
and vary punctuation. Two families of tools were considered.

**Dedicated reference parsers (GROBID, AnyStyle, CERMINE).** These use trained sequence
models (typically CRFs) that label tokens regardless of order, and are the established
academic baseline. In a widely-cited benchmark, machine-learning parsers achieved roughly
three times the recall of rule/regex-based parsers, with GROBID the strongest out-of-the-box
tool (Tkaczyk et al., 2018), and retraining on in-domain data improves all of them (Grennan
et al., 2020).

**Large language models with structured output.** Recent evidence shows LLMs now match or
exceed dedicated parsers on field-level accuracy. Sarin et al. (2025) benchmarked language
models against GROBID on a citation-parsing task and found that even the *worst-performing*
language model beat GROBID's article-title accuracy (GROBID: coverage 0.989, title accuracy
0.667, surname accuracy 0.852), with most models scoring higher still.

**Decision: LLM extraction (Gemini 2.5 Flash).** The LLM route was chosen because it is
inherently style-agnostic (no per-style rules, no training data required) and integrates
cleanly with a schema. The model tier matters less than reliability of *structured output*
and cost: for a short, well-defined extraction task, a cheap, fast model with native
schema-constrained output is the correct choice rather than a frontier model. Gemini 2.5
Flash meets this — low cost per call and deterministic-leaning behaviour at `temperature=0`.

**Documented caveats and mitigations:**

- *Structured-output brittleness.* LLM reference parsing can fail on noisy, multilingual, or
  footnote-style inputs, and hybrid GROBID-plus-LLM routing is recommended for production
  robustness (Zhu, Colavizza, & Romanello, 2026). A natural future extension is to add GROBID
  for well-structured PDFs and reserve the LLM for messy cases.
- *Extraction is not verification.* The LLM only *extracts* the claimed metadata; it never
  decides whether a citation is real. All existence and correctness checks are performed
  against the authoritative sources above. This separation is deliberate — asking an LLM "is
  this citation real?" is precisely the failure mode the project exists to detect, since
  models hallucinate confident citations. Because every extracted field is later checked
  against a registry, an extraction slip typically surfaces downstream as a mismatch rather
  than a silent error.
- *Privacy.* Sending student text to a commercial API raises data-handling questions; for a
  stricter deployment, an open-weight model (e.g. Llama, Mistral, Qwen, DeepSeek) run locally
  would keep student data on-premises with no loss of capability on a task this simple.

---

## 4. Supporting libraries

**Pydantic** defines the extraction schema (`Reference`) and enforces types, and is what makes
the LLM's structured output reliable: the schema is bound to the model so the response is
guaranteed to match the expected shape. It is the de-facto standard for typed data validation
in modern Python.

**LangChain (`langchain-google-genai`)** provides the orchestration glue. Its
`with_structured_output` method binds the Pydantic schema to the model and parses the response
back into a validated object, which is the mechanism that produces dependable JSON from the
LLM.

**BeautifulSoup** reads the embedded `citation_title` / `citation_author` / `citation_*` meta
tags (the Highwire/Dublin Core convention most academic publishers emit) from a page's HTML
head. It is preferred over regex-on-HTML because it correctly handles arbitrary attribute
order and malformed markup, and it is a mature, widely-used parser. Note that the tool reads
these *labelled* tags rather than scraping the visible page, keeping the URL branch's
metadata comparison as structured as the DOI branch.

**Requests** handles all HTTP calls. It is the standard Python HTTP client; a contact `mailto`
is included in the OpenAlex query and (recommended) in the DOI `User-Agent` to use each
service's "polite pool" for better rate limits and reliability.

---

## 5. Methodological integrity

Two practices keep the tool defensible as an academic-integrity instrument:

1. **Evidence is reported, not hidden.** Every verdict records *how* it was reached
   (`doi`, `page meta tags`, `openalex search`, or `openalex search + doi confirmation`),
   because a DOI-confirmed match is genuinely stronger evidence than a title-search match,
   and the report should make that strength visible rather than collapse everything into a
   binary real/fake.
2. **The tool is validated on its own labelled set.** A deterministic test suite checks every
   verdict path (including the deceptive "real DOI, wrong paper" case and the legitimate
   no-DOI book), so confidence rests on measured behaviour, not on the reputation of the
   components alone.

---

## References

Christen, P. (2012). *Data matching: Concepts and techniques for record linkage, entity
resolution, and duplicate detection.* Springer.

Grennan, M., Schibel, M., Collins, A., & Beel, J. (2020). *Synthetic vs. real reference
strings for citation parsing, and the importance of re-training and out-of-sample data for
meaningful evaluations: Experiments with GROBID, GIANT and Cora.* arXiv:2004.10410.

Levenshtein, V. I. (1966). Binary codes capable of correcting deletions, insertions, and
reversals. *Soviet Physics Doklady, 10*(8), 707–710.

Priem, J., Piwowar, H., & Orr, R. (2022). *OpenAlex: A fully-open index of scholarly works,
authors, venues, institutions, and concepts.* arXiv:2205.01833.

*Reference coverage analysis of OpenAlex compared to Web of Science and Scopus.* (2024).
arXiv:2401.16359.

Sarin, P., et al. (2025). *Citation parsing and analysis with language models.*
arXiv:2505.15948.

Simard, M.-A., Basson, I., Hare, M., Larivière, V., & Mongeon, P. (2024). *The open access
coverage of OpenAlex, Scopus and Web of Science.* arXiv:2404.01985.

Tkaczyk, D., Collins, A., Sheridan, P., & Beel, J. (2018). Machine learning vs. rules and
out-of-the-box vs. retrained: An evaluation of open-source bibliographic reference and
citation parsers. *Proceedings of the ACM/IEEE Joint Conference on Digital Libraries (JCDL).*

Zhu, Y., Colavizza, G., & Romanello, M. (2026). *Benchmarking large language models on
reference extraction and parsing in the social sciences and humanities.* arXiv:2603.13651.

---

*Note on citations: bibliographic details here were verified against the live sources at the
time of writing. As this is a document about citation integrity, any reference reused
elsewhere should be re-checked — the same standard the tool itself applies.*