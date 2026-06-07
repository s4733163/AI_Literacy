from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from structured import Reference
from rapidfuzz import fuzz
from typing import Optional
import re
import requests
import os
import json

load_dotenv()


# doi.org resolves any DOI regardless of which agency registered it.
# Asking for CSL-JSON via the Accept header gives clean metadata, not a web page.
DOI_RESOLVER = "https://doi.org/"
HEADERS = {
    "Accept": "application/vnd.citationstyles.csl+json"
}
 

# A title fuzzy-score at or above this counts as a match. 85 sits in the
# conventional 80-90 band: high enough to reject a different paper, loose
# enough to forgive a dropped subtitle or some minor wording differences.
TITLE_THRESHOLD = 85

# check if the api key exists
if not os.getenv("GOOGLE_API_KEY"):
    raise EnvironmentError("GOOGLE_API_KEY is missing from .env file")


# model to be used
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0
)

# returns the output in the specified pydantic format
structured_llm = llm.with_structured_output(Reference)

prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are a reference metadata extraction assistant.

Your task is to extract structured metadata from ONE raw academic or web reference.

Return the result using the provided structured schema.

Rules:
1. The input will contain only one reference.
2. Do not verify whether the reference is real.
3. Do not correct the reference.
4. Do not invent missing information.
5. Keep raw_reference exactly as provided.
6. If a field is missing or unclear, return null or an empty list.
7. Extract DOI only if clearly present.
8. Extract URL only if clearly present.
9. Authors must be returned as a list.
10. Source may be a journal, conference, book, website, publisher, or organisation.
"""
    ),
    (
        "human",
        """
Extract metadata from this reference:

{reference}
"""
    )
])

# chain is invoked with reference to get the metadata of the reference
chain = prompt | structured_llm





def metadata(reference):
    """Extracts the metadata using an llm and returns a reference in a specific format."""
    reference = re.sub(r"\s+", " ", reference).strip()
    result = chain.invoke({"reference": reference})
    return(result.model_dump())


 
def normalize(text: Optional[str]) -> str:
    """Lowercase, drop punctuation, collapse whitespace. Used before comparing."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)   # punctuation -> space (handles trailing '.')
    text = re.sub(r"\s+", " ", text)
    return text.strip()
 
 
def _surname(author: str) -> str:
    """Pull a surname from a claimed author string, in either common order.
 
    "Ng, D. T. K."  -> "ng"      (comma form: surname is before the comma)
    "D. T. K. Ng"   -> "ng"      (no comma: surname is the last token)
    """
    author = author.strip()
    if "," in author:
        return normalize(author.split(",")[0])
    parts = author.split()
    return normalize(parts[-1]) if parts else ""
 
 
def _canonical_title(metadata: dict) -> str:
    """CSL-JSON 'title' is usually a string but can be a list."""
    title = metadata.get("title", "")
    if isinstance(title, list):
        title = title[0] if title else ""
    return title or ""
 
 
def _canonical_surnames(metadata: dict) -> set:
    surnames = set()
    for a in metadata.get("author", []):
        name = a.get("family") or a.get("literal") or ""
        if name:
            surnames.add(normalize(name))
    return surnames
 
 
def _canonical_year(metadata: dict) -> Optional[int]:
    parts = metadata.get("issued", {}).get("date-parts", [])
    if parts and parts[0] and parts[0][0]:
        try:
            return int(parts[0][0])
        except (ValueError, TypeError):
            return None
    return None
 
 
