# Final Self-Audit — Compliance Checklist

**Project:** Hospital Patient Segmentation Study
**Basis:** the brief's 14 requirement groups, audited line by line against the artifacts in this
repository.
**Method:** every "Work completed" claim below was re-verified by reading the produced file or
re-running the calculation. Nothing in this table is asserted from memory.
**Verdict:** all deliverables complete; 3 residual gaps are disclosed rather than closed, and
each is a data-availability constraint rather than a missing analysis step.

---

## 1. Project objective & framing

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| Objective tied to resource utilisation, engagement, efficiency, service quality | Objective section links each of the four to a named analysis stage and a named segment output | Report §1; notebook cell 1 | `reports/…Report.docx` §1 | — |
| RFM-style scoring + K-means segmentation | Both implemented independently, then compared | `rfm_scored.parquet`, `kmeans_segmented.parquet` | `src/segmentation.py` | — |
| Patient-centred framing; never recommend denying care | Explicit ethical constraint + a dedicated subsection; lowest-value segment receives the largest proportional investment | Report §1.4, §17.1; README "Ethical constraints" | `docs/DATA_PROVENANCE.md` §3 | — |

## 2. Data understanding & quality

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| Shapes, dtypes, missingness %, duplicates | 7-table inventory with per-column null counts | Table 4.1; `eda_stats.json` | Report §4 | — |
| Unique patients / hospitals / departments | 42,000 / 4 / 12 | `cleaning_log.json` | Report §4.2 | — |
| Date coverage | 2022-01-01 → 2024-12-31, 1,096 days, verified per table | test `test_all_dates_in_window` | `tests/test_pipeline.py` | — |
| Billing distribution | Percentiles, log-scale histogram, GST decomposition | Figure 09 | `figures/09_billing_distribution.png` | — |
| Diagnosis text inspection | 26,571 injected variants; 30,291 values normalised; 45 canonical diagnoses retained | Figure 08; `cleaning_log.json` | Report §5.3 | — |
| Cross-table consistency | 0 orphan encounters; 0 identity breaks after repair | `cleaning_log.json` → `identity_breaks_after` | Report §5.6 | — |
| **Quality table** (Issue \| records \| % \| correction \| validation) | 13 defect classes, each with all five columns populated and a measured validation result | Table 5.1 | Report §5.1 | — |
| Free-text diagnosis variants | 26,571 injected variants; **30,291 rewritten**, 3,899 resolved via diagnosis-code fallback, **0 unresolvable** | `opd_diagnosis_canonicalised`, `opd_diagnosis_from_code_fallback` | `cleaning_log.json` | — |
| DOB-in-age field | 1,008 rows held a birth year and were recomputed against the registration date; a further 441 impossible ages were median-imputed and flagged | `patients_age_year_of_birth`, `patients_age_impossible` | `cleaning_log.json` | — |
| Duplicate GST | 3,043 rows identified via `total = base + 2×gst` (3,076 injected), recomputed from the row's own rate | `billing_rows_double_gst_detected` | `cleaning_log.json` | — |
| Missing IDs / dates | 652 missing `patient_id` and 490 missing `visit_date` dropped as un-analysable, each with a named counter in the log; every recoverable value repaired instead (e.g. 1,093 impossible billing dates, 8 unrecoverable) | `opd_missing_patient_id_dropped`, `billing_date_unrecoverable_dropped` | `cleaning_log.json` | — |
| Duplicate visits / admissions | **3,013 visits** and **541 admissions** removed on business key (patient + dates + department) with a deterministic tie-break; 2,880 / 283 were injected | `opd_duplicates_removed`, `adm_duplicates_removed` | `cleaning_log.json` | — |
| Invalid amounts / impossible dates | 188 ten-fold inflation errors corrected; 1,093 impossible service dates recovered from the linked encounter; 8 unrecoverable and dropped | `billing_10x_inflation_corrected`, `billing_impossible_date` | `cleaning_log.json` | — |
| Inconsistent hospital / department names | **10,268 hospital** and **9,668 department** values canonicalised; 1,785 unresolvable departments retained as `Unspecified` rather than guessed | `opd_hospital_canonicalised` | `cleaning_log.json` | — |
| No blind deletion | Every removal carries a named counter and an explicit rule in the log; repairs are preferred to deletions wherever a value is recoverable (1,093 dates and 3,899 diagnoses were repaired, not dropped) | `cleaning_log.json` | `reports/…xlsx` sheet `02_Data_Quality` | — |
| Before/after cleaning stats | Row counts, null rates and revenue totals before and after | Table 5.2 | Report §5.2 | — |
| GST derived from data, never assumed | Identity tested empirically (97.58% match), residual explained (2×GST), rate verified by service type | `METHODOLOGY.md` §1 | `docs/METHODOLOGY.md` | — |

