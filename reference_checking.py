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
from bs4 import BeautifulSoup


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

# We are finding a doi inside a url if it exists.
# A DOI looks like 10.<digits>/<something>. This finds one even when it's
# buried inside a URL, e.g. https://dl.acm.org/doi/10.1145/3706599.3719681
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)

# Academic publishers embed labelled metadata in the page head. These are the
# tag names we trust (NOT og:title/twitter:title — those are usually just the
# site name, which would cause false mismatches).
_META_TITLE  = ["citation_title", "dc.title"]
_META_AUTHOR = ["citation_author", "dc.creator"]
_META_DATE   = ["citation_publication_date", "citation_date", "citation_cover_date",
                "dc.date", "prism.publicationDate"]

# OpenAlex is the no-DOI fallback search. A contact email puts you in its
# faster, more reliable "polite pool".
OPENALEX_URL = "https://api.openalex.org/works"
OPENALEX_MAILTO = "vsvarun@utas.edu.au"
 

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

def _meta_by_name(soup, name):
    """All <meta> content values matching one tag name."""
    name = name.lower()
    out = []
    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or "").lower()

        # if the tag matches the specified name
        if key == name and tag.get("content"):
            out.append(tag["content"].strip())
    return out


def _first_meta(soup, names):
    """First value found, trying each name in priority order."""
    for n in names:
        vals = _meta_by_name(soup, n)
        if vals:
            return vals[0]
    return None


def _all_meta(soup, names):
    """All values for the first name that has any (e.g. every author tag)."""
    for n in names:
        vals = _meta_by_name(soup, n)
        if vals:
            return vals
    return []


