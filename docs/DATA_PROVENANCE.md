# Data Provenance, Privacy and Ethical Constraints

## 1. Provenance statement

**No real hospital data was supplied with this project brief.**

Every record in this repository is produced by `src/generate_synthetic_data.py`. The generator
is committed, deterministic and seeded (`config.RANDOM_SEED = 20241111`), so a reviewer can
re-run it and obtain a byte-identical extract.

### What the generator models

The synthetic population is calibrated to realistic Indian community-hospital operating
parameters so that the analytical methods are exercised on data with plausible structure:

| Dimension | Calibration basis |
|---|---|
| Hospital sizes | 35–70 beds per site (small community hospitals) |
| OPD footfall | ~150k visits across 4 sites over 36 months |
| IPD conversion | 32.4% of the panel ever admitted |
| ALOS | 5.41 days mean, lognormal with a genuine long-stay tail |
| Bed occupancy | 68.6% — inside the credible 65–75% band |
| OPD tariff bands | ₹300–₹1,500 by department |
| IPD day rates | ₹3,000–₹9,500 by department, ICU multiplier 2.1 |
| GST treatment | 0% healthcare services, 5% pharmacy, 12% consumables |
| Seasonality | Winter peak, monsoon trough, ~57 index-point amplitude |
| Age/sex mix | Female 52%, paediatric and elderly tails modelled |
| Payer mix | 58% cash, 22% insurance/TPA, 15% government scheme, 5% corporate |

### Latent structure and the hidden ground truth

The generator embeds six behavioural archetypes in the population (chronic-care loyalists,
high-acuity inpatients, routine family OPD, new/early tenure, lapsed one-time, preventive
and wellness). These latent labels are written to
`data/raw/_ground_truth_latent_labels.csv` and are used **only** as a validation benchmark —
never as a model input.

The correlation between the hidden archetypes and the discovered clusters is reported
(ARI 0.156) and interpreted honestly: the model recovers **three operational groupings** of
the six behavioural archetypes, which is the intended behaviour. k=6 was evaluated and
rejected on the 5% segment-viability rule.

**Why this matters.** A synthetic dataset with no embedded structure would make clustering
look equally good at every k — the model selection would be meaningless. The latent
structure guarantees that the unsupervised methods have a real signal to find, and the
hidden labels let the recovery be measured rather than assumed.

### Injected data-quality defects

Seven defect families are injected at measured rates, and a register is written to
`data/raw/_injected_defect_register.csv`:

| Defect family | Records |
|---|---:|
| Free-text diagnosis variants | 29,419 |
| Hospital naming drift | 6,627 |
| Department naming drift | 10,733 |
| Missing values (7 columns) | 9,000+ |
| Duplicate visits | 3,220 |
| Duplicate admissions | 89 |
| Duplicate GST in totals | 2,977 |
| Invalid billing amounts | 1,630 |
| Impossible service dates | 990 |
| Swapped admission/discharge dates | 50 |
| Age holding year of birth | 1,500 |

This register is what allows the cleaning pipeline's detection rate to be **validated against
ground truth** (report Table 5.2) rather than merely asserted. That is a stronger claim than
"the data looks clean".

---

## 2. Privacy

### No real personal data

Because the data is synthetic:

- **No real patient, real person, real hospital or real clinician exists anywhere in this
  repository.**
- **No re-identification is possible** — there is no underlying real population to
  re-identify against.

### Privacy-by-design in the schema

The synthetic schema nonetheless applies the privacy patterns you would require on real data,
so the code transfers without redesign:

| Pattern | Implementation |
|---|---|
| Surrogate keys | `PT100000`… sequential synthetic ids; no names, no MRN |
| Date shifting | Not required (synthetic), but the pipeline is date-parameterised |
| Geographic masking | `pincode_masked` holds `500***` patterns, not full pincodes |
| Minimum cell size | Segment reporting never reports a group below 5% of the base |
| Consent field | `consent_outreach` (Y/N) gates every outreach recommendation — 71.3% coverage |
| Aggregation | All segment KPIs are aggregate; the patient-level exports are keyed only by surrogate id |

### What NOT to do with this repository

- Do **not** present these figures as evidence about a real hospital, real costs or real
  patient outcomes.
- Do **not** cite the ROI figures as business results — they are modelled projections with
  declared assumptions.
- Do **not** remove the synthetic-data disclosure from the report, deck or dashboard when
  reusing the template.

---

## 3. Ethical constraints on segmentation

This is a healthcare setting, and segmentation carries a specific risk: that groups identified
by low financial value are treated as low priority for care.

**Binding constraints applied throughout this project:**

1. **Segments describe engagement and resource intensity. They never gate clinical access.**
   No recommendation in this study denies, delays or reduces medically necessary treatment.

2. **The lowest-value segment receives the largest proportional investment.**
   `Dormant One-Time` is 54.1% of the panel and 3.1% of revenue, but the reactivation and
   screening programme recommended for it is designed around *early detection of undiagnosed
   chronic disease* — a clinical benefit — not around extracting revenue.

3. **The highest-cost recommendation is not ranked first.**
   The recommendations are sequenced by dependency and evidence-strength, not by ROI. The
   programme with the most uncertain benefit is stage-gated precisely so that it is not
   scaled on enthusiasm.

4. **No patient is excluded from analysis for being expensive or complex.**
   High-utilisation patients are retained and profiled as a segment; deleting them would both
   distort the analysis and constitute a form of analytical erasure of the sickest patients.

5. **Clinical governance review is a precondition for deployment.**
   The report states explicitly that any operational use of these segments must pass the
   clinical governance committee before go-live.

6. **Severity is not inferred from spend.**
   The report discloses that "high-acuity" in this analysis means high-acuity *by resource
   consumption*, which is a proxy for clinical severity, not a measurement of it. No Charlson,
   SOFA or similar score is available in the extract.

---

## 4. Reproducing the extract

```bash
python src/generate_synthetic_data.py
```

Outputs to `data/raw/`:

| File | Rows | Grain |
|---|---:|---|
| `patients.csv` | 42,000 | one row per patient |
| `opd_visits.csv` | 162,899 | one outpatient consultation |
| `admissions.csv` | 31,823 | one inpatient admission |
| `lab_tests.csv` | 49,741 | one laboratory test |
| `billing.csv` | 263,081 | one bill line |
| `_manifest.csv` | 5 | table inventory |
| `_injected_defect_register.csv` | 18 | defect ground truth |
| `_ground_truth_latent_labels.csv` | 42,000 | hidden archetype (validation only) |

**Total transactional rows: 507,544** — within 1.5% of the brief’s ~500,000 target.

Runtime: ~25 seconds on 2 vCPU.
