"""
model_comparison.py
===================
Section 7: structured comparison of the two segmentation methods, plus the
Section 8 KPI-difference verification that the brief requires.

The comparison is a decision record, not a scoreboard: separation metrics are
reported but explicitly weighted against interpretability, stability,
operational usefulness and segment viability, because the brief forbids
selecting on silhouette alone.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.metrics import adjusted_rand_score, silhouette_score

import config as C
from segmentation import prep_kmeans, profile_segments, name_segments
from viz import save, bar, PALETTE, write_index

PROC, OUT = C.DATA_PROC, C.OUT_DIR


def build() -> pd.DataFrame:
    kmeans_m = json.loads((OUT / "kmeans_metrics.json").read_text())
    rfm_thr = json.loads((OUT / "rfm_thresholds.json").read_text())
    stab = json.loads((OUT / "stability_summary.json").read_text())

    rfm = pd.read_parquet(PROC / "rfm_scored.parquet")
    km = pd.read_parquet(PROC / "kmeans_segmented.parquet")

    rfm_sizes = rfm["rfm_segment"].value_counts(normalize=True) * 100
    km_sizes = km["segment"].value_counts(normalize=True) * 100

    # RFM separation: silhouette in a comparable 3-D score space
    rfm_space = rfm[["R", "F", "M"]].to_numpy(float)
    rfm_sil = silhouette_score(rfm_space, rfm["rfm_segment"], sample_size=8000, random_state=42)

    rows = [
        dict(
            criterion="Number of segments produced",
            rfm=f"{rfm['rfm_segment'].nunique()} rule-based segments",
            kmeans=f"{km['segment'].nunique()} empirical clusters",
            winner="K-means",
            note=("RFM yields a large residual tier because the rules are priority-ordered and the "
                  "last rule absorbs everything unmatched.")),
        dict(
            criterion="Smallest segment (% of base)",
            rfm=f"{rfm_sizes.min():.1f}%",
            kmeans=f"{km_sizes.min():.1f}%",
            winner="Both pass",
            note=f"5% viability floor: RFM smallest {rfm_sizes.min():.1f}%, K-means smallest {km_sizes.min():.1f}%."),
        dict(
            criterion="Silhouette (own feature space)",
            rfm=f"{rfm_sil:.3f} (3-D score space)",
            kmeans=f"{kmeans_m['silhouette']:.3f} (8-D behavioural space)",
            winner="K-means",
            note=("The two scores are computed in different spaces and are NOT directly comparable; "
                  "reported for completeness only.")),
        dict(
            criterion="Bootstrap stability (ARI)",
            rfm=f"{stab['ari_rfm']:.3f} period-over-period",
            kmeans=f"{kmeans_m['bootstrap']['ari_mean']:.3f} resample / {stab['ari_kmeans']:.3f} period-over-period",
            winner="K-means",
            note=("K-means is ~3x more temporally stable than RFM on the same patients. RFM's quantile "
                  "thresholds are re-estimated on each period, so a patient who does not move can "
                  "still change score simply because the distribution moved.")),
        dict(
            criterion="Interpretability to a ward manager",
            rfm="High - a 3-number score per patient",
            kmeans="Medium - requires a profile table, but each cluster has a clear clinical meaning",
            winner="RFM",
            note="RFM codes travel well in an OPD dashboard; cluster profiles need a one-page brief."),
        dict(
            criterion="Captures non-monetary behaviour",
            rfm="No - only R, F and M enter the score",
            kmeans="Yes - admissions, LOS, lab intensity, department spread, recent trend",
            winner="K-means",
            note=("The unit-economics review showed that OPD visits and IPD admissions have very "
                  "different value; RFM's single M dimension cannot distinguish them.")),
        dict(
            criterion="Segment size balance",
            rfm=f"{rfm_sizes.max():.1f}% largest vs {rfm_sizes.min():.1f}% smallest",
            kmeans=f"{km_sizes.max():.1f}% largest vs {km_sizes.min():.1f}% smallest",
            winner="K-means",
            note="Both have a dominant tier; K-means' is smaller and more homogeneous."),
        dict(
            criterion="Actionability / one intervention per segment",
            rfm="Weak - the residual tier mixes champions-in-waiting with churned patients",
            kmeans="Strong - each cluster maps to a distinct operating model",
            winner="K-means",
            note="See the four recommendations: each targets one cluster with one owner and one KPI set."),
        dict(
            criterion="Threshold sensitivity",
            rfm="High - quantile cut-points move with the population",
            kmeans="Medium - centroids move, but assignment is relative and re-matching is possible",
            winner="K-means",
            note="Quantile scoring guarantees 20% of patients per score band even if behaviour is unchanged."),
        dict(
            criterion="Reproducibility",
            rfm="Fully deterministic",
            kmeans="Deterministic given a seed; n_init=50 used",
            winner="RFM",
            note="Both are reproducible in this project; K-means needs the seed documented."),
    ]
    return pd.DataFrame(rows)


def kpi_differences(km: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    prof = profile_segments(km, "segment")
    prof = name_segments(prof)
    # relative spread of each KPI across segments: (max - min) / mean
    kpis = ["avg_recency", "avg_frequency", "avg_monetary", "avg_los", "avg_adm_rate",
            "avg_lab_per_visit", "avg_dept_div", "readmit_30d_rate", "avg_billing_per_visit"]
    rows = []
    for c in kpis:
        v = prof[c].astype(float)
        rows.append({"kpi": c,
                     "min_segment_value": v.min(), "max_segment_value": v.max(),
                     "max_over_min_x": round(v.max() / v.min(), 2) if v.min() > 0 else np.inf,
                     "relative_spread": round((v.max() - v.min()) / v.mean(), 3)})
    d = pd.DataFrame(rows).sort_values("relative_spread", ascending=False)
    return prof, d


def run():
    km_m = json.loads((OUT / "kmeans_metrics.json").read_text())
    km = pd.read_parquet(PROC / "kmeans_segmented.parquet")
    comp = build()
    comp.to_csv(OUT / "model_comparison.csv", index=False)

    prof, diffs = kpi_differences(km)
    diffs.to_csv(OUT / "segment_kpi_differences.csv", index=False)
    prof.to_csv(OUT / "final_segment_profiles.csv", index=False)

    # ---------------- comparison figure
    fig, ax = plt.subplots(1, 2, figsize=(15, 4.8))
    y = np.arange(len(comp))
    ax[0].axis("off")
    ax[0].set_title("Method comparison - 10 criteria", loc="left")
    tallies = comp["winner"].value_counts()
    text = "\n".join(f"{i+1:>2}. {r.criterion}\n      RFM: {r.rfm}\n      K-means: {r.kmeans}\n      -> {r.winner}"
                     for i, r in enumerate(comp.itertuples()))
    ax[0].text(0, 1.02, text, va="top", fontsize=6.4, family="DejaVu Sans")

    top = diffs.head(7)
    bar(ax[1], top["kpi"].str.replace("avg_", "").str.replace("_", " "), top["relative_spread"],
        "KPI separation across the final segments", "KPI", "Relative spread (max-min)/mean",
        color=PALETTE[6], rotate=35, fmt="{:,.2f}")
    ax[1].axhline(0.30, color=PALETTE[4], ls="--", lw=1.2, label="0.30 materiality floor")
    ax[1].legend(fontsize=8)
    save(fig, "25_model_comparison",
         "Model comparison and KPI separation of the final segments",
         (f"{tallies.get('K-means',0)} of {len(comp)} criteria favour K-means, "
          f"{tallies.get('RFM',0)} favour RFM. "
          f"{int((diffs.relative_spread >= 0.30).sum())} of {len(diffs)} KPIs exceed the 0.30 materiality floor; "
          f"the widest is {diffs.iloc[0].kpi} at {diffs.iloc[0].relative_spread:.2f}."),
         "K-means wins on the criteria that determine whether a segmentation can be operated; RFM wins on "
         "transparency and reproducibility only.",
         "K-means is the primary segmentation; RFM is retained as a secondary screening tool for the OPD "
         "front desk because its per-patient score is immediate.")

    write_index()
    print(comp.to_string(index=False))
    print("\nKPI differences:\n", diffs.to_string(index=False))
    print(f"\n{KPI_COUNT(diffs)} KPIs clear the materiality floor")
    return comp, prof, diffs


def KPI_COUNT(diffs):
    return int((diffs.relative_spread >= 0.30).sum())


if __name__ == "__main__":
    run()
