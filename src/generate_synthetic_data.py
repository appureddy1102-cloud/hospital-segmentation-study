"""
generate_synthetic_data.py
==========================
Builds the five raw source tables for the Hyderabad Community Hospital Network
segmentation study.

PROVENANCE: 100% SYNTHETIC. No real patient, no real hospital. See
docs/DATA_PROVENANCE.md. Every table is written to data/raw/.

Design notes
------------
* A latent 6-archetype behavioural structure is embedded in the population so
  that unsupervised segmentation has a recoverable signal. The latent labels
  are written to data/raw/_ground_truth_latent_labels.csv and are used ONLY
  as a validation benchmark for the clustering (never as a model input).
* Seven families of data-quality defects are injected at measured rates and a
  defect register is written to data/raw/_injected_defect_register.csv so the
  cleaning stage can compute recovery rates rather than asserting success.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

import config as C
from catalogue import (CHRONIC_DEPTS, FAMILY_DEPTS, ACUTE_DEPTS,
                       WELLNESS_DEPTS, DIAGNOSES, DIAG_VARIANTS,
                       HOSP_VARIANTS, DEPT_VARIANTS)


rng = np.random.default_rng(C.RANDOM_SEED)
RAW = C.DATA_RAW

# ===========================================================================
# 1. LATENT ARCHETYPES
# ===========================================================================
ARCHETYPES = {
    # name                      share  visit_rate/yr  spend_mult  adm_prob  lab_rate  chronic  dept_diversity
    "Chronic Care Loyalists":  (0.22, 7.5, 1.15, 0.045, 1.30, 0.95, 4.2),
    "High-Acuity Inpatient":   (0.09, 3.2, 2.35, 0.620, 0.85, 0.55, 2.6),
    "Routine Family OPD":      (0.26, 4.4, 0.72, 0.035, 0.55, 0.15, 2.2),
    "New & Early Tenure":      (0.16, 2.1, 0.85, 0.060, 0.70, 0.30, 1.3),
    "Lapsed One-Time":         (0.19, 1.25, 0.80, 0.090, 0.50, 0.25, 1.25),
    "Preventive & Wellness":   (0.08, 2.6, 0.95, 0.015, 1.60, 0.20, 1.6),
}
ARCH_NAMES = list(ARCHETYPES)
ARCH_P = np.array([ARCHETYPES[a][0] for a in ARCH_NAMES])
ARCH_P = ARCH_P / ARCH_P.sum()

# ===========================================================================
# 2. CALENDAR & SEASONALITY
# ===========================================================================
days = pd.date_range(C.STUDY_START, C.STUDY_END, freq="D")
N_DAYS = len(days)
day_idx = np.arange(N_DAYS)
month = days.month.to_numpy()
dow = days.dayofweek.to_numpy()
day_serial = (days - pd.Timestamp("1970-01-01")).days.to_numpy()

# Seasonal utilisation for a Hyderabad OPD: winter peak (Nov-Feb), monsoon dip (Jul-Aug)
season_mult = np.select(
    [np.isin(month, [11, 12, 1, 2]), np.isin(month, [3, 4, 5]),
     np.isin(month, [6, 7, 8]), np.isin(month, [9, 10])],
    [1.18, 1.02, 0.88, 1.05], default=1.0)
week_mult = np.where(dow == 6, 0.55, np.where(dow == 0, 0.80, 1.0))  # Sun low, Mon-Sat high
trend = 1.0 + 0.008 * (day_idx / 30.0)          # ~0.8% growth per month (~25% over 36 months)
DAY_W = season_mult * week_mult * trend
DAY_W = DAY_W / DAY_W.sum()

# ===========================================================================
# 3. PATIENTS
# ===========================================================================
n_pat = C.N_PATIENTS
arch_id = rng.choice(len(ARCH_NAMES), size=n_pat, p=ARCH_P)
arch_name = np.array(ARCH_NAMES)[arch_id]

pid = np.array([f"PT{100000+i}" for i in range(n_pat)])

# Gender / age by archetype
gender = np.where(rng.random(n_pat) < 0.52, "F", "M")
age = np.zeros(n_pat)
for i, a in enumerate(ARCH_NAMES):
    m = arch_id == i
    k = m.sum()
    if k == 0:
        continue
    if a == "Routine Family OPD":
        age[m] = np.clip(rng.normal(27, 15, k), 0, 88)
    elif a in ("Chronic Care Loyalists",):
        age[m] = np.clip(rng.normal(56, 13, k), 18, 92)
    elif a in ("High-Acuity Inpatient",):
        age[m] = np.clip(rng.normal(58, 15, k), 16, 94)
    elif a == "Preventive & Wellness":
        age[m] = np.clip(rng.normal(44, 14, k), 12, 85)
    else:
        age[m] = np.clip(rng.normal(38, 17, k), 0, 89)
age = np.round(age).astype(int)

home_hosp = rng.choice(list(C.HOSPITAL_WEIGHTS), size=n_pat,
                       p=list(C.HOSPITAL_WEIGHTS.values()))
payer = rng.choice(["Cash", "Insurance/TPA", "Govt Scheme", "Corporate"],
                   size=n_pat, p=[0.58, 0.22, 0.15, 0.05])
# Aarogyasri-type scheme skews to peri-urban sites
scheme_mask = (payer == "Govt Scheme") & np.isin(home_hosp, ["HSP-03", "HSP-04"])
payer[scheme_mask & (rng.random(n_pat) < 0.4)] = "Cash"

# Registration date: depends on archetype tenure
# Registration offset in days relative to STUDY_START. Negative = the patient
# was already on the panel before the study window opened (a mature network
# does not start from zero on day 1 of the analysis). A minority register
# during the window, which is what produces realistic cohort ageing.
reg_off = np.zeros(n_pat, dtype=int)
PRE_SHARE = {"Chronic Care Loyalists": 0.80, "High-Acuity Inpatient": 0.72,
             "Routine Family OPD": 0.68, "New & Early Tenure": 0.0,
             "Lapsed One-Time": 0.62, "Preventive & Wellness": 0.70}
for i, a in enumerate(ARCH_NAMES):
    m = np.where(arch_id == i)[0]
    if len(m) == 0:
        continue
    pre = rng.random(len(m)) < PRE_SHARE[a]
    off = np.where(pre,
                   -rng.integers(60, 700, len(m)),
                   rng.integers(0, int(N_DAYS * 0.45), len(m)))
    if a == "New & Early Tenure":
        off = rng.integers(N_DAYS - 220, N_DAYS - 10, len(m))
    reg_off[m] = off

reg_date = days.to_numpy()[reg_off]

# Last-active date: lapsed patients stop early
last_off = np.full(n_pat, N_DAYS - 1)
for i, a in enumerate(ARCH_NAMES):
    m = arch_id == i
    if a == "Lapsed One-Time":
        last_off[m] = np.clip(reg_off[m] + rng.integers(0, 120, m.sum()), 0, N_DAYS - 60)
    elif a == "New & Early Tenure":
        last_off[m] = N_DAYS - 1
    else:
        last_off[m] = np.clip(N_DAYS - 1 - rng.poisson(25, m.sum()), 0, N_DAYS - 1)
last_off = np.maximum(last_off, reg_off)

patients = pd.DataFrame({
    "patient_id": pid,
    "age_years": age,
    "gender": gender,
    "home_hospital_id": home_hosp,
    "area_locality": rng.choice(["Ameerpet", "Kukatpally", "LB Nagar", "Miyapur", "Secunderabad",
                                 "Begumpet", "Chandanagar", "Dilsukhnagar"], n_pat),
    "pincode_masked": rng.choice(["500***", "5000**", "5001**", "5002**"], n_pat),
    "registration_date": reg_date,
    "primary_payer": payer,
    "consent_outreach": rng.choice(["Y", "N"], n_pat, p=[0.71, 0.29]),
})
patients["registration_date"] = pd.to_datetime(patients["registration_date"])

# ===========================================================================
# 4. OPD VISITS
# ===========================================================================
# ---------------------------------------------------------------------------
# Visit counts. Indian community-hospital OPD panels are strongly "one-and-done"
# heavy, so the count model is explicit: a per-archetype probability of being a
# single-visit patient, otherwise a negative-binomial repeat count. This
# reproduces the long right tail that RFM frequency scoring must handle.
# ---------------------------------------------------------------------------
SINGLE_P = {"Chronic Care Loyalists": 0.05, "High-Acuity Inpatient": 0.12,
            "Routine Family OPD": 0.28, "New & Early Tenure": 0.58,
            "Lapsed One-Time": 0.86, "Preventive & Wellness": 0.34}
REPEAT_MEAN = {"Chronic Care Loyalists": 9.5, "High-Acuity Inpatient": 4.2,
               "Routine Family OPD": 5.2, "New & Early Tenure": 2.6,
               "Lapsed One-Time": 1.8, "Preventive & Wellness": 3.0}

counts = np.ones(n_pat, dtype=int)
for i, a in enumerate(ARCH_NAMES):
    m = np.where(arch_id == i)[0]
    if len(m) == 0:
        continue
    single = rng.random(len(m)) < SINGLE_P[a]
    tenure_yr = (last_off[m] - reg_off[m] + 1) / 365.25
    mu = REPEAT_MEAN[a] * np.clip(tenure_yr / 2.5, 0.25, 1.6)
    nb = rng.negative_binomial(2.0, 2.0 / (2.0 + mu))
    counts[m] = np.where(single, 1, 1 + nb)

# calibrate to the row budget without destroying the shape
target_opd = 152_000
scale = target_opd / counts.sum()
counts = np.maximum(np.round(counts * scale).astype(int), 1)

pid_rep = np.repeat(pid, counts)
arch_rep = np.repeat(arch_id, counts)
hosp_rep = np.repeat(home_hosp, counts)
reg_rep, last_rep = np.repeat(reg_off, counts), np.repeat(last_off, counts)
n_vis = len(pid_rep)

# visit dates: weighted day sampling inside each patient's active window
visit_off = np.empty(n_vis, dtype=int)
pos = 0
for i in range(n_pat):
    k = int(counts[i])
    if k == 0:
        continue
    lo_i, hi_i = max(0, int(reg_off[i])), int(last_off[i])
    if hi_i <= lo_i:
        visit_off[pos:pos + k] = lo_i
    else:
        seg = DAY_W[lo_i:hi_i + 1]
        p = seg / seg.sum()
        cs = np.cumsum(p)
        idx = np.searchsorted(cs, rng.random(k), side="right")
        visit_off[pos:pos + k] = lo_i + np.clip(idx, 0, len(seg) - 1)
    pos += k
assert pos == n_vis, f"date assignment covered {pos} of {n_vis} visits"
visit_date = days.to_numpy()[visit_off]

# cross-hospital utilisation: 18% of visits happen away from home hospital
away = rng.random(n_vis) < 0.18
hosp_visit = hosp_rep.copy()
alts = np.array(list(C.HOSPITAL_WEIGHTS))
for i in range(n_vis):
    if away[i]:
        choices = alts[alts != hosp_visit[i]]
        w = np.array([C.HOSPITAL_WEIGHTS[h] for h in choices])
        hosp_visit[i] = rng.choice(choices, p=w / w.sum())

# departments: archetype affinity x hospital availability
dept = np.empty(n_vis, dtype=object)
for i, a in enumerate(ARCH_NAMES):
    m = arch_rep == i
    idxs = np.where(m)[0]
    if len(idxs) == 0:
        continue
    if a == "Chronic Care Loyalists":
        pool = CHRONIC_DEPTS * 4 + ["General Medicine"] * 3 + ["Orthopaedics"] * 2
    elif a == "High-Acuity Inpatient":
        pool = ACUTE_DEPTS * 3 + ["General Medicine"] * 2 + ["Nephrology"]
    elif a == "Routine Family OPD":
        pool = FAMILY_DEPTS * 3 + ["General Medicine"] * 3
    elif a == "Preventive & Wellness":
        pool = WELLNESS_DEPTS * 3 + ["Dermatology", "General Medicine"]
    else:
        pool = C.DEPARTMENTS
    for j in idxs:
        allowed = C.HOSPITAL_DEPARTMENTS[hosp_visit[j]]
        cand = [d for d in pool if d in allowed]
        if not cand:
            cand = allowed
        dept[j] = cand[rng.integers(0, len(cand))]

# visit type: first visit of each patient = New
first_mask = np.zeros(n_vis, bool)
_, first_pos = np.unique(pid_rep, return_index=True)
first_mask[first_pos] = True
visit_type = np.where(first_mask | (rng.random(n_vis) < 0.22), "New", "Follow-up")

# planned follow-up interval (days) - only on a subset of follow-up visits
fu_plan = np.where((visit_type == "Follow-up") & (rng.random(n_vis) < 0.62),
                   rng.choice([7, 14, 21, 30, 60, 90], n_vis, p=[0.20, 0.30, 0.14, 0.20, 0.10, 0.06]),
                   0).astype(int)

# diagnosis free text
diag_code = np.empty(n_vis, dtype=object)
diag_text = np.empty(n_vis, dtype=object)
for j in range(n_vis):
    d = dept[j]
    opts = DIAGNOSES.get(d, DIAGNOSES["General Medicine"])
    # chronic archetypes favour chronic diagnoses
    if ARCH_NAMES[arch_rep[j]] in ("Chronic Care Loyalists", "High-Acuity Inpatient"):
        w = np.array([3.0 if o[2] else 1.0 for o in opts])
        k = rng.choice(len(opts), p=w / w.sum())
    else:
        k = rng.integers(0, len(opts))
    diag_code[j], diag_text[j] = opts[k][0], opts[k][1]

df_opd = pd.DataFrame({
    "visit_id": [f"OPD{3000000+i}" for i in range(n_vis)],
    "patient_id": pid_rep,
    "hospital_id": hosp_visit,
    "department": dept,
    "visit_date": visit_date,
    "visit_type": visit_type,
    "diagnosis_text": diag_text,
    "diagnosis_code": diag_code,
    "doctor_id": [f"DR{rng.integers(100, 460)}" for _ in range(n_vis)],
    "consultation_fee": [int(rng.integers(*C.OPD_TARIFF[d])) for d in dept],  # placeholder, repriced later
    "planned_followup_days": fu_plan,
    "token_no": rng.integers(1, 90, n_vis),
})

# consultation fee by department tariff band
df_opd["consultation_fee"] = [int(rng.integers(*C.OPD_TARIFF[d])) for d in df_opd["department"]]

# ===========================================================================
# 5. ADMISSIONS
# ===========================================================================
adm_rows = []
adm_id = 0
visit_by_patient = {}
for p, h, d, dt in zip(df_opd["patient_id"], df_opd["hospital_id"],
                       df_opd["department"], df_opd["visit_date"]):
    visit_by_patient.setdefault(p, []).append((h, d, dt))

for i, p in enumerate(pid):
    a = ARCH_NAMES[arch_id[i]]
    n_v = counts[i]
    p_adm = ARCHETYPES[a][3]
    n_adm = rng.poisson(p_adm * n_v * 2.30)
    if rng.random() < 0.12 and a == "High-Acuity Inpatient":
        n_adm += rng.integers(1, 3)
    n_adm = min(n_adm, 8)
    if n_adm <= 0:
        continue
    pool = visit_by_patient.get(p, [])
    for _ in range(n_adm):
        h, d, dt = pool[rng.integers(0, len(pool))]
        if d == "Dermatology":
            d = "General Medicine"
        if d == "Ophthalmology":
            d = "General Surgery"
        if d not in C.DEPARTMENTS:
            d = "General Medicine"
        admits = pd.Timestamp(dt) + pd.Timedelta(days=int(rng.integers(0, 6)))
        if admits.date() > pd.Timestamp(C.STUDY_END).date():
            continue
        base_los = {"General Surgery": 5.0, "Orthopaedics": 6.0, "Cardiology": 6.5,
                    "Obstetrics & Gynaecology": 3.0, "Paediatrics": 3.5,
                    "General Medicine": 4.2, "Nephrology": 6.0, "Pulmonology": 5.5,
                    "ENT": 3.0, "Dermatology": 3.0, "Ophthalmology": 2.0,
                    "Endocrinology": 3.8}.get(d, 4.0)
        los = int(np.clip(rng.lognormal(np.log(base_los), 0.45), 1, 34))
        # occasional long-stay complex case (genuine, not an error)
        if rng.random() < 0.02:
            los += int(rng.integers(10, 26))
        disch = admits + pd.Timedelta(days=los)
        if disch.date() > pd.Timestamp(C.STUDY_END).date():
            disch = pd.Timestamp(C.STUDY_END)
        adm_id += 1
        opts = DIAGNOSES.get(d, DIAGNOSES["General Medicine"])
        k = rng.integers(0, len(opts))
        icu = int((d in ("Cardiology", "Nephrology", "General Surgery")) and rng.random() < 0.28)
        adm_rows.append({
            "admission_id": f"IPD{400000+adm_id}",
            "patient_id": p, "hospital_id": h, "department": d,
            "admission_date": admits, "discharge_date": disch,
            "admitting_diagnosis": opts[k][1],
            "ward_type": "ICU" if icu else rng.choice(["General Ward", "Private Room", "Semi-Private"]),
            "icu_flag": icu,
            "discharge_status": rng.choice(["Recovered", "Improved", "Referred", "LAMA", "Expired"],
                                           p=[0.72, 0.19, 0.055, 0.03, 0.005]),
        })

df_adm = pd.DataFrame(adm_rows)
df_adm["admission_date"] = pd.to_datetime(df_adm["admission_date"])
df_adm["discharge_date"] = pd.to_datetime(df_adm["discharge_date"])
print(f"   admissions: {len(df_adm):,}")

# ===========================================================================
# 6. LAB TESTS
# ===========================================================================
dept_test_aff = {
    "Endocrinology": 1.9, "Nephrology": 1.8, "Cardiology": 1.5, "Pulmonology": 1.2,
    "General Medicine": 1.1, "Obstetrics & Gynaecology": 1.0, "Paediatrics": 0.7,
    "Orthopaedics": 0.6, "General Surgery": 0.8, "Dermatology": 0.3,
    "ENT": 0.35, "Ophthalmology": 0.3,
}
lab_p = np.array([dept_test_aff[d] for d in df_opd["department"]])
do_lab = rng.random(n_vis) < np.clip(lab_p * 0.22 * np.where(
    np.isin(arch_rep, [0, 5]), 1.5, 1.0), 0, 0.85)
n_tests = np.where(do_lab, rng.integers(1, 4, n_vis), 0)
if n_tests.sum() > 50_000:      # tighten to row budget
    keep = rng.random(n_vis) < (50_000 / n_tests.sum())
    n_tests = np.where(keep, n_tests, 0)
test_idx = np.repeat(np.arange(n_vis), n_tests)
lab_names, lab_price = zip(*[(t[0], t[1]) for t in C.LAB_TESTS])
lab_pick = rng.integers(0, len(lab_names), len(test_idx))
lab = pd.DataFrame({
    "test_id": [f"LAB{5000000+i}" for i in range(len(test_idx))],
    "visit_id": df_opd["visit_id"].to_numpy()[test_idx],
    "patient_id": df_opd["patient_id"].to_numpy()[test_idx],
    "hospital_id": df_opd["hospital_id"].to_numpy()[test_idx],
    "test_name": np.array(lab_names)[lab_pick],
    "test_date": df_opd["visit_date"].to_numpy()[test_idx],
    "test_cost": np.array(lab_price)[lab_pick],
})
# 6% walk-in labs with no visit linkage (orphan records - a real integration gap)
orph = 0.06
om = rng.random(len(lab)) < orph
lab.loc[om, "visit_id"] = np.nan
print(f"   lab tests: {len(lab):,}")

# ===========================================================================
# 7. BILLING  (OPD consultation lines + IPD room/procedure lines)
# ===========================================================================
def gst_for(kind, base):
    rate = {"OPD_CONSULTATION": 0.0, "IPD_ROOM": 0.0, "PROCEDURE": 0.0,
            "LAB": 0.0, "PHARMACY": 0.05, "CONSUMABLES": 0.12}[kind]
    return rate, np.round(base * rate, 2)

bill_rows = []
# --- OPD lines: consultation + optional pharmacy line
opd_pharm = rng.random(n_vis) < 0.25
for i in range(n_vis):
    base = float(df_opd["consultation_fee"].iloc[i])
    bill_rows.append((df_opd["visit_id"].iloc[i], df_opd["patient_id"].iloc[i],
                      df_opd["hospital_id"].iloc[i], df_opd["visit_date"].iloc[i],
                      "OPD_CONSULTATION", df_opd["department"].iloc[i],
                      0.0, base))
    if opd_pharm[i]:
        pb = float(np.round(base * rng.uniform(0.4, 1.8), 2))
        bill_rows.append((df_opd["visit_id"].iloc[i], df_opd["patient_id"].iloc[i],
                          df_opd["hospital_id"].iloc[i], df_opd["visit_date"].iloc[i],
                          "PHARMACY", df_opd["department"].iloc[i], 0.0, pb))

# --- IPD lines: room charge + one procedure/consumable line
for r in df_adm.itertuples():
    los = max((r.discharge_date - r.admission_date).days, 1)
    day_rate = C.IPD_DAY_RATE.get(r.department, 4000) * (2.1 if r.icu_flag else 1.0)
    disc = float(np.round(rng.uniform(0.05, 0.18), 3))
    bill_rows.append((r.admission_id, r.patient_id, r.hospital_id, r.admission_date,
                      "IPD_ROOM", r.department, disc, round(day_rate * los, 2)))
    kind = "PROCEDURE" if rng.random() < 0.62 else "CONSUMABLES"
    mult = rng.uniform(0.35, 1.4) if kind == "PROCEDURE" else rng.uniform(0.08, 0.3)
    bill_rows.append((r.admission_id, r.patient_id, r.hospital_id, r.admission_date,
                      kind, r.department, disc, round(day_rate * los * mult, 2)))

bl = pd.DataFrame(bill_rows, columns=["encounter_id", "patient_id", "hospital_id",
                                      "service_date", "service_type", "department",
                                      "discount_pct", "base_amount"])
bl["base_amount"] = (bl["base_amount"] * (1 - bl["discount_pct"])).round(2)
gst = [gst_for(k, b) for k, b in zip(bl["service_type"], bl["base_amount"])]
bl["gst_rate"] = [g[0] for g in gst]
bl["gst_amount"] = [g[1] for g in gst]
bl["total_amount"] = (bl["base_amount"] + bl["gst_amount"]).round(2)
bl["bill_id"] = [f"BILL{7000000+i}" for i in range(len(bl))]
bl["payment_mode"] = rng.choice(["UPI", "Cash", "Card", "Insurance Claim"],
                                len(bl), p=[0.44, 0.31, 0.15, 0.10])
bl["payer_type"] = np.where(bl["payment_mode"] == "Insurance Claim", "Insurance/TPA", "Cash")
bl["service_date"] = pd.to_datetime(bl["service_date"])
print(f"   billing lines: {len(bl):,}")

# ===========================================================================
# 8. DEFECT INJECTION  (with a register so cleaning can be validated)
# ===========================================================================
register = []


def log_defect(table, defect, n, rule):
    register.append({"table": table, "defect": defect, "injected_records": int(n),
                     "rule": rule})


# ---- 8.1 diagnosis free-text variants
cand = df_opd["diagnosis_text"].isin(DIAG_VARIANTS)
pick = cand & (rng.random(n_vis) < 0.35)
for j in np.where(pick)[0]:
    df_opd.at[j, "diagnosis_text"] = DIAG_VARIANTS[df_opd.at[j, "diagnosis_text"]][
        rng.integers(0, len(DIAG_VARIANTS[df_opd.at[j, "diagnosis_text"]]))]
log_defect("opd_visits", "diagnosis_free_text_variants", pick.sum(),
           "canonical diagnosis rewritten to abbreviation/synonym/typo")

# ---- 8.2 age field containing year of birth / impossible values
age_defect = rng.random(n_pat) < 0.035
dob_rows = np.where(age_defect)[0]
for j in dob_rows:
    if rng.random() < 0.7:            # birth year entered in the age column
        patients.at[j, "age_years"] = int(rng.integers(1940, 2012))
    else:                             # impossible / negative age
        patients.at[j, "age_years"] = int(rng.integers(-8, -1))
log_defect("patients", "age_field_holds_year_of_birth_or_impossible", len(dob_rows),
           "age_years value > 110 or < 0")

# ---- 8.3 hospital name drift
for hid, variants in HOSP_VARIANTS.items():
    m = df_opd["hospital_id"] == hid
    idx = np.where(m)[0]
    k = int(len(idx) * 0.08)
    sel = rng.choice(idx, k, replace=False)
    df_opd.loc[sel, "hospital_id"] = [variants[rng.integers(0, len(variants))] for _ in sel]
_hosp_drift_n = int(df_opd["hospital_id"].astype(str).str.len().gt(6).sum())
log_defect("opd_visits", "hospital_name_inconsistency", _hosp_drift_n,
           "hospital_id written as full name / different case / spacing")

# ---- 8.4 department name drift
idx = np.where(df_opd["department"].isin(DEPT_VARIANTS))[0]
sel = rng.choice(idx, int(len(idx) * 0.06), replace=False)
df_opd.loc[sel, "department"] = [rng.choice(DEPT_VARIANTS[df_opd.at[s, "department"]]) for s in sel]
log_defect("opd_visits", "department_name_inconsistency", len(sel),
           "department written as abbreviation / different case / trailing space")

# ---- 8.5 missing values
def sprinkle(df, col, frac, where=None):
    n = int(len(df) * frac)
    m = pd.Series(False, index=df.index)
    pool = df.index if where is None else df.index[where]
    if len(pool) == 0:
        return 0
    m.loc[rng.choice(pool, min(n, len(pool)), replace=False)] = True
    df.loc[m, col] = np.nan
    return int(m.sum())

n_miss = {}
n_miss["opd.patient_id"] = sprinkle(df_opd, "patient_id", 0.004)
n_miss["opd.visit_date"] = sprinkle(df_opd, "visit_date", 0.003)
n_miss["opd.department"] = sprinkle(df_opd, "department", 0.011)
n_miss["opd.diagnosis_text"] = sprinkle(df_opd, "diagnosis_text", 0.024)
n_miss["opd.consultation_fee"] = sprinkle(df_opd, "consultation_fee", 0.005)
n_miss["adm.discharge_date"] = sprinkle(df_adm, "discharge_date", 0.008)
n_miss["bill.gst_amount"] = sprinkle(bl, "gst_amount", 0.006)
n_miss["lab.test_cost"] = sprinkle(lab, "test_cost", 0.004)
for k, v in n_miss.items():
    log_defect(k.split(".")[0], f"missing_value::{k.split('.')[1]}", v, "random missingness injected")

# ---- 8.6 duplicate visits and admissions
dup_opd_idx = rng.choice(len(df_opd), int(len(df_opd) * 0.018), replace=False)
dup_opd = df_opd.loc[dup_opd_idx].copy()
dup_opd["visit_id"] = [f"OPD{9000000+i}" for i in range(len(dup_opd))]   # new ID, same encounter
df_opd = pd.concat([df_opd, dup_opd], ignore_index=True)
log_defect("opd_visits", "duplicate_visits", len(dup_opd),
           "same patient+date+department re-issued under a new visit_id")

dup_adm_idx = rng.choice(len(df_adm), int(len(df_adm) * 0.009), replace=False)
dup_adm = df_adm.loc[dup_adm_idx].copy()
dup_adm["admission_id"] = [f"IPD{900000+i}" for i in range(len(dup_adm))]
df_adm = pd.concat([df_adm, dup_adm], ignore_index=True)
log_defect("admissions", "duplicate_admissions", len(dup_adm),
           "same patient+dates re-issued under a new admission_id")

# ---- 8.7 double GST in total_amount
taxable = bl["gst_rate"] > 0
gst_dup = taxable & (rng.random(len(bl)) < 0.06)
bl.loc[gst_dup, "total_amount"] = (bl.loc[gst_dup, "base_amount"]
                                   + 2 * bl.loc[gst_dup, "gst_amount"]).round(2)
log_defect("billing", "duplicate_gst_in_total", gst_dup.sum(),
           "total_amount = base + 2 x gst_amount (GST counted twice)")

# ---- 8.8 invalid billing amounts
neg = rng.random(len(bl)) < 0.003
zero = (~neg) & (rng.random(len(bl)) < 0.002)
infl = (~neg) & (~zero) & (rng.random(len(bl)) < 0.0015)
bl.loc[neg, "total_amount"] = -bl.loc[neg, "total_amount"].abs()
bl.loc[zero, "total_amount"] = 0.0
bl.loc[infl, "total_amount"] = bl.loc[infl, "total_amount"] * 10
log_defect("billing", "invalid_total_amount", int((neg | zero | infl).sum()),
           "negative / zero / 10x inflated total_amount")

# ---- 8.9 impossible dates
fut = rng.random(len(bl)) < 0.004
bl.loc[fut, "service_date"] = pd.Timestamp("2025-06-15") + pd.to_timedelta(
    rng.integers(0, 200, fut.sum()), unit="D")
log_defect("billing", "impossible_service_date", int(fut.sum()),
           "service_date after study end")

bad_adm = rng.random(len(df_adm)) < 0.005
flip = df_adm.loc[bad_adm]
df_adm.loc[bad_adm, "admission_date"] = flip["discharge_date"].values
df_adm.loc[bad_adm, "discharge_date"] = flip["admission_date"].values
log_defect("admissions", "discharge_before_admission", int(bad_adm.sum()),
           "admission_date and discharge_date swapped")

# register the hospital-name count properly (name drift happens after masking)
# (count captured above at injection time)
register = [r for r in register if r["injected_records"] > 0]

# ===========================================================================
# 9. WRITE
# ===========================================================================
df_opd = df_opd.sample(frac=1.0, random_state=C.RANDOM_SEED).reset_index(drop=True)
bl = bl.sample(frac=1.0, random_state=C.RANDOM_SEED).reset_index(drop=True)
lab = lab.sample(frac=1.0, random_state=C.RANDOM_SEED).reset_index(drop=True)
df_adm = df_adm.sample(frac=1.0, random_state=C.RANDOM_SEED).reset_index(drop=True)

patients.to_csv(RAW / "patients.csv", index=False)
df_opd.to_csv(RAW / "opd_visits.csv", index=False)
df_adm.to_csv(RAW / "admissions.csv", index=False)
lab.to_csv(RAW / "lab_tests.csv", index=False)
bl.to_csv(RAW / "billing.csv", index=False)

pd.DataFrame(register).to_csv(RAW / "_injected_defect_register.csv", index=False)

# latent truth (validation benchmark only - never a model input)
pd.DataFrame({"patient_id": pid, "latent_archetype": arch_name,
              "registration_date": patients["registration_date"]}
             ).to_csv(RAW / "_ground_truth_latent_labels.csv", index=False)

# province manifest
total = len(df_opd) + len(df_adm) + len(lab) + len(bl)
manifest = pd.DataFrame([
    {"table": "patients", "rows": len(patients), "cols": patients.shape[1],
     "grain": "one row per patient"},
    {"table": "opd_visits", "rows": len(df_opd), "cols": df_opd.shape[1],
     "grain": "one row per outpatient consultation"},
    {"table": "admissions", "rows": len(df_adm), "cols": df_adm.shape[1],
     "grain": "one row per inpatient admission"},
    {"table": "lab_tests", "rows": len(lab), "cols": lab.shape[1],
     "grain": "one row per laboratory test"},
    {"table": "billing", "rows": len(bl), "cols": bl.shape[1],
     "grain": "one row per bill line"},
])
manifest.to_csv(RAW / "_manifest.csv", index=False)

print("\n=== SYNTHETIC DATASET BUILT (NOT REAL HOSPITAL DATA) ===")
print(manifest.to_string(index=False))
print(f"Total transactional rows: {total:,}")
print(f"Defects injected: {len(register)} families, "
      f"{int(sum(r['injected_records'] for r in register)):,} records")
