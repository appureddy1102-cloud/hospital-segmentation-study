# Data Dictionary

All tables are **synthetic** (see [DATA_PROVENANCE.md](DATA_PROVENANCE.md)).

---

## 1. `patients` — one row per patient (42,000 rows)

| Column | Type | Description | Notes |
|---|---|---|---|
| `patient_id` | string | Surrogate key, `PT######` | No names, no MRN, no real identifiers |
| `age_years` | int | Age in years | **Raw field contains defects**: 1,500 rows hold a birth year (>110) or a negative value. Use `age_years_clean` after cleaning |
| `gender` | string | `M` / `F` | |
| `home_hospital_id` | string | Assigned site `HSP-01`…`HSP-04` | Patients may be treated away from home site |
| `area_locality` | string | Catchment locality | |
| `pincode_masked` | string | Masked pincode, e.g. `500***` | Never a full pincode |
| `registration_date` | date | First registration | Can pre-date the study window (mature panel) |
| `primary_payer` | string | `Cash` / `Insurance/TPA` / `Govt Scheme` / `Corporate` | |
| `consent_outreach` | string | `Y` / `N` — consent for proactive contact | Gates every outreach recommendation; 71.3% Y |

**Derived after cleaning:** `age_years_clean`, `age_imputed`, `age_repaired_from_year`, `age_band`

---

## 2. `opd_visits` — one row per outpatient consultation (162,899 rows)

| Column | Type | Description | Notes |
|---|---|---|---|
| `visit_id` | string | Surrogate key `OPD#######` | |
| `patient_id` | string | FK to `patients` | **0.4% null in raw** → quarantined |
| `hospital_id` | string | FK to site | **6,627 rows hold name/typo variants** in raw → canonicalised |
| `department` | string | Treating department | **10,733 rows hold abbreviation/case variants** in raw → canonicalised |
| `visit_date` | date | Consultation date | **0.3% null in raw** → quarantined |
| `visit_type` | string | `New` / `Follow-up` | First visit of each patient is always `New` |
| `diagnosis_text` | string | Free-text diagnosis | **29,419 rows rewritten to synonyms/typos** in raw → mapped to `diagnosis_canonical` |
| `diagnosis_code` | string | Internal code, e.g. `GM02` | Used as a fallback when free text is unresolvable |
| `doctor_id` | string | Treating clinician (surrogate) | |
| `consultation_fee` | float | OPD tariff (INR) | **0.5% null in raw** → department median |
| `planned_followup_days` | int | Planned review interval, `0` = none | Basis of `followup_compliance` |
| `token_no` | int | Queue token | Used as the tie-break when de-duplicating |

**Derived after cleaning:** `diagnosis_canonical`, `diagnosis_source`, `visit_year`, `visit_month`, `visit_quarter`, `dow`, `is_weekend`

---

## 3. `admissions` — one row per inpatient admission (31,823 rows)

| Column | Type | Description | Notes |
|---|---|---|---|
| `admission_id` | string | Surrogate key `IPD######` | |
| `patient_id` | string | FK to `patients` | |
| `hospital_id` | string | FK to site | |
| `department` | string | Treating department | |
| `admission_date` | date | Admission date | **50 pairs swapped with discharge in raw** |
| `discharge_date` | date | Discharge date | **0.8% null in raw** → department median LOS |
| `admitting_diagnosis` | string | Diagnosis at admission | |
| `ward_type` | string | `General Ward` / `Semi-Private` / `Private Room` / `ICU` | |
| `icu_flag` | int | 1 if ICU stay | Drives the IPD day-rate multiplier |
| `discharge_status` | string | `Recovered` / `Improved` / `Referred` / `LAMA` / `Expired` | |

**Derived after cleaning:** `los_days`, `discharge_date_imputed`

---

## 4. `lab_tests` — one row per laboratory test (49,741 rows)

| Column | Type | Description | Notes |
|---|---|---|---|
| `test_id` | string | Surrogate key `LAB#######` | |
| `visit_id` | string | FK to `opd_visits` | **6% null by design** — walk-in testing is a real pathway. Flagged, not dropped |
| `patient_id` | string | FK to `patients` | |
| `hospital_id` | string | FK to site | |
| `test_name` | string | Test catalogue name (14 tests) | |
| `test_date` | date | Test date | |
| `test_cost` | float | Test price (INR) | **0.4% null in raw** → test-catalogue price |

**Derived after cleaning:** `has_visit_link`

### Test catalogue

| Test | Price (INR) |
|---|---:|
| CBC | 350 |
| Blood Sugar Fasting | 200 |
| HbA1c | 650 |
| Lipid Profile | 700 |
| Liver Function Test | 850 |
| Renal Function Test | 800 |
| Thyroid Profile | 750 |
| Urine Routine | 250 |
| ECG | 300 |
| Chest X-Ray | 450 |
| Ultrasound Abdomen | 1,200 |
| 2D Echocardiography | 2,200 |
| Serum Electrolytes | 500 |
| Complete Urine Culture | 600 |