## 3. Cleaning & feature engineering

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| Reproducible pipeline | One command rebuilds every artefact deterministically | `python src/run_all.py` → 3.3 min | `src/run_all.py` | — |
| RFM | R/F/M with explicit reference date and 36-month window | `rfm_scored.parquet` | `src/segmentation.py` | — |
| ~14 behavioural features, each with formula + meaning + calculation | 21 features, tabulated with all three | Table 6.1 (21 rows) | Report §6 | — |
| Observation period / reference date explicit | 2022-01-01 → 2024-12-31; reference 2025-01-01; period-specific dates in stability | `config.py` | `src/config.py` | — |
| No leakage between feature window and outcome window | Outcome KPIs (`readmit_30d`, `followup_compliance`) are excluded from clustering inputs; verified by feature-list assertion | `CLUSTER_FEATURES` excludes both | `src/config.py` | — |

## 4. EDA — 16 required charts

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| 16 charts minimum | **25 produced** | `figure_index.csv` (25 rows) | `figures/01–25` | — |
| Each with numeric observation | Every figure has a measured statistic in the index | `figure_index.csv` col `numerical_observation` | `outputs/figure_index.csv` | — |
| Each with pattern | Col `pattern` populated for all 25 | same | same | — |
| Each with business implication | Col `business_implication` populated for all 25 | same | same | — |
| Each with conclusion | In-figure annotation + report narrative | Report §7 | Report | — |
| No decorative charts | Every figure answers a stated question; chart choice justified in the index | — | — | — |

## 5. Statistical analysis

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| Skewness / kurtosis | Table for all 21 features | Table 8.1 | Report §8 | — |
| log1p where justified | Applied to 4 features; skew reduced from 0.9–4.5 → −0.4 to 1.4 | Before/after table | Report §8.2 | — |
| IQR and Z-score outlier detection | Both computed and reported | Table 8.3 | Report §8.3 | — |
| Robust vs standard scaling | Both fitted and compared; RobustScaler selected with stated reason | Figure 16 | `figures/16_outlier_boxplots.png` | — |
| Before/after distributions | Shown for every transformed feature | Figures 09, 12, 16 | `figures/` | — |
| Must not delete genuine high-utilisation patients | **Zero patients removed.** Top 1% by value = 17.4% of billing, 9.4% of admissions — retained and profiled as a segment | test `test_no_fabricated_kpi_claims` | `tests/` | — |

## 6. Two independent segmentation methods

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| RFM quantile scoring with documented thresholds | Quintile cut-points printed with actual values | `rfm_thresholds.json` | `outputs/` | — |
| RFM segment sizes | 7 rule-based segments with counts | `final_segment_profiles.csv` alt view | Report §9.2 | — |
| RFM pros/cons | 3 pros / 3 cons stated per method | Table 9.1 | Report §9 | — |
| K-means feature selection | 8 features, each justified; excluded features listed with reason | Table 10.1 | Report §10.1 | — |
| Missing-value handling | Median imputation + missing-indicator; 0 rows dropped | `cleaning_log.json` | `src/segmentation.py` | — |
| Scaling | RobustScaler, justified vs StandardScaler | Report §10.2 | — | — |
| Elbow | Inertia curve for k=2…10 with the elbow read off | Figure 18 | `figures/18_…png` | — |
| Silhouette over multiple K | Silhouette + CH + DB computed for k=2…10 | `kmeans_k_evaluation.csv` | `outputs/` | — |
| PCA 2-D plot | 2-component projection, variance explained stated | Figure 19 | `figures/19_pca_clusters.png` | — |
| Centroids | Exported in both scaled (distance-metric) and original units (readable) | `kmeans_centroids_scaled.csv`, `kmeans_centroids_original_units.csv` | `outputs/` | — |
| Size distribution | 14.3% / 31.7% / 54.1% | Figure 20 | `figures/20_cluster_profiles.png` | — |
| Feature-level comparison | Heatmap of standardised centroids | Figure 20 | same | — |
| Stated limitations | 5 limitations listed per method | Report §10.7 | Report | — |

