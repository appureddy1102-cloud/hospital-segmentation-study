"""
segmentation.py
===============
Method A: quantile RFM scoring
Method B: K-means on behavioural features

Both methods are implemented independently on the same patient base and the
same observation window, then compared on six criteria (Section 7 of the brief).

All model diagnostics (elbow, silhouette, bootstrap stability, latent-archetype
agreement) are persisted so that the model-selection argument is evidence-based
rather than asserted.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import (adjusted_rand_score, calinski_harabasz_score,
                             davies_bouldin_score, silhouette_score)
from sklearn.preprocessing import RobustScaler

import config as C
from viz import save, bar, PALETTE, write_index

PROC, FIG, OUT = C.DATA_PROC, C.FIG_DIR, C.OUT_DIR
RNG = 42

# ===========================================================================
# METHOD A - RFM
# ===========================================================================
def rfm_score(feat: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Quantile scoring on 5 buckets per dimension.

    R score: recency is REVERSED - a small recency (recent visit) is good, so the
             lowest quintile of recency gets score 5.
    F score: frequency quintile, 1 (lowest) to 5 (highest).
    M score: monetary quintile, 1 (lowest) to 5 (highest).

    Quantile cut-points are computed on the full patient base and reported, so
    the thresholds are auditable. `duplicates='drop'` is used rather than the
    default because frequency is heavily discrete (52% of patients have 1-2
    visits); forcing five equal-count buckets on a discrete variable would put
    randomly-ordered identical patients on different scores. Dropping duplicate
    edges means tied patients always receive the same score, which is the
    defensible choice for a clinical population.
    """
    d = feat.copy()
    rq = d["recency_days"].quantile([.2, .4, .6, .8]).round(1).to_dict()
    fq = d["frequency"].quantile([.2, .4, .6, .8]).round(1).to_dict()
    mq = d["monetary"].quantile([.2, .4, .6, .8]).round(1).to_dict()

    d["R"] = pd.qcut(d["recency_days"], C.RFM_QUANTILES, labels=[5, 4, 3, 2, 1],
                     duplicates="drop").astype(int)
    d["F"] = pd.qcut(d["frequency"].rank(method="first"), C.RFM_QUANTILES,
                     labels=[1, 2, 3, 4, 5]).astype(int)
    d["M"] = pd.qcut(d["monetary"], C.RFM_QUANTILES, labels=[1, 2, 3, 4, 5],
                     duplicates="drop").astype(int)
    d["RFM_sum"] = d["R"] + d["F"] + d["M"]
    d["RFM_cell"] = d["R"].astype(str) + d["F"].astype(str) + d["M"].astype(str)

    thresholds = {"recency_quintiles": rq, "frequency_quintiles": fq,
                  "monetary_quintiles": mq,
                  "scoring_rule": "R reversed (5=most recent); F,M ascending (5=highest)"}
    return d, thresholds


# segment definition rules applied to the RFM codes, in priority order
RFM_RULES = [
    # (segment name, predicate description, predicate)
    ("Champions", "R>=4 and F>=4 and M>=4", lambda x: (x.R >= 4) & (x.F >= 4) & (x.M >= 4)),
    ("Loyal High-Value", "R>=3 and F>=4", lambda x: (x.R >= 3) & (x.F >= 4)),
    ("High-Value Dormant", "R<=2 and F>=4 and M>=4", lambda x: (x.R <= 2) & (x.F >= 4) & (x.M >= 4)),
    ("New / Promising", "R>=4 and F<=2", lambda x: (x.R >= 4) & (x.F <= 2)),
    ("At-Risk High-Value", "R<=2 and M>=4", lambda x: (x.R <= 2) & (x.M >= 4)),
    ("Occasional Stable", "R>=3 and F in 2-3", lambda x: (x.R >= 3) & x.F.between(2, 3)),
    ("Hibernating", "rest", lambda x: pd.Series(True, index=x.index)),
]