---

## 5. `billing` — one row per bill line (263,081 rows)

| Column | Type | Description | Notes |
|---|---|---|---|
| `bill_id` | string | Surrogate key `BILL#######` | |
| `encounter_id` | string | FK to `visit_id` (OPD) or `admission_id` (IPD) | |
| `patient_id` | string | FK to `patients` | |
| `hospital_id` | string | FK to site | |
| `service_date` | date | Date of service | **990 rows after study end in raw** → recovered from encounter |
| `service_type` | string | `OPD_CONSULTATION` / `PHARMACY` / `IPD_ROOM` / `PROCEDURE` / `CONSUMABLES` | Determines the GST rate |
| `department` | string | Billing department | |
| `discount_pct` | float | Discount applied before tax | 5–18% |
| `base_amount` | float | Pre-tax amount (INR) | **1,630 rows invalid** (negative/zero/10× inflated) in raw |
| `gst_rate` | float | Applicable GST rate | 0.00 / 0.05 / 0.12 |
| `gst_amount` | float | GST charged (INR) | **0.6% null in raw** |
| `total_amount` | float | `base + gst` | **2,977 rows had GST counted twice** in raw → rebuilt |
| `payment_mode` | string | `UPI` / `Cash` / `Card` / `Insurance Claim` | |
| `payer_type` | string | Payer classification | |

**Derived after cleaning:** `encounter_type`, `encounter_valid`, `is_zero_value_line`, `date_recovered_from_encounter`, `service_year`, `service_month`

### GST logic (established empirically, not assumed)

| Service type | GST rate | Rationale |
|---|---:|---|
| `OPD_CONSULTATION` | 0% | Healthcare service — exempt |
| `IPD_ROOM` | 0% | Healthcare service — exempt |
| `PROCEDURE` | 0% | Healthcare service — exempt |
| `LAB` | 0% | Healthcare service — exempt |
| `PHARMACY` | 5% | Goods |
| `CONSUMABLES` | 12% | Goods |

Repair rule: `gst_amount = base_amount × gst_rate`, then `total_amount = base_amount + gst_amount`.

---

## 6. Engineered features — `patient_features_full.parquet` (41,834 rows)

| Feature | Formula | Role |
|---|---|---|
| `recency_days` | `reference_date − last_visit_date` | RFM axis |
| `frequency` | count of OPD visits in window | RFM axis |
| `monetary` | Σ corrected `total_amount` in window | RFM axis |
| `visits_per_month` | `frequency ÷ 36` | K-means input |
| `visits_per_active_month` | `frequency ÷ tenure_months` | Diagnostic only (see METHODOLOGY §2) |
| `admission_count` | count of admissions | Profiling |
| `admission_rate` | `admissions ÷ OPD visits` | K-means input |
| `lab_count`, `lab_per_visit` | lab tests; lab tests ÷ OPD visits | K-means input |
| `avg_billing_per_visit` | `monetary ÷ frequency` | Profiling |
| `avg_los_days`, `total_bed_days` | mean and Σ LOS | Profiling, occupancy |
| `n_departments`, `dept_diversity` | distinct departments; ÷ 12 | K-means input |
| `n_hospitals` | distinct sites visited | Profiling |
| `recent_activity_ratio` | `(last 90d + 1) ÷ (prior 90d + 1)` | K-means input |
| `visit_growth_rate` | `(last 6m − prior 6m) ÷ prior 6m` | Profiling |
| `winter_visit_share` | Nov–Feb visits ÷ frequency | Profiling |
| `chronic_share` | share of visits with a chronic diagnosis | Profiling |
| `readmission_30d` | readmissions ≤30 days after discharge | Outcome KPI |
| `followup_compliance` | actual gap ≤ 1.5 × planned gap | Outcome KPI (41% measurable) |
| `opd_to_admission_ratio` | `visits ÷ admissions` | Profiling |

---

## 7. Segmentation outputs

### `rfm_scored.parquet`
`R`, `F`, `M` (1–5 quintile scores), `RFM_sum` (3–15), `RFM_cell` (e.g. `313`), `rfm_segment` (7 rule-based segments).

### `kmeans_segmented.parquet`
`cluster` (K-means id), `segment` (business name), `pca1`/`pca2` (2-D projection), plus all engineered features.

| Segment | Definition rule (from measured profile) |
|---|---|
| `High-Acuity Inpatient` | Highest revenue per patient + admissions per visit > 1 |
| `Frequent OPD Regulars` | Highest visit frequency (8.3 visits/patient) |
| `Dormant One-Time` | Highest recency, lowest value, lowest conversion |

### `segment_evidence.json`
Per-segment observed facts used to anchor the recommendations: size, revenue, unit economics (OPD revenue per visit, IPD revenue per admission), readmission count, bed-days, consent coverage, overdue counts, lab intensity.