## 7. Model comparison

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| Comparison table | 10 criteria × 2 methods, scored with justification | `model_comparison.csv` | `outputs/` | — |
| Separation / silhouette | Reported for both | same | same | — |
| Interpretability / stability / usefulness / actionability | Scored 1–5 with written rationale per row | same | same | — |
| Size balance | Smallest-segment share for both methods | same | same | — |
| Every candidate scored, not just the winner | k=2…10 with silhouette, size, KPI spread, revenue separation, size balance and OUS | `kmeans_operational_utility.csv` | `outputs/` | — |
| Not selected purely on silhouette | k=2 had the highest silhouette in the sweep (**0.648** vs 0.460 for k=3) and was still **rejected** on operational grounds; the OUS table for every candidate is persisted | `kmeans_operational_utility.csv`, `kmeans_reason.txt` | `outputs/` | — |
| Complementary use discussed | Hybrid: K-means for operations, RFM for CRM targeting | Report §11.5 | Report | — |

## 8. Segment profiling

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| Patients, %, revenue, revenue share | All four per segment | Table 13.1 | Report §13 | — |
| Avg frequency / recency / billing / LOS | All four per segment | same | same | — |
| Bed occupancy if reliable | Bed-days per 100 patients; network occupancy 68.6% validated as credible | same | same | — |
| 30-day readmission | Rate + absolute count per segment | same | same | — |
| Department utilisation | Mean distinct departments + diversity index | same | same | — |
| Admission rate | Per segment, 97.5× spread | same | same | — |
| Lab utilisation | Tests per visit | same | same | — |
| Consolidated table | 16 columns × 3 segments | Table 13.1 | Report §13 | — |
| Business-friendly names | High-Acuity Inpatient / Frequent OPD Regulars / Dormant One-Time | — | — | — |
| ≥3 genuine KPI differences | **8 of 9** clear the 0.30 materiality floor | `segment_kpi_differences.csv` | `outputs/` | — |
| ≥5% segment size verified | Smallest = 14.27%; k=5…10 disqualified for breaching the floor and reported | `kmeans_k_evaluation.csv` | `outputs/` | — |
| Never manufacture differences | `avg_los` fails the floor (0.148) and is reported as **not separating** the segments | Report §13.5 | Report | — |

## 9. Recommendations

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| ≥1 concrete action per segment | 3 segment-specific + 1 network-wide = 4 | `recommendations_cost_benefit.csv` | `outputs/` | — |
| 10 elements each | Segment, problem, intervention, process, resources, cost, benefit, financial impact, KPIs, timeline — all 10 columns populated | same (see column list) | same | — |
| Transparent assumptions | 11 assumptions tabulated with source/basis | Table 15.2 | Report §15 | — |
| Observed vs forecast separated | 3-column evidence table: Observed / Assumed (disclosed) / Assumed (stress-tested) | Table 15.1 | Report §15.1 | — |
| Cost-benefit table + ROI | 4 programmes, cost, benefit, net, ROI, payback | Table 15.4 | Report §15.4 | — |
| Cost-benefit arithmetic correct | ROI recomputed from cost and benefit in the test suite | test `test_roi_arithmetic` | `tests/` | — |
| Sensitivity analysis | 3 scenarios × 4 programmes | `recommendation_sensitivity.csv` | `outputs/` | — |

## 10. Stability & migration

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| Two comparable periods | P1 2022-01→2023-06, P2 2023-07→2024-12, each 18 months | `config.py` | `src/config.py` | — |
| Re-segment independently | Full feature rebuild + refit per period | `segments_period1/2.parquet` | `data/processed/` | — |
| Match clusters by profile not number | Hungarian algorithm on correlation distance over 8 KPIs | `stability_summary.json` → `cluster_mapping_p2_to_p1` | `outputs/` | — |
| Migration counts / % | Full matrix, 16,536 both-period patients | `migration_matrix_kmeans.csv` | `outputs/` | — |
| Retention | 20.3% / 92.1% / 8.9% | test `test_retention_bounded` | `tests/` | — |
| Stability metric / ARI | ARI 0.158 (K-means) vs 0.046 (RFM) | test `test_ari_bounded` | `tests/` | — |
| Migration matrix / heatmap | Heatmap + row-normalised % | Figure 22 | `figures/22_segment_migration.png` | — |
| Explanation + management response | 6-row management response table per migration pattern | Table 12.4 | Report §12 | — |

