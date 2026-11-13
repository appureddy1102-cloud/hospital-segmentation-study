# Methodology Notes

This document records the non-obvious methodological decisions in the study, the alternatives
that were rejected, and the evidence for each choice. It exists because a defensible
analytical project is one whose decisions can be interrogated, not just its results.

---

## 1. The GST investigation

**Problem.** The billing table contains `base_amount`, `gst_rate`, `gst_amount` and
`total_amount`. Some rows' totals are inconsistent with their components. The naive fix —
"divide every amount by 1.05" — is wrong in two independent ways.

**What was actually done.**

```
Step 1  Test  total = base + gst
        97.58% of raw rows satisfy this exactly (tolerance ₹0.02)

Step 2  Test  total = base + 2 × gst   on the residual
        3,043 rows satisfy it → duplicate-GST errors, not a different tax regime

Step 3  Inspect gst_rate by service_type
        OPD_CONSULTATION  0%
        IPD_ROOM          0%
        PROCEDURE         0%
        LAB               0%
        PHARMACY          5%
        CONSUMABLES      12%
```

**Conclusion.** GST is service-type dependent, consistent with the Indian GST exemption on
healthcare services. The repair is to recompute `gst_amount = base_amount × gst_rate` using
the row's own rate and rebuild `total_amount = base + gst`. After the repair, the billing
identity holds for 100% of rows (0 breaks).

A blanket 1.05 division would have corrupted 98.8% of the billing table — every row whose
service type is GST-exempt or taxed at 12%. Only the 1.16% of rows that already double-counted
GST would have been accidentally corrected.

**Worked example.**

| Field | Raw (corrupt) | After repair |
|---|---:|---:|
| base_amount | 10,000.00 | 10,000.00 |
| gst_rate | 0.05 | 0.05 |
| gst_amount | 500.00 | 500.00 |
| total_amount | 10,500.00 → **11,000.00** (double-counted) | 10,500.00 |

---

## 2. The feature that had to be redefined

**Problem.** The first implementation of `visits_per_month` was:

```
visits_per_month = frequency / tenure_months
```

This is intuitive and wrong. A patient with exactly one visit has a tenure of exactly one
month, so the ratio is `1.0/month` — the *maximum possible value* — for the *least engaged
patient in the panel*. The feature inverts the relationship it is supposed to measure.

**How it was caught.** The Spearman correlation heatmap (figure 15) showed:

```
rho(visits_per_month, frequency) = −0.749
```

A demand-rate feature must correlate strongly *positively* with visit count. The sign
inversion was the signal.

**Fix.** Two features replaced the single one:

| Feature | Formula | Purpose |
|---|---|---|
| `visits_per_month` | `frequency ÷ 36 months` (fixed window) | Comparable across every patient; **used in clustering** |
| `visits_per_active_month` | `frequency ÷ tenure_months` | Intensity while active; **diagnostic only** |

After the fix, `rho(visits_per_month, frequency) = 1.00` (it is a linear rescaling of
frequency, so it carries no independent signal in a distance metric — which is why
`frequency` alone enters K-means, not both).

**Why this matters.** Had the feature been used as originally defined, the clustering would
have been driven by an artefact that labelled single-visit patients as the most engaged
demographic in the network. No error message would have appeared.

---

## 3. Why k=3 and not the highest silhouette

**The competing solutions** (from `outputs/kmeans_operational_utility.csv`).

| k | Silhouette | Smallest segment | KPI spread | Revenue separation | Size balance | OUS | Verdict |
|---:|---:|---:|---:|---:|---:|---:|---|
| 2 | **0.648** | 14.6% | 0.81 | 0.029 | 1.00 | 0.500 | Highest silhouette, **rejected** |
| **3** | 0.460 | **14.3%** | **1.66** | **0.279** | 1.00 | **0.586** | **Selected** |
| 4 | 0.477 | 3.1% | 1.72 | 0.169 | 0.25 | — | **Disqualified** — below 5% floor |
| 5 | 0.523 | 3.1% | 2.18 | 0.255 | 0.25 | — | **Disqualified** — below 5% floor |
| 6 | 0.470 | 3.1% | 2.48 | 0.225 | 0.25 | — | **Disqualified** — below 5% floor |
| 7–8 | 0.472 | 0.8% | 2.5–2.6 | 0.19–0.20 | 0.07 | — | **Disqualified** — below 5% floor |
| 9–10 | 0.44 | 0.8% | 3.0–3.2 | 0.23 | 0.07 | — | **Disqualified** — below 5% floor |