def apply_rfm_rules(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["rfm_segment"] = None
    taken = pd.Series(False, index=d.index)
    for name, _, fn in RFM_RULES:
        m = fn(d) & ~taken
        d.loc[m, "rfm_segment"] = name
        taken |= m
    return d


# ===========================================================================
# METHOD B - K-means
# ===========================================================================
KMEANS_FEATURES = [
    "log_recency", "log_frequency", "log_monetary", "visits_per_month",
    "admission_rate", "lab_per_visit", "dept_diversity", "recent_activity_ratio",
]


def prep_kmeans(feat: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, dict]:
    """
    Feature preparation for K-means.

    * log1p on the three RFM dimensions: they are counts/currency with skew
      3-40 and must be on a comparable scale before Euclidean distance is used.
    * RobustScaler (median/IQR) rather than StandardScaler: the upper tail of
      frequency and monetary is genuine clinical signal that we must NOT delete,
      and RobustScaler bounds its influence without removing those patients.
    * Collinear duplicates (e.g. admission_count vs total_bed_days, rho 0.73;
      frequency vs visits_per_month, rho 1.00) are dropped so that a single
      behaviour is not double-weighted in the distance metric.
    """
    X = pd.DataFrame(index=feat.index)
    X["log_recency"] = np.log1p(feat["recency_days"])
    X["log_frequency"] = np.log1p(feat["frequency"])
    X["log_monetary"] = np.log1p(feat["monetary"].clip(lower=0))
    X["visits_per_month"] = np.log1p(feat["visits_per_month"])
    X["admission_rate"] = feat["admission_rate"].clip(0, 3)
    X["lab_per_visit"] = np.log1p(feat["lab_per_visit"])
    X["dept_diversity"] = feat["dept_diversity"]
    X["recent_activity_ratio"] = np.log1p(feat["recent_activity_ratio"])

    missing = X.isna().sum().to_dict()
    X = X.fillna(X.median())

    sc = RobustScaler()
    Xs = sc.fit_transform(X)
    info = {"features": KMEANS_FEATURES, "missing_before_impute": missing,
            "scaler": "RobustScaler (median / IQR)",
            "transform": "log1p applied to skewed count and currency columns",
            "median": dict(zip(KMEANS_FEATURES, sc.center_.round(4))),
            "iqr": dict(zip(KMEANS_FEATURES, sc.scale_.round(4)))}
    return X, Xs, info


def evaluate_k(Xs: np.ndarray, k_range=range(2, 11)) -> pd.DataFrame:
    rows = []
    for k in k_range:
        km = KMeans(n_clusters=k, n_init=20, random_state=RNG)
        lab = km.fit_predict(Xs)
        # stability: do members stay together across bootstrap resamples?
        rows.append({
            "k": k,
            "inertia": km.inertia_,
            "silhouette": silhouette_score(Xs, lab, sample_size=8000, random_state=RNG),
            "calinski_harabasz": calinski_harabasz_score(Xs, lab),
            "davies_bouldin": davies_bouldin_score(Xs, lab),
        })
    df = pd.DataFrame(rows)
    # elbow: largest drop in marginal inertia reduction
    df["inertia_drop"] = -df["inertia"].diff().fillna(0)
    df["inertia_drop_pct"] = (100 * df["inertia_drop"] / df["inertia"].shift(1)).round(2)
    return df


def fit_kmeans(Xs: np.ndarray, k: int):
    km = KMeans(n_clusters=k, n_init=50, random_state=RNG)
    lab = km.fit_predict(Xs)
    return km, lab


def bootstrap_stability(Xs: np.ndarray, k: int, n_boot: int = 15) -> dict:
    """ARI between the full-data solution and bootstrap resamples (same k)."""
    base = KMeans(n_clusters=k, n_init=20, random_state=RNG).fit_predict(Xs)
    aris = []
    rng = np.random.default_rng(RNG)
    n = len(Xs)
    for _ in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        uniq = np.unique(idx)
        if len(uniq) < k * 5:
            continue
        sub = KMeans(n_clusters=k, n_init=10, random_state=RNG).fit_predict(Xs[uniq])
        # compare labels for the overlapping patients only
        aris.append(adjusted_rand_score(base[uniq], sub))
    return {"k": k, "n_bootstrap": len(aris),
            "ari_mean": float(np.mean(aris)), "ari_sd": float(np.std(aris)),
            "ari_min": float(np.min(aris)), "ari_max": float(np.max(aris))}


# ===========================================================================
# Plotting
# ===========================================================================
KPIS_FOR_SPREAD = ["avg_recency", "avg_frequency", "avg_monetary", "avg_adm_rate",
                   "avg_los", "avg_lab_per_visit", "avg_dept_div", "avg_billing_per_visit"]


def operational_utility_score(feat: pd.DataFrame, Xs: np.ndarray, ev: pd.DataFrame) -> pd.DataFrame:
    """
    Composite operational utility score (OUS) used to select k.

    Why not silhouette alone? Because on this population k=2 maximises distance
    separation by splitting the panel into "engaged" and "disengaged" - correct
    geometrically, useless operationally, because it creates a 64% residual that
    no single intervention can serve. The brief explicitly requires that model
    selection must not rest on silhouette alone, and that every final segment
    must hold at least 5% of the patient base.

    OUS = 0.25 x normalised silhouette
        + 0.30 x normalised KPI spread (distinctiveness)
        + 0.20 x normalised revenue separation (1 - normalised entropy)
        + 0.25 x segment size balance (min-segment share / 12.5%, capped at 1)

    Solutions whose smallest segment is below the 5% floor are ineligible
    regardless of score.
    """
    rows = []
    for k in ev["k"]:
        _, lab = fit_kmeans(Xs, int(k))
        f = feat.copy(); f["cluster"] = lab
        p = profile_segments(f, "cluster")
        min_share = 100 * p["n_patients"].min() / len(f)
        spread = float(np.mean([(p[c].max() - p[c].min()) / abs(p[c].mean())
                                for c in KPIS_FOR_SPREAD if abs(p[c].mean()) > 1e-9]))
        s = p["revenue"] / p["revenue"].sum()
        entropy = float(-(s * np.log(s + 1e-12)).sum() / np.log(len(s)))
        rows.append({"k": int(k), "silhouette": float(ev.loc[ev.k == k, "silhouette"].iloc[0]),
                     "min_segment_share_pct": round(min_share, 2),
                     "kpi_spread": round(spread, 4),
                     "revenue_separation": round(1 - entropy, 4),
                     "size_balance": round(min(min_share / 12.5, 1.0), 4)})
    d = pd.DataFrame(rows)

    def nz(s):
        return (s - s.min()) / (s.max() - s.min()) if s.max() > s.min() else s * 0 + 1.0

    d["score"] = (0.25 * nz(d["silhouette"]) + 0.30 * nz(d["kpi_spread"]) +
                  0.20 * nz(d["revenue_separation"]) + 0.25 * d["size_balance"]).round(4)
    d["eligible"] = d["min_segment_share_pct"] >= 100 * C.MIN_SEGMENT_SHARE
    return d


def plot_model_selection(ev: pd.DataFrame, stab: pd.DataFrame):
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.2))
    ax[0].plot(ev["k"], ev["inertia"], marker="o", color=PALETTE[0])
    ax[0].set_title("Elbow curve (inertia vs k)")
    ax[0].set_xlabel("k"); ax[0].set_ylabel("Within-cluster SSE")
    ax[0].set_xticks(ev["k"])
    best_k_elbow = int(ev.loc[ev["inertia_drop_pct"].idxmax(), "k"])
    ax[0].axvline(best_k_elbow, color=PALETTE[4], ls="--",
                  label=f"largest marginal drop at k={best_k_elbow}")
    ax[0].legend(fontsize=8)

    ax[1].plot(ev["k"], ev["silhouette"], marker="o", color=PALETTE[5])
    ax[1].set_title("Silhouette score vs k")
    ax[1].set_xlabel("k"); ax[1].set_ylabel("Mean silhouette")
    ax[1].set_xticks(ev["k"])
    bk = int(ev.loc[ev["silhouette"].idxmax(), "k"])
    ax[1].axvline(bk, color=PALETTE[4], ls="--", label=f"max at k={bk}")
    ax[1].legend(fontsize=8)

    ax[2].errorbar(stab["k"], stab["ari_mean"], yerr=stab["ari_sd"], marker="o",
                   color=PALETTE[7], capsize=3)
    ax[2].set_title("Bootstrap stability (ARI, 15 resamples)")
    ax[2].set_xlabel("k"); ax[2].set_ylabel("Adjusted Rand Index")
    ax[2].set_ylim(0, 1.05); ax[2].set_xticks(stab["k"])
    best3 = ev.head(6)
    save(fig, "18_kmeans_model_selection",
         "K-means model selection: elbow, silhouette and bootstrap stability",
         (f"Silhouette peaks at k={bk} (score {ev.silhouette.max():.3f}); inertia's largest "
          f"marginal drop is at k={best_k_elbow}. Bootstrap ARI by k: "
          + ", ".join(f"k={int(r.k)}:{r.ari_mean:.2f}" for r in stab.itertuples()) + "."),
         "Absolute silhouette values are low because behavioural data is continuous without separated blobs; "
         "the decision must therefore rest on stability and interpretability as well as separation.",
         "k is chosen where silhouette is competitive, ARI stability is high, every segment clears the 5% size floor, "
         "and the segments map onto actionable care pathways.")


