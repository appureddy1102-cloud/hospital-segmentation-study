"""
features.py
===========
Patient-level feature engineering.

Every feature is computed over an explicit observation window so that the
analysis can be repeated for any period (used by the stability study) and so
that no future information leaks into a segment definition.

Window contract
---------------
build_patient_features(start, end, reference_date):
    * behavioural features use events with `start <= event_date <= end`
    * Recency uses `reference_date` (normally `end + 1 day`)
    * patients with zero events inside the window are excluded (identified in
      the log, never silently dropped)

build_outcomes(start, end):
    * identical schema but used as the OUTCOME window. Features computed here
      are never used to define the segments that are evaluated against them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as C
from catalogue import DIAGNOSES

CHRONIC_DIAG = {d[1] for lst in DIAGNOSES.values() for d in lst if d[2] == 1}
CHRONIC_DEPT = {"Endocrinology", "Nephrology", "Cardiology", "Pulmonology",
                "General Medicine", "Orthopaedics", "Dermatology"}


def _months_between(a: pd.Timestamp, b: pd.Timestamp) -> float:
    return max((b - a).days / 30.4375, 1.0)


def build_patient_features(
    pat: pd.DataFrame,
    opd: pd.DataFrame,
    adm: pd.DataFrame,
    lab: pd.DataFrame,
    bill: pd.DataFrame,
    start: str,
    end: str,
    reference_date: str,
    label: str = "full",
) -> pd.DataFrame:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    ref = pd.Timestamp(reference_date)

    o = opd[(opd["visit_date"] >= start) & (opd["visit_date"] <= end)]
    a = adm[(adm["admission_date"] >= start) & (adm["admission_date"] <= end)]
    l = lab[(lab["test_date"] >= start) & (lab["test_date"] <= end)]
    b = bill[(bill["service_date"] >= start) & (bill["service_date"] <= end)]

    # ---------------------------------------------------------------- RFM core
    g = o.groupby("patient_id")
    f = pd.DataFrame({
        "last_visit_date": g["visit_date"].max(),
        "first_visit_date": g["visit_date"].min(),
        "frequency": g["visit_id"].count(),
        "n_departments": g["department"].nunique(),
        "n_hospitals": g["hospital_id"].nunique(),
        "n_doctors": g["doctor_id"].nunique(),
        "followup_visits": g["visit_type"].apply(lambda s: (s == "Follow-up").sum()),
    })

    # Monetary: corrected billing tied to this window, at patient level.
    mon = b.groupby("patient_id")["total_amount"].sum().rename("monetary")
    f = f.join(mon)
    f["monetary"] = f["monetary"].fillna(0.0)

    # ------------------------------------------------------------ admissions
    ag = a.groupby("patient_id")
    adm_f = pd.DataFrame({
        "admission_count": ag["admission_id"].count(),
        "avg_los_days": ag["los_days"].mean(),
        "total_bed_days": ag["los_days"].sum(),
        "icu_admissions": ag["icu_flag"].sum(),
        "expired_flag": ag["discharge_status"].apply(lambda s: int((s == "Expired").any())),
        "lama_flag": ag["discharge_status"].apply(lambda s: int((s == "LAMA").any())),
    })
    f = f.join(adm_f)
    f[["admission_count", "icu_admissions", "expired_flag", "lama_flag"]] = \
        f[["admission_count", "icu_admissions", "expired_flag", "lama_flag"]].fillna(0)

    # ----------------------------------------------------------- laboratory
    lg = l.groupby("patient_id")
    lab_f = pd.DataFrame({"lab_count": lg["test_id"].count(),
                          "lab_spend": lg["test_cost"].sum()})
    f = f.join(lab_f)
    f[["lab_count", "lab_spend"]] = f[["lab_count", "lab_spend"]].fillna(0)

    # ------------------------------------------------------- recency & tenure
    f["recency_days"] = (ref - f["last_visit_date"]).dt.days.clip(lower=1)
    f["tenure_days"] = (f["last_visit_date"] - f["first_visit_date"]).dt.days + 1
    f["tenure_months"] = (f["tenure_days"] / 30.4375).clip(lower=1)

    # ------------------------------------------------- normalised utilisation
    # IMPORTANT: the naive rate frequency / tenure_months is not usable as a
    # behavioural feature. A single-visit patient has tenure_months = 1, so the
    # naive rate is 1.0/month - the highest possible value - which inverts the
    # relationship (Spearman rho = -0.75 against frequency in the first run).
    # We therefore use a FIXED-WINDOW rate: visits over the shared observation
    # window, which is comparable across every patient. Intensity relative to the
    # patient's own tenure is kept separately as visits_per_active_month.
    window_months = max((end - start).days / 30.4375, 1.0)
    f["visits_per_month"] = (f["frequency"] / window_months).round(4)
    f["visits_per_active_month"] = (f["frequency"] / f["tenure_months"]).round(4)
    f["admission_rate"] = (f["admission_count"] / f["frequency"]).round(4)
    f["lab_per_visit"] = (f["lab_count"] / f["frequency"]).round(4)
    f["avg_billing_per_visit"] = (f["monetary"] / f["frequency"]).round(2)
    f["opd_to_admission_ratio"] = np.where(
        f["admission_count"] > 0, (f["frequency"] / f["admission_count"]).round(3), np.nan)
    f["bed_days_per_visit"] = (f["total_bed_days"].fillna(0) / f["frequency"]).round(4)
    f["dept_diversity"] = (f["n_departments"] / 12.0).round(4)   # share of the 12 depts used

    # --------------------------------------------------------- recent trend
    d90a, d90b = ref - pd.Timedelta(days=90), ref
    d90p = ref - pd.Timedelta(days=180)
    recent = o[(o["visit_date"] > d90a) & (o["visit_date"] <= d90b)] \
        .groupby("patient_id").size().rename("visits_last_90d")
    prior = o[(o["visit_date"] > d90p) & (o["visit_date"] <= d90a)] \
        .groupby("patient_id").size().rename("visits_prior_90d")
    f = f.join(recent).join(prior)
    f[["visits_last_90d", "visits_prior_90d"]] = \
        f[["visits_last_90d", "visits_prior_90d"]].fillna(0)
    f["recent_activity_ratio"] = (
        (f["visits_last_90d"] + 1) / (f["visits_prior_90d"] + 1)).round(4)

    # Visit growth: last 6 months of window vs the preceding 6 months
    half = end - pd.Timedelta(days=182)
    v_recent = o[o["visit_date"] > half].groupby("patient_id").size().rename("v_last6m")
    v_prior = o[(o["visit_date"] > half - pd.Timedelta(days=182)) &
                (o["visit_date"] <= half)].groupby("patient_id").size().rename("v_prior6m")
    f = f.join(v_recent).join(v_prior)
    f[["v_last6m", "v_prior6m"]] = f[["v_last6m", "v_prior6m"]].fillna(0)
    f["visit_growth_rate"] = np.where(
        f["v_prior6m"] > 0,
        ((f["v_last6m"] - f["v_prior6m"]) / f["v_prior6m"]).round(4),
        np.where(f["v_last6m"] > 0, 1.0, 0.0))

    # ------------------------------------------------ seasonality & clinical
    o2 = o.assign(month=o["visit_date"].dt.month)
    winter = o2[o2["month"].isin([11, 12, 1, 2])].groupby("patient_id").size()
    f["winter_visit_share"] = (winter.reindex(f.index).fillna(0) / f["frequency"]).round(4)

    o3 = o.assign(chronic=o["diagnosis_canonical"].isin(CHRONIC_DIAG).astype(int))
    f["chronic_share"] = o3.groupby("patient_id")["chronic"].mean().round(4)

    # ------------------------------------------------- follow-up compliance
    # A follow-up is compliant when the actual next visit happens within the
    # planned interval + 50% grace. This is only computable where a plan exists.
    o_sorted = o.sort_values(["patient_id", "visit_date"])
    nxt = o_sorted.groupby("patient_id")["visit_date"].shift(-1)
    gap = (nxt - o_sorted["visit_date"]).dt.days
    planned = o_sorted["planned_followup_days"]
    measurable = planned.gt(0) & gap.notna()
    compliant = measurable & (gap <= planned * 1.5) & (gap >= 0)
    comp = pd.DataFrame({"patient_id": o_sorted["patient_id"],
                         "measurable": measurable.values, "compliant": compliant.values})
    cg = comp[comp["measurable"]].groupby("patient_id")["compliant"]
    f["followup_measurable"] = cg.count().reindex(f.index).fillna(0).astype(int)
    f["followup_compliance"] = (cg.mean().reindex(f.index)).astype(float)
    f.loc[f["followup_measurable"] == 0, "followup_compliance"] = np.nan

    # -------------------------------------------------- readmission (30-day)
    a_s = a.sort_values(["patient_id", "admission_date"])
    next_adm = a_s.groupby("patient_id")["admission_date"].shift(-1)
    gap_days = (next_adm - a_s["discharge_date"]).dt.days
    readm = gap_days.notna() & (gap_days >= 0) & (gap_days <= 30)
    f["readmission_30d"] = readm.groupby(a_s["patient_id"]).sum().reindex(f.index).fillna(0).astype(int)

    # ------------------------------------------------------ demographic join
    f = f.join(pat.set_index("patient_id")[["age_years_clean", "gender",
                                            "home_hospital_id", "primary_payer",
                                            "consent_outreach", "age_band"]])
    f = f.rename(columns={"age_years_clean": "age"})
    f["primary_hospital"] = o.groupby("patient_id")["hospital_id"].agg(
        lambda s: s.mode().iat[0]).reindex(f.index)
    f["primary_department"] = o.groupby("patient_id")["department"].agg(
        lambda s: s.mode().iat[0]).reindex(f.index)
    f["window_label"] = label
    f["window_start"] = start
    f["window_end"] = end
    f["reference_date"] = ref
    return f.reset_index()


def build_outcomes(pat, opd, adm, lab, bill, start, end) -> pd.DataFrame:
    """Outcome window metrics only - used with features from an EARLIER window."""
    o = opd[(opd["visit_date"] >= start) & (opd["visit_date"] <= end)]
    a = adm[(adm["admission_date"] >= start) & (adm["admission_date"] <= end)]
    l = lab[(lab["test_date"] >= start) & (lab["test_date"] <= end)]
    b = bill[(bill["service_date"] >= start) & (bill["service_date"] <= end)]
    out = pd.DataFrame(index=pat["patient_id"])
    out["out_visits"] = o.groupby("patient_id").size().reindex(out.index).fillna(0).astype(int)
    out["out_admissions"] = a.groupby("patient_id").size().reindex(out.index).fillna(0).astype(int)
    out["out_labs"] = l.groupby("patient_id").size().reindex(out.index).fillna(0).astype(int)
    out["out_revenue"] = b.groupby("patient_id")["total_amount"].sum().reindex(out.index).fillna(0)
    out["out_los"] = a.groupby("patient_id")["los_days"].mean().reindex(out.index)
    out["out_retained"] = (out["out_visits"] > 0).astype(int)
    return out.reset_index()


if __name__ == "__main__":
    from cleaning import load_raw  # noqa
    pat = pd.read_parquet(C.DATA_PROC / "patients_clean.parquet")
    opd = pd.read_parquet(C.DATA_PROC / "opd_clean.parquet")
    adm = pd.read_parquet(C.DATA_PROC / "admissions_clean.parquet")
    lab = pd.read_parquet(C.DATA_PROC / "lab_clean.parquet")
    bill = pd.read_parquet(C.DATA_PROC / "billing_clean.parquet")
    F = build_patient_features(pat, opd, adm, lab, bill,
                               C.STUDY_START, C.STUDY_END, C.REFERENCE_DATE, "full")
    F.to_parquet(C.DATA_PROC / "patient_features_full.parquet", index=False)
    print(F.shape)
    print(F[["recency_days", "frequency", "monetary", "visits_per_month",
             "admission_rate", "lab_per_visit", "avg_billing_per_visit",
             "dept_diversity", "recent_activity_ratio", "visit_growth_rate",
             "followup_compliance"]].describe().round(2).to_string())