def compare_to_metadata(
    claimed_title: Optional[str],
    claimed_authors: list,
    claimed_year: Optional[int],
    metadata: dict,
    doi: Optional[str] = None,
) -> dict:
    """Pure comparison: claim vs canonical metadata. No network.
 
    Title similarity is the primary signal (the DOI is the key, so we are
    really asking 'does this key point at the paper they cited?').Author names 
    and publication year are used as supporting evidence.If the title matches
    but the year is slightly different, the reference is flagged for review rather
    than automatically marked as invalid.
    """
    # check for TITLE SIMILARITY and get a SCORE
    canonical_title = _canonical_title(metadata)
    score = fuzz.token_set_ratio(normalize(claimed_title), normalize(canonical_title))
 
    # extract the claimed surnames
    claimed_surnames = set()
    for author in claimed_authors:
        surname = _surname(author)
        claimed_surnames.add(surname)
   
    # check for AUTHOR OVERLAP
    # extract the surnames from the metadata
    canonical_surnames = _canonical_surnames(metadata)
    overlap = claimed_surnames & canonical_surnames
 
    canon_year = _canonical_year(metadata)
    year_match = None

    # checking for YEAR MATCH
    # year checking is done if only there exists a claimed year and metadata also has the year
    if claimed_year is not None and canon_year is not None:
        year_match = (claimed_year == canon_year)
 
    # check the score meets the THRESHOLD CRITERIA
    title_matches = score >= TITLE_THRESHOLD
 
    if title_matches:
        verdict = "verified"
        note = "DOI resolves to a record whose title matches the citation."
        if year_match is False:
            note += (f" But the cited year ({claimed_year}) differs from the "
                     f"registry year ({canon_year}) — worth a manual look.")
            
        if not len(overlap) and len(claimed_surnames):
            note += (f" The author list differs from official metadata.")
    else:
        verdict = "metadata_mismatch"
        note = (f"DOI is registered, but it resolves to \"{canonical_title}\", "
                f"which does not match the cited title. Likely fabricated.")
 
    return {
        "verdict": verdict,
        "doi": doi,
        "title_score": round(score, 1),
        "claimed_title": claimed_title,
        "canonical_title": canonical_title,
        "author_overlap": f"{len(overlap)}/{len(claimed_surnames)}" if claimed_surnames else "0/0",
        "claimed_year": claimed_year,
        "canonical_year": canon_year,
        "year_match": year_match,
        "note": note,
    }
 
 
def fetch_csl_metadata(doi: str) -> Optional[dict]:
    """Resolve a DOI to CSL-JSON metadata.
 
    Returns the metadata dict on success, or None if the DOI does not
    resolve (HTTP 404) — that None is the 'doi_not_found' signal.
    Raises requests.RequestException on network/other HTTP errors, so the
    caller can distinguish 'does not exist' from 'lookup failed'.
    """
    resp = requests.get(DOI_RESOLVER + doi.strip(), headers=HEADERS, timeout=15)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()
 
 
def verify_doi(
    claimed_title: Optional[str],
    claimed_authors: list,
    claimed_year: Optional[int],
    doi: str,
) -> dict:
    """Resolve a DOI and compare its metadata against the citation's claim."""
    try:
        metadata = fetch_csl_metadata(doi)
    except requests.RequestException as exc:
        return {
            "verdict": "lookup_error",
            "doi": doi,
            "note": f"Could not reach the DOI resolver: {exc}. Try again later.",
        }
 
    # fabricated doi and fabricated reference
    if metadata is None:
        return {
            "verdict": "doi_not_found",
            "doi": doi,
            "note": "This DOI did not resolve — no such record exists. Likely fabricated.",
        }
 
    return compare_to_metadata(claimed_title, claimed_authors, claimed_year, metadata, doi)
 

def check_metadata(extracted_data):
    # if the doi and url exists, we choose doi 
    if extracted_data.get("doi") and extracted_data.get("doi") is not None:
        return verify_doi(
            extracted_data.get("title"), 
            extracted_data.get("authors"), 
            extracted_data.get("year"), 
            extracted_data.get("doi")
        )
    elif extracted_data.get("url"):
        return {
            "verdict": "url_only",
            "note": "No DOI found. URL verification branch will be added later."
        }

    else:
        return {
            "verdict": "no_doi_or_url",
            "note": "No DOI or URL found. Use title/author/year reverse lookup later."
        }
    
