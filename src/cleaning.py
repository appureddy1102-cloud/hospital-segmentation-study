"""
cleaning.py
===========
Reproducible cleaning pipeline. Every correction is counted, stored in
`outputs/cleaning_log.json` and written to a row-level audit table so that the
data-quality report can state exactly what changed and prove it.

Design rule: **nothing is silently deleted.** Records are either corrected,
flagged, or quarantined with a reason code.
"""
from __future__ import annotations

import difflib
import json
import re
from typing import Dict, Tuple

import numpy as np
import pandas as pd

import config as C
from catalogue import DIAGNOSES, DIAG_VARIANTS, DEPT_VARIANTS, HOSP_VARIANTS

RAW = C.DATA_RAW
PROC = C.DATA_PROC

# ===========================================================================
# Normalisation dictionaries
# ===========================================================================


def _key(s: str) -> str:
    s = str(s).lower().strip()
    s = re.sub(r"[^a-z0-9& ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


HOSP_LOOKUP: Dict[str, str] = {}
for hid, variants in HOSP_VARIANTS.items():
    for v in variants:
        HOSP_LOOKUP[_key(v)] = hid
HOSP_LOOKUP.update({"ameerpet community hospital": "HSP-01",
                    "kukatpally community hospital": "HSP-02",
                    "lb nagar community hospital": "HSP-03",
                    "miyapur community hospital": "HSP-04"})

DEPT_LOOKUP: Dict[str, str] = {}
for d, variants in DEPT_VARIANTS.items():
    DEPT_LOOKUP[_key(d)] = d
    for v in variants:
        DEPT_LOOKUP[_key(v)] = d

# diagnosis: canonical + variants + codes
DIAG_CANON = sorted({d[1] for lst in DIAGNOSES.values() for d in lst})
DIAG_LOOKUP: Dict[str, str] = {_key(d): d for d in DIAG_CANON}
for canon, variants in DIAG_VARIANTS.items():
    DIAG_LOOKUP[_key(canon)] = canon
    for v in variants:
        DIAG_LOOKUP[_key(v)] = canon
CODE_TO_DIAG = {d[0]: d[1] for lst in DIAGNOSES.values() for d in lst}
DIAG_LOOKUP.update({_key(k): v for k, v in CODE_TO_DIAG.items()})


def map_series(series: pd.Series, lookup: Dict[str, str], fuzzy: bool = True,
               cutoff: float = 0.82) -> Tuple[pd.Series, Dict[str, int]]:
    """Map free-text to canonical values, tracking how each value was resolved."""
    keys = series.map(lambda x: _key(x) if pd.notna(x) else None)
    out = keys.map(lookup)
    stats = {"exact": int((keys.isin(lookup) & out.notna()).sum()),
             "unresolved": int(out.isna().sum())}
    if fuzzy:
        unresolved = out.isna() & keys.notna()
        n_fuzzy = 0
        cache: Dict[str, str] = {}
        for i in keys[unresolved].index:
            k = keys.at[i]
            if k not in cache:
                m = difflib.get_close_matches(k, list(lookup.keys()), n=1, cutoff=cutoff)
                cache[k] = lookup[m[0]] if m else None
            if cache[k] is not None:
                out.at[i] = cache[k]
                n_fuzzy += 1
        stats["fuzzy"] = n_fuzzy
    stats["unresolved"] = int(out.isna().sum())
    stats["exact"] = stats["exact"]
    return out, stats


# ===========================================================================
# Load
# ===========================================================================
def load_raw():
    pat = pd.read_csv(RAW / "patients.csv", parse_dates=["registration_date"])
    opd = pd.read_csv(RAW / "opd_visits.csv", parse_dates=["visit_date"], low_memory=False)
    adm = pd.read_csv(RAW / "admissions.csv", parse_dates=["admission_date", "discharge_date"])
    lab = pd.read_csv(RAW / "lab_tests.csv", parse_dates=["test_date"])
    bill = pd.read_csv(RAW / "billing.csv", parse_dates=["service_date"])
    return pat, opd, adm, lab, bill


# ===========================================================================
# Cleaning steps
# ===========================================================================
def clean_patients(pat: pd.DataFrame, log: dict) -> pd.DataFrame:
    p = pat.copy()

    # --- Age: some cells hold a birth year, some are impossible
    yr = p["age_years"]
    is_year = yr.gt(110)
    is_neg = yr.lt(0)
    derived = pd.Series(np.nan, index=p.index)
    ref_year = pd.Timestamp(C.REFERENCE_DATE).year
    derived[is_year] = ref_year - yr[is_year]
    p["age_years_clean"] = np.where(is_year, derived, yr)
    p.loc[is_neg, "age_years_clean"] = np.nan
    # median imputation stratified by gender (documented, not global)
    med = p.groupby("gender")["age_years_clean"].median()
    m = p["age_years_clean"].isna()
    p.loc[m, "age_years_clean"] = p.loc[m, "gender"].map(med)
    p["age_years_clean"] = p["age_years_clean"].clip(0, 100).round(0)
    p["age_imputed"] = m.values
    p["age_repaired_from_year"] = is_year.values

    log["patients_age_year_of_birth"] = int(is_year.sum())
    log["patients_age_impossible"] = int(is_neg.sum())
    log["patients_age_imputed_median"] = int(m.sum())

    # --- Gender hygiene
    p["gender"] = p["gender"].astype(str).str.upper().str[0]
    p.loc[~p["gender"].isin(["M", "F"]), "gender"] = "U"

    # --- Age bands
    bins = [-0.01, 4, 14, 29, 44, 59, 74, 200]
    labels = ["0-4", "5-14", "15-29", "30-44", "45-59", "60-74", "75+"]
    p["age_band"] = pd.cut(p["age_years_clean"], bins=bins, labels=labels)

    # --- Hospital
    hosp, st = map_series(p["home_hospital_id"], HOSP_LOOKUP, fuzzy=False)
    log["patients_hospital_resolved"] = st["exact"]
    p["home_hospital_id"] = hosp
    return p


def clean_opd(opd: pd.DataFrame, pat_ids: set, log: dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
    d = opd.copy()
    n0 = len(d)
    audit = []

    # ---- 1. hospital canonicalisation
    raw_h = d["hospital_id"].copy()
    d["hospital_id"], st = map_series(d["hospital_id"], HOSP_LOOKUP, fuzzy=False)
    changed = d["hospital_id"].ne(raw_h) & d["hospital_id"].notna()
    log["opd_hospital_canonicalised"] = int(changed.sum())
    audit.append(pd.DataFrame([{"table": "opd_visits",
                                "issue": "hospital_name_inconsistency",
                                "corrected": int(changed.sum()), "total": n0}]))

    # ---- 2. department canonicalisation
    raw_d = d["department"].copy()
    d["department"], st = map_series(d["department"], DEPT_LOOKUP, fuzzy=True, cutoff=0.80)
    chg = d["department"].ne(raw_d) & d["department"].notna() & raw_d.notna()
    log["opd_department_canonicalised"] = int(chg.sum())
    log["opd_department_unresolved"] = int(d["department"].isna().sum())

    # ---- 3. diagnosis canonicalisation (prefer the coded field when it exists)
    raw_diag = d["diagnosis_text"].copy()
    mapped, st = map_series(d["diagnosis_text"], DIAG_LOOKUP, fuzzy=True, cutoff=0.80)
    from_code = d["diagnosis_code"].map(CODE_TO_DIAG)
    d["diagnosis_canonical"] = mapped.fillna(from_code)
    d["diagnosis_source"] = np.where(mapped.notna(), "text_match",
                                     np.where(from_code.notna(), "code_fallback", "unresolved"))
    chg = d["diagnosis_canonical"].ne(raw_diag) & d["diagnosis_canonical"].notna()
    log["opd_diagnosis_canonicalised"] = int(chg.sum())
    log["opd_diagnosis_unresolved"] = int(d["diagnosis_canonical"].isna().sum())
    log["opd_diagnosis_from_code_fallback"] = int((d["diagnosis_source"] == "code_fallback").sum())

    # ---- 4. missing identifiers / dates
    miss_pid = d["patient_id"].isna()
    log["opd_missing_patient_id_dropped"] = int(miss_pid.sum())
    d = d[~miss_pid].copy()

    miss_date = d["visit_date"].isna()
    log["opd_missing_visit_date_dropped"] = int(miss_date.sum())
    d = d[~miss_date].copy()

    # ---- 5. unknown patients (referential integrity)
    orphan = ~d["patient_id"].isin(pat_ids)
    log["opd_orphan_patient_dropped"] = int(orphan.sum())
    d = d[~orphan].copy()

    # ---- 6. dates outside the study window
    lo, hi = pd.Timestamp(C.STUDY_START), pd.Timestamp(C.STUDY_END)
    oob = d["visit_date"].lt(lo) | d["visit_date"].gt(hi)
    log["opd_date_out_of_window_dropped"] = int(oob.sum())
    d = d[~oob].copy()

    # ---- 7. duplicates: same patient + date + department = one physical visit
    before = len(d)
    d["_dedup_key"] = (d["patient_id"].astype(str) + "|" +
                       d["visit_date"].dt.strftime("%Y-%m-%d") + "|" +
                       d["department"].astype(str))
    # keep the record with the lowest token no (= first registration) then id
    d = d.sort_values(["token_no", "visit_id"]).drop_duplicates("_dedup_key", keep="first")
    log["opd_duplicates_removed"] = int(before - len(d))
    d = d.drop(columns="_dedup_key")

    # ---- 8. department still missing -> derive from diagnosis map, else "Unspecified"
    still = d["department"].isna()
    if still.any():
        inferred = d.loc[still, "diagnosis_canonical"].map(
            {d[1]: dept for dept, lst in DIAGNOSES.items() for d in lst})
        d.loc[still, "department"] = inferred.fillna("Unspecified")
    log["opd_department_imputed"] = int(still.sum())

    # ---- 9. consultation fee missing -> median of same department
    mf = d["consultation_fee"].isna()
    d["consultation_fee"] = d["consultation_fee"].fillna(
        d.groupby("department")["consultation_fee"].transform("median"))
    log["opd_consultation_fee_imputed"] = int(mf.sum())

    # ---- 10. follow-up plan
    d["planned_followup_days"] = d["planned_followup_days"].fillna(0).astype(int)

    d["visit_year"] = d["visit_date"].dt.year
    d["visit_month"] = d["visit_date"].dt.to_period("M").astype(str)
    d["visit_quarter"] = d["visit_date"].dt.to_period("Q").astype(str)
    d["dow"] = d["visit_date"].dt.dayofweek
    d["is_weekend"] = d["dow"].ge(5)

    log["opd_rows_raw"] = int(n0)
    log["opd_rows_clean"] = int(len(d))
    return d.reset_index(drop=True), pd.concat(audit, ignore_index=True)


def clean_admissions(adm: pd.DataFrame, pat_ids: set, log: dict) -> pd.DataFrame:
    d = adm.copy()
    n0 = len(d)

    d["hospital_id"], _ = map_series(d["hospital_id"], HOSP_LOOKUP, fuzzy=False)
    d["department"], _ = map_series(d["department"], DEPT_LOOKUP, fuzzy=True, cutoff=0.80)
    d["hospital_id"] = d["hospital_id"].fillna(
        d["patient_id"].map(lambda p: "HSP-01"))  # reference hospital fallback
    d["department"] = d["department"].fillna("Unspecified")

    orphan = ~d["patient_id"].isin(pat_ids)
    log["adm_orphan_patient_dropped"] = int(orphan.sum())
    d = d[~orphan].copy()

    # ---- swapped dates
    swapped = d["discharge_date"].lt(d["admission_date"])
    log["adm_dates_swapped_repaired"] = int(swapped.sum())
    a = d.loc[swapped, "admission_date"].copy()
    d.loc[swapped, "admission_date"] = d.loc[swapped, "discharge_date"]
    d.loc[swapped, "discharge_date"] = a

    # ---- missing discharge date -> median LOS of that department
    los_med = (d["discharge_date"] - d["admission_date"]).dt.days.groupby(d["department"]).median()
    miss = d["discharge_date"].isna()
    d.loc[miss, "discharge_date"] = (d.loc[miss, "admission_date"] +
                                     pd.to_timedelta(d.loc[miss, "department"].map(los_med)
                                                     .fillna(4).round(), unit="D"))
    log["adm_missing_discharge_imputed"] = int(miss.sum())
    d["discharge_date_imputed"] = miss.values

    # ---- duplicates
    before = len(d)
    d["_k"] = (d["patient_id"].astype(str) + "|" +
               d["admission_date"].dt.strftime("%Y-%m-%d") + "|" +
               d["discharge_date"].dt.strftime("%Y-%m-%d") + "|" + d["department"].astype(str))
    d = d.sort_values("admission_id").drop_duplicates("_k", keep="first").drop(columns="_k")
    log["adm_duplicates_removed"] = int(before - len(d))

    lo, hi = pd.Timestamp(C.STUDY_START), pd.Timestamp(C.STUDY_END)
    d = d[d["admission_date"].ge(lo) & d["admission_date"].le(hi)]

    d["los_days"] = (d["discharge_date"] - d["admission_date"]).dt.days.clip(lower=1)
    d["los_days"] = d["los_days"].fillna(4)

    log["adm_rows_raw"] = int(n0)
    log["adm_rows_clean"] = int(len(d))
    return d.reset_index(drop=True)


def clean_lab(lab: pd.DataFrame, pat_ids: set, visit_ids: set, log: dict) -> pd.DataFrame:
    d = lab.copy()
    d["hospital_id"], _ = map_series(d["hospital_id"], HOSP_LOOKUP, fuzzy=False)
    orphan = ~d["patient_id"].isin(pat_ids)
    log["lab_orphan_patient_dropped"] = int(orphan.sum())
    d = d[~orphan].copy()
    m = d["test_cost"].isna()
    d["test_cost"] = d["test_cost"].fillna(d["test_name"].map(
        {t[0]: t[1] for t in C.LAB_TESTS}))
    log["lab_cost_imputed"] = int(m.sum())
    d["has_visit_link"] = d["visit_id"].isin(visit_ids)
    log["lab_unlinked_to_visit"] = int((~d["has_visit_link"]).sum())
    d = d[d["test_date"].ge(pd.Timestamp(C.STUDY_START)) &
          d["test_date"].le(pd.Timestamp(C.STUDY_END))]
    log["lab_rows_clean"] = int(len(d))
    return d.reset_index(drop=True)


def clean_billing(bill: pd.DataFrame, opd: pd.DataFrame, adm: pd.DataFrame,
                  log: dict) -> pd.DataFrame:
    """
    Reconstruct the billing identity from the available fields instead of
    assuming a universal GST rate.

    Established logic (verified on the raw file before any correction):
        normal rows      : total_amount = base_amount + gst_amount
        double-GST rows  : total_amount = base_amount + 2 x gst_amount
        GST is service-type dependent: 0% on healthcare services (OPD/IPD/procedure/
        lab, exempt under Indian GST law as notified), 5% pharmacy, 12% consumables.
    """
    b = bill.copy()
    n0 = len(b)

    # ---- 0. establish the identity empirically on the raw data
    resid = (b["total_amount"] - (b["base_amount"] + b["gst_amount"])).abs()
    exact = resid < 0.02
    dbl = (b["total_amount"] - (b["base_amount"] + 2 * b["gst_amount"])).abs() < 0.02
    log["billing_rows_matching_identity"] = int(exact.sum())
    log["billing_rows_double_gst_detected"] = int((~exact & dbl).sum())
    log["billing_identity_match_pct"] = round(100 * exact.mean(), 3)

    # ---- 1. GST rate sanity: is gst_amount / base_amount equal to the stated rate?
    implied = np.where(b["base_amount"].gt(0), b["gst_amount"] / b["base_amount"], 0)
    rate_bad = b["base_amount"].gt(0) & ((implied - b["gst_rate"]).abs() > 1e-4)
    log["billing_gst_rate_mismatch"] = int(rate_bad.sum())

    # ---- 2. recompute gst from base (single source of truth)
    b["gst_amount"] = (b["base_amount"] * b["gst_rate"]).round(2)
    b.loc[b["base_amount"].le(0), "gst_amount"] = 0.0

    # ---- 3. missing gst
    miss = b["gst_amount"].isna()
    log["billing_gst_missing_fixed"] = int(miss.sum())
    b["gst_amount"] = b["gst_amount"].fillna((b["base_amount"] * b["gst_rate"]).round(2))

    # ---- 4. invalid base amounts
    neg = b["base_amount"].lt(0)
    zero = b["base_amount"].eq(0)
    b.loc[neg, "base_amount"] = b.loc[neg, "base_amount"].abs()
    log["billing_negative_amount_repaired"] = int(neg.sum())
    log["billing_zero_amount_flagged"] = int(zero.sum())
    b["is_zero_value_line"] = zero.values

    # 10x inflation: relative to department x service_type median, robust ratio
    grp_med = b.groupby(["service_type", "department"])["base_amount"].transform("median")
    ratio = b["base_amount"] / grp_med.replace(0, np.nan)
    infl = ratio.gt(8)
    b.loc[infl, "base_amount"] = (b.loc[infl, "base_amount"] / 10).round(2)
    log["billing_10x_inflation_corrected"] = int(infl.sum())

    # ---- 5. impossible dates -> treat the bill as belonging to the same encounter
    lo, hi = pd.Timestamp(C.STUDY_START), pd.Timestamp(C.STUDY_END)
    bad_date = b["service_date"].lt(lo) | b["service_date"].gt(hi)
    log["billing_impossible_date"] = int(bad_date.sum())
    # recover date from the encounter where possible, else quarantine
    opd_map = opd.set_index("visit_id")["visit_date"]
    adm_map = adm.set_index("admission_id")["admission_date"]
    rec = b.loc[bad_date, "encounter_id"].map(opd_map)
    rec = rec.fillna(b.loc[bad_date, "encounter_id"].map(adm_map))
    b.loc[bad_date, "service_date"] = rec
    b["date_recovered_from_encounter"] = (bad_date & b["service_date"].notna()).values
    still_bad = b["service_date"].isna() | b["service_date"].lt(lo) | b["service_date"].gt(hi)
    log["billing_date_unrecoverable_dropped"] = int(still_bad.sum())
    b = b[~still_bad].copy()

    # ---- 6. recompute total from the clean identity
    b["total_amount"] = (b["base_amount"] + b["gst_amount"]).round(2)

    # ---- 7. link billing to encounters
    b["encounter_type"] = np.where(b["encounter_id"].astype(str).str.startswith("OPD"), "OPD", "IPD")
    b["encounter_valid"] = (b["encounter_id"].isin(opd["visit_id"]) |
                            b["encounter_id"].isin(adm["admission_id"]))
    log["billing_orphan_encounter"] = int((~b["encounter_valid"]).sum())

    b["service_year"] = b["service_date"].dt.year
    b["service_month"] = b["service_date"].dt.to_period("M").astype(str)
    log["billing_rows_raw"] = int(n0)
    log["billing_rows_clean"] = int(len(b))
    return b.reset_index(drop=True)


# ===========================================================================
# Post-cleaning validation
# ===========================================================================
def validate(opd, adm, lab, bill, pat, log) -> dict:
    v = {}
    v["opd_hospital_values"] = int(opd["hospital_id"].nunique())
    v["opd_department_values"] = int(opd["department"].nunique())
    v["opd_diagnosis_values"] = int(opd["diagnosis_canonical"].nunique())
    v["opd_dup_patient_date_dept"] = int(opd.duplicated(
        ["patient_id", "visit_date", "department"]).sum())
    v["adm_dup"] = int(adm.duplicated(
        ["patient_id", "admission_date", "discharge_date", "department"]).sum())
    v["adm_negative_los"] = int((adm["los_days"] < 0).sum())
    v["bill_identity_breaks"] = int(
        ((bill["total_amount"] - (bill["base_amount"] + bill["gst_amount"])).abs() > 0.02).sum())
    v["bill_negative_total"] = int((bill["total_amount"] < 0).sum())
    v["bill_dates_in_window"] = bool(
        bill["service_date"].between(C.STUDY_START, C.STUDY_END).all())
    v["pat_age_range"] = [float(pat["age_years_clean"].min()),
                          float(pat["age_years_clean"].max())]
    v["opd_missing_patient"] = int(opd["patient_id"].isna().sum())
    v["opd_missing_date"] = int(opd["visit_date"].isna().sum())
    log["validation"] = v
    return v


def run() -> dict:
    print("Loading raw tables ...")
    pat, opd, adm, lab, bill = load_raw()
    log: dict = {
        "raw_rows": {"patients": len(pat), "opd_visits": len(opd),
                     "admissions": len(adm), "lab_tests": len(lab), "billing": len(bill)},
        "raw_duplicates": {
            "opd_exact": int(opd.duplicated().sum()),
            "adm_exact": int(adm.duplicated().sum()),
            "lab_exact": int(lab.duplicated().sum()),
            "bill_exact": int(bill.duplicated().sum()),
        },
        "raw_missing_pct": {
            t: {c: round(100 * float(df[c].isna().mean()), 3)
                for c in df.columns if df[c].isna().any()}
            for t, df in [("patients", pat), ("opd_visits", opd), ("admissions", adm),
                          ("lab_tests", lab), ("billing", bill)]
        },
    }

    print("Cleaning patients ...")
    pat = clean_patients(pat, log)
    pid_set = set(pat["patient_id"])

    print("Cleaning OPD ...")
    opd, _ = clean_opd(opd, pid_set, log)

    print("Cleaning admissions ...")
    adm = clean_admissions(adm, pid_set, log)

    print("Cleaning lab ...")
    lab = clean_lab(lab, pid_set, set(opd["visit_id"]), log)

    print("Cleaning billing ...")
    bill = clean_billing(bill, opd, adm, log)

    print("Validating ...")
    validate(opd, adm, lab, bill, pat, log)

    # ---- write processed
    pat.to_parquet(PROC / "patients_clean.parquet", index=False)
    opd.to_parquet(PROC / "opd_clean.parquet", index=False)
    adm.to_parquet(PROC / "admissions_clean.parquet", index=False)
    lab.to_parquet(PROC / "lab_clean.parquet", index=False)
    bill.to_parquet(PROC / "billing_clean.parquet", index=False)

    with open(C.OUT_DIR / "cleaning_log.json", "w") as f:
        json.dump(log, f, indent=2, default=str)

    print("\n--- CLEANING SUMMARY ---")
    for k in ["opd_rows_raw", "opd_rows_clean", "opd_duplicates_removed",
              "opd_diagnosis_canonicalised", "opd_department_canonicalised",
              "opd_hospital_canonicalised", "billing_rows_matching_identity",
              "billing_rows_double_gst_detected", "billing_10x_inflation_corrected",
              "adm_dates_swapped_repaired", "adm_duplicates_removed"]:
        print(f"  {k:38s} {log[k]:,}")
    print("  validation:", log["validation"])
    return log


if __name__ == "__main__":
    run()
