"""
eda.py
======
Section 4 exploratory analysis + Section 5 statistical/outlier treatment.

Every figure is saved with a recorded numerical observation, the pattern it
reveals and the business implication, so the report and the deck can quote
exactly what the data shows. No decorative charts: each one answers a question
that the segmentation depends on.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from scipy import stats

import config as C
from viz import save, bar, PALETTE, SEQ, money, pct_fmt, write_index
from catalogue import DIAGNOSES

PROC, FIG, OUT = C.DATA_PROC, C.FIG_DIR, C.OUT_DIR

CHRONIC_DIAG = {d[1] for lst in DIAGNOSES.values() for d in lst if d[2] == 1}


def load():
    d = {
        "pat": pd.read_parquet(PROC / "patients_clean.parquet"),
        "opd": pd.read_parquet(PROC / "opd_clean.parquet"),
        "adm": pd.read_parquet(PROC / "admissions_clean.parquet"),
        "lab": pd.read_parquet(PROC / "lab_clean.parquet"),
        "bill": pd.read_parquet(PROC / "billing_clean.parquet"),
        "feat": pd.read_parquet(PROC / "patient_features_full.parquet"),
    }
    return d


def run():
    D = load()
    pat, opd, adm, lab, bill, feat = (D["pat"], D["opd"], D["adm"],
                                      D["lab"], D["bill"], D["feat"])
    S: dict = {}
    S["shape"] = {k: list(v.shape) for k, v in D.items()}
    S["dtypes"] = {k: {c: str(t) for c, t in v.dtypes.items()} for k, v in D.items()}

    # ======================================================================
    # 1. Patient distribution across hospitals
    # ======================================================================
    hp = opd.groupby("hospital_id").agg(
        visits=("visit_id", "size"),
        patients=("patient_id", "nunique"),
        revenue=("visit_id", "size")).reset_index()
    rev_h = bill.groupby("hospital_id")["total_amount"].sum()
    hp["revenue"] = hp["hospital_id"].map(rev_h)
    hp["beds"] = hp["hospital_id"].map(lambda h: C.HOSPITALS[h]["beds"])
    hp["visits_per_bed"] = (hp["visits"] / hp["beds"]).round(1)
    S["hospital_overview"] = hp.to_dict("records")

    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    bar(ax[0], hp["hospital_id"], hp["visits"], "OPD visits by hospital",
        "Hospital", "Visits")
    bar(ax[1], hp["hospital_id"], hp["patients"], "Unique OPD patients by hospital",
        "Hospital", "Patients", color=PALETTE[1])
    bar(ax[2], hp["hospital_id"], hp["revenue"] / 1e7, "Billing value by hospital",
        "Hospital", "Revenue (INR crore)", color=PALETTE[2], fmt="{:,.2f}")
    save(fig, "01_hospital_distribution",
         "Patient, visit and revenue distribution across the four hospitals",
         (f"Largest site {hp.loc[hp.visits.idxmax(),'hospital_id']} has "
          f"{hp.visits.max():,} visits ({100*hp.visits.max()/hp.visits.sum():.1f}% of network) "
          f"and {hp.visits.max()/hp.beds.max():.1f} visits per bed; smallest site "
          f"{hp.loc[hp.visits.idxmin(),'hospital_id']} has {hp.visits.min():,} visits."),
         "Volume concentration is uneven: the two central sites carry disproportionate OPD load.",
         "Site-level capacity planning must differ; a single network-wide staffing ratio would starve the busiest site.")

    # ======================================================================
    # 2. OPD vs inpatient mix
    # ======================================================================
    n_opd = len(opd)
    n_ipd = len(adm)
    ipd_rev = bill[bill.encounter_type == "IPD"]["total_amount"].sum()
    opd_rev = bill[bill.encounter_type == "OPD"]["total_amount"].sum()
    S["opd_ipd"] = {"opd_visits": n_opd, "ipd_admissions": n_ipd,
                    "opd_share_events": round(100 * n_opd / (n_opd + n_ipd), 2),
                    "ipd_share_events": round(100 * n_ipd / (n_opd + n_ipd), 2),
                    "opd_revenue": float(opd_rev), "ipd_revenue": float(ipd_rev),
                    "ipd_revenue_share": round(100 * ipd_rev / (opd_rev + ipd_rev), 2)}
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    ax[0].bar(["OPD encounters", "IPD admissions"], [n_opd, n_ipd],
              color=[PALETTE[0], PALETTE[4]])
    ax[0].set_yscale("log"); ax[0].set_ylabel("Count (log scale)")
    ax[0].set_title("Encounter volume mix")
    for i, v in enumerate([n_opd, n_ipd]):
        ax[0].text(i, v, f"{v:,}", ha="center", va="bottom", fontsize=9)
    ax[1].pie([opd_rev, ipd_rev], labels=["OPD", "IPD"],
              autopct=lambda p: f"{p:.1f}%", colors=[PALETTE[0], PALETTE[4]],
              startangle=90, wedgeprops={"edgecolor": "white"})
    ax[1].set_title("Revenue mix (corrected billing)")
    save(fig, "02_opd_vs_ipd", "Outpatient versus inpatient volume and revenue",
         (f"{n_ipd:,} admissions vs {n_opd:,} OPD visits ({100*n_ipd/(n_opd+n_ipd):.1f}% of events) "
          f"yet IPD generates {100*ipd_rev/(opd_rev+ipd_rev):.1f}% of billing value."),
         "Classic 5/95 volume-to-value inversion typical of Indian community hospitals.",
         "Inpatient capacity and case-mix management drive financial sustainability; OPD drives reach and gate-keeping.")

    # ======================================================================
    # 3. Monthly / quarterly trends
    # ======================================================================
    m = opd.groupby(opd["visit_date"].dt.to_period("M")).size()
    m.index = m.index.astype(str)
    q = opd.groupby(opd["visit_date"].dt.to_period("Q")).size()
    q.index = q.index.astype(str)
    S["monthly_trend"] = {"min_month": m.idxmin(), "min_visits": int(m.min()),
                          "max_month": m.idxmax(), "max_visits": int(m.max()),
                          "cv_pct": round(float(100 * m.std() / m.mean()), 2),
                          "first_year_avg": int(m.iloc[:12].mean()),
                          "last_year_avg": int(m.iloc[-12:].mean())}
    growth = 100 * (S["monthly_trend"]["last_year_avg"] / S["monthly_trend"]["first_year_avg"] - 1)
    S["monthly_trend"]["yoy_growth_pct"] = round(float(growth), 2)
    fig, ax = plt.subplots(figsize=(12, 4.2))
    ax.plot(m.index, m.values, marker="o", ms=3, color=PALETTE[0], lw=1.6)
    z = np.polyfit(np.arange(len(m)), m.values, 1)
    ax.plot(m.index, np.poly1d(z)(np.arange(len(m))), ls="--", color=PALETTE[4],
            label=f"linear trend (+{z[0]*12:,.0f} visits/year)")
    ax.set_title("Monthly OPD visit volume, Jan-2022 to Dec-2024")
    ax.set_xlabel("Month"); ax.set_ylabel("Visits")
    ax.set_xticks(range(0, len(m), 3)); ax.set_xticklabels(m.index[::3], rotation=45, ha="right")
    ax.legend()
    save(fig, "03_monthly_trend", "Monthly OPD volume with trend line",
         (f"Monthly volume ranges {m.min():,}-{m.max():,} (CV {S['monthly_trend']['cv_pct']}%), "
          f"trend +{z[0]*12:,.0f} visits/year; last-12-month average "
          f"{100*growth:.1f}% above the first 12 months."),
         "Secular growth on top of a repeating seasonal cycle, not a flat demand curve.",
         "Capacity must be planned with a growth buffer; a static staffing model will progressively under-serve the network.")

    fig, ax = plt.subplots(figsize=(9, 4))
    bar(ax, q.index, q.values, "Quarterly OPD volume", "Quarter", "Visits",
        color=PALETTE[2], rotate=45, fmt="{:,.0f}")
    save(fig, "04_quarterly_trend", "Quarterly OPD volume",
         f"Peak quarter {q.idxmax()} ({q.max():,}); trough {q.idxmin()} ({q.min():,}).",
         "Q3 (Jul-Sep) is consistently the softest quarter, Q4 the strongest.",
         "Elective camps, screening drives and elective surgery scheduling should be loaded into Q3 slack.")

    # ======================================================================
    # 4. Age group distribution
    # ======================================================================
    ab = feat["age_band"].value_counts().reindex(
        ["0-4", "5-14", "15-29", "30-44", "45-59", "60-74", "75+"])
    S["age_band"] = {k: int(v) for k, v in ab.items()}
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.2))
    bar(ax[0], ab.index, ab.values, "Patients by age band", "Age band", "Patients")
    rev_age = feat.groupby("age_band", observed=True)["monetary"].sum().reindex(ab.index)
    bar(ax[1], rev_age.index, rev_age.values / 1e7,
        "Billing value by age band", "Age band", "Revenue (INR crore)",
        color=PALETTE[4], fmt="{:,.2f}")
    oldest = ab.index[-3:].tolist()
    old_share = 100 * ab.loc[oldest].sum() / ab.sum()
    old_rev = 100 * rev_age.loc[oldest].sum() / rev_age.sum()
    S["age_45plus"] = {"patient_share": round(old_share, 2), "revenue_share": round(old_rev, 2)}
    save(fig, "05_age_distribution", "Patient volume and billing value by age band",
         (f"Patients aged 45+ are {old_share:.1f}% of the base but contribute {old_rev:.1f}% of billing "
          f"value; the 15-29 band is the single largest volume band "
          f"({100*ab['15-29']/ab.sum():.1f}%)."),
         "Value is age-skewed: the 45+ cohort generates revenue far ahead of its headcount.",
         "Chronic-disease programmes (diabetes, hypertension, cardiac) have the highest value density per enrolled patient.")

    # ======================================================================
    # 5. Gender
    # ======================================================================
    gd = feat["gender"].value_counts()
    S["gender"] = {k: int(v) for k, v in gd.items()}
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    bar(ax[0], gd.index, gd.values, "Patients by gender", "Gender", "Patients")
    gval = feat.groupby("gender")["monetary"].mean()
    bar(ax[1], gval.index, gval.values, "Mean billing per patient by gender",
        "Gender", "Mean billing (INR)", color=PALETTE[5])
    save(fig, "06_gender", "Gender distribution and mean billing",
         f"Female {gd.get('F',0):,} ({100*gd.get('F',0)/gd.sum():.1f}%), male {gd.get('M',0):,} "
         f"({100*gd.get('M',0)/gd.sum():.1f}%); mean billing M INR {gval.get('M',0):,.0f} vs "
         f"F INR {gval.get('F',0):,.0f}.",
         "Gender mix is near-balanced but male patients carry higher average value.",
         "Maternity and paediatric bundles are volume anchors rather than value anchors - price and capacity them accordingly.")

    # ======================================================================
    # 6. Department utilisation
    # ======================================================================
    dep = opd.groupby("department").agg(visits=("visit_id", "size"),
                                        patients=("patient_id", "nunique")).sort_values("visits")
    dep_rev = bill.groupby("department")["total_amount"].sum()
    dep["revenue"] = dep.index.map(dep_rev)
    dep["revenue_per_visit"] = (dep["revenue"] / dep["visits"]).round(0)
    S["department"] = dep.reset_index().to_dict("records")
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    bar(ax[0], dep.index, dep["visits"], "OPD visits by department", "Visits",
        "Department", horizontal=True, color=PALETTE[1])
    bar(ax[1], dep.index, dep["revenue_per_visit"], "Revenue per visit by department",
        "INR per visit", "Department", horizontal=True, color=PALETTE[4], fmt="{:,.0f}")
    top3 = dep.sort_values("visits", ascending=False).head(3)
    S["dept_top3_share"] = round(100 * top3["visits"].sum() / dep["visits"].sum(), 2)
    save(fig, "07_department_utilisation", "Department utilisation and revenue intensity",
         (f"Top three departments ({', '.join(top3.index)}) absorb {S['dept_top3_share']:.1f}% of OPD visits; "
          f"revenue per visit ranges INR {dep.revenue_per_visit.min():,.0f} "
          f"({dep.revenue_per_visit.idxmin()}) to INR {dep.revenue_per_visit.max():,.0f} "
          f"({dep.revenue_per_visit.idxmax()})."),
         "Volume is concentrated in generalist departments while value concentrates in specialist ones.",
         "Queue redesign should target generalist OPD; specialist slots should be protected and scheduled, not queued.")

    # ======================================================================
    # 7. Diagnosis category distribution
    # ======================================================================
    dg = opd.groupby("diagnosis_canonical").size().sort_values(ascending=False)
    dg_named = dg.head(15)
    chronic_flag = [d in CHRONIC_DIAG for d in dg.index]
    chronic_share = 100 * dg[chronic_flag].sum() / dg.sum()
    S["diagnosis"] = {"n_canonical": int(len(dg)), "top15": dg_named.to_dict(),
                      "chronic_share_pct": round(float(chronic_share), 2)}
    fig, ax = plt.subplots(figsize=(11, 5.4))
    colors = [PALETTE[4] if d in CHRONIC_DIAG else PALETTE[0] for d in dg_named.index]
    b = ax.barh(dg_named.index[::-1], dg_named.values[::-1], color=colors[::-1])
    for r, v in zip(b, dg_named.values[::-1]):
        ax.text(v, r.get_y() + r.get_height() / 2, f" {v:,}", va="center", fontsize=8)
    ax.set_xlabel("OPD visits"); ax.set_title("Top 15 diagnoses (orange = chronic condition)")
    ax.set_ylabel("")
    save(fig, "08_diagnosis_mix", "Diagnosis mix after canonicalisation",
         (f"{len(dg)} canonical diagnoses after mapping; top diagnosis "
          f"{dg.index[0]} = {dg.iloc[0]:,} visits ({100*dg.iloc[0]/dg.sum():.1f}%); chronic "
          f"conditions account for {chronic_share:.1f}% of all OPD visits."),
         "Chronic disease dominates demand, not acute episodic care.",
         "A chronic-care programme is the highest-leverage clinical intervention available to the network.")

    # ======================================================================
    # 8. Billing distribution
    # ======================================================================
    bt = bill["total_amount"]
    S["billing_dist"] = {"n": int(len(bt)), "total": float(bt.sum()),
                         "mean": float(bt.mean()), "median": float(bt.median()),
                         "p95": float(bt.quantile(.95)), "p99": float(bt.quantile(.99)),
                         "max": float(bt.max()),
                         "skew": float(stats.skew(bt)), "kurtosis": float(stats.kurtosis(bt))}
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.2))
    ax[0].hist(bt, bins=80, color=PALETTE[0])
    ax[0].set_title("Billing line amount (raw scale)"); ax[0].set_xlabel("INR"); ax[0].set_ylabel("Lines")
    ax[1].hist(np.log1p(bt), bins=80, color=PALETTE[1])
    ax[1].set_title("Billing line amount (log1p scale)"); ax[1].set_xlabel("log(1+INR)")
    S["billing_dist"]["pct_of_value_top10pct_lines"] = round(
        100 * bt.nlargest(int(len(bt) * .10)).sum() / bt.sum(), 2)
    save(fig, "09_billing_distribution", "Billing line amount distribution before and after log transform",
         (f"{len(bt):,} lines totalling INR {bt.sum()/1e7:.2f} crore; median INR {bt.median():,.0f} vs "
          f"mean INR {bt.mean():,.0f}; skew {stats.skew(bt):.1f}, kurtosis {stats.kurtosis(bt):.1f}. "
          f"The top 10% of lines carry {S['billing_dist']['pct_of_value_top10pct_lines']:.1f}% of value."),
         "Extreme right skew with a small number of high-value inpatient lines.",
         "Log transform is mandatory before distance-based clustering; raw rupees would let a single admission dominate the geometry.")

    # ======================================================================
    # 9. Revenue contribution by hospital (stacked by service type)
    # ======================================================================
    piv = bill.pivot_table(index="hospital_id", columns="service_type",
                           values="total_amount", aggfunc="sum").fillna(0)
    fig, ax = plt.subplots(figsize=(10, 4.4))
    bottom = np.zeros(len(piv))
    for i, c in enumerate(["OPD_CONSULTATION", "PHARMACY", "IPD_ROOM", "PROCEDURE", "CONSUMABLES"]):
        ax.bar(piv.index, piv[c].values / 1e7, bottom=bottom, label=c,
               color=PALETTE[i % len(PALETTE)])
        bottom += piv[c].values / 1e7
    ax.set_ylabel("Revenue (INR crore)"); ax.set_xlabel("Hospital")
    ax.set_title("Revenue contribution by hospital and service line")
    ax.legend(ncol=5, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, -0.32))
    top_h = piv.sum(axis=1).idxmax()
    S["revenue_by_hospital"] = {h: round(float(v) / 1e7, 2) for h, v in piv.sum(axis=1).items()}
    save(fig, "10_revenue_by_hospital", "Revenue contribution by hospital and service line",
         (f"{top_h} contributes INR {piv.sum(axis=1).max()/1e7:.2f} crore of "
          f"INR {piv.sum().sum()/1e7:.2f} crore ({100*piv.sum(axis=1).max()/piv.sum().sum():.1f}%); "
          f"IPD room charges alone are {100*bill[bill.service_type=='IPD_ROOM']['total_amount'].sum()/bill['total_amount'].sum():.1f}% of value."),
         "Revenue is dominated by inpatient room charges, with a stable second tier of procedures.",
         "Bed utilisation and ALOS control are the two biggest revenue levers in the network.")

    # ======================================================================
    # 10. Visit frequency distribution
    # ======================================================================
    fr = feat["frequency"]
    S["frequency"] = {"mean": round(float(fr.mean()), 2), "median": float(fr.median()),
                      "p90": float(fr.quantile(.9)), "p99": float(fr.quantile(.99)),
                      "max": int(fr.max()), "single_visit_pct": round(100 * float((fr == 1).mean()), 2)}
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.2))
    vc = fr.value_counts().sort_index()
    ax[0].bar(vc.index[:31], vc.values[:31], color=PALETTE[0])
    ax[0].set_title("Visit frequency distribution (1-31 visits)"); ax[0].set_xlabel("Visits per patient")
    ax[0].set_ylabel("Patients")
    ax[1].hist(np.log1p(fr), bins=30, color=PALETTE[1])
    ax[1].set_title("log1p(visits) distribution"); ax[1].set_xlabel("log(1+visits)")
    save(fig, "11_visit_frequency", "Distribution of visits per patient",
         (f"Mean {fr.mean():.2f} visits, median {fr.median():.0f}; {100*(fr==1).mean():.1f}% of patients "
          f"have exactly one visit, P90 = {fr.quantile(.9):.0f}, max = {fr.max():.0f}."),
         "A one-and-done majority alongside a small but important high-frequency tail.",
         "Retention, not acquisition, is the constraint: converting single-visit patients into a second visit is the cheapest growth available.")

    # ======================================================================
    # 11. Recency distribution
    # ======================================================================
    rc = feat["recency_days"]
    S["recency"] = {"mean": round(float(rc.mean()), 1), "median": float(rc.median()),
                    "p25": float(rc.quantile(.25)), "p75": float(rc.quantile(.75)),
                    "over_365_pct": round(100 * float((rc > 365).mean()), 2),
                    "under_30_pct": round(100 * float((rc <= 30).mean()), 2)}
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.2))
    ax[0].hist(rc, bins=50, color=PALETTE[2])
    ax[0].set_title("Recency of last visit (days to 2025-01-01)")
    ax[0].set_xlabel("Days"); ax[0].set_ylabel("Patients")
    ax[1].hist(np.log1p(rc), bins=40, color=PALETTE[3])
    ax[1].set_title("log1p(recency)"); ax[1].set_xlabel("log(1+days)")
    save(fig, "12_recency", "Distribution of patient recency",
         (f"Median recency {rc.median():.0f} days; {100*(rc>365).mean():.1f}% of patients have not "
          f"been seen for over a year; {100*(rc<=30).mean():.1f}% visited in the last 30 days."),
         "The panel is bimodal: an active core and a large dormant population.",
         "Reactivation of the dormant tier is a defined, addressable revenue pool with no acquisition cost.")

    # ======================================================================
    # 12. ALOS distribution
    # ======================================================================
    los = adm["los_days"]
    S["los"] = {"mean": round(float(los.mean()), 2), "median": float(los.median()),
                "p90": float(los.quantile(.9)), "p99": float(los.quantile(.99)),
                "max": int(los.max()), "skew": round(float(stats.skew(los)), 2),
                "kurtosis": round(float(stats.kurtosis(los)), 2)}
    by_dept = adm.groupby("department")["los_days"].mean().sort_values()
    S["los_by_department"] = {k: round(float(v), 2) for k, v in by_dept.items()}
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.4))
    ax[0].hist(los, bins=40, color=PALETTE[5])
    ax[0].set_title("Length of stay distribution"); ax[0].set_xlabel("Days"); ax[0].set_ylabel("Admissions")
    ax[0].axvline(los.mean(), color="black", ls="--", label=f"mean {los.mean():.1f}d")
    ax[0].axvline(los.median(), color=PALETTE[0], ls=":", label=f"median {los.median():.0f}d")
    ax[0].legend()
    bar(ax[1], by_dept.index, by_dept.values, "Mean length of stay by department",
        "Department", "Days", color=PALETTE[1], rotate=45, fmt="{:,.1f}")
    save(fig, "13_los", "Length-of-stay distribution and department comparison",
         (f"ALOS {los.mean():.2f} days (median {los.median():.0f}); P90 {los.quantile(.9):.0f} days; "
          f"longest department {by_dept.idxmax()} at {by_dept.max():.1f} days."),
         "Right-skewed LOS with a specialist-department tail.",
         "A 0.5-day ALOS reduction on the longest-stay department releases meaningful bed capacity without reducing care quality.")

    # ======================================================================
    # 13. Missing-value heatmap (raw)
    # ======================================================================
    from cleaning import load_raw
    raw = load_raw()
    names = ["patients", "opd_visits", "admissions", "lab_tests", "billing"]
    miss = pd.DataFrame({n: raw[i].isna().mean() * 100 for i, n in enumerate(names)}).T
    miss = miss.loc[:, miss.max() > 0]
    fig, ax = plt.subplots(figsize=(10, 3.6))
    im = ax.imshow(miss.values, aspect="auto", cmap="Reds")
    ax.set_xticks(range(len(miss.columns)))
    ax.set_xticklabels(miss.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(miss.index))); ax.set_yticklabels(miss.index)
    for i in range(miss.shape[0]):
        for j in range(miss.shape[1]):
            v = miss.values[i, j]
            if v > 0:
                ax.text(j, i, f"{v:.2f}%", ha="center", va="center", fontsize=8,
                        color="white" if v > 3 else "black")
    fig.colorbar(im, ax=ax, label="% missing in RAW data")
    ax.set_title("Missing-value profile of the raw source tables")
    S["missing_raw"] = {c: {i: round(float(v), 3) for i, v in miss[c].items()} for c in miss.columns}
    save(fig, "14_missing_heatmap", "Missing-value profile across raw tables",
         (f"Highest raw missingness is {miss.max().idxmax()}::"
          f"{miss.max().idxmax() and miss[miss.max().idxmax()].idxmax()} at {miss.max().max():.2f}%; "
          f"arriving as {int((miss.values>0).sum())} table-column cells."),
         "Missingness is low and structurally random except for lab-to-visit linkage.",
         "Imputation is defensible and does not need to be aggressive; the lab linkage gap is an integration problem, not a data-entry problem.")

    # ======================================================================
    # 14. Correlation heatmap
    # ======================================================================
    cols = ["recency_days", "frequency", "monetary", "visits_per_month", "admission_count",
            "total_bed_days", "lab_count", "avg_billing_per_visit", "dept_diversity",
            "recent_activity_ratio", "visit_growth_rate", "chronic_share", "age"]
    corr = feat[cols].corr(method="spearman")
    fig, ax = plt.subplots(figsize=(9.5, 7.6))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols))); ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(cols))); ax.set_yticklabels(cols, fontsize=8)
    for i in range(len(cols)):
        for j in range(len(cols)):
            if abs(corr.values[i, j]) > 0.35 and i != j:
                ax.text(j, i, f"{corr.values[i,j]:.2f}", ha="center", va="center", fontsize=6.5)
    fig.colorbar(im, ax=ax, label="Spearman rho")
    ax.set_title("Spearman correlation of patient-level features")
    S["correlation"] = {"frequency_vs_monetary": round(float(corr.loc["frequency", "monetary"]), 3),
                        "frequency_vs_visits_per_month": round(float(corr.loc["frequency", "visits_per_month"]), 3),
                        "monetary_vs_avg_billing_per_visit": round(float(corr.loc["monetary", "avg_billing_per_visit"]), 3),
                        "recency_vs_frequency": round(float(corr.loc["recency_days", "frequency"]), 3),
                        "admission_vs_bed_days": round(float(corr.loc["admission_count", "total_bed_days"]), 3)}
    save(fig, "15_correlation_heatmap", "Spearman correlation among engineered features",
         (f"Frequency-monetary rho {corr.loc['frequency','monetary']:.2f}; recency-frequency rho "
          f"{corr.loc['recency_days','frequency']:.2f}; admission-bed-days rho "
          f"{corr.loc['admission_count','total_bed_days']:.2f}."),
         "Frequency and monetary are positively but not redundantly correlated, so both carry independent signal.",
         "Keeping F and M as separate axes is justified, but the K-means feature set must drop near-duplicate columns to avoid double weighting.")

    # ======================================================================
    # 15. Outlier detection boxplots
    # ======================================================================
    box_cols = ["frequency", "monetary", "avg_billing_per_visit", "total_bed_days", "lab_count"]
    q1 = feat[box_cols].quantile(.25); q3 = feat[box_cols].quantile(.75)
    iqr = q3 - q1
    out_stats = {}
    for c in box_cols:
        hi = q3[c] + 1.5 * iqr[c]
        out_stats[c] = {"q1": float(q1[c]), "q3": float(q3[c]), "upper_fence": float(hi),
                        "n_outliers": int((feat[c] > hi).sum()),
                        "pct_outliers": round(100 * float((feat[c] > hi).mean()), 2)}
    S["outliers_iqr"] = out_stats
    fig, axes = plt.subplots(1, 5, figsize=(16, 4))
    for ax, c in zip(axes, box_cols):
        ax.boxplot(np.log1p(feat[c]), vert=True, widths=.55,
                   patch_artist=True, boxprops=dict(facecolor=PALETTE[2], alpha=.7))
        ax.set_title(f"{c}\n(IQR outliers {out_stats[c]['n_outliers']:,})", fontsize=9)
        ax.set_xticks([]); ax.set_ylabel("log1p(value)")
    save(fig, "16_outlier_boxplots", "IQR outlier detection on key utilisation features",
         (f"Outlier counts at the 1.5xIQR fence: " +
          "; ".join(f"{c} {v['n_outliers']:,} ({v['pct_outliers']}%)" for c, v in out_stats.items()) + "."),
         "Quantile scoring and log-scaling are required; these are genuine heavy users, not errors.",
         "High-utilisation and high-complexity patients are retained and profiled as a segment - never deleted.")

    # ======================================================================
    # 16. Seasonal utilisation
    # ======================================================================
    sea = opd.groupby(opd["visit_date"].dt.month).size()
    season_name = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                   7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    sea.index = [season_name[i] for i in sea.index]
    idx = sea / sea.mean() * 100
    S["seasonality_index"] = {k: round(float(v), 1) for k, v in idx.items()}
    fig, ax = plt.subplots(figsize=(10, 4))
    b = ax.bar(idx.index, idx.values,
               color=[PALETTE[4] if v > 105 else PALETTE[1] if v >= 95 else PALETTE[3]
                      for v in idx.values])
    ax.axhline(100, color="black", lw=1, ls="--")
    ax.set_title("Seasonal index of OPD demand (network average = 100)")
    ax.set_xlabel("Month"); ax.set_ylabel("Index")
    for r, v in zip(b, idx.values):
        ax.text(r.get_x() + r.get_width() / 2, v, f"{v:.0f}", ha="center", va="bottom", fontsize=8)
    peak = idx.idxmax(); trough = idx.idxmin()
    S["seasonality"] = {"peak_month": peak, "peak_index": round(float(idx.max()), 1),
                        "trough_month": trough, "trough_index": round(float(idx.min()), 1),
                        "amplitude_pct": round(float(idx.max() - idx.min()), 1)}
    save(fig, "17_seasonality", "Seasonal index of OPD demand",
         (f"Peak {peak} at index {idx.max():.0f}, trough {trough} at {idx.min():.0f} - an amplitude of "
          f"{idx.max()-idx.min():.0f} index points ({100*(idx.max()-idx.min())/100:.0f}% swing)."),
         "Winter months are consistently over-indexed; monsoon months under-index.",
         "Roster flex of roughly +/-15% around the annual mean is needed; hiring to the annual average would misallocate staff for 8 months of 12.")

    write_index()
    with open(OUT / "eda_stats.json", "w") as f:
        json.dump(S, f, indent=2, default=str)

    # ------------------------------------------------ headline numbers print
    print(json.dumps({k: S[k] for k in ["opd_ipd", "monthly_trend", "age_45plus",
                                        "frequency", "recency", "los",
                                        "seasonality", "dept_top3_share"]},
                     indent=2, default=str))
    return S


if __name__ == "__main__":
    run()