**Why silhouette alone is not the criterion.** Silhouette measures how well-separated
clusters are in feature space. It does not measure whether those clusters are *useful*. k=2
splits the panel into a small engaged group and an 85.4% residual. A residual that size cannot
be served by any single intervention, so the segmentation cannot be operationalised. This is
the clearest case in the study of a metric disagreeing with the business requirement: k=2 wins
on separation by a margin of 0.19 and loses on every operational criterion.

**The composite operational utility score (OUS).**

```
OUS = 0.25 × normalised_silhouette
    + 0.30 × normalised_KPI_spread
    + 0.20 × normalised_revenue_separation
    + 0.25 × segment_size_balance
```

where
- **KPI spread** = mean of `(max − min) / mean` across eight profiling KPIs — measures whether
  the segments differ on things an operator can act on
- **Revenue separation** = `1 − normalised_entropy` of revenue across segments — measures
  whether the segmentation identifies the economic structure of the panel
- **Segment size balance** = `min_segment_share / 12.5%`, capped at 1.0 — penalises
  degenerate solutions

Solutions with any segment below 5% of the patient base are **disqualified before scoring**,
per the brief's viability requirement.

**Result.** k=3 scores 0.586 and k=2 scores 0.500. k=4 and above never reach scoring, because
every one of them breaches the 5% segment-viability floor (smallest segments 3.1%, 3.1%, 3.1%,
0.8%, 0.8%, 0.8%, 0.8% for k=4…10). The OUS is a tie-break between two *viable* solutions, not
a mechanism for selecting an unviable one.

The selection reason is persisted to `outputs/kmeans_reason.txt` so the decision is auditable
rather than a matter of recollection.

---

## 4. Outlier policy

**What was measured.**
| Feature | IQR outliers | % of base | >3 SD |
|---|---:|---:|---:|
| frequency | 2,811 | 6.7% | — |
| monetary | 6,491 | 15.5% | — |
| avg_billing_per_visit | 7,268 | 17.4% | — |

**What was NOT done.** No patient was deleted as an outlier. The justification:

```
Top 1% of patients by billing value (419 patients)
  → 17.4% of all billing value
  → 9.4% of all admissions
  → 12.6% of all bed-days
```

Deleting them would erase the cohort the entire study exists to understand.

**What was done instead.**

| Technique | Applied to | Why |
|---|---|---|
| `log1p` | recency, frequency, monetary, lab_count | Skew falls from 0.9–4.5 to −0.4–1.4 without removing the tail |
| `RobustScaler` | all K-means inputs | Median/IQR scaling is not distorted by the tail the way mean/SD is |
| IQR/Z-score reporting | EDA only | Characterises the tail; does **not** gate retention |
| Segment profiling | high-utilisation patients | They are the `High-Acuity Inpatient` segment and are analysed as such |

---

## 5. Stability methodology

**The problem with naive re-fitting.** Fitting K-means independently on two periods produces
two sets of clusters whose *numbers* are unrelated. Cluster 0 in period 1 has no relationship
to cluster 0 in period 2. Comparing label ids would produce a meaningless migration matrix.

**What was done.**

1. Split the 36-month window into two independent 18-month periods:
   - P1: 2022-01-01 → 2023-06-30, recency reference 2023-07-01
   - P2: 2023-07-01 → 2024-12-31, recency reference 2025-01-01
   Period-specific reference dates prevent period-1 recency being contaminated by period-2
   activity.

