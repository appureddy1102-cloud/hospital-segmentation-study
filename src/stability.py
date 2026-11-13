"""
stability.py
============
Section 10: segment stability and migration.

Approach
--------
1. Split the 36-month window into two 18-month periods.
2. Recompute ALL patient features independently in each period, each with its
   own reference date (so recency is measured against the end of that period,
   not against the end of the study - otherwise period 1 recency would be
   contaminated by period 2 activity).
3. Re-fit K-means (same feature set, same k, same scaler specification) in each
   period independently. Cluster numbering is meaningless across fits, so the
   period-2 clusters are matched to period-1 clusters by profile using the
   Hungarian algorithm on standardised centroid profiles - never by label id.
4. For patients present in BOTH periods, build the migration matrix, compute
   retention, ARI and the stability of each segment.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import adjusted_rand_score

import config as C
from features import build_patient_features
from segmentation import (KMEANS_FEATURES, fit_kmeans, prep_kmeans,
                          profile_segments, name_segments)
from viz import save, PALETTE, write_index

PROC, OUT, FIG = C.DATA_PROC, C.OUT_DIR, C.FIG_DIR


def build_period_features(pat, opd, adm, lab, bill):
    specs = {
        "P1": (C.PERIOD1_START, C.PERIOD1_END,
               (pd.Timestamp(C.PERIOD1_END) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")),
        "P2": (C.PERIOD2_START, C.PERIOD2_END,
               (pd.Timestamp(C.PERIOD2_END) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")),
    }
    out = {}
    for name, (s, e, ref) in specs.items():
        f = build_patient_features(pat, opd, adm, lab, bill, s, e, ref, name)
        out[name] = f
        print(f"  {name}: {s} to {e} (ref {ref}) -> {len(f):,} patients with activity")
    return out


def fit_period(f, label, k):
    X, Xs, _ = prep_kmeans(f)
    km, lab = fit_kmeans(Xs, k)
    d = f.copy()
    d["cluster"] = lab
    prof = profile_segments(d, "cluster")
    prof = name_segments(prof)
    d["segment"] = d["cluster"].map(prof.set_index("cluster")["segment_name"])
    return d, prof, km, Xs


def match_clusters(prof1: pd.DataFrame, prof2: pd.DataFrame) -> dict:
    """
    Match period-2 clusters onto period-1 clusters by PROFILE using the
    Hungarian algorithm on the correlation distance between standardised
    centroid profiles.

    Two design choices are deliberate:

    * CORRELATION distance (1 - Pearson r), not raw Euclidean distance. The two
      periods have materially different intensity levels - period 2 is more
      acute-weighted because the inpatient-heavy cohort grew - so a Euclidean
      comparison would pair clusters by magnitude rather than by shape and
      could match a dormant period-2 cluster to a high-acuity period-1 cluster.
      Correlation distance compares the *shape* of each cluster's profile across
      eight KPIs, which is the property that defines a segment's identity.
    * PROFILE shape, not cluster id. Cluster numbering is meaningless across
      independent fits and is never assumed to persist.
    """
    cols = ["avg_recency", "avg_frequency", "avg_monetary", "avg_adm_rate",
            "avg_los", "avg_lab_per_visit", "avg_dept_div", "avg_billing_per_visit"]
    A = prof1.set_index("cluster")[cols].astype(float)
    B = prof2.set_index("cluster")[cols].astype(float)
    mu = pd.concat([A, B]).mean()
    sd = pd.concat([A, B]).std().replace(0, 1)
    Az = ((A - mu) / sd).values
    Bz = ((B - mu) / sd).values

    cost = np.zeros((len(Az), len(Bz)))
    for i in range(len(Az)):
        for j in range(len(Bz)):
            if Az[i].std() == 0 or Bz[j].std() == 0:
                cost[i, j] = 1.0
            else:
                cost[i, j] = 1.0 - np.corrcoef(Az[i], Bz[j])[0, 1]
    r, c = linear_sum_assignment(cost)
    return {int(B.index[j]): int(A.index[i]) for i, j in zip(r, c)}


def run(k=None):
    pat = pd.read_parquet(PROC / "patients_clean.parquet")
    opd = pd.read_parquet(PROC / "opd_clean.parquet")
    adm = pd.read_parquet(PROC / "admissions_clean.parquet")
    lab = pd.read_parquet(PROC / "lab_clean.parquet")
    bill = pd.read_parquet(PROC / "billing_clean.parquet")

    metrics = json.loads((OUT / "kmeans_metrics.json").read_text())
    k = int(metrics["k"]) if k is None else k
    print(f"Stability analysis at k={k}")

    pf = build_period_features(pat, opd, adm, lab, bill)
    d1, prof1, km1, Xs1 = fit_period(pf["P1"], "P1", k)
    d2, prof2, km2, Xs2 = fit_period(pf["P2"], "P2", k)

    mapping = match_clusters(prof1, prof2)
    print("  period-2 cluster -> period-1 cluster mapping:", mapping)

    # remap period 2 to period 1's segment names
    name1 = prof1.set_index("cluster")["segment_name"].to_dict()
    d2["segment_p1_space"] = d2["cluster"].map(mapping).map(name1)

    both = set(d1["patient_id"]) & set(d2["patient_id"])
    print(f"  patients active in P1: {len(d1):,} | P2: {len(d2):,} | both: {len(both):,} "
          f"({100*len(both)/len(set(d1.patient_id)|set(d2.patient_id)):.1f}% of the union)")
    m1 = d1[d1.patient_id.isin(both)].set_index("patient_id")["segment"].rename("P1")
    m2 = d2[d2.patient_id.isin(both)].set_index("patient_id")["segment_p1_space"].rename("P2")
    mig = pd.concat([m1, m2], axis=1).dropna()
    mig = mig[mig.P2.notna()]

    matrix = pd.crosstab(mig["P1"], mig["P2"])
    matrix = matrix.reindex(index=prof1["segment_name"], columns=prof1["segment_name"]).fillna(0).astype(int)
    retention = (np.diag(matrix) / matrix.sum(axis=1).replace(0, np.nan) * 100).round(1)
    counts = matrix.sum(axis=1)
    ari = adjusted_rand_score(mig["P1"], mig["P2"])

    # ------------------------------------------------------------------
    # Period-over-period change per segment.
    # Both periods must be expressed in ONE naming vocabulary, otherwise a
    # segment that is stable in behaviour but re-named by the naming rules in
    # period 2 would look like it disappeared. We therefore:
    #   * profile period 2 using the period-1 -> period-2 cluster mapping, so
    #     every period-2 patient carries the period-1 segment name;
    #   * compute period-2 statistics on that harmonised label.
    # ------------------------------------------------------------------
    d2h = d2.copy()
    d2h["segment_h"] = d2h["segment_p1_space"]
    both = set(d1["patient_id"]) & set(d2["patient_id"])
    b1 = d1[d1.patient_id.isin(both)].set_index("patient_id")
    b2 = d2h[d2h.patient_id.isin(both)].set_index("patient_id").reindex(b1.index)
    p1b = profile_segments(b1.reset_index(), "segment").set_index("segment")
    b2r = b2.reset_index()
    p2b = profile_segments(b2r, "segment_h").set_index("segment_h")
    shared = [s for s in p1b.index if s in p2b.index]
    delta = pd.DataFrame({
        # all statistics are measured on the SAME patients (active in both
        # periods), so growth reflects genuine migration rather than the
        # difference in panel size between the two windows.
        "P1_patients": [int((mig["P1"] == s).sum()) for s in shared],
        "P2_patients": [int((mig["P2"] == s).sum()) for s in shared],
        "P1_avg_monetary": p1b.loc[shared, "avg_monetary"].round(0).values,
        "P2_avg_monetary": p2b.loc[shared, "avg_monetary"].round(0).values,
        "P1_avg_frequency": p1b.loc[shared, "avg_frequency"].round(2).values,
        "P2_avg_frequency": p2b.loc[shared, "avg_frequency"].round(2).values,
        "P1_avg_recency": p1b.loc[shared, "avg_recency"].round(0).values,
        "P2_avg_recency": p2b.loc[shared, "avg_recency"].round(0).values,
    }, index=shared)
    delta["patient_growth_pct"] = (100 * (delta.P2_patients / delta.P1_patients - 1)).round(1)
    delta.index.name = "segment"

    # ------------------------------------------------ migration heatmap
    fig, ax = plt.subplots(1, 2, figsize=(15, 5.4))
    share = matrix.div(matrix.sum(axis=1), axis=0) * 100
    im = ax[0].imshow(share.values, cmap="Blues", vmin=0, vmax=100)
    ax[0].set_xticks(range(len(matrix.columns)))
    ax[0].set_xticklabels(matrix.columns, rotation=25, ha="right", fontsize=8)
    ax[0].set_yticks(range(len(matrix.index)))
    ax[0].set_yticklabels(matrix.index, fontsize=8)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            v = share.values[i, j]
            ax[0].text(j, i, f"{v:.0f}%\n({matrix.values[i,j]:,})", ha="center", va="center",
                       fontsize=7.5, color="white" if v > 55 else "black")
    ax[0].set_xlabel("Segment in period 2 (2023-H2 to 2024)")
    ax[0].set_ylabel("Segment in period 1 (2022 to 2023-H1)")
    ax[0].set_title("Segment migration matrix (row % and patient counts)")
    fig.colorbar(im, ax=ax[0], label="% of period-1 segment")

    r = retention.reindex(prof1["segment_name"])
    bars = ax[1].barh(r.index[::-1], r.values[::-1],
                      color=[PALETTE[6] if v >= 50 else PALETTE[4] for v in r.values[::-1]])
    for b, v, n in zip(bars, r.values[::-1], counts.reindex(r.index).values[::-1]):
        ax[1].text(v, b.get_y() + b.get_height() / 2, f" {v:.1f}% (n={n:,})",
                   va="center", fontsize=8.5)
    ax[1].set_xlim(0, 110)
    ax[1].set_xlabel("Retention: share of the period-1 segment still in the same segment")
    ax[1].set_title("Within-segment retention, period 1 to period 2")
    save(fig, "22_segment_migration",
         "Segment migration and retention between two independent 18-month periods",
         (f"ARI between the two independent segmentations for the {len(mig):,} patients active in both "
          f"periods is {ari:.3f}. Retention ranges {r.min():.1f}% to {r.max():.1f}%; "
          f"off-diagonal migration is {(1 - np.trace(matrix.values)/matrix.values.sum())*100:.1f}% of the cohort."),
         "The high-value segment is far stickier than the dormant segment, which behaves as a revolving door.",
         "Retention investment should be concentrated on the engaged segment where status is defensible; "
         "the dormant segment needs a reactivation programme with a short payback horizon, not a loyalty programme.")

    # ------------------------------------------------ segment size drift
    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    x = np.arange(len(shared))
    w = 0.38
    ax.bar(x - w / 2, delta["P1_patients"], w, label="Period 1 (18 months)", color=PALETTE[0])
    ax.bar(x + w / 2, delta["P2_patients"], w, label="Period 2 (18 months)", color=PALETTE[4])
    ax.set_xticks(x); ax.set_xticklabels(shared, fontsize=8.5)
    ax.set_ylabel("Patients in segment"); ax.legend()
    ax.set_title("Segment size shift, patients active in both periods")
    for i, (a, b) in enumerate(zip(delta["P1_patients"], delta["P2_patients"])):
        ax.text(i, max(a, b), f"{100*(b/a-1):+.1f}%", ha="center", va="bottom", fontsize=8)
    save(fig, "23_segment_size_drift", "Segment size drift between the two periods",
         "; ".join(f"{s}: {int(r.P1_patients):,} -> {int(r.P2_patients):,} ({r.patient_growth_pct:+.1f}%)"
                   for s, r in delta.iterrows()) + ".",
         "Growth is not uniform: the engaged segment compounds while the dormant pool also grows as one-visit patients accumulate.",
         "Left unmanaged, the dormant pool becomes the dominant cost of the panel; the reactivation programme in the recommendations targets exactly this drift.")

    # ------------------------------------------------ RFM stability for contrast
    from segmentation import apply_rfm_rules, rfm_score
    r1 = pd.read_parquet(PROC / "rfm_scored.parquet")[["patient_id", "rfm_segment"]]
    rf1 = apply_rfm_rules(rfm_score(pf["P1"])[0])
    rf2 = apply_rfm_rules(rfm_score(pf["P2"])[0])
    j1 = rf1.set_index("patient_id")["rfm_segment"].rename("P1")
    j2 = rf2.set_index("patient_id")["rfm_segment"].rename("P2")
    rfm_mig = pd.concat([j1, j2], axis=1).dropna()
    rfm_ari = adjusted_rand_score(rfm_mig["P1"], rfm_mig["P2"])
    rfm_matrix = pd.crosstab(rfm_mig["P1"], rfm_mig["P2"])
    rfm_retention = (np.diag(rfm_matrix.reindex(index=rfm_matrix.index, columns=rfm_matrix.index).fillna(0))
                     / rfm_matrix.sum(axis=1).replace(0, np.nan) * 100)

    summary = {
        "k": k,
        "patients_p1": int(len(d1)), "patients_p2": int(len(d2)),
        "patients_both": int(len(mig)),
        "cluster_mapping_p2_to_p1": mapping,
        "ari_kmeans": float(ari),
        "ari_rfm": float(rfm_ari),
        "retention_pct": {k2: float(v) for k2, v in retention.items()},
        "rfm_retention_pct": {k2: float(v) for k2, v in rfm_retention.items()},
        "migration_matrix": matrix.to_dict(),
        "delta": delta.reset_index().rename(columns={"index": "segment"}).to_dict("records"),
        "off_diagonal_pct": float(100 * (1 - np.trace(matrix.values) / matrix.values.sum())),
    }
    matrix.to_csv(OUT / "migration_matrix_kmeans.csv")
    delta.to_csv(OUT / "segment_size_drift.csv", index=False)
    rfm_matrix.to_csv(OUT / "migration_matrix_rfm.csv")
    with open(OUT / "stability_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    d1.to_parquet(PROC / "segments_period1.parquet", index=False)
    d2.to_parquet(PROC / "segments_period2.parquet", index=False)
    write_index()
    print(f"\n  ARI kmeans = {ari:.3f} | ARI RFM = {rfm_ari:.3f}")
    print("  retention:", {k2: round(v, 1) for k2, v in retention.items()})
    return summary


if __name__ == "__main__":
    run()