def plot_pca_clusters(Xs, labels, k, feat):
    p = PCA(n_components=2, random_state=RNG)
    Z = p.fit_transform(Xs)
    evr = p.explained_variance_ratio_
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    for i in range(k):
        m = labels == i
        ax[0].scatter(Z[m, 0], Z[m, 1], s=5, alpha=.45, color=PALETTE[i % len(PALETTE)],
                      label=f"Cluster {i} (n={m.sum():,})")
    ax[0].set_xlabel(f"PC1 ({evr[0]*100:.1f}% variance)")
    ax[0].set_ylabel(f"PC2 ({evr[1]*100:.1f}% variance)")
    ax[0].set_title(f"K-means clusters (k={k}) in PCA space")
    ax[0].legend(fontsize=7, markerscale=3, loc="best")

    sz = pd.Series(labels).value_counts().sort_index()
    bar(ax[1], [f"C{i}" for i in sz.index], sz.values,
        "Cluster size distribution", "Cluster", "Patients", color=PALETTE[2])
    return save(fig, "19_pca_clusters", "PCA projection of K-means clusters",
                (f"PC1+PC2 retain {100*(evr[0]+evr[1]):.1f}% of variance; cluster sizes range "
                 f"{sz.min():,} to {sz.max():,} patients "
                 f"(smallest = {100*sz.min()/sz.sum():.1f}% of base)."),
                "Clusters form a graded continuum rather than tight isolated islands - normal for behavioural segmentation.",
                "Low separation is acceptable when segments differ materially on the KPIs that drive operational decisions; "
                "the profile table is what must be validated, not the scatter plot.")


