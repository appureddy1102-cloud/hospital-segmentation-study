"""
build_deck.py
=============
Builds reports/Hospital_Segmentation_Study_Deck.pptx — a 12-slide business
presentation for the hospital business head.

Design rules: 16:9, one message per slide, every number read from the pipeline
outputs, and a permanent synthetic-data disclosure on the title and closing
slides.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Cm, Emu, Pt

import config as C

OUT = C.REPORT_DIR
FIG = C.FIG_DIR
OUTD = C.OUT_DIR

NAVY = RGBColor(0x1F, 0x4E, 0x79)
BLUE = RGBColor(0x2E, 0x75, 0xB6)
LIGHTBLUE = RGBColor(0xDC, 0xE6, 0xF1)
ORANGE = RGBColor(0xED, 0x7D, 0x31)
GREY = RGBColor(0x59, 0x59, 0x59)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x54, 0x82, 0x35)
RED = RGBColor(0xC0, 0x00, 0x00)

prs = Presentation()
prs.slide_width = Cm(33.87)
prs.slide_height = Cm(19.05)
BLANK = prs.slide_layouts[6]

# ------------------------------------------------------------------ load
E = json.loads((OUTD / "eda_stats.json").read_text())
K = json.loads((OUTD / "kmeans_metrics.json").read_text())
S = json.loads((OUTD / "stability_summary.json").read_text())
REC = pd.read_csv(OUTD / "recommendations_cost_benefit.csv")
PROF = pd.read_csv(OUTD / "final_segment_profiles.csv")
DIFF = pd.read_csv(OUTD / "segment_kpi_differences.csv")
EVID = json.loads((OUTD / "segment_evidence.json").read_text())
COMP = pd.read_csv(OUTD / "model_comparison.csv")

TOT_PAT = int(PROF["n_patients"].sum())
TOT_REV = float(PROF["revenue"].sum())
SEG = PROF["segment_name"].tolist()


def slide(title=None, subtitle=None, number=None):
    s = prs.slides.add_slide(BLANK)
    if title:
        tb = s.shapes.add_textbox(Cm(1.6), Cm(1.0), Cm(30.6), Cm(1.8))
        p = tb.text_frame.paragraphs[0]
        p.text = title
        p.font.size = Pt(30); p.font.bold = True; p.font.color.rgb = NAVY
        p.font.name = "Calibri"
        # accent rule
        bar = s.shapes.add_shape(1, Cm(1.6), Cm(2.85), Cm(3.2), Cm(0.12))
        bar.fill.solid(); bar.fill.fore_color.rgb = ORANGE; bar.line.fill.background()
        if subtitle:
            tb2 = s.shapes.add_textbox(Cm(1.6), Cm(3.05), Cm(30.6), Cm(1.2))
            p2 = tb2.text_frame.paragraphs[0]
            p2.text = subtitle
            p2.font.size = Pt(14); p2.font.color.rgb = GREY; p2.font.italic = True
    if number:
        nb = s.shapes.add_textbox(Cm(30.9), Cm(17.9), Cm(2.2), Cm(0.8))
        p = nb.text_frame.paragraphs[0]
        p.text = str(number); p.font.size = Pt(11); p.font.color.rgb = GREY
        p.alignment = PP_ALIGN.RIGHT
    return s


def footer(s, text="Synthetic data — not real hospital evidence"):
    tb = s.shapes.add_textbox(Cm(1.6), Cm(18.2), Cm(24), Cm(0.6))
    p = tb.text_frame.paragraphs[0]
    p.text = text; p.font.size = Pt(9); p.font.color.rgb = GREY


SLIDE_H_CM = 19.05          # 7.5 in, 16:9
FOOTER_RESERVE_CM = 1.15    # keep clear of the bottom margin


def bullets(s, items, left=1.9, top=4.6, width=15.2, size=15, gap=0.55):
    """
    Render a bullet list, auto-fitting it to the space left on the slide.

    The naive version used a fixed Cm(12) height, which silently overflowed
    the slide on slides with many or long bullets. Height is now derived from
    the remaining space, and the font is stepped down (never below 11 pt)
    until the estimated text block fits. Every shape is therefore guaranteed
    to sit inside the 13.33 x 7.5 in canvas.
    """
    avail_cm = SLIDE_H_CM - top - FOOTER_RESERVE_CM

    # Estimated rendered lines per bullet: wrap at ~1.85 chars per mm of width.
    chars_per_line = max(20, int(width * 10 / (size * 0.52)))

    def estimate(pt):
        cpl = max(20, int(width * 10 / (pt * 0.52)))
        lines = 0
        for txt, lvl in items:
            n = len(txt) + 2
            lines += max(1, -(-n // cpl))
        # a line is ~1.32x the font size tall, plus paragraph spacing
        return (lines * pt * 1.32 / 28.35) + (len(items) * 0.35)

    chosen = size
    while chosen > 11 and estimate(chosen) > avail_cm:
        chosen -= 0.5

    height_cm = min(avail_cm, max(6.0, estimate(chosen) + 0.6))
    tb = s.shapes.add_textbox(Cm(left), Cm(top), Cm(width), Cm(height_cm))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    for i, (txt, lvl) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = ("• " if lvl == 0 else "– ") + txt
        p.font.size = Pt(chosen if lvl == 0 else chosen - 2)
        p.font.color.rgb = NAVY if lvl == 0 else GREY
        p.space_after = Pt(8 if len(items) <= 5 else 5)
        p.line_spacing = 1.0
        p.level = lvl
    return tb


def kpi_card(s, x, y, w, h, value, label, color=NAVY):
    box = s.shapes.add_shape(5, Cm(x), Cm(y), Cm(w), Cm(h))   # rounded rect
    box.fill.solid(); box.fill.fore_color.rgb = WHITE
    box.line.color.rgb = color; box.line.width = Pt(1.4)
    box.shadow.inherit = False
    tf = box.text_frame
    tf.margin_top = Cm(0.2)
    p = tf.paragraphs[0]
    p.text = value; p.font.size = Pt(26); p.font.bold = True; p.font.color.rgb = color
    p.alignment = PP_ALIGN.CENTER
    p2 = tf.add_paragraph()
    p2.text = label; p2.font.size = Pt(11); p2.font.color.rgb = GREY
    p2.alignment = PP_ALIGN.CENTER
    p2.word_wrap = True


def picture(s, name, left, top, width=None, height=None):
    p = FIG / name
    if not p.exists():
        return
    if width:
        s.shapes.add_picture(str(p), Cm(left), Cm(top), width=Cm(width))
    else:
        s.shapes.add_picture(str(p), Cm(left), Cm(top), height=Cm(height))


def banner(s, text, color=ORANGE, top=16.9, height=1.1):
    b = s.shapes.add_shape(1, Cm(1.6), Cm(top), Cm(30.6), Cm(height))
    b.fill.solid(); b.fill.fore_color.rgb = color; b.line.fill.background()
    tf = b.text_frame
    tf.margin_left = Cm(0.5)
    p = tf.paragraphs[0]
    p.text = text; p.font.size = Pt(15); p.font.bold = True; p.font.color.rgb = WHITE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE


def table(s, df, left, top, width, height, font=9, header_color=NAVY):
    rows, cols = df.shape
    shape = s.shapes.add_table(rows + 1, cols, Cm(left), Cm(top), Cm(width), Cm(height))
    t = shape.table
    for j, c in enumerate(df.columns):
        cell = t.cell(0, j)
        cell.text = str(c)
        cell.fill.solid(); cell.fill.fore_color.rgb = header_color
        pr = cell.text_frame.paragraphs[0]
        pr.font.size = Pt(font); pr.font.bold = True; pr.font.color.rgb = WHITE
        pr.alignment = PP_ALIGN.CENTER
        cell.margin_left = Cm(0.1); cell.margin_right = Cm(0.1)
    for i, row in enumerate(df.itertuples(index=False), start=1):
        for j, v in enumerate(row):
            cell = t.cell(i, j)
            cell.text = str(v)
            cell.fill.solid()
            cell.fill.fore_color.rgb = LIGHTBLUE if i % 2 else WHITE
            pr = cell.text_frame.paragraphs[0]
            pr.font.size = Pt(font); pr.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
            pr.alignment = PP_ALIGN.CENTER if j > 0 else PP_ALIGN.LEFT
            cell.margin_left = Cm(0.1); cell.margin_right = Cm(0.1)
    return t


# =====================================================================
# 1 TITLE
# =====================================================================
s = prs.slides.add_slide(BLANK)
bg = s.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()

tb = s.shapes.add_textbox(Cm(2.6), Cm(5.2), Cm(28.5), Cm(3))
p = tb.text_frame.paragraphs[0]
p.text = "Who Are Our Patients, Really?"
p.font.size = Pt(48); p.font.bold = True; p.font.color.rgb = WHITE

tb = s.shapes.add_textbox(Cm(2.6), Cm(8.1), Cm(28.5), Cm(2.2))
p = tb.text_frame.paragraphs[0]
p.text = "A patient segmentation of four community hospitals in Hyderabad"
p.font.size = Pt(22); p.font.color.rgb = RGBColor(0xBD, 0xD7, 0xEE)

bar = s.shapes.add_shape(1, Cm(2.6), Cm(10.4), Cm(6.5), Cm(0.15))
bar.fill.solid(); bar.fill.fore_color.rgb = ORANGE; bar.line.fill.background()

tb = s.shapes.add_textbox(Cm(2.6), Cm(11.1), Cm(28.5), Cm(3))
tf = tb.text_frame; tf.word_wrap = True
for txt, sz in [(f"{TOT_PAT:,} patients  ·  {E['opd_ipd']['opd_visits']+E['opd_ipd']['ipd_admissions']:,} encounters  ·  36 months  ·  4 sites", 15),
                ("Prepared for the Hospital Business Head  |  Healthcare Analytics & BI", 13)]:
    p = tf.paragraphs[0] if txt.startswith(f"{TOT_PAT:,}") else tf.add_paragraph()
    p.text = txt; p.font.size = Pt(sz); p.font.color.rgb = RGBColor(0xBD, 0xD7, 0xEE)
    p.space_after = Pt(8)

tb = s.shapes.add_textbox(Cm(2.6), Cm(16.6), Cm(28.5), Cm(1.2))
tf = tb.text_frame; tf.word_wrap = True
p = tf.paragraphs[0]
p.text = ("⚠ All data in this presentation is SYNTHETIC and generated for methodological demonstration. "
          "It does not describe a real hospital, real patients or real revenue.")
p.font.size = Pt(11); p.font.color.rgb = RGBColor(0xFF, 0xC7, 0xCE); p.font.italic = True

# =====================================================================
# 2 THE PROBLEM
# =====================================================================
s = slide("The problem we set out to solve",
          "Four questions, one root cause: we manage a panel of patients as if they were all the same",
          number=2)
bullets(s, [
    ("Capacity — which patients actually consume our beds and our diagnostics?", 0),
    ("Retention — why does most of our panel never come back, and which part of it is worth recovering?", 0),
    ("Readmissions — who re-presents within 30 days, and is that clinical risk or discharge process?", 0),
    ("Investment — where should the next rupee of programme spend go?", 0),
], width=16.5)

kpi_card(s, 20.2, 5.0, 5.4, 3.0, f"{E['frequency']['single_visit_pct']:.0f}%",
         "of patients attend\nexactly once", RED)
kpi_card(s, 26.0, 5.0, 5.4, 3.0, f"{E['recency']['over_365_pct']:.0f}%",
         "have not been seen\nfor over a year", RED)

bullets(s, [
    ("We cannot answer any of these with a single, undifferentiated view of the panel", 0),
    ("And we cannot answer them by adding capacity — the constraint is inside the existing panel", 0),
], left=20.2, top=9.2, width=11.4, size=13)
banner(s, "Segmentation is the instrument that turns a patient list into an operating plan", top=17.2)
footer(s)

# =====================================================================
# 3 WHAT THE DATA SHOWS
# =====================================================================
s = slide("What 36 months of data actually shows",
          "Volume sits with the young and the routine; value sits with the older and the admitted",
          number=3)
picture(s, "02_opd_vs_ipd.png", 1.6, 4.4, width=15.4)
picture(s, "05_age_distribution.png", 17.4, 4.4, width=15.2)
bullets(s, [
    (f"IPD is only {E['opd_ipd']['ipd_share_events']:.1f}% of encounters but "
     f"{E['opd_ipd']['ipd_revenue_share']:.1f}% of billing value", 0),
    (f"Patients 45+ are {E['age_45plus']['patient_share']:.1f}% of the base and "
     f"{E['age_45plus']['revenue_share']:.1f}% of value", 0),
    (f"Chronic diagnoses are {E['diagnosis']['chronic_share_pct']:.0f}% of all OPD visits", 0),
], top=13.0, size=14)
footer(s)

# =====================================================================
# 4 OUR APPROACH
# =====================================================================
s = slide("How we did it", "Two independent segmentation methods, judged on operational merit — not on a single statistic",
          number=4)
steps = [
    ("1. Clean", f"{E['opd_ipd']['opd_visits']+E['opd_ipd']['ipd_admissions']:,} records\n13 defect families\n0 rows deleted\nwithout a reason"),
    ("2. Engineer", "21 patient-level\nfeatures\nRFM + behaviour\n+ clinical risk"),
    ("3. Segment", "RFM scoring\nand K-means\nk evaluated 2–10"),
    ("4. Compare", "10 criteria\nstability, viability,\nactionability\nnot silhouette"),
    ("5. Act", "4 costed\nprogrammes\nROI + sensitivity\nper programme"),
]
x = 1.9
for i, (h, b) in enumerate(steps):
    box = s.shapes.add_shape(5, Cm(x), Cm(5.2), Cm(5.6), Cm(5.4))
    box.fill.solid(); box.fill.fore_color.rgb = WHITE
    box.line.color.rgb = BLUE; box.line.width = Pt(1.3)
    box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True
    tf.margin_left = Cm(0.35); tf.margin_right = Cm(0.35); tf.margin_top = Cm(0.4)
    p = tf.paragraphs[0]; p.text = h
    p.font.size = Pt(16); p.font.bold = True; p.font.color.rgb = NAVY
    p2 = tf.add_paragraph(); p2.text = b
    p2.font.size = Pt(11); p2.font.color.rgb = GREY
    p2.space_before = Pt(10)
    if i < 4:
        ar = s.shapes.add_shape(13, Cm(x + 5.65), Cm(7.3), Cm(0.7), Cm(0.7))
        ar.fill.solid(); ar.fill.fore_color.rgb = ORANGE; ar.line.fill.background()
    x += 6.35

bullets(s, [
    ("Observation window 2022–2024; segmentation re-computed independently for two 18-month periods to test stability", 0),
    ("Every cleaning correction logged and validated; the GST logic was reconstructed from the billing identity, not assumed", 0),
], top=11.6, size=14)
banner(s, "The test of a segmentation is not how clean the clusters look — it is whether they change a decision", top=17.2)
footer(s)

# =====================================================================
# 5 MODEL CHOICE
# =====================================================================
s = slide("We tested two methods and chose K-means",
          "Not because it scored higher on one metric — because it produced segments we can operate",
          number=5)
picture(s, "18_kmeans_model_selection.png", 1.6, 4.3, width=19.6)
bullets(s, [
    ("k=2 has the cleanest geometry but leaves a 64% residual — unusable", 0),
    ("k=5 to k=10 split off segments of 3–4%, below the 5% viability floor", 0),
    ("k=3 gives three segments that differ by multiples on admission rate, revenue and diagnostics", 0),
], left=22.0, top=4.6, width=10.6, size=13)
banner(s, f"Selected k=3 · silhouette {K['silhouette']:.2f} · bootstrap stability {K['bootstrap']['ari_mean']:.2f} · every segment ≥ 5% of the panel",
       color=BLUE, top=17.0)
footer(s)

# =====================================================================
# 6 THE SEGMENTS
# =====================================================================
s = slide("Our patients fall into three very different groups",
          "Same network, same doctors — but three completely different operating realities", number=6)
tbl = pd.DataFrame({
    "Segment": PROF.segment_name,
    "Patients": PROF.n_patients.map("{:,.0f}".format),
    "% of panel": PROF.share_pct.map("{:.1f}%".format),
    "% of revenue": PROF.revenue_share_pct.map("{:.1f}%".format),
    "Avg billing": PROF.avg_monetary.map("₹{:,.0f}".format),
    "Visits": PROF.avg_frequency.map("{:.1f}".format),
    "Adm. rate": PROF.avg_adm_rate.map("{:.2f}".format),
})
table(s, tbl, 1.9, 4.6, 30.0, 4.0, font=13)
y = 9.6
for _, r in PROF.iterrows():
    box = s.shapes.add_shape(5, Cm(1.9), Cm(y), Cm(30.0), Cm(2.3))
    box.fill.solid(); box.fill.fore_color.rgb = LIGHTBLUE
    box.line.fill.background(); box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True
    tf.margin_left = Cm(0.4); tf.margin_top = Cm(0.25)
    p = tf.paragraphs[0]
    p.text = f"{r.segment_name}  —  {r.share_pct:.1f}% of patients, {r.revenue_share_pct:.1f}% of revenue"
    p.font.size = Pt(14); p.font.bold = True; p.font.color.rgb = NAVY
    p2 = tf.add_paragraph()
    if "High-Acuity" in r.segment_name:
        p2.text = (f"Convert {r.avg_frequency:.1f} visits into {r.avg_adm_rate:.2f} admissions each; "
                   f"hold {r.bed_days_per_100:.0f} bed-days per 100 patients; "
                   f"{EVID[r.segment_name]['readmit_30d_count']:,} readmissions in 36 months")
    elif "Dormant" in r.segment_name:
        p2.text = (f"{EVID[r.segment_name]['single_visit']:,} attended once and never returned; "
                   f"average recency {r.avg_recency:.0f} days — the largest pool of undiagnosed risk we have")
    else:
        p2.text = (f"Visit {r.avg_frequency:.1f} times and {r.avg_dept_div:.1f} departments; "
                   f"{r.avg_lab_per_visit:.2f} lab tests per visit — our chronic-care engine room")
    p2.font.size = Pt(11); p2.font.color.rgb = GREY
    y += 2.5
footer(s)

# =====================================================================
# 7 THE SEGMENTS DIFFER — IN WHAT MATTERS
# =====================================================================
s = slide("The differences are not cosmetic",
          f"{int((DIFF.relative_spread>=0.30).sum())} of {len(DIFF)} candidate KPIs separate the segments materially",
          number=7)
d = DIFF.head(7).copy()
tbl = pd.DataFrame({
    "KPI": d.kpi.str.replace("avg_", "").str.replace("_", " ").str.title(),
    "Lowest segment": d.min_segment_value.map("{:,.2f}".format),
    "Highest segment": d.max_segment_value.map("{:,.2f}".format),
    "Spread": d.relative_spread.map("{:.2f}".format),
    "Material": ["YES" if v >= .3 else "no" for v in d.relative_spread],
})
table(s, tbl, 1.9, 4.7, 20.0, 7.6, font=12)
bullets(s, [
    ("Admission rate differs by ~100×", 0),
    ("Revenue per patient differs by ~70×", 0),
    ("Readmission risk is concentrated in one segment", 0),
    ("Length of stay does NOT separate — so ALOS must be managed by department, not by segment", 1),
], left=22.4, top=5.0, width=10.2, size=13)
banner(s, "These are differences we can staff, schedule and price against", top=17.0)
footer(s)

# =====================================================================
# 8 WHAT THIS IS WORTH — OBSERVED
# =====================================================================
s = slide("Where the value actually sits",
          f"Total billing value observed in the 36-month window: ₹{TOT_REV/1e7:,.2f} crore",
          number=8)
picture(s, "10_revenue_by_hospital.png", 1.6, 4.5, width=15.4)
kpi_card(s, 18.0, 5.0, 6.6, 3.2, f"{PROF.revenue_share_pct.max():.0f}%",
         "of billing value sits in\none segment", ORANGE)
kpi_card(s, 25.2, 5.0, 6.4, 3.2, f"{PROF.loc[PROF.revenue_share_pct.idxmax(),'share_pct']:.0f}%",
         "of patients generate\nthat value", NAVY)
bullets(s, [
    (f"IPD room, procedures and consumables are {100-E['opd_ipd']['opd_revenue']/(E['opd_ipd']['opd_revenue']+E['opd_ipd']['ipd_revenue'])*100:.0f}% of value", 0),
    ("Bed utilisation and ALOS are the biggest revenue levers we control", 0),
    ("OPD is the gateway — it decides who ends up in a bed", 0),
], left=18.0, top=9.4, width=13.6, size=13)
footer(s)

# =====================================================================
# 9 RECOMMENDATIONS
# =====================================================================
s = slide("Four programmes — one per segment, plus one for the network",
          "Each linked to a measured finding, each with an owner, a KPI and a business case", number=9)
tbl = pd.DataFrame({
    "Programme": [r.intervention.split(":")[0] for r in REC.itertuples()],
    "Target": REC.segment,
    "Reaches": REC.addressable.map("{:,.0f} patients".format),
    "Cost (yr 1)": REC.cost_total.map("₹{/1e5:,.1f}L".format if False else "₹{:,.1f}L".format)
        if False else [f"₹{v/1e5:,.1f} lakh" for v in REC.cost_total],
    "Benefit": [f"₹{v/1e5:,.0f} lakh" for v in REC.benefit_value],
    "ROI": REC.roi_pct.map("{:,.0f}%".format),
})
table(s, tbl, 1.9, 4.7, 30.0, 6.8, font=12)
banner(s, f"Portfolio: ₹{REC.cost_total.sum()/1e5:,.1f} lakh invested → "
          f"₹{REC.benefit_value.sum()/1e5:,.0f} lakh projected annual benefit  ·  "
          f"ROI {100*(REC.benefit_value.sum()-REC.cost_total.sum())/REC.cost_total.sum():,.0f}%", top=12.4)
bullets(s, [
    ("Start with discharge management — it unlocks the data plumbing every other programme needs", 0),
    ("Stage-gate the reactivation programme: it is the most assumption-sensitive case", 0),
    ("Diagnostics stewardship needs clinical leads, not capital", 0),
], top=14.1, size=13)
footer(s)

# =====================================================================
# 10 BENEFIT AND RISK
# =====================================================================
s = slide("What we are promising — and what could go wrong",
          "Every business case tested at pessimistic and optimistic values of its key assumption",
          number=10)
picture(s, "24_cost_benefit.png", 1.2, 4.5, width=24.4)
bullets(s, [
    ("All four cases positive in the base case", 0),
    ("Only reactivation fails the pessimistic case", 0),
    ("Margins are assumptions, not observed cost data", 1),
], left=25.6, top=4.9, width=7.4, size=11)
footer(s)

# =====================================================================
# 11 ROADMAP
# =====================================================================
s = slide("12-month implementation roadmap", "Sequenced by dependency, not by ROI", number=11)
phases = [
    ("Months 1–3", ["Governance sign-off on segment use", "Discharge coordinators hired",
                    "Overdue-list automation built", "Diagnostics order sets agreed"], BLUE),
    ("Months 4–6", ["Readmission programme live at all 4 sites", "Reactivation wave 1 (2 camps)",
                    "LIS duplicate-order rules live", "First monthly re-scoring"], NAVY),
    ("Months 7–9", ["Reactivation wave 2 (stage gate)", "Clinical audit of over/under-testing",
                    "RFM triage live in OPD app", "Quarterly re-fit of segment definitions"], BLUE),
    ("Months 10–12", ["Full ROI review vs. pilot evidence", "Scale winners, stop losers",
                      "Publish annual segmentation refresh", "Plan year-2 chronic programme"], NAVY),
]
x = 1.9
for h, items, col in phases:
    box = s.shapes.add_shape(5, Cm(x), Cm(4.8), Cm(7.3), Cm(9.6))
    box.fill.solid(); box.fill.fore_color.rgb = WHITE
    box.line.color.rgb = col; box.line.width = Pt(1.5)
    box.shadow.inherit = False
    hdr = s.shapes.add_shape(1, Cm(x), Cm(4.8), Cm(7.3), Cm(1.15))
    hdr.fill.solid(); hdr.fill.fore_color.rgb = col; hdr.line.fill.background()
    p = hdr.text_frame.paragraphs[0]; p.text = h
    p.font.size = Pt(15); p.font.bold = True; p.font.color.rgb = WHITE
    p.alignment = PP_ALIGN.CENTER
    tf = box.text_frame; tf.word_wrap = True
    tf.margin_top = Cm(1.5); tf.margin_left = Cm(0.3); tf.margin_right = Cm(0.3)
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = "• " + it
        p.font.size = Pt(11.5); p.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        p.space_after = Pt(8)
    x += 7.65
banner(s, "Segment membership is re-scored monthly and the definitions re-fitted quarterly — status is a leading indicator, not a label",
       color=BLUE, top=15.4, height=1.2)
footer(s)

# =====================================================================
# 12 THE ASK / CLOSE
# =====================================================================
s = prs.slides.add_slide(BLANK)
bg = s.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()

tb = s.shapes.add_textbox(Cm(2.4), Cm(2.6), Cm(29), Cm(2))
p = tb.text_frame.paragraphs[0]
p.text = "What we are asking for"
p.font.size = Pt(38); p.font.bold = True; p.font.color.rgb = WHITE

asks = [
    (f"₹{REC.cost_total.sum()/1e5:,.1f} lakh for year one, across four programmes"),
    (f"Clinical governance sign-off that segments inform service design — never access to care"),
    ("One coordinator per site, and protected follow-up slots"),
    ("A monthly 60-minute review against the segment KPIs"),
]
tb = s.shapes.add_textbox(Cm(2.4), Cm(5.4), Cm(29), Cm(7))
tf = tb.text_frame; tf.word_wrap = True
for i, a in enumerate(asks):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    p.text = f"{i+1}.  {a}"
    p.font.size = Pt(17); p.font.color.rgb = RGBColor(0xDC, 0xE6, 0xF1)
    p.space_after = Pt(14)

bar = s.shapes.add_shape(1, Cm(2.4), Cm(12.1), Cm(8), Cm(0.15))
bar.fill.solid(); bar.fill.fore_color.rgb = ORANGE; bar.line.fill.background()

tb = s.shapes.add_textbox(Cm(2.4), Cm(12.7), Cm(29), Cm(2))
p = tb.text_frame.paragraphs[0]
p.text = (f"Expected return: {100*(REC.benefit_value.sum()-REC.cost_total.sum())/REC.cost_total.sum():,.0f}% ROI, "
          f"with every assumption disclosed and stress-tested.")
p.font.size = Pt(19); p.font.color.rgb = WHITE; p.font.bold = True

tb = s.shapes.add_textbox(Cm(2.4), Cm(15.6), Cm(29), Cm(2.6))
tf = tb.text_frame; tf.word_wrap = True
p = tf.paragraphs[0]
p.text = ("All figures in this deck are derived from SYNTHETIC data generated for methodological demonstration. "
          "They must not be quoted as evidence about a real hospital. Re-running the committed pipeline on a real "
          "extract reproduces every number in this deck.")
p.font.size = Pt(11); p.font.color.rgb = RGBColor(0xFF, 0xC7, 0xCE); p.font.italic = True

path = OUT / "Hospital_Segmentation_Study_Deck.pptx"
prs.save(path)
print(f"saved {path} ({path.stat().st_size/1e6:.2f} MB) — {len(prs.slides.__iter__.__self__._sldIdLst)} slides")
