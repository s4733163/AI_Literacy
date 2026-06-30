#!/usr/bin/env python3
"""
build_dataset.py  --  Construct a labelled reference-verification benchmark.

The benchmark is a *realistic mix*: genuine references harvested live from
OpenAlex, plus hallucinated references built by corrupting real seeds along a
labelled error taxonomy. Every row keeps DETAILED ground truth:

    label           real | fake
    error_type      none (real) | fabricated_doi | metadata_mismatch |
                    wrong_authors | wrong_year | fabricated_nodoi |
                    fabricated_fakedoi | lookalike_title
    expected_tier   doi | url | reverse        (which branch should resolve it)
    expected_verdict  the verdict the tool *should* emit, given its design

We deliberately do NOT label items "for the tool to predict real/fake". The
tool's job is to route each reference to a verifiable / needs-checking verdict.
The detailed label is the actual value we map the 7 verdicts against.

OUTPUT  benchmark_dataset.csv  with columns:
        Entry id, Entry name, label, error_type, expected_tier, expected_verdict
        ("Entry id"/"Entry name" are the two columns reference_checking.py reads;
         the rest are the answer key, ignored by the tool, used by analyze_eval.py)

USAGE
    # real run (hits OpenAlex; needs network):
    python build_dataset.py --n-real 105 --n-fake 45 --out benchmark_dataset.csv
    # offline smoke test (synthetic registry, no network):
    python build_dataset.py --mock --n-real 105 --n-fake 45
"""
import argparse, csv, json, random, re, sys, time
from urllib.parse import quote

OPENALEX = "https://api.openalex.org/works"
MAILTO = "vsvarun@utas.edu.au"

# Topics to spread the real sample across domains (mirrors GhostCite / CiteAudit
# practice of sampling many fields so results are not domain-specific).
TOPICS = [
    "machine learning", "oncology", "climate change", "macroeconomics",
    "molecular biology", "civil engineering", "linguistics", "public health",
    "astrophysics", "criminology", "marine biology", "educational technology",
    "renewable energy", "neuroscience",
]

# ---------------------------------------------------------------------------
# Reference string formatting (APA-ish, the form a student would paste in)
# ---------------------------------------------------------------------------
def fmt_authors(authors):
    """['Jane Doe','John Smith'] -> 'Doe, J., & Smith, J.'"""
    out = []
    for a in authors:
        parts = a.split()
        if not parts:
            continue
        sur = parts[-1]
        inits = " ".join(f"{p[0]}." for p in parts[:-1] if p)
        out.append(f"{sur}, {inits}".strip().rstrip(","))
    if not out:
        return "Anonymous"
    if len(out) == 1:
        return out[0]
    if len(out) <= 6:
        return ", ".join(out[:-1]) + ", & " + out[-1]
    return ", ".join(out[:6]) + ", et al."

def make_reference(meta, *, include_doi=True, include_url=False):
    """Build a reference string from a metadata dict."""
    a = fmt_authors(meta["authors"])
    y = meta.get("year") or "n.d."
    t = meta["title"].rstrip(". ")
    venue = meta.get("venue") or ""
    s = f"{a} ({y}). {t}."
    if venue:
        s += f" {venue}."
    if include_doi and meta.get("doi"):
        s += f" https://doi.org/{meta['doi']}"
    elif include_url and meta.get("url"):
        s += f" {meta['url']}"
    return re.sub(r"\s+", " ", s).strip()

# ---------------------------------------------------------------------------
# OpenAlex harvest
# ---------------------------------------------------------------------------
def _clean_doi(doi):
    if not doi:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)