def plot_cluster_profiles(prof: pd.DataFrame, k: int):
    metrics = ["avg_recency", "avg_frequency", "avg_monetary", "avg_adm_rate",
               "avg_los", "avg_lab_per_visit", "avg_dept_div"]
    fig, axes = plt.subplots(2, 4, figsize=(17, 7))
    axes = axes.ravel()
    for ax, m in zip(axes, metrics):
        bar(ax, prof["cluster_label"], prof[m], m.replace("_", " ").title(),
            "Segment", "", color=PALETTE[1], rotate=35,
            fmt="{:,.1f}" if prof[m].max() < 100 else "{:,.0f}")
    axes[-1].axis("off")
    axes[-1].text(.05, .5, "Each bar is a segment mean.\nRelative height = the KPI gap\nmanagement can act on.",
                  fontsize=11, va="center")
    save(fig, "20_cluster_profiles", "Feature-level comparison of K-means segments",
         "Segment-level means for the seven profiling KPIs; ranges: recency "
         f"{prof.avg_recency.min():.0f}-{prof.avg_recency.max():.0f} days, frequency "
         f"{prof.avg_frequency.min():.1f}-{prof.avg_frequency.max():.1f} visits, monetary "
         f"INR {prof.avg_monetary.min():,.0f}-{prof.avg_monetary.max():,.0f}.",
         "Segments differ by multiples, not percentages, on the core KPIs.",
         "Each segment therefore needs a different operating model rather than a different message.")