## 11. BI dashboard

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| Tool-level specification | 7-page build spec with exact fields, visuals, interactions | `dashboard_specification.md` | `dashboards/` | Power BI Desktop not installable in this environment — spec + prototype supplied instead, as the brief permits |
| Hospital overview | Page 1 defined + prototyped | prototype tab 1 | `dashboards/dashboard_prototype.html` | — |
| Segmentation overview | Page 2 | tab 2 | same | — |
| Revenue / utilisation | Page 3 | tab 3 | same | — |
| Department performance | Page 4 | tab 4 | same | — |
| Segment comparison | Page 5 | tab 5 | same | — |
| Readmission / LOS | Page 6 | tab 6 | same | — |
| Migration | Page 7 | tab 7 | same | — |
| KPI cards / slicers / drill-downs | 8 KPI cards, 4 global slicers, drill-through paths specified | spec §4–6 | `dashboard_specification.md` | — |
| Calculated measures + formulas | 16 DAX measures with full formulas | spec §7 | same | — |
| Reproducible steps | Star schema + import steps + relationship diagram | spec §2–3 | same | — |
| Working interactive prototype | 7 tabbed pages, self-contained, no external dependencies | 1.06 MB HTML | `dashboards/dashboard_prototype.html` | — |

## 12. Deliverables A–D

| # | Requirement | Work completed | Evidence | Location | Gap |
|---|---|---|---|---|---|
| A | Executable commented notebook, full arc | 41 cells, 0 errors, 20 embedded figures, narrative markdown between stages | `nbconvert --execute` exit 0 | `notebooks/Hospital_Segmentation_Study.ipynb` | — |
| B | Excel workbook, 10 required sheets | **15 sheets** (10 required + 5 supporting: README, sensitivity, EDA stats, model comparison, K-selection) | openpyxl sheet list | `reports/…xlsx` | — |
| C | Word report, 20 numbered sections | 20 numbered sections + contents + executive summary + references/technical appendix + self-audit | heading walk (23 H1) | `reports/…Report.docx` | — |
| D | 10–12 slide business deck | **12 slides**, 16:9 | python-pptx slide count | `reports/…Deck.pptx` | Deck could not be rendered to PDF for visual QA (`libreoffice` unavailable in the build environment); layout was verified geometrically. Charts and text are image/shape-verified, not eye-verified |

## 13. Quality bar

| Requirement | Work completed | Evidence | Location | Remaining gap |
|---|---|---|---|---|
| Only actual analysis | Every number originates in a computed output file | `outputs/*.json|csv` | `outputs/` | — |
| No fabricated scores / counts / revenue | Arithmetic re-verified by test suite; ROI, shares and identities recomputed | 49 tests | `tests/test_pipeline.py` | — |
| Flag unavailable data explicitly | Cost data absent → margins declared as assumptions; clinical severity absent → proxy disclosed | Report §15.1, §18.4 | Report | — |
| Label synthetic data | Banner on report cover, deck slide 1 and 12, notebook cell 1, README, dashboard footer | test `test_provenance_disclosed` | multiple | — |
| Worked numerical examples | 6 worked examples (GST repair, readmission ROI, OUS, retention, drift, payback) | `METHODOLOGY.md` §1, §6; Report §5.1, §15.5 | multiple | — |
| Charts titled / labelled with interpretation | 25/25, each with a stated observation | `figure_index.csv` | `outputs/` | — |
| Every recommendation traceable to a finding | Each recommendation row cites the segment KPI that motivates it | `recommendations_cost_benefit.csv` col `problem` | `outputs/` | — |
| No repetition | Cross-references used instead of restating; one-home principle per topic | — | Report | — |
| Professional language | Formal register throughout; no marketing superlatives without a number | — | — | — |
| Reproducible code + validation checks | `run_all.py` + 49 tests | `pytest -q` → 49 passed | `tests/` | — |
| Methodological decisions explained | 7 decisions documented with rejected alternatives | `docs/METHODOLOGY.md` | `docs/` | — |
| Findings vs assumptions separated | 3-class evidence table in every cost-benefit section | Table 15.1 | Report §15.1 | — |
| Patient privacy protected | Surrogate keys, masked pincode, no names, 5% cell-size floor | `docs/DATA_PROVENANCE.md` §2 | `docs/` | — |

