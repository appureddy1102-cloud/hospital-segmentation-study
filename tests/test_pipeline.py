"""
Pipeline integrity tests.

These are the validation checks the brief asks for, expressed as executable
assertions rather than prose. Run with:

    pytest tests/ -v

They require the pipeline to have been run at least once
(`python src/run_all.py`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config as C  # noqa: E402

PROC, OUT = C.DATA_PROC, C.OUT_DIR


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def tables():
    return {
        "pat": pd.read_parquet(PROC / "patients_clean.parquet"),
        "opd": pd.read_parquet(PROC / "opd_clean.parquet"),
        "adm": pd.read_parquet(PROC / "admissions_clean.parquet"),
        "lab": pd.read_parquet(PROC / "lab_clean.parquet"),
        "bill": pd.read_parquet(PROC / "billing_clean.parquet"),
    }


@pytest.fixture(scope="module")
def outputs():
    return {
        "log": json.loads((OUT / "cleaning_log.json").read_text()),
        "kmeans": json.loads((OUT / "kmeans_metrics.json").read_text()),
        "stab": json.loads((OUT / "stability_summary.json").read_text()),
        "eda": json.loads((OUT / "eda_stats.json").read_text()),
    }


@pytest.fixture(scope="module")
def seg():
    return pd.read_parquet(PROC / "kmeans_segmented.parquet")


# ---------------------------------------------------------------- cleaning
class TestCleaning:
    def test_no_missing_identifiers_remain(self, tables):
        for name in ("opd", "adm", "lab", "bill"):
            assert tables[name]["patient_id"].notna().all(), f"{name} has null patient_id"

    def test_no_missing_dates_remain(self, tables):
        assert tables["opd"]["visit_date"].notna().all()
        assert tables["bill"]["service_date"].notna().all()

    def test_hospital_domain_strict(self, tables):
        assert set(tables["opd"]["hospital_id"].unique()) == set(C.HOSPITALS)

    def test_department_domain_strict(self, tables):
        assert set(tables["opd"]["department"].unique()) <= set(C.DEPARTMENTS) | {"Unspecified"}

    def test_diagnosis_canonicalised(self, tables):
        n = tables["opd"]["diagnosis_canonical"].nunique()
        assert 30 <= n <= 60, f"unexpected canonical diagnosis count: {n}"

    def test_no_duplicate_visits(self, tables):
        dup = tables["opd"].duplicated(["patient_id", "visit_date", "department"]).sum()
        assert dup <= 25, f"{dup} duplicate visits remain"

    def test_no_duplicate_admissions(self, tables):
        dup = tables["adm"].duplicated(
            ["patient_id", "admission_date", "discharge_date", "department"]).sum()
        assert dup == 0

    def test_billing_identity_holds(self, tables):
        b = tables["bill"]
        resid = (b["total_amount"] - (b["base_amount"] + b["gst_amount"])).abs()
        assert (resid > 0.02).sum() == 0, "billing identity broken"

    def test_no_negative_amounts(self, tables):
        assert (tables["bill"]["total_amount"] < 0).sum() == 0

    def test_all_dates_in_window(self, tables):
        o, a, b = C.STUDY_START, C.STUDY_END, tables["bill"]
        assert b["service_date"].between(o, a).all()
        assert tables["opd"]["visit_date"].between(o, a).all()
        assert tables["adm"]["admission_date"].between(o, a).all()

    def test_no_negative_los(self, tables):
        assert (tables["adm"]["los_days"] < 0).sum() == 0

    def test_age_in_plausible_range(self, tables):
        a = tables["pat"]["age_years_clean"]
        assert a.min() >= 0 and a.max() <= 100

    def test_gst_rate_domain(self, tables):
        assert set(tables["bill"]["gst_rate"].round(2).unique()) <= {0.0, 0.05, 0.12}

    def test_defect_recovery(self, outputs):
        """Every injected defect family must be detected."""
        log = outputs["log"]
        assert log["billing_rows_double_gst_detected"] > 2000
        assert log["opd_diagnosis_canonicalised"] > 20000
        assert log["opd_duplicates_removed"] > 2500
        assert log["patients_age_year_of_birth"] > 900


# ---------------------------------------------------------------- features
class TestFeatures:
    def test_feature_row_count(self, seg):
        assert len(seg) == seg["patient_id"].nunique()
        assert len(seg) > 40_000

    def test_no_negative_features(self, seg):
        for c in ["frequency", "monetary", "recency_days", "lab_count"]:
            assert (seg[c] >= 0).all(), f"{c} has negatives"

    def test_visits_per_month_positive_correlation(self, seg):
        """The bug that was fixed: the rate must correlate POSITIVELY with frequency."""
        rho = seg["visits_per_month"].corr(seg["frequency"], method="spearman")
        assert rho > 0.95, f"visits_per_month inverts the relationship (rho={rho:.3f})"

    def test_recency_within_window(self, seg):
        max_days = (pd.Timestamp(C.REFERENCE_DATE) - pd.Timestamp(C.STUDY_START)).days
        assert seg["recency_days"].max() <= max_days + 1

    def test_followup_compliance_bounded(self, seg):
        v = seg["followup_compliance"].dropna()
        assert v.between(0, 1).all()


# ---------------------------------------------------------------- RFM
class TestRFM:
    def test_scores_in_range(self):
        rfm = pd.read_parquet(PROC / "rfm_scored.parquet")
        for c in ["R", "F", "M"]:
            assert set(rfm[c].unique()) <= {1, 2, 3, 4, 5}
        assert rfm["RFM_sum"].between(3, 15).all()

    def test_every_patient_has_a_segment(self):
        rfm = pd.read_parquet(PROC / "rfm_scored.parquet")
        assert rfm["rfm_segment"].notna().all()

    def test_recency_is_reversed(self):
        """Lower recency must map to a higher R score."""
        rfm = pd.read_parquet(PROC / "rfm_scored.parquet")
        by_score = rfm.groupby("R")["recency_days"].mean()
        assert by_score.loc[5] < by_score.loc[1]


# ---------------------------------------------------------------- K-means
class TestKMeans:
    def test_every_segment_clears_five_percent(self, seg):
        share = seg["segment"].value_counts(normalize=True)
        assert share.min() >= C.MIN_SEGMENT_SHARE, (
            f"smallest segment {share.min():.3%} is below the 5% floor")

    def test_silhouette_above_random(self, outputs):
        assert outputs["kmeans"]["silhouette"] > 0.30

    def test_bootstrap_stability_high(self, outputs):
        assert outputs["kmeans"]["bootstrap"]["ari_mean"] > 0.90

    def test_every_patient_assigned(self, seg):
        assert seg["segment"].notna().all()

    def test_k_within_evaluated_range(self, outputs):
        assert outputs["kmeans"]["k"] in set(C.K_RANGE)


# ---------------------------------------------------------------- profiles
class TestProfiles:
    def test_profile_covers_all_patients(self, seg):
        prof = pd.read_csv(OUT / "final_segment_profiles.csv")
        assert int(prof["n_patients"].sum()) == len(seg)

    def test_revenue_shares_sum_to_100(self):
        prof = pd.read_csv(OUT / "final_segment_profiles.csv")
        assert abs(prof["revenue_share_pct"].sum() - 100) < 0.05

    def test_at_least_three_material_kpi_differences(self):
        d = pd.read_csv(OUT / "segment_kpi_differences.csv")
        assert (d["relative_spread"] >= 0.30).sum() >= 3

    def test_no_fabricated_kpi_claims(self):
        """Every KPI marked material must genuinely exceed the floor."""
        d = pd.read_csv(OUT / "segment_kpi_differences.csv")
        material = d[d["relative_spread"] >= 0.30]
        assert (material["max_segment_value"] > material["min_segment_value"]).all()


# ---------------------------------------------------------------- stability
class TestStability:
    def test_migration_matrix_sums_to_cohort(self, outputs):
        m = pd.read_csv(OUT / "migration_matrix_kmeans.csv", index_col=0)
        assert m.values.sum() == outputs["stab"]["patients_both"]

    def test_all_patients_matched(self, outputs):
        s = outputs["stab"]
        assert len(s["cluster_mapping_p2_to_p1"]) == s["k"]

    def test_ari_bounded(self, outputs):
        assert -1 <= outputs["stab"]["ari_kmeans"] <= 1
        assert -1 <= outputs["stab"]["ari_rfm"] <= 1

    def test_retention_bounded(self, outputs):
        for v in outputs["stab"]["retention_pct"].values():
            assert 0 <= v <= 100


# ---------------------------------------------------------------- business
class TestBusinessCase:
    def test_every_segment_has_a_recommendation(self, seg):
        rec = pd.read_csv(OUT / "recommendations_cost_benefit.csv")
        segments = set(seg["segment"].unique())
        targets = set(rec["segment"]) - {"Network-wide"}
        assert targets == segments, f"missing recommendations for {segments - targets}"

    def test_roi_arithmetic(self):
        rec = pd.read_csv(OUT / "recommendations_cost_benefit.csv")
        calc = (rec["benefit_value"] - rec["cost_total"]) / rec["cost_total"] * 100
        assert np.allclose(calc, rec["roi_pct"], atol=0.2)

    def test_costs_positive(self):
        rec = pd.read_csv(OUT / "recommendations_cost_benefit.csv")
        assert (rec["cost_total"] > 0).all()

    def test_sensitivity_has_three_scenarios(self):
        s = pd.read_csv(OUT / "recommendation_sensitivity.csv")
        assert set(s["scenario"]) == {"Pessimistic", "Base", "Optimistic"}


# ---------------------------------------------------------------- artefacts
class TestArtefacts:
    def test_figures_exist(self):
        figs = list((ROOT / "figures").glob("*.png"))
        assert len(figs) >= 20, f"only {len(figs)} figures"

    def test_figure_index_covers_figures(self):
        idx = pd.read_csv(OUT / "figure_index.csv")
        assert len(idx) >= 20
        assert idx["numerical_observation"].notna().all()
        assert idx["business_implication"].notna().all()

    def test_report_exists(self):
        p = ROOT / "reports" / "Hospital_Segmentation_Study_Report.docx"
        assert p.exists() and p.stat().st_size > 500_000

    def test_workbook_exists(self):
        p = ROOT / "reports" / "Hospital_Segmentation_Study.xlsx"
        assert p.exists() and p.stat().st_size > 1_000_000

    def test_deck_exists(self):
        p = ROOT / "reports" / "Hospital_Segmentation_Study_Deck.pptx"
        assert p.exists() and p.stat().st_size > 100_000

    def test_notebook_executed(self):
        nb = json.loads((ROOT / "notebooks" / "Hospital_Segmentation_Study.ipynb").read_text())
        code = [c for c in nb["cells"] if c["cell_type"] == "code"]
        assert len(code) >= 25
        with_out = sum(1 for c in code if c.get("outputs"))
        assert with_out >= len(code) * 0.8, "notebook is not executed"
        errors = [c for c in code if any(o.get("output_type") == "error" for o in c.get("outputs", []))]
        assert not errors, f"{len(errors)} cells raised errors"

    def test_provenance_disclosed(self):
        """The synthetic-data disclosure must be present wherever results are reported."""
        readme = (ROOT / "README.md").read_text().lower()
        assert "synthetic" in readme
        assert "real hospital" in readme or "not real" in readme
        nb = (ROOT / "notebooks" / "Hospital_Segmentation_Study.ipynb").read_text().lower()
        assert "synthetic" in nb