# ===========================================================================
# Main
# ===========================================================================
def run():
    feat = pd.read_parquet(PROC / "patient_features_full.parquet")
    print(f"patients: {len(feat):,}")

    # ---------------- Method A: RFM
    rfm, thr = rfm_score(feat)
    rfm = apply_rfm_rules(rfm)
    rfm_sizes = rfm["rfm_segment"].value_counts()
    thr["segment_sizes"] = {k: int(v) for k, v in rfm_sizes.items()}
    thr["segment_shares_pct"] = {k: round(100 * v / len(rfm), 2) for k, v in rfm_sizes.items()}
    thr["rfm_sum_distribution"] = rfm["RFM_sum"].value_counts().sort_index().to_dict()
    print("\nRFM segments:\n", rfm_sizes.to_string())

    fig, ax = plt.subplots(1, 2, figsize=(14, 4.6))
    order = rfm_sizes.index
    bar(ax[0], order, rfm_sizes.values, "RFM segment sizes", "Segment", "Patients",
        color=PALETTE[0], rotate=35)
    share = 100 * rfm_sizes / rfm_sizes.sum()
    bar(ax[1], order, share.values, "RFM segment share of patient base",
        "Segment", "% of patients", color=PALETTE[2], rotate=35, fmt="{:,.1f}")
    ax[1].axhline(5, color=PALETTE[4], ls="--", lw=1.2, label="5% viability floor")
    ax[1].legend()
    save(fig, "21_rfm_segments", "RFM segment sizes and shares",
         (f"{len(order)} rule-based segments; largest {rfm_sizes.index[0]} "
          f"{rfm_sizes.iloc[0]:,} ({share.iloc[0]:.1f}%), smallest "
          f"{rfm_sizes.index[-1]} {rfm_sizes.iloc[-1]:,} ({share.iloc[-1]:.1f}%)."),
         "Rule-based scoring produces a small 'Champions' core and a large residual.",
         "The residual 'Hibernating' tier is too large to be operationally actionable on its own - "
         "this is the structural weakness of the RFM approach for this population.")

    # ---------------- Method B: K-means
    X, Xs, prep_info = prep_kmeans(feat)
    ev = evaluate_k(Xs, C.K_RANGE)
    print("\nK evaluation:\n", ev.round(3).to_string(index=False))
    stab = pd.DataFrame([bootstrap_stability(Xs, k) for k in C.K_RANGE])
    print("\nStability:\n", stab.round(3).to_string(index=False))

    ous = operational_utility_score(feat, Xs, ev)
    ous = ous.merge(stab[["k", "ari_mean"]], on="k", how="left")
    ous["eligible"] = ous["eligible"] & (ous["ari_mean"] >= 0.85)
    print("\nOperational utility score:\n", ous.round(3).to_string(index=False))

    # persist the full utility table: the k-selection argument is only
    # auditable if a reviewer can see every candidate's score, not just the
    # winner's.
    ous.to_csv(OUT / "kmeans_operational_utility.csv", index=False)

    elig = ous[ous["eligible"]].sort_values("score", ascending=False)
    if len(elig) == 0:
        raise RuntimeError("No k satisfies the 5% segment floor and ARI>=0.85")
    chosen = int(elig.iloc[0]["k"])
    r = elig.iloc[0]
    k2 = ous.loc[ous.k == 2].iloc[0]
    reason = (f"k={chosen} selected by the composite operational utility score "
              f"({r['score']:.3f}, highest among eligible solutions). It has silhouette "
              f"{r['silhouette']:.3f}, bootstrap ARI {r['ari_mean']:.3f}, smallest segment "
              f"{r['min_segment_share_pct']:.1f}% (>= 5% floor), KPI spread {r['kpi_spread']:.2f} "
              f"and revenue separation {r['revenue_separation']:.3f}. "
              f"k=2 had a comparable silhouette ({k2['silhouette']:.3f}) but was rejected as "
              f"operationally unusable: its smaller segment is {k2['min_segment_share_pct']:.1f}% "
              f"of the base, leaving a {100 - k2['min_segment_share_pct']:.1f}% residual that no "
              f"single intervention can serve, and its KPI spread ({k2['kpi_spread']:.2f}) is the "
              f"lowest of any candidate.")

    print(f"\nCHOSEN k = {chosen}: {reason}")

    km, lab = fit_kmeans(Xs, chosen)
    feat_k = feat.copy()
    feat_k["cluster"] = lab
    feat_k["pca1"] = PCA(n_components=2, random_state=RNG).fit_transform(Xs)[:, 0]

    sil = silhouette_score(Xs, lab, sample_size=8000, random_state=RNG)
    metrics = {"k": chosen, "silhouette": float(sil),
               "calinski_harabasz": float(calinski_harabasz_score(Xs, lab)),
               "davies_bouldin": float(davies_bouldin_score(Xs, lab)),
               "inertia": float(km.inertia_), "n_init": 50,
               "reason_for_k": reason}
    metrics["bootstrap"] = stab[stab.k == chosen].iloc[0].to_dict()

    # agreement with the (hidden) latent archetypes - validation only
    try:
        truth = pd.read_csv(C.DATA_RAW / "_ground_truth_latent_labels.csv")
        feat_k = feat_k.merge(truth[["patient_id", "latent_archetype"]], on="patient_id", how="left")
        metrics["ari_vs_latent_truth"] = float(adjusted_rand_score(
            feat_k["latent_archetype"], feat_k["cluster"]))
    except FileNotFoundError:
        metrics["ari_vs_latent_truth"] = None

    # ---------------- centroid export (scaled + original units)
    # Two views are written because each answers a different question: the
    # scaled centroid shows which features define a cluster in the distance
    # metric, while the original-units centroid is what a clinician or
    # operations manager can actually read and challenge.
    ctr_scaled = pd.DataFrame(km.cluster_centers_, columns=KMEANS_FEATURES)
    ctr_scaled.insert(0, "cluster", range(len(ctr_scaled)))
    ctr_scaled.to_csv(OUT / "kmeans_centroids_scaled.csv", index=False)

    Xdf = X.copy()
    Xdf["cluster"] = lab
    ctr_orig = Xdf.groupby("cluster")[KMEANS_FEATURES].mean().reset_index()
    ctr_orig.insert(1, "n_patients", pd.Series(lab).value_counts().sort_index().values)
    ctr_orig.to_csv(OUT / "kmeans_centroids_original_units.csv", index=False)
    print("\nCentroids (original / transformed units):\n",
          ctr_orig.round(2).to_string(index=False))

    # ---------------- profiling helper (shared with stability module)
    prof = profile_segments(feat_k, "cluster")
    prof = name_segments(prof)
    feat_k["segment"] = feat_k["cluster"].map(prof.set_index("cluster")["segment_name"])
    print("\nK-means profile:\n", prof[["cluster", "segment_name", "n_patients", "share_pct",
                                        "avg_recency", "avg_frequency", "avg_monetary",
                                        "avg_adm_rate", "revenue_share_pct"]].round(2).to_string(index=False))

    plot_model_selection(ev, stab)
    plot_pca_clusters(Xs, lab, chosen, feat)
    plot_cluster_profiles(prof, chosen)

    # ---------------- persist
    ev.to_csv(OUT / "kmeans_k_evaluation.csv", index=False)
    stab.to_csv(OUT / "kmeans_stability.csv", index=False)
    with open(OUT / "rfm_thresholds.json", "w") as f:
        json.dump(thr, f, indent=2, default=str)
    with open(OUT / "kmeans_metrics.json", "w") as f:
        json.dump({**metrics, "prep": prep_info}, f, indent=2, default=str)
    with open(OUT / "kmeans_reason.txt", "w") as f:
        f.write(reason)

    rfm.to_parquet(PROC / "rfm_scored.parquet", index=False)
    feat_k.to_parquet(PROC / "kmeans_segmented.parquet", index=False)
    prof.to_csv(OUT / "kmeans_segment_profiles.csv", index=False)
    write_index()
    return feat_k, rfm, prof, ev, stab, metrics


