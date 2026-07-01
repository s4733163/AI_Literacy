#!/usr/bin/env python3
"""
diagnose_reverse.py  --  Explain why the reverse-lookup tier yielded nothing.

It (1) reads your checked output and shows the ACTUAL verdict + note for the
references that were supposed to go through reverse lookup, and (2) pings
OpenAlex directly so you can see whether the API is reachable/answering.

USAGE
    python diagnose_reverse.py benchmark_dataset.csv benchmark_dataset_checked.xlsx
"""
import sys, json
import pandas as pd

REVERSE_ERRORS = {"fabricated_nodoi", "lookalike_title", "url_dead"}

def part1(dataset_csv, checked_xlsx):
    d = pd.read_csv(dataset_csv); d.columns = [c.lower().strip() for c in d.columns]
    d = d.rename(columns={"entry id": "entry_id", "entry name": "entry_name"})
    c = pd.read_excel(checked_xlsx); c.columns = [x.lower().strip() for x in c.columns]
    m = d.merge(c[["entry_id", "verdict", "evidence", "note"]], on="entry_id", how="inner")

    rev = m[(m["expected_tier"] == "reverse") | (m["error_type"].isin(REVERSE_ERRORS))]
    print(f"\n=== Reverse-dependent references: {len(rev)} ===")
    print("\nActual verdicts they received:")
    print(rev["verdict"].value_counts().to_string())
    print("\nSample notes (this tells you the ROOT CAUSE):")
    for _, r in rev.head(6).iterrows():
        print(f"  [{r['error_type']:>18}] {r['verdict']:<14} | {str(r['note'])[:90]}")

    if (rev["verdict"] == "lookup_error").any():
        print("\n>>> At least one 'lookup_error' -> OpenAlex requests are FAILING.")
        print(">>> Read the note above: 'Could not reach OpenAlex: <reason>' names it")
        print(">>> (DNS/connection = blocked egress; 403/429 = rate/policy; 400 = bad query).")
    elif (rev["verdict"] == "unverifiable").all() and len(rev):
        print("\n>>> They ARE 'unverifiable' -> reverse lookup WORKED; the tier just reads")
        print(">>> as blank because reverse_lookup only tags evidence on a successful match.")

def part2():
    print("\n=== Live OpenAlex connectivity test ===")
    try:
        import requests
    except Exception as e:
        print("requests not importable:", e); return
    url = "https://api.openalex.org/works"
    title = "Deep Residual Learning for Image Recognition"
    try:
        r = requests.get(url, params={"filter": "title.search:" + title,
                                      "per-page": 3, "mailto": "vsvarun@utas.edu.au"},
                         timeout=15)
        print("HTTP status:", r.status_code)
        if r.status_code == 200:
            n = len(r.json().get("results", []))
            print(f"OK - OpenAlex reachable, returned {n} results.")
            print("If the tool still fails, the problem is per-title (e.g. a 400 on")
            print("special characters), not connectivity - check the notes in part 1.")
        else:
            print("Non-200 -> this is your failure. Body (first 200 chars):")
            print("  ", r.text[:200])
    except Exception as e:
        print("REQUEST FAILED:", type(e).__name__, str(e)[:160])
        print(">>> OpenAlex is unreachable from this environment. Allow egress to")
        print(">>> api.openalex.org, or run where it is reachable.")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        part1(sys.argv[1], sys.argv[2])
    else:
        print("(skipping part 1 - pass dataset.csv and checked.xlsx to enable it)")
    part2()