2. Recompute every feature independently in each period.

3. Re-fit K-means independently in each period (same k, same feature set, same scaler
   specification).

4. **Match clusters by profile**, not by id, using the Hungarian algorithm on the correlation
   distance between standardised centroid vectors across eight KPIs.

**Why correlation distance and not Euclidean.** The two periods have materially different
intensity levels (period 2 is more acute-weighted because the inpatient-heavy cohort grew).
Euclidean distance would pair clusters by *magnitude* rather than *shape* and could match a
dormant period-2 cluster to a high-acuity period-1 cluster. Correlation distance compares the
*shape* of each cluster's profile across KPIs, which is the property that defines a segment's
identity. An earlier implementation using unweighted Euclidean distance produced exactly this
failure and was replaced.

5. Build the migration matrix for patients present in **both** periods, compute retention,
   ARI, and segment-size drift on that common cohort.

**Result.** ARI 0.158 (K-means) vs 0.046 (RFM). Retention ranges 8.9% to 92.1%. This is
reported as a **finding** — segmentation drift is real and monthly re-scoring is required —
not smoothed over.

---

## 6. Cost-benefit model construction

**Three input classes, always separated.**

| Class | Examples | Treatment |
|---|---|---|
| **Observed** | segment sizes, readmission counts, bed-days, tests per visit, OPD revenue per visit, IPD revenue per admission | Measured directly from cleaned data |
| **Assumed (disclosed)** | contribution margins: OPD 38%, IPD 30%, lab 42% | Gross billing is in the data; cost is not. A margin assumption is unavoidable, so it is declared in `config.ASSUMPTIONS` |
| **Assumed (stress-tested)** | 18% retention uplift, 7% reactivation, 22% avoidable repeat testing, 6% avoidable bed-days, 40% capacity backfill | Each varied to pessimistic/optimistic values in `outputs/recommendation_sensitivity.csv` |

**An error found and corrected during construction.** The first version valued incremental OPD
revisits at the segment's *blended* revenue per visit. For the `High-Acuity Inpatient` segment
that blended figure was ₹67,043 per visit — because it averaged a small number of visits
against a very large inpatient billing total. Valuing a routine follow-up consultation at
₹67,043 produced a portfolio ROI of 2,167%, which is obviously wrong.

The model was rebuilt on **observed outpatient revenue per visit** (₹752–₹852 by segment) and
**observed inpatient revenue per admission** (₹32,095–₹53,838), with the two valued
separately against their own margins. Portfolio ROI is now 433%.

**Another correction.** The bed-day release in the network-wide recommendation was initially
valued at full contribution margin on 100% of freed capacity. Network occupancy is 68.6% —
below the 75–80% band at which released capacity becomes scarce. Only 40% of freed bed-days
are credited as refillable demand; the rest is banked as unmonetised capacity headroom.

**Worked example — readmission prevention.**

```
Observed 30-day readmissions in segment ......... 1,624
× avoidability assumption (15%) ................. 244 avoidable events
× observed IPD revenue per admission (₹53,838) .. ₹13,136,472
× IPD contribution margin (30%) ................. ₹3,940,942
+ guaranteed 7-day review visits
  (6,039 admitted patients × ₹822 × 38%) ........ ₹1,885,022
− programme cost ................................ ₹1,762,000
─────────────────────────────────────────────────────────────
  Net benefit ................................... ₹4,027,892
  ROI ........................................... 229%
```

---

## 7. Reproducibility contract

Every random process uses a declared seed:

| Process | Seed |
|---|---|
| Synthetic data generation | `20241111` (`config.RANDOM_SEED`) |
| K-means | `42` (`segmentation.RNG`), `n_init=50` |
| Bootstrap resampling | `42` |
| PCA | `42` |
| Excel 25k-row sample | `42` |

The pipeline is **idempotent**: `python src/run_all.py` on a clean checkout reproduces every
figure, table and number in the report, workbook and deck.

Determinism is verified by `tests/test_pipeline.py`.