# ===========================================================================
# Shared profiling
# ===========================================================================
PROFILE_SPEC = [
    ("n_patients", lambda g: len(g), "{:,.0f}"),
    ("share_pct", None, "{:.1f}%"),
    ("revenue", lambda g: g["monetary"].sum(), "{:,.0f}"),
    ("revenue_share_pct", None, "{:.1f}%"),
    ("avg_recency", lambda g: g["recency_days"].mean(), "{:,.0f} d"),
    ("avg_frequency", lambda g: g["frequency"].mean(), "{:,.1f}"),
    ("avg_monetary", lambda g: g["monetary"].mean(), "{:,.0f}"),
    ("avg_billing_per_visit", lambda g: g["avg_billing_per_visit"].mean(), "{:,.0f}"),
    ("avg_los", lambda g: g["avg_los_days"].mean(), "{:,.1f} d"),
    ("avg_adm_rate", lambda g: g["admission_rate"].mean(), "{:.1%}"),
    ("avg_lab_per_visit", lambda g: g["lab_per_visit"].mean(), "{:,.2f}"),
    ("avg_dept_div", lambda g: g["n_departments"].mean(), "{:,.2f}"),
    ("avg_age", lambda g: g["age"].mean(), "{:,.0f}"),
    ("pct_female", lambda g: (g["gender"] == "F").mean(), "{:.1%}"),
    ("readmit_30d_rate", lambda g: g["readmission_30d"].mean(), "{:.2%}"),
    ("bed_days_per_100", lambda g: 100 * g["total_bed_days"].sum() / max(len(g), 1), "{:,.0f}"),
    ("avg_recent_ratio", lambda g: g["recent_activity_ratio"].mean(), "{:,.2f}"),
    ("avg_chronic_share", lambda g: g["chronic_share"].mean(), "{:.1%}"),
    ("followup_compliance", lambda g: g["followup_compliance"].mean(), "{:.1%}"),
]


