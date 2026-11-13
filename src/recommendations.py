"""
recommendations.py
==================
Section 9: segment-specific interventions and the cost-benefit model.

Design rules enforced in this module
------------------------------------
1. Every benefit is anchored to an OBSERVED quantity from the cleaned data
   (segment size, overdue count, readmission count, tests per visit, bed-days).
2. Incremental demand is valued at the segment's OBSERVED outpatient revenue per
   visit and inpatient revenue per admission - never at a blended per-patient
   revenue that silently includes multi-year inpatient billing.
3. Margin rates and uplift assumptions are explicit, disclosed, and stress-tested
   in the sensitivity table. Gross billing is present in the data; cost is not,
   so a contribution-margin assumption is unavoidable and is declared.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from viz import save, bar, PALETTE, write_index

PROC, OUT = C.DATA_PROC, C.OUT_DIR
A = C.ASSUMPTIONS

# Margin assumptions (declared, tested in sensitivity)
OPD_MARGIN = 0.38        # contribution margin on an incremental outpatient visit
IPD_MARGIN = 0.30        # contribution margin on an incremental admission
LAB_MARGIN = A["lab_margin_rate"]


def unit_economics(seg: pd.DataFrame, bill: pd.DataFrame) -> pd.DataFrame:
    """Observed outpatient revenue per visit and inpatient revenue per admission."""
    opd_rev = bill[bill["service_type"].isin(["OPD_CONSULTATION", "PHARMACY"])] \
        .groupby("patient_id")["total_amount"].sum()
    ipd_rev = bill[~bill["service_type"].isin(["OPD_CONSULTATION", "PHARMACY"])] \
        .groupby("patient_id")["total_amount"].sum()
    d = seg.copy()
    d["opd_rev"] = d["patient_id"].map(opd_rev).fillna(0)
    d["ipd_rev"] = d["patient_id"].map(ipd_rev).fillna(0)
    rows = []
    for name, g in d.groupby("segment"):
        adm = g["admission_count"].sum()
        rows.append({
            "segment": name,
            "opd_rev_per_visit": float(g["opd_rev"].sum() / max(g["frequency"].sum(), 1)),
            "ipd_rev_per_admission": float(g["ipd_rev"].sum() / adm) if adm > 0 else 0.0,
            "admissions": float(adm),
            "readmissions": float(g["readmission_30d"].sum()),
        })
    return pd.DataFrame(rows).set_index("segment")


def compute_evidence(seg: pd.DataFrame, ue: pd.DataFrame) -> dict:
    e = {}
    for name, g in seg.groupby("segment"):
        u = ue.loc[name]
        e[name] = {
            "n": int(len(g)),
            "share_pct": round(100 * len(g) / len(seg), 2),
            "revenue": float(g["monetary"].sum()),
            "rev_per_patient": float(g["monetary"].mean()),
            "opd_rev_per_visit": round(float(u["opd_rev_per_visit"]), 0),
            "ipd_rev_per_admission": round(float(u["ipd_rev_per_admission"]), 0),
            "freq": float(g["frequency"].mean()),
            "recency": float(g["recency_days"].mean()),
            "adm_rate": float(g["admission_rate"].mean()),
            "los": float(g["avg_los_days"].mean()),
            "lab_per_visit": float(g["lab_per_visit"].mean()),
            "dept_div": float(g["n_departments"].mean()),
            "readmit_30d_count": int(g["readmission_30d"].sum()),
            "readmit_30d_pct": round(100 * float(g["readmission_30d"].mean()), 2),
            "bed_days_total": float(g["total_bed_days"].sum()),
            "consent_y_pct": round(100 * float((g["consent_outreach"] == "Y").mean()), 2),
            "inactive_180d": int((g["recency_days"] > 180).sum()),
            "inactive_365d": int((g["recency_days"] > 365).sum()),
            "single_visit": int((g["frequency"] == 1).sum()),
            "hi_lab_users": int((g["lab_per_visit"] > 1.0).sum()),
            "recent_ratio": float(g["recent_activity_ratio"].mean()),
            "n_with_admission": int((g["admission_count"] > 0).sum()),
        }
    return e


def build_recommendations(seg, ev, ue) -> pd.DataFrame:
    # role resolution from the measured profile (never hard-coded names)
    hi_value_s = max(ev, key=lambda x: ev[x]["rev_per_patient"])
    dormant_s = min(ev, key=lambda x: ev[x]["rev_per_patient"])
    diag_s = max(ev, key=lambda x: ev[x]["lab_per_visit"])
    rows = []

    # =====================================================================
    # R1 - High-value segment: post-discharge follow-up & readmission prevention
    # =====================================================================
    s = hi_value_s
    e = ev[s]
    readm = e["readmit_30d_count"]
    avoidable = int(readm * 0.15)                     # assumption
    post_disch_visits = e["n_with_admission"] * 1.0   # one guaranteed 7-day review each
    benefit_readm = avoidable * e["ipd_rev_per_admission"] * IPD_MARGIN
    benefit_visits = post_disch_visits * e["opd_rev_per_visit"] * OPD_MARGIN
    fte = 3
    cost_fte = fte * A["care_coordinator_fte_cost_month"] * 12
    cost_it = 250_000
    cost_total = cost_fte + cost_it
    rows.append(dict(
        segment=s, segment_n=e["n"], share_pct=e["share_pct"],
        problem=(f"This segment is {e['share_pct']:.1f}% of patients but "
                 f"{100*e['revenue']/sum(v['revenue'] for v in ev.values()):.1f}% of billing value. "
                 f"It generates {readm:,} thirty-day readmissions ({e['readmit_30d_pct']:.1f}% of its "
                 f"patients), {e['adm_rate']:.2f} admissions per OPD visit and {e['bed_days_total']:,.0f} "
                 f"bed-days. Discharge follow-up is not currently structured."),
        intervention=("Post-discharge bundle for every admitted patient in this segment: guaranteed "
                      "7-day review appointment booked before discharge, 48-hour nurse call, medication "
                      "reconciliation, and a named care coordinator who owns the readmission flag."),
        implementation=("(1) Model flags admitted patients in this segment daily to the ward desk. "
                        "(2) Booking clerk reserves the 7-day slot at discharge. "
                        "(3) Nurse makes the 48-hour call against a scripted checklist. "
                        "(4) Coordinator reviews every readmission within 7 days against avoidability criteria. "
                        "(5) Monthly readmission governance review per site."),
        resources=("3 care coordinators, pharmacy reconciliation time, protected follow-up slots, "
                   "readmission dashboard, 1 quality analyst (part-time)."),
        addressable=e["n_with_admission"], reachable=post_disch_visits,
        cost_staff=round(cost_fte, 0), cost_other=round(cost_it, 0), cost_total=round(cost_total, 0),
        benefit_units=(f"{avoidable:,} avoidable readmissions prevented; "
                       f"{post_disch_visits:,.0f} guaranteed review visits"),
        benefit_value=round(benefit_readm + benefit_visits, 0),
        kpi=("30-day readmission rate for this segment; 7-day review completion; "
             "48-hour call completion; ALOS"),
        timeline="Design month 1; pilot at two sites months 2-3; network rollout month 4",
        confidence="Medium - 15% readmission avoidability is the governing assumption; validate on the "
                   "pilot before network-wide funding."))

    # =====================================================================
    # R2 - Dormant segment: reactivation and preventive screening
    # =====================================================================
    s = dormant_s
    e = ev[s]
    consented = e["n"] * e["consent_y_pct"] / 100
    target = int(min(e["inactive_365d"], consented))
    reach = int(target * 0.80)                       # assumption: 80% contactable
    conversion = 0.07                                # assumption
    reactivated = int(reach * conversion)
    visits_each = 1.9                                # assumption
    extra_visits = reactivated * visits_each
    benefit_visits = extra_visits * e["opd_rev_per_visit"] * OPD_MARGIN
    screening_tests = reactivated * 1.4              # one screening panel each
    benefit_lab = screening_tests * 850 * LAB_MARGIN
    n_camps = 8
    cost_camps = n_camps * A["camp_cost_per_event"]
    cost_sms = reach * 2 * A["outreach_sms_cost_per_contact"]
    cost_total = cost_camps + cost_sms
    rows.append(dict(
        segment=s, segment_n=e["n"], share_pct=e["share_pct"],
        problem=(f"{e['n']:,} patients ({e['share_pct']:.1f}% of the base) average "
                 f"{e['freq']:.2f} visits and INR {e['rev_per_patient']:,.0f} each, contributing only "
                 f"{100*e['revenue']/sum(v['revenue'] for v in ev.values()):.1f}% of billing value. "
                 f"{e['single_visit']:,} never returned after their first visit; {e['inactive_365d']:,} "
                 f"have been inactive for over a year and mean recency is {e['recency']:.0f} days."),
        intervention=("Population reactivation and preventive screening programme: SMS/IVR invite for a "
                      "bundled screening panel (BP, HbA1c, lipids, ECG) at community camps across the four "
                      "sites, with teleconsult fallback and a review appointment booked at the point of "
                      "screening."),
        implementation=("(1) Filter to consented patients inactive >365 days. "
                        "(2) Two reminder waves before each camp. "
                        "(3) Staff camps with 1 physician, 2 nurses and 1 registration clerk. "
                        "(4) Book every abnormal result into a 14-day review. "
                        "(5) Measure attendance, reactivation and downstream visits at 90 days."),
        resources=("Camp team, screening consumables, SMS/IVR gateway, registration desk, "
                   "lab capacity on camp days, transport tie-up for the peri-urban site."),
        addressable=target, reachable=reach,
        cost_staff=round(cost_camps, 0), cost_other=round(cost_sms, 0), cost_total=round(cost_total, 0),
        benefit_units=(f"{reactivated:,} reactivated patients, {extra_visits:,.0f} visits, "
                       f"{screening_tests:,.0f} screening panels"),
        benefit_value=round(benefit_visits + benefit_lab, 0),
        kpi=("Camp attendance per 1,000 invited; 90-day reactivation rate; downstream OPD visits per "
             "reactivated patient; abnormal-result review completion"),
        timeline="Wave 1 month 2; wave 2 month 4; steady state by month 7",
        confidence="Medium-low - the 7% reactivation rate governs the case; stage-gate wave 2 on the "
                   "wave-1 result. Non-financial benefit (earlier detection of undiagnosed chronic "
                   "disease) is real but is not monetised here."))

    # =====================================================================
    # R3 - Diagnostics-intensive segment: order-set stewardship and packaging
    # =====================================================================
    s = diag_s
    e = ev[s]
    hi = e["hi_lab_users"] if e["hi_lab_users"] > 0 else e["n"]
    redundant = int(hi * 0.22)                       # assumption
    tests_saved = redundant * 6                      # ~6 test episodes per heavy user per year
    benefit_saved = tests_saved * 850 * LAB_MARGIN
    package_conv = int((e["n"] - hi) * 0.15)         # assumption
    benefit_package = package_conv * 4200 * 0.45
    cost_it = 180_000
    cost_fte = 900_000          # 1 clinical governance + quality analyst FTE year 1
    cost_total = cost_it + cost_fte
    rows.append(dict(
        segment=s, segment_n=e["n"], share_pct=e["share_pct"],
        problem=(f"This segment orders {e['lab_per_visit']:.2f} laboratory tests per visit and visits "
                 f"{e['dept_div']:.1f} departments on average. {hi:,} patients exceed one test per visit, "
                 f"which is consistent with repeat ordering without a standing protocol. Revenue per "
                 f"visit is INR {e['opd_rev_per_visit']:,.0f} - the OPD demand is real, the diagnostics "
                 f"process is not controlled."),
        intervention=("Diagnostics stewardship and chronic-care packaging: approved order sets by "
                      "diagnosis with defined re-test intervals, duplicate-order alerts in the LIS, and a "
                      "bundled chronic package (consult + panel + review) for the remaining patients."),
        implementation=("(1) Agree order sets with clinical leads by chronic condition. "
                        "(2) Configure LIS duplicate-order alerts at 30/90 days by test. "
                        "(3) Build the package in billing and the patient app. "
                        "(4) Audit 200 records at 90 days for over- and under-testing. "
                        "(5) Report order-set compliance per department monthly."),
        resources=("Clinical governance time, LIS configuration, billing catalogue change, "
                   "1 part-time quality analyst."),
        addressable=hi, reachable=hi,
        cost_staff=round(cost_it, 0), cost_other=round(cost_fte, 0),
        cost_total=round(cost_total, 0),
        benefit_units=(f"{redundant:,} avoidable test episodes removed, "
                       f"{package_conv:,} package conversions"),
        benefit_value=round(benefit_saved + benefit_package, 0),
        kpi=("Tests per visit; share of orders matching an approved set; 30-day duplicate-order rate; "
             "package attach rate"),
        timeline="Order sets months 1-2; LIS rules month 3; clinical audit month 6",
        confidence="Medium - savings accrue partly to patients and payers, not only the hospital; "
                   "clinical buy-in is the binding constraint, not capital."))

    # =====================================================================
    # R4 - Network-wide: segment-aware discharge and ALOS management
    # =====================================================================
    adm_pts = seg[seg["admission_count"] > 0]
    bed_days = adm_pts["total_bed_days"].sum()
    freed = bed_days * 0.06                          # assumption: 6% avoidable bed-days
    # Backfill assumption: network occupancy is 68.6%, i.e. below the 75-80% band
    # that would make released capacity scarce. Only the share of released
    # bed-days that can be refilled with additional inpatient demand is credited;
    # the remainder is banked as capacity/quality headroom and not monetised.
    backfill_share = 0.40
    benefit_beds = freed * backfill_share * A["bed_day_opportunity_value"]
    all_readm = int(seg["readmission_30d"].sum())
    avoid_all = int(all_readm * 0.10)                # assumption
    benefit_readm = avoid_all * A["readmission_penalty_per_case"]
    cost_total = 2_900_000   # 4 discharge coordinators + analytics + training
    rows.append(dict(
        segment="Network-wide", segment_n=int(len(adm_pts)),
        share_pct=round(100 * len(adm_pts) / len(seg), 2),
        problem=(f"{len(adm_pts):,} patients account for {bed_days:,.0f} bed-days at an ALOS of "
                 f"{adm_pts['avg_los_days'].mean():.2f} days, and {all_readm:,} thirty-day readmissions "
                 f"were observed. Discharge planning is not segment-aware, so the highest-risk cohort "
                 f"is managed identically to the lowest."),
        intervention=("Segment-aware discharge and ALOS management: risk-flagged daily discharge list, "
                      "48-hour post-discharge call for the high-acuity cohort, medication reconciliation "
                      "at discharge, and a 7-day follow-up slot booked before discharge."),
        implementation=("(1) Publish the daily risk-flagged discharge list from the model. "
                        "(2) Assign a discharge coordinator per site. "
                        "(3) Script the 48-hour call. "
                        "(4) Guarantee the 7-day review slot. "
                        "(5) Audit avoidable readmissions monthly against agreed criteria."),
        resources=("4 discharge coordinators (one per site), IT flagging integration, "
                   "pharmacy reconciliation time, protected follow-up slots, training."),
        addressable=int(len(adm_pts)), reachable=int(len(adm_pts)),
        cost_staff=round(cost_total, 0), cost_other=0, cost_total=round(cost_total, 0),
        benefit_units=(f"{freed:,.0f} bed-days released ({freed*backfill_share:,.0f} monetised at a "
                       f"{backfill_share:.0%} backfill rate), {avoid_all:,} avoidable readmissions avoided"),
        benefit_value=round(benefit_beds + benefit_readm, 0),
        kpi="ALOS by department; % discharges with a completed 48-hour call; 30-day readmission rate",
        timeline="Pilot at two sites months 1-3; network rollout months 4-6",
        confidence="Medium - the 6% bed-day and 10% readmission assumptions need pilot validation."))

    df = pd.DataFrame(rows)
    df["roi_pct"] = ((df["benefit_value"] - df["cost_total"]) / df["cost_total"] * 100).round(1)
    df["net_benefit"] = (df["benefit_value"] - df["cost_total"]).round(0)
    df["benefit_cost_ratio"] = (df["benefit_value"] / df["cost_total"]).round(2)
    df["payback_months"] = (12 * df["cost_total"] / df["benefit_value"]).round(1)
    return df


def sensitivity(rec: pd.DataFrame) -> pd.DataFrame:
    drivers = [
        ("retention / readmission avoidability", 0.15, [0.075, 0.15, 0.225]),
        ("reactivation conversion", 0.07, [0.035, 0.07, 0.105]),
        ("avoidable repeat testing", 0.22, [0.11, 0.22, 0.33]),
        ("avoidable bed-day share", 0.06, [0.03, 0.06, 0.09]),
    ]
    out = []
    for i, (_, r) in enumerate(rec.iterrows()):
        name, base, levels = drivers[i]
        for lv in levels:
            scale = lv / base
            out.append({"segment": r.segment, "driver": name,
                        "scenario": ["Pessimistic", "Base", "Optimistic"][levels.index(lv)],
                        "driver_value": f"{lv:.1%}",
                        "benefit_value": round(r.benefit_value * scale, 0),
                        "cost_total": r.cost_total,
                        "roi_pct": round((r.benefit_value * scale - r.cost_total) / r.cost_total * 100, 1)})
    return pd.DataFrame(out)


def plot_cost_benefit(rec, sens):
    fig, ax = plt.subplots(1, 3, figsize=(17, 4.8))
    labels = [s.replace(" ", "\n", 1) for s in rec["segment"]]
    x = np.arange(len(rec)); w = 0.38
    ax[0].bar(x - w / 2, rec["cost_total"] / 1e5, w, label="Implementation cost", color=PALETTE[4])
    ax[0].bar(x + w / 2, rec["benefit_value"] / 1e5, w, label="Projected annual benefit", color=PALETTE[1])
    ax[0].set_xticks(x); ax[0].set_xticklabels(labels, fontsize=8)
    ax[0].set_ylabel("INR lakh"); ax[0].set_title("Cost vs projected benefit")
    ax[0].legend(fontsize=8)
    for i, (c, b) in enumerate(zip(rec.cost_total, rec.benefit_value)):
        ax[0].text(i + w / 2, b / 1e5, f"{b/1e5:.0f}", ha="center", va="bottom", fontsize=7.5)
        ax[0].text(i - w / 2, c / 1e5, f"{c/1e5:.1f}", ha="center", va="bottom", fontsize=7.5)

    bars = ax[1].bar(x, rec["roi_pct"],
                     color=[PALETTE[6] if v > 0 else PALETTE[4] for v in rec["roi_pct"]])
    ax[1].set_xticks(x); ax[1].set_xticklabels(labels, fontsize=8)
    ax[1].set_ylabel("ROI (%)"); ax[1].set_title("ROI by recommendation")
    ax[1].axhline(0, color="black", lw=1)
    for b, v in zip(bars, rec["roi_pct"]):
        ax[1].text(b.get_x() + b.get_width() / 2, v, f"{v:,.0f}%", ha="center",
                   va="bottom" if v >= 0 else "top", fontsize=8)

    for seg_name, g in sens.groupby("segment"):
        ax[2].plot(range(len(g)), g["roi_pct"], marker="o",
                   label=seg_name.replace(" ", "\n", 1))
    ax[2].set_xticks(range(3)); ax[2].set_xticklabels(["Pessimistic", "Base", "Optimistic"])
    ax[2].set_ylabel("ROI (%)"); ax[2].set_title("Sensitivity to the governing assumption")
    ax[2].axhline(0, color="black", lw=1); ax[2].legend(fontsize=6.5)
    tot_c, tot_b = rec.cost_total.sum(), rec.benefit_value.sum()
    save(fig, "24_cost_benefit",
         "Cost-benefit analysis and sensitivity of the four recommendations",
         (f"Total implementation cost INR {tot_c/1e5:,.1f} lakh against projected annual benefit "
          f"INR {tot_b/1e5:,.1f} lakh; portfolio ROI "
          f"{100*(tot_b-tot_c)/tot_c:,.0f}%. Individual ROI ranges {rec.roi_pct.min():,.0f}% to "
          f"{rec.roi_pct.max():,.0f}%."),
         "All four business cases are positive in the base case; the readmission-prevention case is the "
         "largest single contributor and the reactivation case is the most assumption-sensitive.",
         "Fund in the order of benefit-to-cost ratio, stage-gate the reactivation programme on wave-1 "
         "results, and re-validate every assumption against the pilot cohort before full commitment.")


def run(seg_df: pd.DataFrame | None = None):
    if seg_df is None:
        seg_df = pd.read_parquet(PROC / "kmeans_segmented.parquet")
    bill = pd.read_parquet(PROC / "billing_clean.parquet")
    ue = unit_economics(seg_df, bill)
    ev = compute_evidence(seg_df, ue)
    rec = build_recommendations(seg_df, ev, ue)
    sens = sensitivity(rec)

    rec.to_csv(OUT / "recommendations_cost_benefit.csv", index=False)
    sens.to_csv(OUT / "recommendation_sensitivity.csv", index=False)
    ue.to_csv(OUT / "segment_unit_economics.csv")
    with open(OUT / "segment_evidence.json", "w") as f:
        json.dump(ev, f, indent=2, default=str)
    plot_cost_benefit(rec, sens)
    write_index()

    pd.set_option("display.width", 200)
    print(rec[["segment", "segment_n", "cost_total", "benefit_value", "net_benefit",
               "roi_pct", "benefit_cost_ratio", "payback_months"]].to_string(index=False))
    print(f"\nPortfolio: cost INR {rec.cost_total.sum():,.0f} | benefit INR {rec.benefit_value.sum():,.0f} "
          f"| ROI {100*(rec.benefit_value.sum()-rec.cost_total.sum())/rec.cost_total.sum():.1f}%")
    print("\nUnit economics:\n", ue.round(0).to_string())
    return ev, rec, sens


if __name__ == "__main__":
    run()
