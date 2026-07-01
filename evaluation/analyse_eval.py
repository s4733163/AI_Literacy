#!/usr/bin/env python3
"""
analyze_eval.py  --  Turn one batch run into answers for all five questions.

INPUT
    benchmark_dataset.csv          (the answer key)
    benchmark_dataset_checked.xlsx (output of: python reference_checking.py benchmark_dataset.csv)

The winning evidence tier is read straight off the tool's `evidence` column:
    blank            -> DOI tier     (0 OpenAlex queries)
    "page meta tags" -> URL tier     (0 OpenAlex queries)
    "openalex ..."   -> reverse tier (1 OpenAlex query)

RQ1 (hierarchy helps) is derived analytically: a reference resolved at the DOI
tier resolves identically with the URL/reverse tiers switched off; a reference
that needed the reverse tier would fall to 'unverifiable' under DOI-only. So the
ablation curve follows from each reference's actual winning tier.

OUTPUT  eval_stats.json , eval_tables.md
USAGE   python analyze_eval.py benchmark_dataset.csv benchmark_dataset_checked.xlsx
"""
import json, sys
from collections import Counter, defaultdict
import pandas as pd

# Verdicts that count as an evidence-backed resolution (not left for guesswork).
RESOLVED = {"verified", "verified_review", "metadata_mismatch", "doi_not_found"}
# Verdicts that are a hard reject (a false-accusation risk if applied to a real ref).
HARD_REJECT = {"metadata_mismatch", "doi_not_found"}
# Coarse buckets (secondary view only; full 7-verdict detail is always retained).
BUCKET = {
    "verified": "ACCEPT", "verified_review": "REVIEW",
    "metadata_mismatch": "REJECT", "doi_not_found": "REJECT",
    "unverifiable": "ABSTAIN", "url_only": "ABSTAIN",
    "lookup_error": "ERROR", "error": "ERROR",
}
# Per-call latency assumptions for the RQ5 estimate (seconds); override-able.
LAT = {"doi": 0.6, "url": 1.2, "openalex": 0.9}

def tier_of(evidence):
    e = (str(evidence) or "").strip().lower()
    if e == "" or e == "nan":
        return "doi"
    if "meta tag" in e:
        return "url"
    if "openalex" in e:
        return "reverse"
    return "doi"

def load(dataset_csv, checked_xlsx):
    d = pd.read_csv(dataset_csv)
    d.columns = [c.lower().strip() for c in d.columns]
    d = d.rename(columns={"entry id": "entry_id", "entry name": "entry_name"})
    c = pd.read_excel(checked_xlsx)
    c.columns = [c_.lower().strip() for c_ in c.columns]
    c = c[["entry_id", "verdict", "evidence"]].copy()
    c["tier"] = c["evidence"].map(tier_of)
    m = d.merge(c, on="entry_id", how="inner", validate="one_to_one")
    m["bucket"] = m["verdict"].map(BUCKET).fillna("ERROR")
    return m

# ---------------------------------------------------------------------------
def rq1_hierarchy(m):
    """Resolution & false-accusation rate as tiers are switched on cumulatively."""
    N = len(m)
    strategies = {
        "DOI-only":          {"doi"},
        "DOI+URL":           {"doi", "url"},
        "Full (DOI+URL+rev)":{"doi", "url", "reverse"},
    }
    rows = {}
    for name, tiers in strategies.items():
        # A ref is handled only if its winning tier is enabled in this strategy.
        handled = m[m["tier"].isin(tiers)]
        resolved = handled[handled["verdict"].isin(RESOLVED)]
        # False accusation: a REAL ref given a hard-reject verdict.
        false_acc = handled[(handled["label"] == "real") &
                            (handled["verdict"].isin(HARD_REJECT))]
        rows[name] = {
            "resolution_rate": round(len(resolved) / N, 4),
            "resolved_n": int(len(resolved)),
            "unresolved_n": int(N - len(resolved)),
            "false_accusation_rate": round(len(false_acc) / max(1, (m["label"] == "real").sum()), 4),
            "false_accusation_n": int(len(false_acc)),
        }
    delta = rows["Full (DOI+URL+rev)"]["resolution_rate"] - rows["DOI-only"]["resolution_rate"]
    return {"by_strategy": rows, "full_minus_doi_only": round(delta, 4), "N": N}