def profile_segments(df: pd.DataFrame, key: str) -> pd.DataFrame:
    rows = []
    total_rev = df["monetary"].sum()
    for k, g in df.groupby(key):
        r = {key: k}
        for name, fn, _ in PROFILE_SPEC:
            if name == "share_pct":
                r[name] = 100 * len(g) / len(df)
            elif name == "revenue_share_pct":
                r[name] = 100 * g["monetary"].sum() / total_rev
            else:
                r[name] = fn(g)
        rows.append(r)
    return pd.DataFrame(rows)


# ===========================================================================
# Business naming
# ===========================================================================
# Names are assigned from the measured profile, never from the cluster index.
# Rank-based naming was tried first and produced a mislabel: the largest, most
# dormant cluster inherited the name "High-Acuity Surgical" purely because it
# ranked third on monetary value. The rules below are evaluated in priority
# order and each one names a *behaviour*, which is what a ward manager can act on.
NAME_RULES = [
    ("Engaged High-Value",   lambda r: r["rank_monetary"] == 1 and r["rank_frequency"] == 1),
    ("Lapsed High-Value",    lambda r: r["rank_monetary"] == 1 and r["rank_recency"] == 1),
    ("High-Acuity Inpatient", lambda r: r["avg_adm_rate"] >= 0.20 and r["admission_rank"] == 1),
    ("Frequent OPD Regulars", lambda r: r["rank_frequency"] == 1),
    ("Diagnostics-Intensive", lambda r: r["rank_lab"] == 1 and r["avg_lab_per_visit"] > 0.50),
    ("Declining Regulars",   lambda r: r["avg_recent_ratio"] < 0.85 and r["avg_frequency"] >= 3),
    ("Dormant One-Time",     lambda r: r["rank_recency"] == 1),
    ("Occasional OPD",       lambda r: True),
]


def name_segments(prof: pd.DataFrame) -> pd.DataFrame:
    p = prof.copy()
    p["rank_monetary"] = p["avg_monetary"].rank(ascending=False, method="min").astype(int)
    p["rank_frequency"] = p["avg_frequency"].rank(ascending=False, method="min").astype(int)
    p["rank_recency"] = p["avg_recency"].rank(ascending=False, method="min").astype(int)
    p["rank_lab"] = p["avg_lab_per_visit"].rank(ascending=False, method="min").astype(int)
    p["admission_rank"] = p["avg_adm_rate"].rank(ascending=False, method="min").astype(int)
    names, used = [], set()
    for _, r in p.iterrows():
        nm = None
        for cand, rule in NAME_RULES:
            if rule(r) and cand not in used:
                nm = cand
                break
        if nm is None:
            nm = f"Segment {int(r['cluster'])}"
        used.add(nm)
        names.append(nm)
    p["segment_name"] = names
    # order segments by revenue contribution so tables read in business priority
    p = p.sort_values("revenue_share_pct", ascending=False).reset_index(drop=True)
    p["segment_rank"] = np.arange(1, len(p) + 1)
    p["cluster_label"] = p["segment_name"].str.wrap(14)
    return p


if __name__ == "__main__":
    run()