def _metatags_to_metadata(html):
    """Build a CSL-JSON-shaped dict from a page's embedded tags, so it can be
    fed straight into compare_to_metadata. Returns None if the page has no
    usable academic metadata (e.g. an ordinary blog)."""
    soup = BeautifulSoup(html, "html.parser")

    # check for TITLE
    # only 1 entry required
    title = _first_meta(soup, _META_TITLE)
    if not title:
        return None
    
    # check for AUTHOR
    authors = _all_meta(soup, _META_AUTHOR)

    # check for DATE
    date = _first_meta(soup, _META_DATE)
    year = None
    if date:
        m = re.search(r"(\d{4})", date)
        if m:
            year = int(m.group(1))

    return {
        "title": title,
        "author": [{"family": _surname(a)} for a in authors],
        "issued": {"date-parts": [[year]]} if year else {},
    }
 
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
        note = "DOI/URL resolves to a record whose title matches the citation."
        if year_match is False:
            note += (f" But the cited year ({claimed_year}) differs from the "
                     f"registry year ({canon_year}) — worth a manual look.")
            
        if not len(overlap) and len(claimed_surnames):
            verdict = "verified_review"
            note += (f" The author list differs from official metadata.")
    else:
        verdict = "metadata_mismatch"
        note = (f"DOI/URL is registered, but it resolves to \"{canonical_title}\", "
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
 

def _openalex_to_metadata(work):
    """Reshape ONE OpenAlex result into the CSL-like dict compare_to_metadata
    expects, so the same comparison logic is reused everywhere."""

    # list of authors
    authors = []
    for a in work.get("authorships", []):
        name = (a.get("author") or {}).get("display_name") or ""
        if name:
            authors.append({"family": _surname(name)})

    # publication year
    year = work.get("publication_year")

    # metadata in the same format, to be used in compare metadata
    return {
        "title": work.get("display_name") or "",
        "author": authors,
        "issued": {"date-parts": [[year]]} if year else {},
    }

def reverse_lookup(claimed_title, claimed_authors, claimed_year, max_candidates=5):
    """Last resort: no DOI and no usable page metadata.
 
    Search OpenAlex by title, then use title + author + year TOGETHER to pick
    which result is really the cited paper (not just the top-ranked one). If
    the chosen paper has a DOI, confirm it the strong way. Otherwise judge on
    the combined match, STRICTLY: a title-only match is NOT enough here, because
    we searched by title and could be looking at a same-titled lookalike.
 
    Never returns 'fake' — only verified / verified_review / unverifiable."""
    claimed_authors = claimed_authors or []
 
    if not claimed_title:
        return {"verdict": "unverifiable",
                "note": "No title available to search with — cannot look this up."}
 
    # 1. Search OpenAlex by title.
    try:
        resp = requests.get(
            OPENALEX_URL,
            params={"search": claimed_title,
                    "per-page": max_candidates,
                    "mailto": OPENALEX_MAILTO},
            timeout=15,
        )
        resp.raise_for_status()

        # main results we are interested in
        results = resp.json().get("results", [])

    except requests.RequestException as exc:
        return {"verdict": "lookup_error",
                "note": f"Could not reach OpenAlex: {exc}. Try again later."}
 
    if not results:
        return {"verdict": "unverifiable",
                "note": ("No matching work found in OpenAlex. This may be a book, an "
                         "older work, or simply not indexed — not necessarily fabricated.")}
 
    # 2. Score EVERY candidate on title + author + year together; keep the best.
    #    Author/year agreement (not search rank) decides the winner — this is
    #    what stops a same-titled lookalike from being chosen.
    best = None
    best_combined = -1
    for work in results:
        meta = _openalex_to_metadata(work)
        cmp = compare_to_metadata(claimed_title, claimed_authors, claimed_year, meta)

        # check how many authors match
        overlap_count = int(cmp["author_overlap"].split("/")[0])
        combined = cmp["title_score"] + (15 * overlap_count) + (10 if cmp["year_match"] else 0)
        if combined > best_combined:
            best_combined = combined
            best = (work, cmp)
 
    work, cmp = best
 
    # 3. If the chosen paper carries a DOI, climb back onto the STRONG path.
    doi = extract_doi_from_url(work.get("doi") or "")
    if doi and cmp["title_score"] >= TITLE_THRESHOLD:
        result = verify_doi(claimed_title, claimed_authors, claimed_year, doi)
        result["evidence"] = "openalex search + doi confirmation"
        result["note"] = "Found via title search, then confirmed against its DOI. " + result.get("note", "")
        return result
 
    # 4. No DOI on the chosen paper -> judge on the combined match, STRICTLY.
    overlap_count = int(cmp["author_overlap"].split("/")[0])
    if cmp["title_score"] >= TITLE_THRESHOLD and overlap_count > 0:
        if cmp["year_match"] is False:
            verdict = "verified_review"
            note = "Found in OpenAlex; title and authors match, but the year differs — worth a manual look."
        else:
            verdict = "verified"
            note = "Found in OpenAlex; title and authors match the citation."
    elif cmp["title_score"] >= TITLE_THRESHOLD:
        verdict = "unverifiable"
        note = ("A work with this title exists in OpenAlex, but the authors do not match — "
                "this may be a different paper that happens to share the title.")
    else:
        verdict = "unverifiable"
        note = ("No close title match in OpenAlex. May be an unindexed book or older "
                "work rather than a fabrication.")
 
    return {
        "verdict": verdict,
        "evidence": "openalex search",
        "title_score": cmp["title_score"],
        "claimed_title": claimed_title,
        "canonical_title": cmp["canonical_title"],
        "author_overlap": cmp["author_overlap"],
        "claimed_year": claimed_year,
        "canonical_year": cmp["canonical_year"],
        "note": note,
    }
 
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
 
def extract_doi_from_url(url):
    """Try to pull a DOI out of a URL. Returns the bare DOI, or None.

    This is the high-value step: many 'no DOI' references actually have one
    sitting inside the link, which lets us jump back onto the strong DOI path.
    """
    if not url:
        return None
    
    # find the DOI in the url if exists
    match = DOI_PATTERN.search(url)
    if not match:
        return None
    doi = match.group(0)

    # URLs often have trailing junk after the DOI (?query, #fragment, etc.)
    return doi.split("?")[0].split("#")[0].rstrip(".,)/")


def check_url_alive(url):
    """Weak check: does the link load? True = loads, False = dead,
    None = couldn't tell. A live link is mild positive evidence; a dead
    one is a mild warning — neither is proof on its own."""
    try:
        resp = requests.get(url, timeout=15, allow_redirects=True, headers=HEADERS)
        return resp.status_code < 400
    except requests.RequestException:
        return None


def verify_url_via_metatags(claimed_title, claimed_authors, claimed_year, url):
    """Read structured metadata from the page head and compare it like DOI
    metadata. Returns a verdict dict, or None if the page couldn't be fetched
    or had no usable tags (caller then falls back to the weak link check)."""
    try:
        resp = requests.get(url, timeout=15, allow_redirects=True, headers=HEADERS)
    except requests.RequestException:
        return None
    
    # if the status code is not alive
    # DO THE LAST BRANCH CHECKING HERE AS WELL
    if resp.status_code >= 400:
        return None

    # get the metadata out of the text 
    metadata = _metatags_to_metadata(resp.text)
    if metadata is None:
        return None

    # compare the metadata
    result = compare_to_metadata(claimed_title, claimed_authors, claimed_year, metadata, doi=None)

    # compare_to_metadata's note mentions a "DOI"; reword it, since this
    # evidence came from the page itself and is weaker than a registry.
    if result["verdict"] == "verified":
        result["note"] = ("The page's own embedded metadata matches the citation. "
                        "Weaker than a DOI check, but supportive.")
    elif result["verdict"] == "verified_review":
        result["note"] = ("The page's title matches, but the authors differ from the "
                        "citation — this may be a different paper. Worth a manual look.")
    else:
        result["note"] = (f"The page's embedded title (\"{result['canonical_title']}\") "
                        f"does not match the cited title. Treat with suspicion.")
    result["evidence"] = "page meta tags"
    result["url"] = url
    return result

def verify_url(claimed_title, claimed_authors, claimed_year, url):
    # 1. Strongest: a DOI hiding inside the URL -> reuse the DOI check.
    doi = extract_doi_from_url(url)
    if doi:
        return verify_doi(claimed_title, claimed_authors, claimed_year, doi)

    # 2. Decent: structured metadata embedded in the page head.
    meta_result = verify_url_via_metatags(claimed_title, claimed_authors, claimed_year, url)
    if meta_result is not None:
        return meta_result

    # 3. Weak: can we at least tell the link is alive?
    alive = check_url_alive(url)
    if alive is True:
        note = ("No DOI and no embedded metadata. The link loads, but that's weak "
                "evidence — needs a title/author lookup.")
    elif alive is False:
        note = ("No DOI or embedded metadata, and the link does not load. "
                "Weak warning — needs a title/author lookup.")
    else:
        note = "No DOI or embedded metadata, and the link could not be reached."
    return {
        "verdict": "url_only",
        "url": url,
        "link_alive": alive,
        "note": note,
    }

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
        response = verify_url(
            extracted_data.get("title"),
            extracted_data.get("authors"),
            extracted_data.get("year"),
            extracted_data.get("url"),
        )
        # If the URL gave us nothing solid, fall back to the title/author/year search.
        if response.get("verdict") == "url_only":
            fallback = reverse_lookup(
                extracted_data.get("title"),
                extracted_data.get("authors"),
                extracted_data.get("year"),
            )
            fallback["link_alive"] = response.get("link_alive")
            fallback["url"] = extracted_data.get("url")
            return fallback
        return response
    else:
        return reverse_lookup(
            extracted_data.get("title"),
            extracted_data.get("authors"),
            extracted_data.get("year"),
        )

def metadata(reference):
    """Extracts the metadata using an llm and returns a reference in a specific format."""
    reference = re.sub(r"\s+", " ", reference).strip()
    result = chain.invoke({"reference": reference})
    return(result.model_dump())


def check_reference(reference):
    """Gives a verdict about a citation combining all the above functionality"""
    return check_metadata(metadata(reference))


if __name__ == "__main__":
    import sys

    # Read the reference from stdin (a pipe or a redirected file).
    reference = sys.stdin.read().strip()

    if not reference:
        print('No reference provided. Use:  python reference_checking.py < reference.txt', file=sys.stderr)
        sys.exit(1)

    result = check_reference(reference)
    print(json.dumps(result, indent=2, ensure_ascii=False))