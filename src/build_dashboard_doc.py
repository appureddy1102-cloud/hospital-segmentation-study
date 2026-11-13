"""
build_dashboard_doc.py
======================
Produces dashboards/dashboard_specification.md and the star-schema CSV exports
that back the Power BI / Tableau build, plus a self-contained interactive HTML
prototype (dashboards/dashboard_prototype.html) that renders the real analysis
outputs with inline CSS/SVG so it previews without any network access.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pandas as pd

import config as C

DASH = C.ROOT / "dashboards"
PROC, OUTD, FIG = C.DATA_PROC, C.OUT_DIR, C.FIG_DIR
DASH.mkdir(parents=True, exist_ok=True)

# ===========================================================================
# 1. Star schema exports
# ===========================================================================
def build_star_schema():
    d = DASH / "power_bi" / "data"
    d.mkdir(parents=True, exist_ok=True)

    pat = pd.read_parquet(PROC / "patients_clean.parquet")
    km = pd.read_parquet(PROC / "kmeans_segmented.parquet")
    opd = pd.read_parquet(PROC / "opd_clean.parquet")
    adm = pd.read_parquet(PROC / "admissions_clean.parquet")
    lab = pd.read_parquet(PROC / "lab_clean.parquet")
    bill = pd.read_parquet(PROC / "billing_clean.parquet")

    # Dim_Patient
    dp = km[["patient_id", "segment", "cluster", "age", "gender", "home_hospital_id",
             "primary_payer", "recency_days", "frequency", "monetary", "admission_count",
             "readmission_30d", "followup_compliance", "consent_outreach"]].copy()
    dp.rename(columns={"home_hospital_id": "hospital_id", "segment": "segment_name"}, inplace=True)
    dp.to_csv(d / "Dim_Patient.csv", index=False)

    # Dim_Hospital
    dh = pd.DataFrame([{"hospital_id": k, "hospital_name": v["name"], "beds": v["beds"],
                        "zone": v["zone"], "tier": v["tier"]} for k, v in C.HOSPITALS.items()])
    dh.to_csv(d / "Dim_Hospital.csv", index=False)

    # Dim_Department / Dim_Diagnosis
    dep = pd.DataFrame({"department": sorted(opd["department"].dropna().unique())})
    dep.to_csv(d / "Dim_Department.csv", index=False)
    from catalogue import DIAGNOSES
    diag = pd.DataFrame([{"diagnosis_code": c, "diagnosis": n, "department": dp_,
                          "chronic_flag": f}
                         for dp_, lst in DIAGNOSES.items() for c, n, f in lst])
    diag.to_csv(d / "Dim_Diagnosis.csv", index=False)

    # Dim_Date
    dates = pd.date_range(C.STUDY_START, C.STUDY_END, freq="D")
    dd = pd.DataFrame({"date": dates})
    dd["year"] = dd.date.dt.year
    dd["quarter"] = dd.date.dt.quarter
    dd["month"] = dd.date.dt.month
    dd["month_name"] = dd.date.dt.strftime("%b")
    dd["year_month"] = dd.date.dt.strftime("%Y-%m")
    dd["weekday"] = dd.date.dt.day_name()
    dd["is_weekend"] = dd.date.dt.dayofweek >= 5
    dd["fy_india"] = dd.date.apply(lambda x: f"FY{x.year if x.month>=4 else x.year-1}-"
                                            f"{str((x.year+1) if x.month>=4 else x.year)[-2:]}")
    dd["date"] = dd["date"].dt.strftime("%Y-%m-%d")
    dd.to_csv(d / "Dim_Date.csv", index=False)

    # Facts (date keys are ISO strings so Power BI parses them as dates)
    f_opd = opd[["visit_id", "patient_id", "hospital_id", "department", "visit_date",
                 "visit_type", "diagnosis_canonical", "consultation_fee"]].copy()
    f_opd["visit_date"] = f_opd["visit_date"].dt.strftime("%Y-%m-%d")
    f_opd.rename(columns={"visit_date": "date", "diagnosis_canonical": "diagnosis"}).to_csv(
        d / "Fact_OPD.csv", index=False)

    f_adm = adm[["admission_id", "patient_id", "hospital_id", "department", "admission_date",
                 "discharge_date", "los_days", "icu_flag", "discharge_status"]].copy()
    f_adm["admission_date"] = f_adm["admission_date"].dt.strftime("%Y-%m-%d")
    f_adm["discharge_date"] = f_adm["discharge_date"].dt.strftime("%Y-%m-%d")
    f_adm.rename(columns={"admission_date": "date"}).to_csv(d / "Fact_Admission.csv", index=False)

    f_lab = lab[["test_id", "patient_id", "hospital_id", "test_name", "test_date", "test_cost"]].copy()
    f_lab["test_date"] = f_lab["test_date"].dt.strftime("%Y-%m-%d")
    f_lab.rename(columns={"test_date": "date"}).to_csv(d / "Fact_Lab.csv", index=False)

    f_bill = bill[["bill_id", "patient_id", "hospital_id", "service_date", "service_type",
                   "department", "base_amount", "gst_amount", "total_amount", "encounter_type"]].copy()
    f_bill["service_date"] = f_bill["service_date"].dt.strftime("%Y-%m-%d")
    f_bill.rename(columns={"service_date": "date"}).to_csv(d / "Fact_Billing.csv", index=False)

    # segment KPI table for the comparison page
    kp = pd.read_csv(OUTD / "final_segment_profiles.csv")
    kp.to_csv(d / "Segment_KPIs.csv", index=False)

    # migration fact
    mig = pd.read_csv(OUTD / "migration_matrix_kmeans.csv", index_col=0)
    mm = mig.stack().reset_index()
    mm.columns = ["P1_segment", "P2_segment", "patients"]
    mm.to_csv(d / "Fact_Migration.csv", index=False)

    print(f"star schema written to {d} ({len(list(d.glob('*.csv')))} files)")
    return d


# ===========================================================================
# 2. Specification markdown
# ===========================================================================
SPEC = r"""# Interactive Dashboard — Complete Build Specification

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
"""


def write_spec():
    p = DASH / "dashboard_specification.md"
    p.write_text(SPEC)
    print(f"spec written: {p}")


# ===========================================================================
# 3. HTML prototype
# ===========================================================================
def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def build_html():
    prof = pd.read_csv(OUTD / "final_segment_profiles.csv")
    rec = pd.read_csv(OUTD / "recommendations_cost_benefit.csv")
    diff = pd.read_csv(OUTD / "segment_kpi_differences.csv")
    eda = json.loads((OUTD / "eda_stats.json").read_text())
    stab = json.loads((OUTD / "stability_summary.json").read_text())
    kmeans = json.loads((OUTD / "kmeans_metrics.json").read_text())
    mig = pd.read_csv(OUTD / "migration_matrix_kmeans.csv", index_col=0)

    COL = ["#1f4e79", "#2e75b6", "#5b9bd5", "#ed7d31", "#70ad47", "#7030a0"]

    # --- KPI cards
    tot_pat = int(prof.n_patients.sum())
    tot_rev = prof.revenue.sum()
    cards = [
        (f"{tot_pat:,}", "Patients in panel"),
        (f"{eda['opd_ipd']['opd_visits']:,}", "OPD visits"),
        (f"{eda['opd_ipd']['ipd_admissions']:,}", "IPD admissions"),
        (f"₹{tot_rev/1e7:,.2f} Cr", "Billing value"),
        (f"{eda['los']['mean']:.2f} d", "ALOS"),
        (f"{eda['frequency']['single_visit_pct']:.0f}%", "Single-visit patients"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="kv">{v}</div><div class="kl">{l}</div></div>'
        for v, l in cards)

    # --- segment donut (SVG arcs)
    def donut(series, colors, size=230, thick=54):
        total = float(sum(series.values()))
        cx = cy = size / 2
        r = (size - thick) / 2
        import math
        out = [f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">']
        a0 = -math.pi / 2
        for (lab, val), col in zip(series.items(), colors):
            frac = val / total
            a1 = a0 + frac * 2 * math.pi
            large = 1 if frac > 0.5 else 0
            x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            out.append(
                f'<path d="M {x0:.2f} {y0:.2f} A {r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}" '
                f'stroke="{col}" stroke-width="{thick}" fill="none" stroke-linecap="butt"/>')
            a0 = a1
        out.append('</svg>')
        return "".join(out)

    seg_series = dict(zip(prof.segment_name, prof.revenue.astype(float)))
    donut_svg = donut(seg_series, COL)
    legend = "".join(
        f'<div class="lg"><span class="dot" style="background:{c}"></span>'
        f'<b>{n}</b> — {s:.1f}% of patients · ₹{v/1e7:.2f} Cr ({rs:.1f}% of value)</div>'
        for (n, s, v, rs), c in zip(
            prof[["segment_name", "share_pct", "revenue", "revenue_share_pct"]].itertuples(index=False),
            COL))

    # --- bars helper
    def hbars(pairs, color=COL[1], w=560, maxv=None):
        maxv = maxv or max(v for _, v in pairs)
        rows = []
        for i, (lab, v) in enumerate(pairs):
            bw = max(2, v / maxv * (w - 190))
            rows.append(
                f'<div class="brow"><div class="blab">{lab}</div>'
                f'<svg width="{w}" height="24"><rect x="150" y="4" width="{bw:.1f}" height="16" '
                f'rx="3" fill="{color if i % 2 == 0 else COL[2]}"/>'
                f'<text x="{156+bw:.1f}" y="17" font-size="11" fill="#333">{v:,.1f}</text></svg></div>')
        return "".join(rows)

    seg_bars = hbars([(r.segment_name, r.revenue / 1e7) for r in prof.itertuples()], COL[0])

    # --- segment KPI table
    prof_tbl = "".join(
        "<tr>"
        f"<td style='text-align:left'><b>{r.segment_name}</b></td>"
        f"<td>{r.n_patients:,.0f}</td><td>{r.share_pct:.1f}%</td><td>{r.revenue_share_pct:.1f}%</td>"
        f"<td>{r.avg_recency:,.0f}</td><td>{r.avg_frequency:.2f}</td>"
        f"<td>₹{r.avg_monetary:,.0f}</td><td>₹{r.avg_billing_per_visit:,.0f}</td>"
        f"<td>{r.avg_los:.2f}</td><td>{r.avg_adm_rate:.2f}</td><td>{r.avg_lab_per_visit:.2f}</td>"
        f"<td>{r.readmit_30d_rate*100:.2f}%</td></tr>"
        for r in prof.itertuples())

    # --- recommendations table
    rec_tbl = "".join(
        "<tr>"
        f"<td style='text-align:left'><b>{r.segment}</b></td>"
        f"<td style='text-align:left'>{r.intervention.split(':')[0]}</td>"
        f"<td>₹{r.cost_total/1e5:,.1f}L</td><td>₹{r.benefit_value/1e5:,.0f}L</td>"
        f"<td>{r.roi_pct:,.0f}%</td><td>{r.payback_months:.1f}</td></tr>"
        for r in rec.itertuples())

    # --- migration matrix
    mig_tbl = "<tr><th>Period 1 \\ Period 2</th>" + "".join(
        f"<th>{c}</th>" for c in mig.columns) + "</tr>"
    for idx, row in mig.iterrows():
        tot = row.sum()
        mig_tbl += f"<tr><th style='text-align:left'>{idx}</th>"
        for c in mig.columns:
            v = row[c]
            pct = 100 * v / tot if tot else 0
            alpha = 0.10 + 0.75 * (pct / 100)
            mig_tbl += (f"<td style='background:rgba(31,78,121,{alpha:.2f});"
                        f"color:{'#fff' if pct>50 else '#111'}'>{v:,}<br><small>{pct:.0f}%</small></td>")
        mig_tbl += "</tr>"

    diff_tbl = "".join(
        f"<tr><td style='text-align:left'>{r.kpi}</td><td>{r.min_segment_value:,.2f}</td>"
        f"<td>{r.max_segment_value:,.2f}</td><td>{r.relative_spread:.2f}</td>"
        f"<td style='color:{'#70ad47' if r.relative_spread>=0.3 else '#c00'}'>"
        f"{'material' if r.relative_spread>=0.3 else 'not material'}</td></tr>"
        for r in diff.itertuples())

    imgs = {
        "monthly": b64(FIG / "03_monthly_trend.png"),
        "season": b64(FIG / "17_seasonality.png"),
        "mig": b64(FIG / "22_segment_migration.png"),
        "k": b64(FIG / "18_kmeans_model_selection.png"),
        "cb": b64(FIG / "24_cost_benefit.png"),
        "pca": b64(FIG / "19_pca_clusters.png"),
    }

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hospital Segmentation Dashboard — Prototype</title>
<style>
:root{{--navy:#1f4e79;--blue:#2e75b6;--lb:#dce6f1;--orange:#ed7d31;--grey:#595959;--bg:#f4f6f9}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
background:var(--bg);color:#222;font-size:14px}}
header{{background:linear-gradient(135deg,#1f4e79,#2e75b6);color:#fff;padding:26px 34px 22px}}
header h1{{margin:0 0 6px;font-size:26px;font-weight:650;letter-spacing:-.3px}}
header p{{margin:0;opacity:.9;font-size:13.5px}}
.warn{{background:#742a2a;color:#ffe0e0;font-size:12px;padding:9px 34px;letter-spacing:.1px}}
nav{{display:flex;gap:2px;background:#fff;border-bottom:1px solid #dfe4ea;padding:0 26px;
position:sticky;top:0;z-index:20;overflow-x:auto}}
nav button{{border:0;background:none;padding:14px 18px;font-size:13.5px;color:var(--grey);
cursor:pointer;border-bottom:3px solid transparent;white-space:nowrap;font-weight:500}}
nav button.on{{color:var(--navy);border-bottom-color:var(--orange);font-weight:650}}
main{{padding:22px 26px 60px;max-width:1500px;margin:0 auto}}
section{{display:none}} section.on{{display:block}}
h2{{font-size:19px;color:var(--navy);margin:0 0 4px;font-weight:650}}
.sub{{color:var(--grey);font-size:12.5px;margin:0 0 18px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:13px;margin-bottom:22px}}
.kpi{{background:#fff;border-radius:9px;padding:16px 18px;border-left:4px solid var(--blue);
box-shadow:0 1px 4px rgba(16,32,64,.07)}}
.kv{{font-size:25px;font-weight:700;color:var(--navy);line-height:1.1}}
.kl{{font-size:11.5px;color:var(--grey);margin-top:5px;text-transform:uppercase;letter-spacing:.4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px;margin-bottom:18px}}
.card{{background:#fff;border-radius:9px;padding:18px 20px;box-shadow:0 1px 4px rgba(16,32,64,.07)}}
.card h3{{margin:0 0 12px;font-size:14px;color:var(--navy);font-weight:650}}
table{{width:100%;border-collapse:collapse;font-size:12.3px}}
th{{background:var(--navy);color:#fff;padding:8px 9px;text-align:center;font-weight:600;font-size:11.5px}}
td{{padding:7px 9px;text-align:center;border-bottom:1px solid #e8ecf1}}
tbody tr:hover td{{background:#eef4fa}}
.brow{{display:flex;align-items:center;gap:0;margin-bottom:2px}}
.blab{{width:150px;font-size:12px;color:#333;flex-shrink:0}}
.dot{{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:8px;vertical-align:-1px}}
.lg{{font-size:12.5px;margin:6px 0;color:#333}}
.flexrow{{display:flex;gap:26px;align-items:center;flex-wrap:wrap}}
img{{max-width:100%;border-radius:6px;display:block}}
.note{{font-size:11.5px;color:var(--grey);margin-top:10px;font-style:italic}}
.pill{{display:inline-block;padding:3px 10px;border-radius:11px;font-size:11px;
background:var(--lb);color:var(--navy);font-weight:600;margin-right:6px}}
footer{{text-align:center;color:var(--grey);font-size:11.5px;padding:24px}}
</style></head><body>
<header>
  <h1>Hospital Patient Segmentation — Interactive Dashboard</h1>
  <p>Hyderabad Community Hospital Network · 4 sites · 36 months · {tot_pat:,} patients</p>
</header>
<div class="warn">⚠ ALL DATA IS SYNTHETIC — generated for methodological demonstration. Not real hospital evidence.</div>
<nav>
  <button class="on" onclick="go(this,'overview')">Hospital Overview</button>
  <button onclick="go(this,'segment')">Segmentation</button>
  <button onclick="go(this,'revenue')">Revenue &amp; Utilisation</button>
  <button onclick="go(this,'compare')">Segment Comparison</button>
  <button onclick="go(this,'readmit')">Readmission &amp; LOS</button>
  <button onclick="go(this,'migration')">Migration</button>
  <button onclick="go(this,'actions')">Actions &amp; ROI</button>
</nav>
<main>

<section id="overview" class="on">
  <h2>Hospital Overview</h2>
  <p class="sub">Network-level volume, value and operational KPIs across the full observation window.</p>
  <div class="kpis">{kpi_html}</div>
  <div class="grid">
    <div class="card"><h3>Monthly OPD volume and trend</h3>
      <img src="data:image/png;base64,{imgs['monthly']}" alt="Monthly OPD trend"></div>
    <div class="card"><h3>Seasonal index of demand (100 = average month)</h3>
      <img src="data:image/png;base64,{imgs['season']}" alt="Seasonality"></div>
  </div>
  <div class="card"><h3>Volume and value structure</h3>
  <p style="margin:0 0 10px;font-size:13px">
    Inpatient admissions are <b>{eda['opd_ipd']['ipd_share_events']:.1f}%</b> of encounters but
    <b>{eda['opd_ipd']['ipd_revenue_share']:.1f}%</b> of billing value. Patients aged 45+ are
    <b>{eda['age_45plus']['patient_share']:.1f}%</b> of the panel and
    <b>{eda['age_45plus']['revenue_share']:.1f}%</b> of value.</p>
    <div class="flexrow">
      <div>{hbars([('OPD visits', eda['opd_ipd']['opd_visits']),
                   ('IPD admissions', eda['opd_ipd']['ipd_admissions'])], COL[1])}</div>
      <div>{hbars([('OPD revenue (₹Cr)', eda['opd_ipd']['opd_revenue']/1e7),
                   ('IPD revenue (₹Cr)', eda['opd_ipd']['ipd_revenue']/1e7)], COL[3])}</div>
    </div>
  </div>
</section>

<section id="segment">
  <h2>Patient Segmentation Overview</h2>
  <p class="sub">K-means (k={kmeans['k']}) on 8 behavioural features · silhouette {kmeans['silhouette']:.3f} ·
  bootstrap ARI {kmeans['bootstrap']['ari_mean']:.3f}</p>
  <div class="grid">
    <div class="card"><h3>Segment share of patient base</h3>
      <div class="flexrow" style="justify-content:center">{donut_svg}</div></div>
    <div class="card"><h3>Revenue by segment (₹ crore)</h3>{seg_bars}</div>
  </div>
  <div class="card"><h3>Segment legend</h3>{legend}</div>
  <div class="grid">
    <div class="card"><h3>K-means model selection</h3>
      <img src="data:image/png;base64,{imgs['k']}" alt="k selection"></div>
    <div class="card"><h3>Clusters in PCA space</h3>
      <img src="data:image/png;base64,{imgs['pca']}" alt="PCA"></div>
  </div>
</section>

<section id="revenue">
  <h2>Revenue and Utilisation</h2>
  <p class="sub">Billing is corrected for duplicate GST and invalid amounts; every figure below is post-cleaning.</p>
  <div class="grid">
    <div class="card"><h3>Billing value by segment (₹ crore)</h3>{seg_bars}</div>
    <div class="card"><h3>Demand rate and diagnostics intensity</h3>
      {hbars([(r.segment_name, r.avg_frequency) for r in prof.itertuples()], COL[0])}
      <div class="note">Average OPD visits per patient over 36 months.</div>
      {hbars([(r.segment_name, r.avg_lab_per_visit) for r in prof.itertuples()], COL[4])}
      <div class="note">Laboratory tests per OPD visit.</div>
    </div>
  </div>
  <div class="card"><h3>Bed-day consumption per 100 patients</h3>
    {hbars([(r.segment_name, r.bed_days_per_100) for r in prof.itertuples()], COL[3])}
  </div>
</section>

<section id="compare">
  <h2>Segment Comparison</h2>
  <p class="sub">Every figure is observed, not modelled. All segments exceed the 5% viability floor.</p>
  <div class="card" style="overflow-x:auto">
    <table><thead><tr>
      <th style="text-align:left">Segment</th><th>Patients</th><th>% base</th><th>% revenue</th>
      <th>Recency (d)</th><th>Visits</th><th>Billing/patient</th><th>Billing/visit</th>
      <th>ALOS (d)</th><th>Adm. rate</th><th>Labs/visit</th><th>30-d readmit</th>
    </tr></thead><tbody>{prof_tbl}</tbody></table>
  </div>
  <div class="card" style="margin-top:16px">
    <h3>Verified KPI separation</h3>
    <table><thead><tr><th style="text-align:left">KPI</th><th>Lowest</th><th>Highest</th>
      <th>Relative spread</th><th>Verdict</th></tr></thead><tbody>{diff_tbl}</tbody></table>
    <div class="note">Relative spread = (max − min) ÷ mean. 0.30 is the materiality floor.
    Length of stay is reported as NOT separating — ALOS must be managed by department, not segment.</div>
  </div>
</section>

<section id="readmit">
  <h2>Readmission and Length of Stay</h2>
  <p class="sub">30-day readmissions observed inside the window; ALOS measured per admission.</p>
  <div class="kpis">
    <div class="kpi"><div class="kv">{eda['los']['mean']:.2f} d</div><div class="kl">Network ALOS</div></div>
    <div class="kpi"><div class="kv">{eda['los']['p90']:.0f} d</div><div class="kl">LOS P90</div></div>
    <div class="kpi"><div class="kv">{prof.readmit_30d_rate.max()*100:.1f}%</div><div class="kl">Highest segment readmission</div></div>
    <div class="kpi"><div class="kv">{int(prof.readmit_30d_rate.mul(prof.n_patients).sum()):,}</div><div class="kl">Readmission patients</div></div>
  </div>
  <div class="grid">
    <div class="card"><h3>30-day readmission rate by segment</h3>
      {hbars([(r.segment_name, r.readmit_30d_rate*100) for r in prof.itertuples()], COL[3])}
      <div class="note">Risk is concentrated: the high-acuity segment carries almost all readmissions.</div></div>
    <div class="card"><h3>Average length of stay by segment</h3>
      {hbars([(r.segment_name, r.avg_los) for r in prof.itertuples()], COL[1])}
      <div class="note">LOS does NOT separate segments materially — see the comparison page.</div></div>
  </div>
</section>

<section id="migration">
  <h2>Segment Migration (two independent 18-month periods)</h2>
  <p class="sub">Period 2 clusters matched to period 1 by profile using the Hungarian algorithm ·
  ARI {stab['ari_kmeans']:.3f} (K-means) vs {stab['ari_rfm']:.3f} (RFM)</p>
  <div class="card" style="overflow-x:auto">
    <table><tbody>{mig_tbl}</tbody></table>
    <div class="note">Cell = patients; shade = row percentage. Diagonal = retention.</div>
  </div>
  <div class="card" style="margin-top:16px">
    <h3>Migration and retention</h3>
    <img src="data:image/png;base64,{imgs['mig']}" alt="migration">
  </div>
</section>

<section id="actions">
  <h2>Recommended Actions and Cost-Benefit</h2>
  <p class="sub">One programme per segment plus one network-wide · observed inputs, disclosed assumptions</p>
  <div class="card" style="overflow-x:auto">
    <table><thead><tr><th style="text-align:left">Segment</th><th style="text-align:left">Programme</th>
      <th>Cost yr 1</th><th>Benefit</th><th>ROI</th><th>Payback (mo)</th></tr></thead>
      <tbody>{rec_tbl}</tbody></table>
    <div class="note">Total cost ₹{rec.cost_total.sum()/1e5:,.1f} lakh ·
    benefit ₹{rec.benefit_value.sum()/1e5:,.0f} lakh ·
    portfolio ROI {100*(rec.benefit_value.sum()-rec.cost_total.sum())/rec.cost_total.sum():,.0f}%</div>
  </div>
  <div class="card" style="margin-top:16px"><h3>Cost, benefit and sensitivity</h3>
    <img src="data:image/png;base64,{imgs['cb']}" alt="cost benefit"></div>
</section>

</main>
<footer>
  <span class="pill">SYNTHETIC DATA</span> Reproduce with
  <code>python src/build_dashboard_doc.py</code> · Built on the same outputs as the notebook, workbook, report and deck.
</footer>
<script>
function go(btn, id){{
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('section').forEach(s=>s.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  window.scrollTo({{top:0,behavior:'smooth'}});
}}
</script>
</body></html>"""
    p = DASH / "dashboard_prototype.html"
    p.write_text(html)
    print(f"prototype written: {p} ({p.stat().st_size/1e6:.2f} MB)")
    return p


if __name__ == "__main__":
    build_star_schema()
    write_spec()
    build_html()
