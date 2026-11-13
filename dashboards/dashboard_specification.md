# Interactive Dashboard — Complete Build Specification

**Status:** specification + reproducible data model + working HTML prototype.
A native `.pbix` / `.twbx` file cannot be authored in this environment (no Power BI
Desktop / Tableau Desktop), so this document is the build instruction set. The star
schema it refers to is exported and ready to import.

> ⚠️ **Data provenance:** the dataset is **synthetic**. Nothing on these dashboards
> describes a real hospital.

---

## 1. Data model (star schema)

Import from `dashboards/power_bi/data/`.

| Table | Type | Key | Grain | Rows |
|---|---|---|---|---|
| `Fact_OPD` | Fact | `visit_id` | One outpatient consultation | see file |
| `Fact_Admission` | Fact | `admission_id` | One inpatient admission | see file |
| `Fact_Lab` | Fact | `test_id` | One laboratory test | see file |
| `Fact_Billing` | Fact | `bill_id` | One bill line | see file |
| `Fact_Migration` | Fact | composite | Segment pair across periods | 9 |
| `Dim_Patient` | Dimension | `patient_id` | One patient + segment assignment | all |
| `Dim_Hospital` | Dimension | `hospital_id` | One site | 4 |
| `Dim_Department` | Dimension | `department` | Canonical department | 12 |
| `Dim_Diagnosis` | Dimension | `diagnosis_code` | Canonical diagnosis + chronic flag | 45 |
| `Dim_Date` | Dimension | `date` | Calendar, 2022-01-01 to 2024-12-31 | 1,096 |

**Relationships**

```
Dim_Date[date]        1 ── * Fact_OPD[date]
Dim_Date[date]        1 ── * Fact_Admission[date]
Dim_Date[date]        1 ── * Fact_Lab[date]
Dim_Date[date]        1 ── * Fact_Billing[date]
Dim_Patient[patient_id] 1 ── * Fact_OPD / Fact_Admission / Fact_Lab / Fact_Billing
Dim_Hospital[hospital_id] 1 ── * Fact_*  and  * Dim_Patient
Dim_Department[department] 1 ── * Fact_OPD / Fact_Admission / Fact_Billing
Dim_Diagnosis[diagnosis] 1 ── * Fact_OPD
```

Mark `Dim_Date` as a date table (`Dim_Date[date]`), and set all fact→dimension
relationships to **single direction**. Segment filtering flows through `Dim_Patient`.

---

## 2. Calculated measures (DAX)

```dax
Total Billing = SUM ( Fact_Billing[total_amount] )

Total Patients = DISTINCTCOUNT ( Dim_Patient[patient_id] )

OPD Visits = COUNTROWS ( Fact_OPD )

Admissions = COUNTROWS ( Fact_Admission )

ALOS =
    DIVIDE ( SUM ( Fact_Admission[los_days] ), COUNTROWS ( Fact_Admission ) )

Total Beds = SUM ( Dim_Hospital[beds] )

Days in Period =
    COUNTROWS ( Dim_Date )

Bed Occupancy % =
    DIVIDE ( SUM ( Fact_Admission[los_days] ), [Total Beds] * [Days in Period] )

Bed Days per 100 Patients =
    DIVIDE ( SUM ( Fact_Admission[los_days] ) * 100, [Total Patients] )

Revenue per Patient =
    DIVIDE ( [Total Billing], [Total Patients] )

OPD Revenue =
    CALCULATE ( [Total Billing], Fact_Billing[encounter_type] = "OPD" )

Revenue per Visit =
    DIVIDE ( [OPD Revenue], [OPD Visits] )

Patients Admitted =
    CALCULATE ( [Total Patients], Dim_Patient[admission_count] > 0 )

Readmission Rate 30d =
    DIVIDE (
        CALCULATE ( [Total Patients], Dim_Patient[readmission_30d] = 1 ),
        [Patients Admitted]
    )

Segment Revenue Share % =
    DIVIDE ( [Total Billing],
             CALCULATE ( [Total Billing], ALL ( Dim_Patient[segment_name] ) ) )

Segment Patient Share % =
    DIVIDE ( [Total Patients],
             CALCULATE ( [Total Patients], ALL ( Dim_Patient[segment_name] ) ) )

Active Patients 90d =
    CALCULATE ( [Total Patients], Dim_Patient[recency_days] <= 90 )

Dormant Patients 365d =
    CALCULATE ( [Total Patients], Dim_Patient[recency_days] > 365 )

Follow-up Compliance % =
    AVERAGE ( Dim_Patient[followup_compliance] )

Migration Retention % =
    DIVIDE (
        CALCULATE ( SUM ( Fact_Migration[patients] ),
                    FILTER ( Fact_Migration, Fact_Migration[P1_segment] = Fact_Migration[P2_segment] ) ),
        SUM ( Fact_Migration[patients] )
    )

Prior Period Billing =
    CALCULATE ( [Total Billing],
                DATEADD ( Dim_Date[date], -12, MONTH ) )

Billing YoY % =
    DIVIDE ( [Total Billing] - [Prior Period Billing], [Prior Period Billing] )
```

---

## 3. Pages and visuals

