# AI Citation Checker

A tool that automatically verifies academic references cited in AI-generated content. It extracts structured metadata from raw citation strings using an LLM, then cross-checks that metadata against live registries (DOI resolver, page meta tags) to detect fabricated or misattributed citations.

## How It Works

![Citation Checker Flow](Citation_Checker_Flow.png)

The pipeline has two stages:

**1. Metadata Extraction** — A Gemini LLM parses each raw reference string into structured fields (title, authors, year, source, DOI, URL) using a Pydantic schema.

**2. Verification** — The extracted metadata is checked against live sources using a tiered strategy:

| Priority | Method | Strength |
|----------|--------|----------|
| 1 | DOI registry lookup via `doi.org` (CSL-JSON) | Strong |
| 2 | DOI hidden inside a URL | Strong |
| 3 | Embedded academic meta tags (`citation_title`, `dc.title`, etc.) | Moderate |
| 4 | Link liveness check | Weak |

Title similarity is the primary match signal, scored with fuzzy matching (`token_set_ratio ≥ 85`). Author overlap and publication year serve as supporting evidence.

## Verdicts

| Verdict | Meaning |
|---------|---------|
| `verified` | DOI/URL resolves and the title matches. |
| `verified_review` | Title matches, but author list or year differs — worth a manual look. |
| `metadata_mismatch` | DOI/URL is real but points to a different paper. Likely fabricated. |
| `doi_not_found` | DOI is well-formed but does not resolve — no such record exists. |
| `url_only` | No DOI or meta tags; only liveness was checked. Inconclusive. |
| `no_doi_or_url` | No DOI or URL in the reference. Cannot verify automatically. |
| `lookup_error` | Network error reaching the DOI resolver. Retry later. |

## Project Structure

```
.
├── reference_checking.py   # Core verification logic (DOI, URL, meta tag checks)
├── structured.py           # Pydantic schema for extracted reference fields
├── doi_verify.py           # Entry point / test driver
└── Citation_Checker_Flow.png
```

## Setup

**1. Clone the repository**

```bash
git clone <repo-url>
cd AI_Literacy
```

**2. Create and activate a virtual environment**

```bash
# Create the virtual environment
python -m venv venv

# Activate it (macOS / Linux)
source venv/bin/activate

# Activate it (Windows)
venv\Scripts\activate
```

You should see `(venv)` at the start of your terminal prompt once it is active.

**3. Install dependencies**

```bash
pip install python-dotenv langchain-google-genai langchain-core rapidfuzz requests beautifulsoup4 pydantic
```

**4. Get a Google Gemini API key**

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account
3. Click **Create API key** and copy the key

**5. Add the key to a `.env` file**

Create a file named `.env` in the project root (same folder as `reference_checking.py`):

```bash
# macOS / Linux
echo "GOOGLE_API_KEY=your_key_here" > .env

# Windows (Command Prompt)
echo GOOGLE_API_KEY=your_key_here > .env
```

Or open any text editor and create `.env` manually with this content:

```
GOOGLE_API_KEY=your_key_here
```

Replace `your_key_here` with the actual key you copied from Google AI Studio.

## Usage

Import `check_metadata` from `reference_checking` and pass it the extracted fields:

```python
from reference_checking import check_metadata, metadata

# Step 1: extract fields from a raw reference string
ref = 'Ng, D. T. K., et al. (2021). Conceptualizing AI literacy. Computers and Education: AI, 2, 100041. https://doi.org/10.1016/j.caeai.2021.100041'
extracted = metadata(ref)

# Step 2: verify against live registries
result = check_metadata(extracted)
print(result)
```

## Example Output

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