def harvest_real(n, seed=7):
    """Pull n real works from OpenAlex, spread across topics. Needs network."""
    import requests
    random.seed(seed)
    per = max(4, n // len(TOPICS) + 2)
    pool, seen = [], set()
    for topic in TOPICS:
        params = {
            "search": topic,
            "filter": "has_doi:true,type:article",
            "per-page": per,
            "select": "title,authorships,publication_year,doi,primary_location",
            "mailto": MAILTO,
        }
        try:
            r = requests.get(OPENALEX, params=params, timeout=30)
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as e:
            print(f"  ! {topic}: {e}", file=sys.stderr)
            continue
        for w in results:
            doi = _clean_doi(w.get("doi"))
            title = (w.get("title") or "").strip()
            if not doi or not title or doi in seen or len(title) < 12:
                continue
            authors = [a["author"]["display_name"]
                       for a in w.get("authorships", [])[:8]
                       if a.get("author", {}).get("display_name")]
            if not authors:
                continue
            loc = w.get("primary_location") or {}
            venue = ((loc.get("source") or {}).get("display_name")) or ""
            url = loc.get("landing_page_url") or ""
            seen.add(doi)
            pool.append({"title": title, "authors": authors,
                         "year": w.get("publication_year"),
                         "doi": doi, "venue": venue, "url": url})
        time.sleep(0.2)
    random.shuffle(pool)
    return pool

def harvest_mock(n, seed=7):
    """Deterministic synthetic 'registry' so the pipeline runs with no network."""
    random.seed(seed)
    firsts = ["Wei","Maria","John","Aisha","Chen","Olga","Raj","Sofia","Liam","Yuki",
              "Ahmed","Elena","David","Priya","Tom","Nina","Carlos","Mei","Omar","Sara"]
    lasts = ["Zhang","Garcia","Smith","Khan","Wang","Ivanova","Patel","Rossi","Murphy",
             "Tanaka","Hassan","Petrov","Cohen","Nair","Brown","Berg","Lopez","Lin","Ali","Costa"]
    nouns = ["networks","dynamics","models","systems","pathways","markets","reactions",
             "structures","corpora","outcomes","emissions","circuits","habitats","curricula"]
    adjs = ["robust","scalable","empirical","longitudinal","comparative","adaptive",
            "stochastic","clinical","computational","quantitative","ecological","semantic"]
    pool = []
    for i in range(n + 80):
        k = random.randint(1, 4)
        authors = [f"{random.choice(firsts)} {random.choice(lasts)}" for _ in range(k)]
        title = (f"{random.choice(adjs).capitalize()} {random.choice(nouns)} "
                 f"in {random.choice(adjs)} {random.choice(nouns)}")
        year = random.randint(2015, 2026)
        doi = f"10.{random.randint(1000,9999)}/mock.{i:05d}"
        pool.append({"title": title, "authors": authors, "year": year,
                     "doi": doi, "venue": "Journal of Mock Studies",
                     "url": f"https://example.org/abs/{i:05d}"})
    random.shuffle(pool)
    return pool

# ---------------------------------------------------------------------------
# Corruption taxonomy -> fakes (each maps to an expected verdict)
# ---------------------------------------------------------------------------
def scramble_doi(doi):
    """Keep the prefix, mangle the suffix so it will not resolve."""
    if "/" in doi:
        pre, suf = doi.split("/", 1)
    else:
        pre, suf = "10.9999", doi
    digits = "0123456789"
    suf2 = "".join(random.choice(digits) if c.isdigit() else c for c in suf)
    return f"{pre}/{suf2}zzx{random.randint(100,999)}"

def fake_title(seed_title):
    swaps = {"Robust":"Resilient","Scalable":"Distributed","Empirical":"Theoretical",
             "Adaptive":"Dynamic","networks":"frameworks","models":"architectures",
             "Comparative":"Integrated","systems":"ecosystems","dynamics":"behaviours"}
    t = seed_title
    for a, b in swaps.items():
        t = t.replace(a, b)
    if t == seed_title:
        t = "Revisiting " + seed_title
    return t

def random_authors(n=2):
    f = ["Gregory","Helena","Marcus","Indira","Felix","Naomi"]
    l = ["Aldridge","Vasquez","Okonkwo","Lindqvist","Yamamoto","Delacroix"]
    return [f"{random.choice(f)} {random.choice(l)}" for _ in range(n)]

FAKE_TYPES = [
    "fabricated_doi", "metadata_mismatch", "wrong_authors",
    "wrong_year", "fabricated_nodoi", "fabricated_fakedoi", "lookalike_title",
]

def make_fake(kind, seed, other):
    """Return (reference_string, error_type, expected_tier, expected_verdict)."""
    m = dict(seed)
    if kind == "fabricated_doi":
        m["doi"] = scramble_doi(seed["doi"])
        return make_reference(m, include_doi=True), kind, "doi", "doi_not_found"
    if kind == "metadata_mismatch":
        # real, resolvable DOI of seed, but title+authors from a DIFFERENT paper
        m["title"] = other["title"]; m["authors"] = other["authors"]
        return make_reference(m, include_doi=True), kind, "doi", "metadata_mismatch"
    if kind == "wrong_authors":
        m["authors"] = random_authors(2)
        return make_reference(m, include_doi=True), kind, "doi", "verified_review"
    if kind == "wrong_year":
        yr = (seed.get("year") or 2020)
        m["year"] = yr + random.choice([-3, -2, 2, 3])
        return make_reference(m, include_doi=True), kind, "doi", "verified"
    if kind == "fabricated_nodoi":
        m = {"title": fake_title(seed["title"]) + " under uncertainty",
             "authors": random_authors(2), "year": random.randint(2016, 2026),
             "venue": "Journal of Applied Studies", "doi": None, "url": None}
        return make_reference(m, include_doi=False), kind, "reverse", "unverifiable"
    if kind == "fabricated_fakedoi":
        m = {"title": fake_title(seed["title"]), "authors": random_authors(2),
             "year": random.randint(2016, 2026), "venue": "Intl. Review of Studies",
             "doi": scramble_doi(seed["doi"]), "url": None}
        return make_reference(m, include_doi=True), kind, "doi", "doi_not_found"
    if kind == "lookalike_title":
        m = {"title": fake_title(seed["title"]), "authors": seed["authors"],
             "year": seed.get("year"), "venue": seed.get("venue"),
             "doi": None, "url": None}
        return make_reference(m, include_doi=False), kind, "reverse", "unverifiable"
    raise ValueError(kind)

# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------
def construct_dataset(pool, n_real, n_fake, seed=7):
    random.seed(seed)
    pool = list(pool)
    reals = pool[:n_real]
    seeds_for_fakes = pool[n_real:n_real + n_fake + 5]
    rows = []
    eid = 1
    # reals: mostly DOI tier; a slice without DOI (reverse tier); a slice URL-only
    for i, m in enumerate(reals):
        r = dict(m)
        mod = i % 10
        if mod == 8 and m.get("url"):          # URL branch (no explicit DOI field)
            ref = make_reference(r, include_doi=False, include_url=True)
            tier, exp = "url", "verified"
        elif mod == 9:                          # no DOI, no URL -> reverse lookup
            ref = make_reference(r, include_doi=False, include_url=False)
            tier, exp = "reverse", "verified"
        else:                                   # DOI tier
            ref = make_reference(r, include_doi=True)
            tier, exp = "doi", "verified"
        rows.append([eid, ref, "real", "none", tier, exp]); eid += 1
    # fakes: cycle through the taxonomy
    for j in range(n_fake):
        kind = FAKE_TYPES[j % len(FAKE_TYPES)]
        seed_m = seeds_for_fakes[j % len(seeds_for_fakes)]
        other = seeds_for_fakes[(j + 3) % len(seeds_for_fakes)]
        ref, etype, tier, exp = make_fake(kind, seed_m, other)
        rows.append([eid, ref, "fake", etype, tier, exp]); eid += 1
    random.shuffle(rows)
    for new_id, row in enumerate(rows, 1):     # renumber after shuffle
        row[0] = new_id
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-real", type=int, default=105)
    ap.add_argument("--n-fake", type=int, default=45)
    ap.add_argument("--out", default="benchmark_dataset.csv")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--mock", action="store_true", help="offline synthetic registry")
    args = ap.parse_args()

    need = args.n_real + args.n_fake + 10
    print(f"Harvesting {'mock' if args.mock else 'OpenAlex'} pool (~{need})...")
    pool = harvest_mock(need, args.seed) if args.mock else harvest_real(need, args.seed)
    if len(pool) < args.n_real + args.n_fake:
        print(f"  ! only {len(pool)} works available; reduce --n-real/--n-fake.",
              file=sys.stderr)
        if not pool:
            sys.exit(1)

    rows = construct_dataset(pool, args.n_real, args.n_fake, args.seed)
    header = ["Entry id", "Entry name", "label", "error_type",
              "expected_tier", "expected_verdict"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)

    n_real = sum(1 for r in rows if r[2] == "real")
    n_fake = len(rows) - n_real
    print(f"Wrote {args.out}: {len(rows)} refs ({n_real} real / {n_fake} fake)")
    from collections import Counter
    print(" error types:", dict(Counter(r[3] for r in rows)))
    print(" expected tiers:", dict(Counter(r[4] for r in rows)))

if __name__ == "__main__":
    main()