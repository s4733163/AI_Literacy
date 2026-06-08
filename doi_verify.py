"""
Test cases for the citation verifier — DOI pathways + URL pathways.

Run on a machine WITH internet (it makes live calls to doi.org and a few sites):
    python3 test_verify.py

The import below must match the file that holds check_metadata.
(If your file is verify.py this is correct; if it's main.py use 'from main import ...'.)

NOTE on the "verified" cases: they use a DOI whose real, resolver-confirmed
record is this paper. Never guess a title<->DOI pairing — resolve it first.
"""

from reference_checking import check_metadata


# --- A CONFIRMED real pairing (checked against the publisher record) -----
DOI_REAL = "10.1016/j.caeai.2021.100041"          # really IS this paper:
REAL_TITLE = "Conceptualizing AI literacy: An exploratory review"
REAL_AUTHORS = ["Ng, D. T. K.", "Leung, J. K. L.", "Chu, S. K. W.", "Qiao, M. S."]
REAL_YEAR = 2021

# A real DOI that points at a DIFFERENT paper ("Automated coding of student
# chats..."). Pairing it with the title above is a genuine fabricated citation.
DOI_WRONG_PAPER = "10.1016/j.caeai.2023.100123"


CASES = [

    # ================= DOI PATHWAYS =================

    # 1. Clean, honest reference -> verified
    {
        "label": "1. verified (clean)",
        "data": {"title": REAL_TITLE, "authors": REAL_AUTHORS, "year": REAL_YEAR,
                 "doi": DOI_REAL, "url": None},
        "expect_verdict": "verified",
        "note_has": ["matches"],
    },

    # 2. Title right but YEAR wrong -> still verified, with a year note
    {
        "label": "2. verified + year warning",
        "data": {"title": REAL_TITLE, "authors": REAL_AUTHORS, "year": 2019,
                 "doi": DOI_REAL, "url": None},
        "expect_verdict": "verified",
        "note_has": ["registry year"],
    },

    # 3. Title right but AUTHORS wrong -> still verified, with an author note
    {
        "label": "3. verified + author warning",
        "data": {"title": REAL_TITLE, "authors": ["Einstein, A."], "year": REAL_YEAR,
                 "doi": DOI_REAL, "url": None},
        "expect_verdict": "verified_review",
        "note_has": ["author list differs"],
    },

    # 4. Title right, BOTH year and authors wrong -> verified + both notes
    {
        "label": "4. verified + both warnings",
        "data": {"title": REAL_TITLE, "authors": ["Newton, I."], "year": 2010,
                 "doi": DOI_REAL, "url": None},
        "expect_verdict": "verified_review",
        "note_has": ["registry year", "author list differs"],
    },

    # 5. Title right, NO claimed year -> verified, and NO year note
    {
        "label": "5. verified, year missing (no year note)",
        "data": {"title": REAL_TITLE, "authors": REAL_AUTHORS, "year": None,
                 "doi": DOI_REAL, "url": None},
        "expect_verdict": "verified",
        "note_has": [],
        "note_has_not": ["registry year"],
    },

    # 5b. Subtitle dropped -> should still match (fuzzy forgives it)
    {
        "label": "5b. verified, subtitle dropped",
        "data": {"title": "Conceptualizing AI literacy", "authors": REAL_AUTHORS,
                 "year": REAL_YEAR, "doi": DOI_REAL, "url": None},
        "expect_verdict": "verified",
        "note_has": [],
    },

    # 6. THE DANGEROUS FAKE: correct title, but a DOI that points elsewhere
    {
        "label": "6. metadata_mismatch (real DOI, wrong paper)",
        "data": {"title": REAL_TITLE, "authors": REAL_AUTHORS, "year": 2023,
                 "doi": DOI_WRONG_PAPER, "url": None},
        "expect_verdict": "metadata_mismatch",
        "note_has": ["does not match"],
    },

    # 7. Well-formed but NON-EXISTENT DOI -> doi_not_found
    {
        "label": "7. doi_not_found (fabricated DOI)",
        "data": {"title": "A paper that does not exist", "authors": ["Nobody, A."],
                 "year": 2099, "doi": "10.1016/j.caeai.2099.000000", "url": None},
        "expect_verdict": "doi_not_found",
        "note_has": ["no such record"],
    },

    # 10. Neither DOI nor URL (the Kuhn book) -> no_doi_or_url branch
    {
        "label": "10. no_doi_or_url (book)",
        "data": {"title": "The Structure of Scientific Revolutions",
                 "authors": ["Kuhn, T. S."], "year": 1962, "doi": None, "url": None},
        "expect_verdict": "no_doi_or_url",
        "note_has": [],
    },

    # 11. ROBUSTNESS: DOI arrives WITH the resolver prefix attached.
    {
        "label": "11. robustness: DOI with https://doi.org/ prefix",
        "data": {"title": REAL_TITLE, "authors": REAL_AUTHORS, "year": REAL_YEAR,
                 "doi": "https://doi.org/" + DOI_REAL, "url": None},
        "expect_verdict": "verified",
        "note_has": [],
    },

    # ================= URL PATHWAYS =================

    # U1. A DOI hiding inside the URL -> reuse the strong DOI path -> verified
    {
        "label": "U1. url with DOI inside -> verified",
        "data": {"title": REAL_TITLE, "authors": ["Ng, D. T. K.", "Leung, J. K. L."],
                 "year": 2021, "doi": None,
                 "url": "https://doi.org/10.1016/j.caeai.2021.100041"},
        "expect_verdict": "verified",
        "note_has": ["matches"],
    },

    # U2. DOI inside URL, but it points to a DIFFERENT paper -> metadata_mismatch
    {
        "label": "U2. url with DOI inside, wrong paper -> mismatch",
        "data": {"title": REAL_TITLE, "authors": ["Ng, D. T. K."], "year": 2021,
                 "doi": None,
                 "url": "https://bera-journals.onlinelibrary.wiley.com/doi/10.1111/bjet.13445"},
        "expect_verdict": "metadata_mismatch",
        "note_has": ["does not match"],
    },

    # U3. No DOI in URL, page HAS academic meta tags, title matches -> verified
    {
        "label": "U3. url meta-tags match -> verified",
        "data": {"title": "Attention Is All You Need", "authors": ["Vaswani, A."],
                 "year": 2017, "doi": None, "url": "https://arxiv.org/abs/1706.03762"},
        "expect_verdict": "verified",
        "note_has": ["embedded metadata"],
    },

    # U4. No DOI, page HAS meta tags, but title does NOT match -> metadata_mismatch
    {
        "label": "U4. url meta-tags wrong paper -> mismatch",
        "data": {"title": "A study of coral reef ecosystems in the Pacific",
                 "authors": ["Nemo, F."], "year": 2017, "doi": None,
                 "url": "https://arxiv.org/abs/1706.03762"},
        "expect_verdict": "metadata_mismatch",
        "note_has": ["does not match"],
    },

    # U5. No DOI, no academic meta tags, link is alive -> url_only (weak)
    {
        "label": "U5. url no metadata, link alive -> url_only",
        "data": {"title": "Some blog post", "authors": ["Writer, A."], "year": 2022,
                 "doi": None, "url": "https://example.com"},
        "expect_verdict": "url_only",
        "note_has": ["link loads"],
    },

    # U6. No DOI, no metadata, link unreachable -> url_only (weak warning)
    {
        "label": "U6. url no metadata, link unreachable -> url_only",
        "data": {"title": "Ghost reference", "authors": ["Phantom, P."], "year": 2020,
                 "doi": None, "url": "https://this-domain-does-not-exist-9999xyz.com"},
        "expect_verdict": "url_only",
        "note_has": ["could not be reached"],
    },
]


def run():
    passed = 0
    for case in CASES:
        result = check_metadata(case["data"])
        verdict = result.get("verdict")
        note = (result.get("note") or "").lower()

        ok = verdict == case["expect_verdict"]
        for word in case.get("note_has", []):
            ok = ok and (word.lower() in note)
        for word in case.get("note_has_not", []):
            ok = ok and (word.lower() not in note)

        passed += ok
        flag = "PASS" if ok else "FAIL"
        print(f"[{flag}] {case['label']}")
        print(f"        got verdict={verdict!r}  expected={case['expect_verdict']!r}")
        if not ok:
            print(f"        note: {result.get('note')}")
    print(f"\n{passed}/{len(CASES)} passed")


if __name__ == "__main__":
    run()