### Page 1 — Hospital overview
| Element | Type | Fields |
|---|---|---|
| KPI strip | 4 cards | Total Patients · OPD Visits · Admissions · Total Billing |
| Volume by site | Clustered bar | `Dim_Hospital[hospital_name]` × OPD Visits, Admissions |
| Monthly trend | Line | `Dim_Date[year_month]` × Total Billing, OPD Visits |
| Seasonality | Column | `Dim_Date[month_name]` × OPD Visits |
| Slicers | 3 | Date range · `Dim_Hospital` · `Dim_Patient[primary_payer]` |

**Message:** which site carries the load, and how demand moves across the year.

### Page 2 — Segmentation overview
| Element | Type | Fields |
|---|---|---|
| Segment mix | Donut | `Dim_Patient[segment_name]` × Segment Patient Share % |
| Value concentration | Treemap | `segment_name` × Total Billing |
| Segment KPIs | Clustered bar | `Segment_KPIs[kpi]` by segment (small multiples) |
| Active vs dormant | Stacked bar | hospital × Active Patients 90d / Dormant Patients 365d |
| Slicers | 3 | Segment · Hospital · Department |

**Message:** value is concentrated; the dormant majority is the recoverable pool.

### Page 3 — Revenue and utilisation
| Element | Type | Fields |
|---|---|---|
| Revenue by service line | Stacked bar | hospital × `Fact_Billing[service_type]` |
| Revenue per visit by department | Bar | `Dim_Department` × Revenue per Visit |
| Bed-day consumption | Bar | `segment_name` × Bed Days per 100 Patients |
| Billing distribution | Histogram (bin) | `Fact_Billing[total_amount]` |
| Matrix | Table | department × (visits, admissions, revenue, ALOS) |

### Page 4 — Department performance
| Element | Type | Fields |
|---|---|---|
| Performance matrix | Matrix with conditional formatting | Department rows; Visits, Admissions, ALOS, Revenue per Visit, Bed Occupancy % |
| Top diagnoses | Bar | `Dim_Diagnosis[diagnosis]` filtered to chronic_flag = 1 |
| Department trend | Line | `year_month` × visits, by department slicer |

### Page 5 — Segment comparison
Matrix reproducing the consolidated profile table (report Table 13.1), with
drill-through to a patient list. Fields: segment rows × (Patients, % base,
% revenue, Recency, Visits, Billing/patient, Billing/visit, ALOS, Admission rate,
Labs/visit, Departments, Readmission %, Age, % female).

### Page 6 — Readmission and LOS
| Element | Type | Fields |
|---|---|---|
| Readmission KPI | Card | Readmission Rate 30d |
| Readmission by segment | Bar | segment × Readmission Rate 30d |
| Readmission by department | Bar | department × Readmission Rate 30d |
| LOS distribution | Histogram | `Fact_Admission[los_days]` |
| ALOS trend | Line | `year_month` × ALOS |

### Page 7 — Segment migration
| Element | Type | Fields |
|---|---|---|
| Migration heatmap | Matrix + conditional formatting | `Fact_Migration[P1_segment]` rows × `P2_segment` columns × patients |
| Retention | Bar | Migration Retention % by P1 segment |
| Size drift | Clustered bar | segment × P1 / P2 patient counts |

---

## 4. Interactivity

- **Slicers** on every page: date range, hospital, department, segment, payer.
- **Drill-through:** from any segment visual → *Patient detail* page filtered to the segment.
- **Drill-down hierarchy:** Hospital → Department → Segment.
- **Bookmarks:** "Base case" / "Pessimistic" toggle on the migration page.
- **Row-level security** on `hospital_id` so a site head sees only their own site.

```dax
-- RLS role for site heads
[hospital_id] = LOOKUPVALUE (
    Dim_Hospital[hospital_id],
    Dim_Hospital[hospital_id], USERPRINCIPALNAME ()
)
```
(In practice, map an identity table to hospital; the pattern is the same.)

---

## 5. Build steps (reproducible)

1. Open Power BI Desktop → *Get Data* → *Text/CSV* → import all files from
   `dashboards/power_bi/data/`.
2. In Power Query, set `date`, `test_date`, `admission_date`, `discharge_date` and
   `service_date` to **Date** type.
3. Create the relationships listed in section 1; mark `Dim_Date` as the date table.
4. Paste the DAX measures from section 2 into a `_Measures` table.
5. Build the seven pages from section 3.
6. Add the `ROWS`/`VALUES` slicers and the drill-through page.
7. Set RLS roles and publish to the workspace.
8. Schedule refresh if the source moves to a database; the CSV export is a snapshot.

**Tableau equivalent:** connect to the same CSVs, build one data source per fact with
the dimensions joined (Tableau prefers a physical join over a star), and recreate the
calculated fields with the same formulas — `ZN`, `COUNTD`, `SUM([total_amount]) /
COUNTD([patient_id])` and so on.

---

## 6. Prototype

`dashboards/dashboard_prototype.html` is a self-contained, offline interactive
prototype built from the real pipeline outputs. It is not a substitute for the Power BI
build, but it demonstrates every page's content and lets a reviewer click through the
segments before the BI tool is licensed.