## 14. Self-audit deficiencies found and fixed

| # | Deficiency found during this audit | Action taken | Status |
|---|---|---|---|
| 1 | `figure_index.csv` was overwritten by each pipeline stage, so only the last stage's figures were indexed | `viz.write_index()` rewritten to merge on disk by filename | **Fixed** — 25 indexed |
| 2 | `visits_per_month = frequency ÷ tenure` inverted the engagement relationship | Redefined to a fixed-window rate; tenure version demoted to diagnostic | **Fixed** — ρ 1.000 |
| 3 | Cluster matching used Euclidean distance and paired by magnitude, not shape | Replaced with correlation distance on the 8-KPI profile | **Fixed** — mapping verified |
| 4 | Segment-size drift compared different cohorts (full-period counts vs both-period matrix) | All drift statistics recomputed on the both-period cohort | **Fixed** |
| 4b | The same audit initially asserted 16 workbook sheets, 3,220 duplicate visits and role-based replacement counts that did not match the cleaned log | Every row re-verified against `cleaning_log.json` and the workbook itself; corrected to measured values (15 sheets, 3,013 visits, 541 admissions, 1,008 age repairs) | **Fixed** |
| 4c | K-means centroids were discussed in the report but never exported as a file, so the claim was not independently checkable | Added a two-view centroid export (scaled and original units) to `segmentation.py` | **Fixed** |
| 4d | **Table 11.2 and the surrounding k-selection narrative were hardcoded, and stated k=3 as having the highest silhouette (0.511) when the measured value is 0.460 and k=2 actually peaks at 0.648.** The claim "silhouette peaks at k=3" was false | Section 11.2–11.3 rewritten to read every figure from `kmeans_operational_utility.csv`, which is now persisted by `segmentation.py` for all k=2…10. The prose now states that k=2 wins on silhouette and explains why it is rejected anyway | **Fixed** |
| 5 | `avg_billing_per_visit` was labelled "billing per visit", misleading for a segment whose billing includes inpatient revenue | Relabelled "value density" with an explicit definition footnote | **Fixed** |
| 6 | Report narrative on drift direction was hardcoded | Generated from measured values via `_delta()` | **Fixed** |
| 7 | Incremental OPD visits were valued at blended revenue per visit (₹67,043) → ROI 2,167% | Rebuilt on observed outpatient revenue per visit (₹752–852) | **Fixed** — ROI 433% |
| 8 | `build_notebook.py` sat at repo root, breaking the documented `src/` layout | Moved to `src/` with corrected path resolution | **Fixed** |
| 9 | No `requirements.txt` | Generated from the verified environment | **Fixed** |
| 10 | Deck could not be visually rendered in this environment | Layout verified geometrically; gap disclosed above | **Disclosed, not closed** |

---

## Summary

| Category | Required | Delivered | Status |
|---|---:|---:|---|
| Report sections | 20 | 20 + appendix | ✅ |
| EDA charts | 16 | 25 | ✅ |
| Segments ≥5% | all | 3/3 (min 14.3%) | ✅ |
| Material KPI differences | ≥3 | 8 | ✅ |
| Recommendations with 10 elements | ≥3 | 4 | ✅ |
| Excel sheets | 10 | 15 | ✅ |
| Deck slides | 10–12 | 12 | ✅ |
| Notebook cells | — | 41, executed | ✅ |
| Dashboard pages | 7 | 7 | ✅ |
| Pipeline tests | — | 49 passing | ✅ |

**Open disclosures (3):** cost data unavailable → margins assumed; clinical severity scores
unavailable → resource-intensity proxy; deck not visually rendered in this environment.
None of these is a missing analytical step, and each is stated at the point in the report where
it could affect a conclusion.
