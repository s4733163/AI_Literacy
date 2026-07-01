#!/usr/bin/env python3
"""
make_eval_charts.py  --  Four figures from eval_stats.json into ./figures/.
    fig1_hierarchy.png    RQ1  resolution rate across ablations
    fig2_coverage.png     RQ2  evidence-tier coverage of verified refs
    fig3_error_matrix.png RQ3  error_type x verdict heatmap
    fig4_efficiency.png   RQ4+5 query + time, DOI-first vs retrieval-first
USAGE  python make_eval_charts.py            (reads eval_stats.json, eval_merged.csv)
"""
import json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

NAVY, TEAL, AMBER, RED, GREY = "#1F4E79", "#2A9D8F", "#E9C46A", "#E76F51", "#9AA5B1"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                     "axes.spines.top": False, "axes.spines.right": False})

os.makedirs("figures", exist_ok=True)
S = json.load(open("eval_stats.json"))

# ---- fig1: RQ1 hierarchy ablation ----
r1 = S["rq1_hierarchy"]["by_strategy"]
names = list(r1.keys())
res = [r1[n]["resolution_rate"] * 100 for n in names]
fa = [r1[n]["false_accusation_rate"] * 100 for n in names]
fig, ax = plt.subplots(figsize=(7, 4.2))
x = np.arange(len(names))
bars = ax.bar(x, res, color=[GREY, TEAL, NAVY], width=0.6)
ax.plot(x, fa, "o-", color=RED, lw=2, label="False-accusation rate")
for i, v in enumerate(res):
    ax.text(i, v + 1.2, f"{v:.0f}%", ha="center", fontweight="bold")
ax.set_xticks(x); ax.set_xticklabels(names)
ax.set_ylabel("References resolved (%)"); ax.set_ylim(0, 105)
ax.set_title("RQ1  Hierarchical strategy raises resolution, no false accusations")
ax.legend(loc="lower right", frameon=False)
plt.tight_layout(); plt.savefig("figures/fig1_hierarchy.png", dpi=150); plt.close()

# ---- fig2: RQ2 coverage ----
r2 = S["rq2_coverage"]["by_tier_n"]
order = ["doi", "url", "reverse"]
vals = [r2.get(t, 0) for t in order]
labels = ["DOI", "URL meta", "Reverse\n(OpenAlex)"]
fig, ax = plt.subplots(figsize=(5.6, 4.4))
w = ax.bar(labels, vals, color=[NAVY, TEAL, AMBER], width=0.6)
tot = max(1, sum(vals))
for i, v in enumerate(vals):
    ax.text(i, v + 0.6, f"{v}\n({v/tot:.0%})", ha="center", fontweight="bold")
ax.set_ylabel("Verified references"); ax.set_ylim(0, max(vals) * 1.25 + 1)
ax.set_title("RQ2  Which tier resolved each verified reference")
plt.tight_layout(); plt.savefig("figures/fig2_coverage.png", dpi=150); plt.close()

# ---- fig3: RQ3 error_type x verdict heatmap ----
m = pd.read_csv("eval_merged.csv")
ct = pd.crosstab(m["error_type"], m["verdict"])
# order rows so 'none' (reals) is on top
rows = (["none"] if "none" in ct.index else []) + [r for r in ct.index if r != "none"]
ct = ct.loc[rows]
fig, ax = plt.subplots(figsize=(8.6, 5.2))
data = ct.values
im = ax.imshow(data, cmap="Blues", aspect="auto")
ax.set_xticks(range(len(ct.columns))); ax.set_xticklabels(ct.columns, rotation=35, ha="right")
ax.set_yticks(range(len(ct.index))); ax.set_yticklabels(ct.index)
for i in range(data.shape[0]):
    for j in range(data.shape[1]):
        if data[i, j]:
            ax.text(j, i, data[i, j], ha="center", va="center",
                    color="white" if data[i, j] > data.max() * 0.5 else NAVY,
                    fontweight="bold")
ax.set_xlabel("Tool verdict (observed)"); ax.set_ylabel("Error type (ground truth)")
ax.set_title("RQ3  Error type \u2192 verdict mapping")
plt.tight_layout(); plt.savefig("figures/fig3_error_matrix.png", dpi=150); plt.close()

# ---- fig4: RQ4+RQ5 efficiency ----
r4, r5 = S["rq4_queries"], S["rq5_cost_estimate"]
fig, (axA, axB) = plt.subplots(1, 2, figsize=(9.4, 4.2))
axA.bar(["Retrieval-first", "DOI-first"],
        [r4["openalex_queries_retrieval_first"], r4["openalex_queries_doi_first"]],
        color=[RED, NAVY], width=0.6)
for i, v in enumerate([r4["openalex_queries_retrieval_first"], r4["openalex_queries_doi_first"]]):
    axA.text(i, v + 1, str(v), ha="center", fontweight="bold")
axA.set_ylabel("OpenAlex queries")
axA.set_title(f"RQ4  Queries  (\u2212{r4['query_reduction_rate']:.0%})")
axB.bar(["Retrieval-first", "DOI-first"],
        [r5["est_time_retrieval_first_s"], r5["est_time_doi_first_s"]],
        color=[RED, NAVY], width=0.6)
for i, v in enumerate([r5["est_time_retrieval_first_s"], r5["est_time_doi_first_s"]]):
    axB.text(i, v + 2, f"{v:.0f}s", ha="center", fontweight="bold")
axB.set_ylabel("Estimated time (s)")
axB.set_title(f"RQ5  Time  (\u2212{r5['est_pct_faster']:.0%}, estimate)")
plt.tight_layout(); plt.savefig("figures/fig4_efficiency.png", dpi=150); plt.close()

print("Wrote figures/fig1_hierarchy.png, fig2_coverage.png, fig3_error_matrix.png, fig4_efficiency.png")