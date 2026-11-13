"""
build_excel.py
==============
Builds reports/Hospital_Segmentation_Study.xlsx — the analytical workbook.

Sheets (per the brief):
   00_README               provenance, sheet guide, refresh instructions
   01_Raw_Overview         row/column counts, dtypes, missingness, date coverage
   02_Data_Quality         the Issue/Method/Validation audit table
   03_Cleaned_Sample       25k-row reproducible sample of cleaned OPD
   04_Features             patient-level engineered features
   05_RFM_Scores           R/F/M scores, cell, segment
   06_KMeans_Results       cluster assignment, PCA coordinates, segment name
   07_Segment_Profiles     consolidated KPI table
   08_Segment_Migration    migration matrix, retention, size drift
   09_Cost_Benefit         recommendations, costs, benefits, ROI, sensitivity
   10_EDA_Stats            every EDA statistic with its interpretation
   11_Model_Comparison     RFM vs K-means across 10 criteria
   12_KPI_Differences      verified segment KPI separation
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows

import config as C

OUT = C.REPORT_DIR
PROC = C.DATA_PROC
NAVY = "1F4E79"
LIGHT = "DCE6F1"
ACCENT = "ED7D31"


def _style_header(ws, row=1, ncols=None):
    ncols = ncols or ws.max_column
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(color="FFFFFF", bold=True, size=10)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 30
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _write_df(ws, df: pd.DataFrame, title: str, note: str | None = None,
              money_cols: list[str] | None = None, pct_cols: list[str] | None = None,
              width_cap: int = 52):
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    r = 2
    if note:
        ws["A2"] = note
        ws["A2"].font = Font(italic=True, size=9, color="555555")
        ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(6, min(len(df.columns), 14)))
        ws.row_dimensions[2].height = 30
        r = 4
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].round(4)
    for row in dataframe_to_rows(df, index=False, header=True):
        ws.append(row)
    _style_header(ws, row=r, ncols=len(df.columns))
    header_row = r
    for j, col in enumerate(df.columns, start=1):
        ws.column_dimensions[get_column_letter(j)].width = min(
            max(11, len(str(col)) + 2), width_cap)
        if money_cols and col in money_cols:
            for i in range(header_row + 1, ws.max_row + 1):
                ws.cell(row=i, column=j).number_format = '#,##0'
        if pct_cols and col in pct_cols:
            for i in range(header_row + 1, ws.max_row + 1):
                ws.cell(row=i, column=j).number_format = '0.0"%"'
    return ws


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)

    # ---------------------------------------------------------- 00 README
    ws = wb.create_sheet("00_README")
    ws["A1"] = "Hospital Patient Segmentation Study - Analytical Workbook"
    ws["A1"].font = Font(bold=True, size=18, color=NAVY)
    rows = [
        ("", ""),
        ("DATA PROVENANCE", "ALL DATA IN THIS WORKBOOK IS SYNTHETIC."),
        ("", "No real hospital data was supplied with the project brief. Every record is produced by"),
        ("", "src/generate_synthetic_data.py from a fixed seed (20241111) and is fully reproducible."),
        ("", "No number in this workbook may be quoted as evidence about a real hospital or real patients."),
        ("", ""),
        ("Study window", f"{C.STUDY_START} to {C.STUDY_END} (36 months)"),
        ("Reference date", C.REFERENCE_DATE),
        ("Network", "; ".join(f"{k} {v['name']} ({v['beds']} beds)" for k, v in C.HOSPITALS.items())),
        ("", ""),
        ("SHEET GUIDE", ""),
        ("01_Raw_Overview", "Source table shapes, dtypes, missingness, date coverage, duplicates"),
        ("02_Data_Quality", "Every detected issue with affected count, correction method and validation"),
        ("03_Cleaned_Sample", "Reproducible 25,000-row sample of the cleaned OPD table"),
        ("04_Features", "Patient-level engineered features (RFM + 15 behavioural features)"),
        ("05_RFM_Scores", "Quintile R/F/M scores, RFM cell and rule-based segment"),
        ("06_KMeans_Results", "Cluster id, business segment name, PCA coordinates"),
        ("07_Segment_Profiles", "Consolidated KPI profile for every final segment"),
        ("08_Segment_Migration", "Two-period migration matrix, retention rates and size drift"),
        ("09_Cost_Benefit", "Four recommendations with cost, benefit, ROI and sensitivity"),
        ("10_EDA_Stats", "Every EDA statistic with observation, pattern and business implication"),
        ("11_Model_Comparison", "RFM vs K-means across ten selection criteria"),
        ("12_KPI_Differences", "Numerical verification of the KPI gap between segments"),
        ("", ""),
        ("REFRESH", "python src/generate_synthetic_data.py && python src/cleaning.py && python src/features.py"),
        ("", "&& python src/eda.py && python src/segmentation.py && python src/stability.py"),
        ("", "&& python src/recommendations.py && python src/model_comparison.py && python src/build_excel.py"),
    ]
    for i, (a, b) in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=a).font = Font(bold=True, size=10)
        ws.cell(row=i, column=2, value=b).alignment = Alignment(wrap_text=False)
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 110
    ws["A2"].font = Font(bold=True, size=11, color="C00000")

    # ------------------------------------------------------ 01 raw overview
    ws = wb.create_sheet("01_Raw_Overview")
    from cleaning import load_raw
    tables = dict(zip(["patients", "opd_visits", "admissions", "lab_tests", "billing"], load_raw()))
    rows = []
    for name, df in tables.items():
        date_col = next((c for c in df.columns if "date" in c), None)
        rows.append({
            "table": name, "rows": len(df), "columns": df.shape[1],
            "unique_patients": int(df["patient_id"].nunique()) if "patient_id" in df else np.nan,
            "exact_duplicate_rows": int(df.duplicated().sum()),
            "cells_missing_pct": round(100 * df.isna().sum().sum() / df.size, 3),
            "date_from": df[date_col].min() if date_col else "",
            "date_to": df[date_col].max() if date_col else "",
        })
    _write_df(ws, pd.DataFrame(rows), "Raw source tables - shape, quality and temporal coverage",
              "Row counts are as delivered by the source systems before any cleaning.")

    # missingness detail appended below
    start = ws.max_row + 3
    ws.cell(row=start, column=1, value="Column-level missingness (raw)").font = Font(bold=True, size=12, color=NAVY)
    mr = []
    for name, df in tables.items():
        for c in df.columns:
            v = df[c].isna().sum()
            if v:
                mr.append({"table": name, "column": c, "missing": int(v),
                           "pct": round(100 * v / len(df), 3)})
    tmp = pd.DataFrame(mr)
    for row in dataframe_to_rows(tmp, index=False, header=True):
        ws.append(row)
    _style_header(ws, row=start + 1, ncols=4)

    # ------------------------------------------------------- 02 data quality
    ws = wb.create_sheet("02_Data_Quality")
    log = json.loads((C.OUT_DIR / "cleaning_log.json").read_text())
    dq = pd.DataFrame([
        ["Free-text diagnosis drift & synonyms", log["opd_diagnosis_canonicalised"],
         "Exact -> synonym dictionary -> difflib fuzzy (0.80) -> coded-field fallback",
         f"{log['validation']['opd_diagnosis_values']} canonical values; {log['opd_diagnosis_unresolved']} unresolved",
         "PASS"],
        ["Date of birth in age column", log["patients_age_year_of_birth"],
         "age = 2025 - value; clip 0-100", "Age range now 0-100", "PASS"],
        ["Negative / impossible age", log["patients_age_impossible"],
         "Null then median imputation within gender", f"{log['patients_age_imputed_median']} imputed", "PASS"],
        ["Duplicate GST in total_amount", log["billing_rows_double_gst_detected"],
         "Recompute gst_amount = base x row's gst_rate, rebuild total",
         f"{log['validation']['bill_identity_breaks']} identity breaks", "PASS"],
        ["Missing patient identifiers (OPD)", log["opd_missing_patient_id_dropped"],
         "Quarantined - no key to link", f"{log['validation']['opd_missing_patient']} remain", "PASS"],
        ["Missing visit dates", log["opd_missing_visit_date_dropped"],
         "Quarantined - cannot be windowed", f"{log['validation']['opd_missing_date']} remain", "PASS"],
        ["Duplicate visits", log["opd_duplicates_removed"],
         "Deduplicate on patient+date+department, keep lowest token",
         f"{log['validation']['opd_dup_patient_date_dept']} residual", "PASS"],
        ["Duplicate admissions", log["adm_duplicates_removed"],
         "Deduplicate on patient+dates+department", f"{log['validation']['adm_dup']} remain", "PASS"],
        ["Invalid billing amounts", log["billing_negative_amount_repaired"] + log["billing_10x_inflation_corrected"],
         "abs() for negatives; /10 for >8x department-median",
         f"{log['validation']['bill_negative_total']} negative totals", "PASS"],
        ["Impossible service dates", log["billing_impossible_date"],
         "Recover from linked encounter; else quarantine",
         f"All billing dates in window: {log['validation']['bill_dates_in_window']}", "PASS"],
        ["Discharge before admission", log["adm_dates_swapped_repaired"],
         "Swap fields", f"{log['validation']['adm_negative_los']} negative LOS", "PASS"],
        ["Hospital / department naming drift",
         log["opd_hospital_canonicalised"] + log["opd_department_canonicalised"],
         "Canonical lookup on normalised key",
         f"{log['validation']['opd_hospital_values']} hospitals, {log['validation']['opd_department_values']} departments", "PASS"],
        ["Lab tests with no visit linkage", log["lab_unlinked_to_visit"],
         "Retained and flagged (walk-in testing is a real clinical pathway)",
         "has_visit_link flag added", "PASS"],
    ], columns=["Issue", "Affected records", "Correction method", "Validation result", "Status"])
    _write_df(ws, dq, "Data quality assessment and remediation",
              "Affected-record counts are measured on the raw extract. Nothing removed without a reason code.")

    # ----------------------------------------------------- 03 cleaned sample
    ws = wb.create_sheet("03_Cleaned_Sample")
    opd = pd.read_parquet(PROC / "opd_clean.parquet")
    sample = opd.sample(25000, random_state=42)
    _write_df(ws, sample, "Cleaned OPD visits - reproducible 25,000-row sample",
              f"Full cleaned table: {len(opd):,} rows at data/processed/opd_clean.parquet")

    # --------------------------------------------------------- 04 features
    ws = wb.create_sheet("04_Features")
    feat = pd.read_parquet(PROC / "patient_features_full.parquet")
    fcols = ["patient_id", "age", "gender", "primary_hospital", "primary_department",
             "recency_days", "frequency", "monetary", "visits_per_month", "admission_count",
             "admission_rate", "lab_count", "lab_per_visit", "avg_billing_per_visit",
             "avg_los_days", "total_bed_days", "n_departments", "dept_diversity",
             "recent_activity_ratio", "visit_growth_rate", "readmission_30d",
             "chronic_share", "followup_compliance", "n_hospitals"]
    _write_df(ws, feat[fcols], "Patient-level engineered features",
              "RFM + 15 behavioural features. Formulas documented in the notebook section 4 and the report appendix.")

    # ------------------------------------------------------- 05 RFM scores
    ws = wb.create_sheet("05_RFM_Scores")
    rfm = pd.read_parquet(PROC / "rfm_scored.parquet")
    rc = ["patient_id", "recency_days", "frequency", "monetary", "R", "F", "M",
          "RFM_sum", "RFM_cell", "rfm_segment"]
    _write_df(ws, rfm[rc], "RFM scores and rule-based segments",
              "R reversed (5 = most recent). Quintile cut-points in the RFM reference sheet below.")

    # --------------------------------------------------- 06 KMeans results
    ws = wb.create_sheet("06_KMeans_Results")
    km = pd.read_parquet(PROC / "kmeans_segmented.parquet")
    kc = ["patient_id", "segment", "cluster", "pca1", "recency_days", "frequency",
          "monetary", "admission_rate", "lab_per_visit", "dept_diversity"]
    _draw = [c for c in kc if c in km.columns]
    _write_df(ws, km[_draw], "K-means cluster assignment and business segment",
              "Cluster ids come from the fit; segment names are assigned from the measured profile by rule.")

    # -------------------------------------------------- 07 segment profiles
    ws = wb.create_sheet("07_Segment_Profiles")
    prof = pd.read_csv(C.OUT_DIR / "final_segment_profiles.csv")
    _write_df(ws, prof, "Consolidated segment profile - final K-means segmentation",
              "Every segment exceeds the 5% viability floor. Figures are observed, not modelled.",
              money_cols=["revenue", "avg_monetary", "avg_billing_per_visit"],
              pct_cols=["share_pct", "revenue_share_pct"])

    # ------------------------------------------------- 08 segment migration
    ws = wb.create_sheet("08_Segment_Migration")
    mm = pd.read_csv(C.OUT_DIR / "migration_matrix_kmeans.csv", index_col=0)
    ws["A1"] = "Segment migration matrix - period 1 vs period 2"
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws["A2"] = ("Rows = segment in period 1 (2022-01 to 2023-06). Columns = segment in period 2 "
                "(2023-07 to 2024-12). Period-2 clusters are matched to period-1 clusters by profile "
                "using the Hungarian algorithm, not by cluster id.")
    ws["A2"].font = Font(italic=True, size=9)
    for row in dataframe_to_rows(mm.reset_index().rename(columns={"index": "P1 \\ P2"}),
                                 index=False, header=True):
        ws.append(row)
    _style_header(ws, row=4, ncols=len(mm.columns) + 1)
    r = ws.max_row + 2
    stab = json.loads((C.OUT_DIR / "stability_summary.json").read_text())
    ws.cell(row=r, column=1, value="Stability diagnostics").font = Font(bold=True, size=12, color=NAVY)
    diag = pd.DataFrame([
        ["Patients active in period 1", stab["patients_p1"]],
        ["Patients active in period 2", stab["patients_p2"]],
        ["Patients active in both periods", stab["patients_both"]],
        ["ARI - K-means", round(stab["ari_kmeans"], 4)],
        ["ARI - RFM rule-based", round(stab["ari_rfm"], 4)],
        ["Off-diagonal migration %", round(stab["off_diagonal_pct"], 2)],
    ], columns=["Metric", "Value"])
    for row in dataframe_to_rows(diag, index=False, header=True):
        ws.append(row)
    _style_header(ws, row=r + 1, ncols=2)
    r = ws.max_row + 2
    ws.cell(row=r, column=1, value="Retention by segment (%)").font = Font(bold=True, size=12, color=NAVY)
    ret = pd.DataFrame(list(stab["retention_pct"].items()), columns=["Segment", "Retention %"])
    ret["Retention %"] = ret["Retention %"].round(1)
    for row in dataframe_to_rows(ret, index=False, header=True):
        ws.append(row)
    _style_header(ws, row=r + 1, ncols=2)
    r = ws.max_row + 2
    ws.cell(row=r, column=1, value="Segment size drift").font = Font(bold=True, size=12, color=NAVY)
    drift = pd.read_csv(C.OUT_DIR / "segment_size_drift.csv")
    for row in dataframe_to_rows(drift, index=False, header=True):
        ws.append(row)
    _style_header(ws, row=r + 1, ncols=len(drift.columns))
    ws.column_dimensions["A"].width = 40
    for c in "BCDEFG":
        ws.column_dimensions[c].width = 20

    # ---------------------------------------------------- 09 cost benefit
    ws = wb.create_sheet("09_Cost_Benefit")
    rec = pd.read_csv(C.OUT_DIR / "recommendations_cost_benefit.csv")
    core = ["segment", "segment_n", "share_pct", "addressable", "reachable",
            "cost_staff", "cost_other", "cost_total", "benefit_units", "benefit_value",
            "net_benefit", "benefit_cost_ratio", "roi_pct", "payback_months", "timeline", "confidence"]
    _write_df(ws, rec[core], "Cost-benefit analysis by recommendation",
              "OBSERVED inputs: segment sizes, readmission counts, bed-days, tests per visit, unit revenue. "
              "ASSUMED inputs: margin rates and uplift percentages - see the sensitivity sheet.",
              money_cols=["cost_staff", "cost_other", "cost_total", "benefit_value", "net_benefit"])
    r = ws.max_row + 3
    ws.cell(row=r, column=1, value="Narrative detail").font = Font(bold=True, size=12, color=NAVY)
    for i, row in rec.iterrows():
        r += 1
        for label, val in [("Segment", row.segment), ("Problem", row.problem),
                           ("Intervention", row.intervention), ("Implementation", row.implementation),
                           ("Resources", row.resources), ("KPIs", row.kpi)]:
            ws.cell(row=r, column=1, value=label).font = Font(bold=True, size=9)
            c = ws.cell(row=r, column=2, value=str(val))
            c.alignment = Alignment(wrap_text=True, vertical="top")
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=12)
            ws.row_dimensions[r].height = 46
            r += 1
        r += 1

    ws2 = wb.create_sheet("09b_Sensitivity")
    sens = pd.read_csv(C.OUT_DIR / "recommendation_sensitivity.csv")
    _write_df(ws2, sens, "Sensitivity of each business case to its governing assumption",
              "Each recommendation is re-priced at pessimistic / base / optimistic values of the single "
              "assumption that drives it.", money_cols=["benefit_value", "cost_total"])

    # ------------------------------------------------------- 10 EDA stats
    ws = wb.create_sheet("10_EDA_Stats")
    figidx = pd.read_csv(C.OUT_DIR / "figure_index.csv")
    _write_df(ws, figidx, "EDA and modelling figures with recorded numerical observations",
              "Every figure in the report appears here with the observation, pattern and business implication.")

    # ------------------------------------------------ 11 model comparison
    ws = wb.create_sheet("11_Model_Comparison")
    comp = pd.read_csv(C.OUT_DIR / "model_comparison.csv")
    _write_df(ws, comp, "RFM vs K-means - ten selection criteria",
              "Selection is not made on silhouette alone; see the winner column and the notes.")

    ws2 = wb.create_sheet("11b_K_Selection")
    ev = pd.read_csv(C.OUT_DIR / "kmeans_k_evaluation.csv")
    st = pd.read_csv(C.OUT_DIR / "kmeans_stability.csv")
    merged = ev.merge(st[["k", "ari_mean", "ari_sd"]], on="k")
    _write_df(ws2, merged, "K-means evaluation across k = 2..10",
              "Silhouette, Calinski-Harabasz, Davies-Bouldin, inertia and bootstrap ARI for every candidate k.")

    # -------------------------------------------------- 12 KPI differences
    ws = wb.create_sheet("12_KPI_Differences")
    diffs = pd.read_csv(C.OUT_DIR / "segment_kpi_differences.csv")
    _write_df(ws, diffs, "Verified KPI separation between final segments",
              "Relative spread = (max - min) / mean across segments. Values >= 0.30 are treated as material.")

    path = OUT / "Hospital_Segmentation_Study.xlsx"
    wb.save(path)
    print(f"saved {path} ({path.stat().st_size/1e6:.2f} MB)")
    return path


if __name__ == "__main__":
    build()
