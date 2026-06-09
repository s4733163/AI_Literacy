# AI Citation Checker

A tool that automatically verifies academic references cited in AI-generated content. It extracts structured metadata from raw citation strings using an LLM, then cross-checks that metadata against live registries (DOI resolver, page meta tags) to detect fabricated or misattributed citations.

## How It Works

![Citation Checker Flow](https://varun-devops-s3-2026.s3.amazonaws.com/Citation_Checker_Flow1.png)

The pipeline has two stages:

**1. Metadata Extraction** — A Gemini LLM parses each raw reference string into structured fields (title, authors, year, source, DOI, URL) using a Pydantic schema.

**2. Verification** — The extracted metadata is checked against live sources using a tiered strategy:

| Priority | Method | Strength |
|----------|--------|----------|
| 1 | DOI registry lookup via `doi.org` (CSL-JSON) | Strong |
| 2 | DOI hidden inside a URL | Strong |
| 3 | Embedded academic meta tags (`citation_title`, `dc.title`, etc.) | Moderate |
| 4 | OpenAlex title search (reverse lookup) | Moderate |
| 5 | Link liveness check | Weak |

Title similarity is the primary match signal, scored with fuzzy matching (`token_set_ratio ≥ 85`). Author overlap and publication year serve as supporting evidence.

## Verdicts

| Verdict | Meaning |
|---------|---------|
| `verified` | DOI/URL resolves and the title matches. |
| `verified_review` | Title matches, but author list or year differs — worth a manual look. |
| `metadata_mismatch` | DOI/URL is real but points to a different paper. Likely fabricated. |
| `doi_not_found` | DOI is well-formed but does not resolve — no such record exists. |
| `url_only` | No DOI or meta tags; only liveness was checked. Inconclusive. |
| `unverifiable` | No DOI or URL and no OpenAlex match. Cannot verify automatically. |
| `lookup_error` | Network error reaching the DOI resolver. Retry later. |

## Project Structure

```
.
├── reference_checking.py   # Core verification logic + CLI entry point
├── structured.py           # Pydantic schema for extracted reference fields
├── reference.txt           # Sample input — paste any reference here to test
├── requirements.txt        # Pinned dependencies
└── test_cases/
    ├── pytest.ini          # Pytest config (marker definitions)
    ├── test_verify_suite.py # Comprehensive test suite
    └── doi_verify.py       # Standalone test driver (legacy)
```

## Setup

**1. Clone the repository**

```bash
git clone <repo-url>
cd AI_Literacy
```

**2. Create and activate a virtual environment**

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Get a Google Gemini API key**

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account
3. Click **Create API key** and copy the key

**5. Add the key to a `.env` file**

Create `.env` in the project root:

```
GOOGLE_API_KEY=your_key_here
```

## Usage

### Run the full pipeline

Paste any valid reference string into `reference.txt`, then run:

```bash
python3 reference_checking.py < reference.txt
```

The script reads the reference from stdin, extracts metadata via the LLM, verifies it against live registries, and prints a JSON result. Change `reference.txt` to test different references.

### Example

`reference.txt`:
```
Ng, D. T. K., et al. (2021). Conceptualizing AI literacy. Computers and Education: AI, 2, 100041. https://doi.org/10.1016/j.caeai.2021.100041
```

```bash
python3 reference_checking.py < reference.txt
```

Output:
```json
{
  "verdict": "verified",
  "doi": "10.1016/j.caeai.2021.100041",
  "title_score": 97.4,
  "claimed_title": "Conceptualizing AI literacy: An exploratory review",
  "canonical_title": "Conceptualizing AI literacy: An exploratory review",
  "author_overlap": "4/4",
  "claimed_year": 2021,
  "canonical_year": 2021,
  "year_match": true,
  "note": "DOI/URL resolves to a record whose title matches the citation."
}
```

## Testing

Tests live in `test_cases/`. Run them from that directory:

```bash
cd test_cases
```

**Run offline tests only** (fast, no internet required):

```bash
pytest test_verify_suite.py -m "not live"
```

**Run all tests including live network checks** (hits doi.org / OpenAlex):

```bash
pytest test_verify_suite.py
```

**Run via the pytest.ini config file:**

```bash
pytest pytest.ini
```

All three commands are equivalent in terms of test discovery — `pytest.ini` is in the same directory and is picked up automatically.
