"""
Comprehensive test suite for the citation verifier.

Run OFFLINE (fast, deterministic, no internet) — the default:
    pytest test_verify_suite.py -m "not live"

Run the LIVE smoke tests too (hits doi.org / OpenAlex / arxiv):
    pytest test_verify_suite.py

NOTES
- The module guards import with a GOOGLE_API_KEY check and builds the LLM at
  import time. We set a dummy key below BEFORE importing so the suite can load
  it without your real key. (A cleaner long-term fix is to make the LLM init
  lazy so importing the module has no side effects — see the chat notes.)
- If your module file is not named verify.py, change the import line.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("GOOGLE_API_KEY", "your-key-here")  # satisfy the import-time guard

import pytest
import requests
import reference_checking as V


# --------------------------------------------------------------------------
# Shared fixtures / fakes
# --------------------------------------------------------------------------
T = "Conceptualizing AI literacy: An exploratory review"
AUTHORS = ["Ng, D. T. K.", "Leung, J. K. L."]
YEAR = 2021

CSL_MATCH = {"title": T, "author": [{"family": "Ng"}, {"family": "Leung"}],
             "issued": {"date-parts": [[2021]]}}
CSL_OTHER = {"title": "A completely different paper on network routing",
             "author": [{"family": "Smith"}], "issued": {"date-parts": [[2010]]}}

HTML_MATCH = ('<html><head>'
              '<meta name="citation_title" content="Conceptualizing AI literacy: An exploratory review">'
              '<meta name="citation_author" content="Ng, Davy Tsz Kit">'
              '<meta name="citation_author" content="Leung, Jac Ka Lok">'
              '<meta name="citation_publication_date" content="2021/01/01">'
              '</head></html>')
HTML_OTHER = ('<html><head>'
              '<meta name="citation_title" content="Deep sea coral reef ecology">'
              '<meta name="citation_author" content="Fish, Marlin">'
              '</head></html>')
HTML_NONE = '<html><head><meta property="og:title" content="My Blog"></head></html>'


class FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def make_fake_get(doi=None, openalex=None, page=None):
    """Return a fake requests.get that dispatches by URL. Each arg may be a
    FakeResp, or an Exception instance to be raised."""
    def fake_get(url, **kwargs):
        if url.startswith(V.DOI_RESOLVER):
            target = doi
        elif url.startswith(V.OPENALEX_URL):
            target = openalex
        else:
            target = page
        if isinstance(target, Exception):
            raise target
        if target is None:
            raise AssertionError(f"unexpected GET to {url}")
        return target
    return fake_get


def oa_work(title=T, names=("Davy Ng", "Jac Leung"), year=2021, doi=None):
    w = {"display_name": title, "publication_year": year,
         "authorships": [{"author": {"display_name": n}} for n in names]}
    if doi:
        w["doi"] = doi
    return w


def oa_results(*works):
    return FakeResp(200, json_data={"results": list(works)})


# ==========================================================================
# 1. PURE HELPERS (no network)
# ==========================================================================
class TestNormalize:
    def test_lowercase_and_strip_punct(self):
        assert V.normalize("Hello, World!") == "hello world"
    def test_collapse_whitespace(self):
        assert V.normalize("  A   B ") == "a b"
    def test_none(self):
        assert V.normalize(None) == ""

class TestSurname:
    def test_comma_form(self):
        assert V._surname("Ng, D. T. K.") == "ng"
    def test_given_first(self):
        assert V._surname("D. T. K. Ng") == "ng"
    def test_empty(self):
        assert V._surname("") == ""

class TestCanonicalHelpers:
    def test_title_string(self):
        assert V._canonical_title({"title": "X"}) == "X"
    def test_title_list(self):
        assert V._canonical_title({"title": ["A", "B"]}) == "A"
    def test_title_missing(self):
        assert V._canonical_title({}) == ""
    def test_surnames(self):
        meta = {"author": [{"family": "Ng"}, {"literal": "Smith"}]}
        assert V._canonical_surnames(meta) == {"ng", "smith"}
    def test_year(self):
        assert V._canonical_year({"issued": {"date-parts": [[2021, 1, 1]]}}) == 2021
    def test_year_missing(self):
        assert V._canonical_year({}) is None

class TestExtractDoiFromUrl:
    def test_acm(self):
        assert V.extract_doi_from_url("https://dl.acm.org/doi/10.1145/3706599.3719681") == "10.1145/3706599.3719681"
    def test_doiorg(self):
        assert V.extract_doi_from_url("https://doi.org/10.1016/j.caeai.2021.100041") == "10.1016/j.caeai.2021.100041"
    def test_strips_query_and_fragment(self):
        assert V.extract_doi_from_url("https://x.com/10.1007/s10639-021-1?utm=a#frag") == "10.1007/s10639-021-1"
    def test_no_doi(self):
        assert V.extract_doi_from_url("https://example.com/post") is None
    def test_none(self):
        assert V.extract_doi_from_url(None) is None

class TestMetatagsToMetadata:
    def test_good_page(self):
        meta = V._metatags_to_metadata(HTML_MATCH)
        assert meta["title"] == T
        assert {a["family"] for a in meta["author"]} == {"ng", "leung"}
        assert meta["issued"]["date-parts"] == [[2021]]
    def test_no_tags_returns_none(self):
        assert V._metatags_to_metadata(HTML_NONE) is None

class TestOpenAlexReshape:
    def test_reshape(self):
        meta = V._openalex_to_metadata(oa_work())
        assert meta["title"] == T
        assert {a["family"] for a in meta["author"]} == {"ng", "leung"}
        assert meta["issued"]["date-parts"] == [[2021]]


# ==========================================================================
# 2. compare_to_metadata (the core decision, pure)
# ==========================================================================
class TestCompare:
    def test_exact_match(self):
        r = V.compare_to_metadata(T, AUTHORS, YEAR, CSL_MATCH)
        assert r["verdict"] == "verified" and r["title_score"] == 100.0
        assert r["author_overlap"] == "2/2" and r["year_match"] is True
    def test_subtitle_dropped(self):
        r = V.compare_to_metadata("Conceptualizing AI literacy", AUTHORS, YEAR, CSL_MATCH)
        assert r["verdict"] == "verified"
    def test_title_mismatch(self):
        r = V.compare_to_metadata("Totally unrelated title here", AUTHORS, YEAR, CSL_MATCH)
        assert r["verdict"] == "metadata_mismatch"
    def test_same_title_wrong_authors(self):
        r = V.compare_to_metadata(T, ["Einstein, A."], YEAR, CSL_MATCH)
        assert r["verdict"] == "verified_review" and r["author_overlap"] == "0/1"
    def test_no_claimed_authors_stays_verified(self):
        r = V.compare_to_metadata(T, [], YEAR, CSL_MATCH)
        assert r["verdict"] == "verified"
    def test_wrong_year_keeps_verified_with_note(self):
        r = V.compare_to_metadata(T, AUTHORS, 2010, CSL_MATCH)
        assert r["verdict"] == "verified" and r["year_match"] is False
        assert "registry year" in r["note"]
    def test_wrong_year_and_authors(self):
        r = V.compare_to_metadata(T, ["Newton, I."], 2010, CSL_MATCH)
        assert r["verdict"] == "verified_review"
        assert "registry year" in r["note"] and "author list differs" in r["note"]


# ==========================================================================
# 3. NETWORK FUNCTIONS (monkeypatched requests.get)
# ==========================================================================
class TestFetchCslMetadata:
    def test_200(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(doi=FakeResp(200, json_data=CSL_MATCH)))
        assert V.fetch_csl_metadata("10.1/x") == CSL_MATCH
    def test_404_returns_none(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(doi=FakeResp(404)))
        assert V.fetch_csl_metadata("10.1/x") is None
    def test_500_raises(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(doi=FakeResp(500)))
        with pytest.raises(requests.RequestException):
            V.fetch_csl_metadata("10.1/x")

class TestVerifyDoi:
    def test_verified(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(doi=FakeResp(200, json_data=CSL_MATCH)))
        assert V.verify_doi(T, AUTHORS, YEAR, "10.1/x")["verdict"] == "verified"
    def test_mismatch(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(doi=FakeResp(200, json_data=CSL_OTHER)))
        assert V.verify_doi(T, AUTHORS, YEAR, "10.1/x")["verdict"] == "metadata_mismatch"
    def test_not_found(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(doi=FakeResp(404)))
        assert V.verify_doi(T, AUTHORS, YEAR, "10.1/x")["verdict"] == "doi_not_found"
    def test_lookup_error(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(doi=requests.ConnectionError("down")))
        assert V.verify_doi(T, AUTHORS, YEAR, "10.1/x")["verdict"] == "lookup_error"

class TestCheckUrlAlive:
    def test_alive(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=FakeResp(200)))
        assert V.check_url_alive("https://x.com") is True
    def test_dead(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=FakeResp(404)))
        assert V.check_url_alive("https://x.com") is False
    def test_unreachable(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=requests.ConnectionError("x")))
        assert V.check_url_alive("https://x.com") is None

class TestVerifyUrlViaMetatags:
    def test_match(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=FakeResp(200, text=HTML_MATCH)))
        r = V.verify_url_via_metatags(T, AUTHORS, YEAR, "https://x.com")
        assert r["verdict"] == "verified" and r["evidence"] == "page meta tags"
    def test_wrong_paper(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=FakeResp(200, text=HTML_OTHER)))
        assert V.verify_url_via_metatags(T, AUTHORS, YEAR, "https://x.com")["verdict"] == "metadata_mismatch"
    def test_no_tags_returns_none(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=FakeResp(200, text=HTML_NONE)))
        assert V.verify_url_via_metatags(T, AUTHORS, YEAR, "https://x.com") is None
    def test_http_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=FakeResp(500)))
        assert V.verify_url_via_metatags(T, AUTHORS, YEAR, "https://x.com") is None
    def test_connection_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=requests.ConnectionError("x")))
        assert V.verify_url_via_metatags(T, AUTHORS, YEAR, "https://x.com") is None

class TestVerifyUrl:
    def test_doi_inside_url(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(doi=FakeResp(200, json_data=CSL_MATCH)))
        r = V.verify_url(T, AUTHORS, YEAR, "https://x.com/doi/10.1234/abc")
        assert r["verdict"] == "verified"
    def test_metatags_path(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=FakeResp(200, text=HTML_MATCH)))
        assert V.verify_url(T, AUTHORS, YEAR, "https://x.com/article")["verdict"] == "verified"
    def test_url_only_alive(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=FakeResp(200, text=HTML_NONE)))
        r = V.verify_url(T, AUTHORS, YEAR, "https://blog.com")
        assert r["verdict"] == "url_only" and r["link_alive"] is True

class TestReverseLookup:
    def test_no_title(self):
        assert V.reverse_lookup(None, AUTHORS, YEAR)["verdict"] == "unverifiable"
    def test_clean_match(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(openalex=oa_results(oa_work())))
        assert V.reverse_lookup(T, AUTHORS, YEAR)["verdict"] == "verified"
    def test_picks_correct_over_lookalike(self, monkeypatch):
        lookalike = oa_work(names=("John Smith",), year=2015)
        monkeypatch.setattr(V.requests, "get", make_fake_get(openalex=oa_results(lookalike, oa_work())))
        r = V.reverse_lookup(T, AUTHORS, YEAR)
        assert r["verdict"] == "verified" and r["author_overlap"] == "2/2"
    def test_only_lookalike_is_unverifiable(self, monkeypatch):
        lookalike = oa_work(names=("John Smith", "Jane Doe"), year=2015)
        monkeypatch.setattr(V.requests, "get", make_fake_get(openalex=oa_results(lookalike)))
        assert V.reverse_lookup(T, AUTHORS, YEAR)["verdict"] == "unverifiable"
    def test_nothing_found(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(openalex=oa_results()))
        assert V.reverse_lookup(T, AUTHORS, YEAR)["verdict"] == "unverifiable"
    def test_doi_confirmation_path(self, monkeypatch):
        work = oa_work(doi="https://doi.org/10.1234/confirmed")
        monkeypatch.setattr(V.requests, "get",
            make_fake_get(openalex=oa_results(work), doi=FakeResp(200, json_data=CSL_MATCH)))
        r = V.reverse_lookup(T, AUTHORS, YEAR)
        assert r["verdict"] == "verified" and "doi confirmation" in r["evidence"]
    def test_openalex_error(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(openalex=requests.ConnectionError("x")))
        assert V.reverse_lookup(T, AUTHORS, YEAR)["verdict"] == "lookup_error"

class TestCheckMetadataRouting:
    def test_routes_to_doi(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(doi=FakeResp(200, json_data=CSL_MATCH)))
        r = V.check_metadata({"title": T, "authors": AUTHORS, "year": YEAR, "doi": "10.1/x", "url": None})
        assert r["verdict"] == "verified"
    def test_routes_to_url(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(page=FakeResp(200, text=HTML_MATCH)))
        r = V.check_metadata({"title": T, "authors": AUTHORS, "year": YEAR, "doi": None, "url": "https://x.com/a"})
        assert r["verdict"] == "verified"
    def test_url_only_falls_back_to_reverse_lookup(self, monkeypatch):
        # page has no tags (url_only) -> fallback hits OpenAlex which finds the paper
        monkeypatch.setattr(V.requests, "get",
            make_fake_get(page=FakeResp(200, text=HTML_NONE), openalex=oa_results(oa_work())))
        r = V.check_metadata({"title": T, "authors": AUTHORS, "year": YEAR, "doi": None, "url": "https://blog.com"})
        assert r["verdict"] == "verified" and r["link_alive"] is True
    def test_no_doi_no_url_reverse_lookup(self, monkeypatch):
        monkeypatch.setattr(V.requests, "get", make_fake_get(openalex=oa_results(oa_work())))
        r = V.check_metadata({"title": T, "authors": AUTHORS, "year": YEAR, "doi": None, "url": None})
        assert r["verdict"] == "verified"


# ==========================================================================
# 4. LIVE smoke tests (real network) — run with: pytest  (no -m filter)
# ==========================================================================
@pytest.mark.live
class TestLive:
    def test_real_doi_verifies(self):
        r = V.verify_doi(T, AUTHORS, 2021, "10.1016/j.caeai.2021.100041")
        assert r["verdict"] in ("verified", "verified_review")
    def test_real_doi_wrong_paper_mismatches(self):
        r = V.verify_doi(T, AUTHORS, 2023, "10.1016/j.caeai.2023.100123")
        assert r["verdict"] == "metadata_mismatch"
    def test_fake_doi_not_found(self):
        r = V.verify_doi("x", ["y"], 2099, "10.1016/j.caeai.2099.000000")
        assert r["verdict"] == "doi_not_found"
    def test_reverse_lookup_real_title(self):
        r = V.reverse_lookup(T, AUTHORS, 2021)
        assert r["verdict"] in ("verified", "verified_review")