def rq2_coverage(m):
    """Where verified references were resolved (DOI / URL / reverse)."""
    ver = m[m["verdict"].isin({"verified", "verified_review"})]
    dist = Counter(ver["tier"])
    total = max(1, len(ver))
    return {
        "verified_n": int(len(ver)),
        "by_tier_n": {k: int(v) for k, v in dist.items()},
        "by_tier_pct": {k: round(v / total, 4) for k, v in dist.items()},
        "all_checked_by_tier_n": {k: int(v) for k, v in Counter(m["tier"]).items()},
    }

def rq3_errors(m):
    """error_type (ground truth) x verdict (observed) -- the detailed mapping."""
    ct = pd.crosstab(m["error_type"], m["verdict"])
    matrix = {et: {v: int(ct.loc[et, v]) for v in ct.columns} for et in ct.index}
    # Per-error 'routed as expected?' accuracy vs expected_verdict.
    acc = {}
    for et, g in m.groupby("error_type"):
        ok = (g["verdict"] == g["expected_verdict"]).sum()
        acc[et] = {"n": int(len(g)), "as_expected": int(ok),
                   "rate": round(ok / len(g), 4)}
    overall = (m["verdict"] == m["expected_verdict"]).mean()
    return {"matrix": matrix, "per_error_accuracy": acc,
            "overall_expected_match": round(float(overall), 4),
            "verdict_order": list(ct.columns)}

def rq4_queries(m):
    """DOI-first OpenAlex queries vs a retrieval-first workflow (queries every ref)."""
    N = len(m)
    reverse_n = int((m["tier"] == "reverse").sum())
    doi_first = reverse_n                 # only reverse-tier refs hit OpenAlex
    retrieval_first = N                   # retrieval-first queries OpenAlex for all
    reduction = 1 - doi_first / max(1, retrieval_first)
    return {
        "N": N,
        "resolved_at_doi_tier_n": int((m["tier"] == "doi").sum()),
        "openalex_queries_doi_first": doi_first,
        "openalex_queries_retrieval_first": retrieval_first,
        "query_reduction_rate": round(reduction, 4),
        "queries_saved": retrieval_first - doi_first,
    }

def rq5_cost_estimate(m, lat=LAT):
    """Latency-model estimate of time saved vs retrieval-first.
    (Replace with measured numbers from run_timing.py for the final figure.)"""
    N = len(m)
    # DOI-first: each ref pays its own winning-tier latency (+DOI confirm on reverse hits).
    t_doi_first = 0.0
    for tier in m["tier"]:
        if tier == "doi":
            t_doi_first += lat["doi"]
        elif tier == "url":
            t_doi_first += lat["url"]
        else:
            t_doi_first += lat["openalex"] + lat["doi"]  # search then confirm
    # Retrieval-first: OpenAlex search for EVERY ref, then DOI confirm where available.
    t_retr_first = N * lat["openalex"] + (m["tier"] == "doi").sum() * lat["doi"]
    saved = t_retr_first - t_doi_first
    return {
        "assumptions_seconds_per_call": lat,
        "est_time_doi_first_s": round(t_doi_first, 1),
        "est_time_retrieval_first_s": round(t_retr_first, 1),
        "est_time_saved_s": round(saved, 1),
        "est_pct_faster": round(saved / max(1e-9, t_retr_first), 4),
        "note": "Latency-model estimate; run_timing.py yields measured wall-clock.",
    }

def composition(m):
    return {
        "n": int(len(m)),
        "real": int((m["label"] == "real").sum()),
        "fake": int((m["label"] == "fake").sum()),
        "by_error_type": {k: int(v) for k, v in Counter(m["error_type"]).items()},
        "bucket_distribution": {k: int(v) for k, v in Counter(m["bucket"]).items()},
        "verdict_distribution": {k: int(v) for k, v in Counter(m["verdict"]).items()},
    }

