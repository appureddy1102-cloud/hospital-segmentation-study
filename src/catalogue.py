"""
catalogue.py
============
Shared reference catalogues (diagnoses, free-text variants, hospital and
department naming drift). Imported by both the synthetic generator and the
cleaning pipeline so that the two can never drift apart.
"""
from __future__ import annotations

CHRONIC_DEPTS = ["Endocrinology", "Nephrology", "Cardiology", "Pulmonology"]
FAMILY_DEPTS = ["Paediatrics", "Obstetrics & Gynaecology", "Dermatology", "ENT"]
ACUTE_DEPTS = ["General Surgery", "Orthopaedics", "Cardiology", "General Medicine"]
WELLNESS_DEPTS = ["Ophthalmology", "Endocrinology", "General Medicine"]

# Canonical diagnosis catalogue per department: (code, canonical text, chronic_flag)
DIAGNOSES = {
    "General Medicine": [
        ("GM01", "Acute Viral Fever", 0), ("GM02", "Type 2 Diabetes Mellitus", 1),
        ("GM03", "Essential Hypertension", 1), ("GM04", "Acute Gastroenteritis", 0),
        ("GM05", "Iron Deficiency Anaemia", 0), ("GM06", "Upper Respiratory Tract Infection", 0),
    ],
    "General Surgery": [
        ("GS01", "Acute Appendicitis", 0), ("GS02", "Inguinal Hernia", 0),
        ("GS03", "Cholelithiasis", 0), ("GS04", "Acute Fissure in Ano", 0),
    ],
    "Orthopaedics": [
        ("OR01", "Osteoarthritis of Knee", 1), ("OR02", "Fracture of Distal Radius", 0),
        ("OR03", "Mechanical Low Back Pain", 1), ("OR04", "Ligament Injury of Knee", 0),
    ],
    "Paediatrics": [
        ("PD01", "Acute Bronchiolitis", 0), ("PD02", "Febrile Illness in Child", 0),
        ("PD03", "Acute Otitis Media", 0), ("PD04", "Protein Energy Malnutrition", 1),
    ],
    "Obstetrics & Gynaecology": [
        ("OG01", "Antenatal Care - Second Trimester", 0), ("OG02", "Abnormal Uterine Bleeding", 0),
        ("OG03", "Polycystic Ovary Syndrome", 1), ("OG04", "Postnatal Care", 0),
    ],
    "Cardiology": [
        ("CD01", "Congestive Heart Failure", 1), ("CD02", "Stable Angina Pectoris", 1),
        ("CD03", "Atrial Fibrillation", 1), ("CD04", "Acute Coronary Syndrome", 0),
    ],
    "Dermatology": [
        ("DR01", "Atopic Dermatitis", 1), ("DR02", "Tinea Corporis", 0),
        ("DR03", "Acne Vulgaris", 0), ("DR04", "Chronic Urticaria", 1),
    ],
    "ENT": [
        ("EN01", "Chronic Suppurative Otitis Media", 1), ("EN02", "Allergic Rhinitis", 1),
        ("EN03", "Acute Tonsillitis", 0),
    ],
    "Ophthalmology": [
        ("OP01", "Senile Cataract", 1), ("OP02", "Refractive Error", 0),
        ("OP03", "Diabetic Retinopathy", 1), ("OP04", "Acute Conjunctivitis", 0),
    ],
    "Pulmonology": [
        ("PU01", "Chronic Obstructive Pulmonary Disease", 1), ("PU02", "Bronchial Asthma", 1),
        ("PU03", "Community Acquired Pneumonia", 0),
    ],
    "Endocrinology": [
        ("ED01", "Type 2 Diabetes Mellitus", 1), ("ED02", "Hypothyroidism", 1),
        ("ED03", "Obesity with Metabolic Syndrome", 1),
    ],
    "Nephrology": [
        ("NP01", "Chronic Kidney Disease Stage 3", 1), ("NP02", "Acute Kidney Injury", 0),
        ("NP03", "Nephrotic Syndrome", 1),
    ],
}

