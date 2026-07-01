#!/usr/bin/env python3
"""
run_timing.py  --  OPTIONAL. Measured wall-clock for RQ5, DOI-first vs
retrieval-first, by importing the real reference_checking module.

For each reference it extracts metadata once (shared), then times:
  * DOI-first  : the tool's real check_metadata() flow
  * Retrieval-first : force an OpenAlex reverse_lookup for EVERY reference first
It also counts external calls (DOI resolver, OpenAlex, URL fetches).

Run on YOUR machine (needs network + API key):
    python run_timing.py benchmark_dataset.csv --limit 60
Writes timing_results.json (drop its measured numbers into the write-up to
replace the latency-model estimate).
"""
import argparse, json, time
import pandas as pd
import reference_checking as rc

counters = {"doi": 0, "openalex": 0, "url": 0}

def _wrap():
    """Monkeypatch the module's network entry points to count calls."""
    _csl, _rev, _alive, _meta = (rc.fetch_csl_metadata, rc.reverse_lookup,
                                 rc.check_url_alive, rc.verify_url_via_metatags)
    def csl(doi):
        counters["doi"] += 1; return _csl(doi)
    def rev(*a, **k):
        counters["openalex"] += 1; return _rev(*a, **k)
    def alive(u):
        counters["url"] += 1; return _alive(u)
    def meta(*a, **k):
        counters["url"] += 1; return _meta(*a, **k)
    rc.fetch_csl_metadata, rc.reverse_lookup = csl, rev
    rc.check_url_alive, rc.verify_url_via_metatags = alive, meta

def retrieval_first(extracted):
    """Baseline: always hit OpenAlex first, then confirm a DOI if one was given."""
    res = rc.reverse_lookup(extracted.get("title"), extracted.get("authors"),
                            extracted.get("year"))
    if extracted.get("doi"):
        rc.fetch_csl_metadata(extracted["doi"])   # the confirm call it would still make
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args()
    _wrap()

    df = pd.read_csv(args.dataset).head(args.limit)
    namec = next(c for c in df.columns if c.lower().strip() == "entry name")

    t_full = t_retr = 0.0
    c_full = dict(doi=0, openalex=0, url=0)
    c_retr = dict(doi=0, openalex=0, url=0)
    for ref in df[namec]:
        extracted = rc.metadata(str(ref))             # shared extraction (untimed)
        for k in counters: counters[k] = 0
        t0 = time.perf_counter(); rc.check_metadata(extracted); t_full += time.perf_counter() - t0
        for k in c_full: c_full[k] += counters[k]
        for k in counters: counters[k] = 0
        t0 = time.perf_counter(); retrieval_first(extracted); t_retr += time.perf_counter() - t0
        for k in c_retr: c_retr[k] += counters[k]

    out = {
        "n": int(len(df)),
        "doi_first":      {"wall_s": round(t_full, 2), "calls": c_full},
        "retrieval_first":{"wall_s": round(t_retr, 2), "calls": c_retr},
        "time_saved_s":   round(t_retr - t_full, 2),
        "pct_faster":     round((t_retr - t_full) / max(1e-9, t_retr), 4),
        "openalex_queries_saved": c_retr["openalex"] - c_full["openalex"],
    }
    json.dump(out, open("timing_results.json", "w"), indent=2)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()