# ---------------------------------------------------------------------------
def tables_md(stats):
    L = []
    L.append("# Evaluation results (tables)\n")
    c = stats["composition"]
    L.append(f"**Dataset:** {c['n']} references "
             f"({c['real']} real / {c['fake']} fake).\n")

    L.append("\n## RQ1 - Does the hierarchy improve verification?\n")
    L.append("| Strategy | Resolution rate | Resolved | Unresolved | False-accusation rate |")
    L.append("|---|---|---|---|---|")
    for s, v in stats["rq1_hierarchy"]["by_strategy"].items():
        L.append(f"| {s} | {v['resolution_rate']:.1%} | {v['resolved_n']} | "
                 f"{v['unresolved_n']} | {v['false_accusation_rate']:.1%} |")
    L.append(f"\nFull hierarchy resolves "
             f"{stats['rq1_hierarchy']['full_minus_doi_only']:.1%} more references than DOI-only.\n")

    L.append("\n## RQ2 - How often via DOI / URL / reverse lookup?\n")
    r2 = stats["rq2_coverage"]
    L.append("| Tier | Verified refs | Share |")
    L.append("|---|---|---|")
    for t in ["doi", "url", "reverse"]:
        n = r2["by_tier_n"].get(t, 0); p = r2["by_tier_pct"].get(t, 0)
        L.append(f"| {t} | {n} | {p:.1%} |")

    L.append("\n## RQ3 - How accurately are different errors identified?\n")
    r3 = stats["rq3_errors"]
    L.append(f"Overall match to expected verdict: **{r3['overall_expected_match']:.1%}**.\n")
    L.append("| Error type | n | Routed as expected | Rate |")
    L.append("|---|---|---|---|")
    for et, v in sorted(r3["per_error_accuracy"].items()):
        L.append(f"| {et} | {v['n']} | {v['as_expected']} | {v['rate']:.1%} |")

    L.append("\n## RQ4 - Query reduction from DOI-first\n")
    r4 = stats["rq4_queries"]
    L.append(f"- OpenAlex queries, retrieval-first: **{r4['openalex_queries_retrieval_first']}** "
             f"(one per reference)")
    L.append(f"- OpenAlex queries, DOI-first: **{r4['openalex_queries_doi_first']}** "
             f"(only the {r4['openalex_queries_doi_first']} reverse-tier refs)")
    L.append(f"- Reduction: **{r4['query_reduction_rate']:.1%}** "
             f"({r4['queries_saved']} queries saved)\n")

    L.append("\n## RQ5 - Estimated time saved vs retrieval-first\n")
    r5 = stats["rq5_cost_estimate"]
    L.append(f"- Retrieval-first (est.): {r5['est_time_retrieval_first_s']} s")
    L.append(f"- DOI-first (est.): {r5['est_time_doi_first_s']} s")
    L.append(f"- Saved: **{r5['est_time_saved_s']} s ({r5['est_pct_faster']:.1%} faster)**")
    L.append(f"\n_{r5['note']}_\n")
    return "\n".join(L)

def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    m = load(sys.argv[1], sys.argv[2])
    stats = {
        "composition": composition(m),
        "rq1_hierarchy": rq1_hierarchy(m),
        "rq2_coverage": rq2_coverage(m),
        "rq3_errors": rq3_errors(m),
        "rq4_queries": rq4_queries(m),
        "rq5_cost_estimate": rq5_cost_estimate(m),
    }
    with open("eval_stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    with open("eval_tables.md", "w") as f:
        f.write(tables_md(stats))
    m.to_csv("eval_merged.csv", index=False)
    print("Wrote eval_stats.json, eval_tables.md, eval_merged.csv")
    print(f"  RQ1 full vs DOI-only: +{stats['rq1_hierarchy']['full_minus_doi_only']:.1%} resolution")
    print(f"  RQ4 query reduction: {stats['rq4_queries']['query_reduction_rate']:.1%}")
    print(f"  RQ3 expected-match: {stats['rq3_errors']['overall_expected_match']:.1%}")

if __name__ == "__main__":
    main()