# ---------------------------------------------------------------------------
# Free-text defect dictionary (canonical -> observed variants)
# 35% of diagnosis cells are rewritten into one of these variants.
# ---------------------------------------------------------------------------
DIAG_VARIANTS = {
    "Type 2 Diabetes Mellitus": [
        "T2DM", "type2 diabetes", "Type-2 D.M.", "DM Type II", "Diabetes Mellitus Type2",
        "Diabetis Mellitus Type 2", "Type 2 Diabetes mellitus (T2DM)", "T2 DM"],
    "Essential Hypertension": [
        "HTN", "essential HTN", "Hypertension essential", "HYPERTENSION",
        "Esenntial Hypertension", "HTN - essential"],
    "Acute Viral Fever": ["AVF", "viral fever", "Viral Fever (acute)", "Acute viral pyrexia"],
    "Upper Respiratory Tract Infection": ["URTI", "upper respiratory infection", "URTI (viral)"],
    "Acute Gastroenteritis": ["AGE", "acute gastro-enteritis", "Gastroenteritis acute", "Acute GE"],
    "Community Acquired Pneumonia": ["CAP", "community acquired pneumonia", "Pneumonia - community acquired"],
    "Chronic Obstructive Pulmonary Disease": ["COPD", "C.O.P.D", "Chronic obstructive lung disease"],
    "Congestive Heart Failure": ["CHF", "CCF", "Congestive cardiac failure", "congestive heart failure"],
    "Chronic Kidney Disease Stage 3": ["CKD stage3", "CKD-3", "Chronic kidney disease stage III"],
    "Acute Appendicitis": ["appendicitis acute", "Ac Appendicitis", "ACUTE APPENDICITIS"],
    "Osteoarthritis of Knee": ["OA knee", "Osteoarthrosis knee", "Knee OA bilateral"],
    "Senile Cataract": ["Cataract - senile", "senile cataract (both eyes)", "CATARACT SENILE"],
    "Antenatal Care - Second Trimester": ["ANC 2nd trimester", "Antenatal care 2nd trim", "ANC - II trimester"],
    "Acute Bronchiolitis": ["Bronchiolitis acute", "acute bronchiolitis (viral)"],
    "Hypothyroidism": ["hypothyroid", "Hypo-thyroidism", "Hypothyroidism (primary)"],
}

# Hospital & department spelling drift
HOSP_VARIANTS = {
    "HSP-01": ["HSP-01", "hsp 01", "Hosp-1", "Ameerpet Community Hospital", "AMEERPET COMMUNITY HOSPITAL"],
    "HSP-02": ["HSP-02", "hsp-02 ", "Hosp-2", "Kukatpally Community Hospital", "KUKATPALLY COMMUNITY HOSPITAL"],
    "HSP-03": ["HSP-03", "hsp 03", "Hosp-3", "LB Nagar Community Hospital", "L B Nagar Community Hospital"],
    "HSP-04": ["HSP-04", "Hosp-4", "Miyapur Community Hospital", "MIYAPUR COMMUNITY HOSPITAL"],
}
DEPT_VARIANTS = {
    "General Medicine": ["Gen Med", "general medicine", "GENERAL MEDICINE", "Gen. Medicine", "Generalmedicine"],
    "General Surgery": ["Gen Surg", "general surgery", "GEN SURGERY", "Gen. Surgery"],
    "Orthopaedics": ["Ortho", "orthopaedics", "ORTHOPEDICS", "Ortho.", "Orthopaedics "],
    "Paediatrics": ["Paeds", "pediatrics", "PAEDIATRICS", "Paed.", "Pediatrics "],
    "Obstetrics & Gynaecology": ["OBG", "obstetrics and gynaecology", "OBSTETRICS & GYNECOLOGY", "Obs & Gyn"],
    "Cardiology": ["Cardio", "cardiology", "CARDIOLOGY", "Cardio."],
    "Dermatology": ["Derm", "dermatology", "DERMATOLOGY", "Derm."],
    "ENT": ["E.N.T", "ent", "Ent", "ENT "],
    "Ophthalmology": ["Ophthal", "ophthalmology", "OPHTHALMOLOGY", "Eye"],
    "Pulmonology": ["Pulmo", "pulmonology", "PULMONOLOGY", "Pulm. Medicine"],
    "Endocrinology": ["Endo", "endocrinology", "ENDOCRINOLOGY", "Endo."],
    "Nephrology": ["Nephro", "nephrology", "NEPHROLOGY", "Neph."],
}

