"""
build_docs_pdf.py
=================
Renders the markdown documentation to a single, submission-ready PDF.

The docs are written in GitHub-flavoured markdown (tables, nested lists, code
fences). This converter handles the subset actually used in these files:
headings, paragraphs, bullets, numbered lists, fenced code, blockquotes and
pipe tables. It is deliberately small rather than general - it targets this
repository's own docs so the output stays faithful.

    python src/build_docs_pdf.py
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = ROOT / "reports" / "Hospital_Segmentation_Study_Docs.pdf"

NAVY = colors.HexColor("#1F4E79")
BLUE = colors.HexColor("#2E75B6")
ORANGE = colors.HexColor("#C55A11")
GREY = colors.HexColor("#595959")
LIGHT = colors.HexColor("#EAF1F8")
RULE = colors.HexColor("#BFCEDE")

# ------------------------------------------------------------------ styles
ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold",
                            fontSize=27, leading=32, textColor=NAVY, spaceAfter=6),
    "subtitle": ParagraphStyle("st", parent=ss["Normal"], fontName="Helvetica",
                               fontSize=12.5, leading=17, textColor=GREY, spaceAfter=4),
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                         fontSize=17, leading=21, textColor=NAVY,
                         spaceBefore=16, spaceAfter=8),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                         fontSize=13, leading=16, textColor=BLUE,
                         spaceBefore=12, spaceAfter=5),
    "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                         fontSize=11, leading=14, textColor=ORANGE,
                         spaceBefore=9, spaceAfter=4),
    "body": ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica",
                           fontSize=9.4, leading=13.4, alignment=TA_JUSTIFY,
                           textColor=colors.HexColor("#1A1A1A"), spaceAfter=5),
    # firstLineIndent is set negative so wrapped lines hang under the text
    # rather than running back to the left margin
    # Hanging indent done the predictable way: the marker lives in the text
    # itself and firstLineIndent pulls only the first line back.
    # The bulletText= mechanism was abandoned because its interaction with
    # leftIndent/bulletIndent drew continuation lines LEFT of the marker.
    "bullet": ParagraphStyle("bu", parent=ss["BodyText"], fontName="Helvetica",
                             fontSize=9.4, leading=13.2, leftIndent=17,
                             firstLineIndent=-9, spaceAfter=3),
    "num": ParagraphStyle("nu", parent=ss["BodyText"], fontName="Helvetica",
                          fontSize=9.4, leading=13.2, leftIndent=17,
                          firstLineIndent=-17, spaceAfter=3),
    "code": ParagraphStyle("c", parent=ss["Code"], fontName="Courier",
                           fontSize=7.9, leading=10.4,
                           textColor=colors.HexColor("#1F3864"),
                           backColor=colors.HexColor("#F4F7FB"),
                           borderPadding=5, spaceBefore=3, spaceAfter=7),
    "quote": ParagraphStyle("q", parent=ss["BodyText"], fontName="Helvetica-Oblique",
                            fontSize=9.2, leading=13, leftIndent=12,
                            textColor=colors.HexColor("#33475B"),
                            borderPadding=(0, 0, 0, 6), spaceAfter=6),
    "th": ParagraphStyle("th", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=7.7, leading=9.6, textColor=colors.white),
    "td": ParagraphStyle("td", parent=ss["Normal"], fontName="Helvetica",
                         fontSize=7.6, leading=9.5),
}


def clean_inline(t: str) -> str:
    """Markdown inline -> reportlab mini-HTML."""
    t = html.escape(t, quote=False)
    # Protect runs of 3+ asterisks (e.g. masked pincodes like 500***) so the
    # emphasis regexes below cannot eat them.
    t = re.sub(r"(\*{3,})", lambda m: "\x00" * len(m.group(1)), t)
    t = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8.3">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", t)   # keep the label
    t = t.replace("—", "\u2014").replace("→", "\u2192").replace("ρ", "\u03c1")
    t = t.replace("₹", "\u20b9").replace("≥", "\u2265").replace("≤", "\u2264")
    t = t.replace("×", "\u00d7").replace("✓", "\u2713").replace("⚠", "\u26a0")
    t = t.replace("✅", "\u2713").replace("❌", "\u2717").replace("⏭", "\u2192")
    t = re.sub(r"\s{2,}", " ", t)
    t = t.replace("\x00", "*")
    return t.strip()


def parse_table(lines: list[str]):
    """Split a pipe table into header + body rows, dropping the rule line."""
    rows = []
    for ln in lines:
        if re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", ln) and "-" in ln:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return None
    header, body = rows[0], rows[1:]
    ncol = max(len(r) for r in rows)
    header += [""] * (ncol - len(header))
    body = [r + [""] * (ncol - len(r)) for r in body]
    return header, body


def make_table(header, body, avail_w):
    data = [[Paragraph(clean_inline(c), S["th"]) for c in header]]
    for r in body:
        data.append([Paragraph(clean_inline(c), S["td"]) for c in r])

    ncol = len(header)
    # width by content length, with a floor so narrow columns stay readable
    weights = []
    for i in range(ncol):
        lens = [len(header[i])] + [len(r[i]) for r in body]
        weights.append(max(6, sum(lens) / max(1, len(lens))))
    total = sum(weights)
    widths = [max(1.35 * cm, avail_w * w / total) for w in weights]
    scale = avail_w / sum(widths)
    widths = [w * scale for w in widths]

    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.32, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.6),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
    ]))
    return t


def md_to_flowables(md: str, avail_w: float):
    """Convert one markdown document into a list of flowables."""
    out = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        # ---- fenced code
        if s.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            txt = html.escape("\n".join(buf), quote=False).replace(" ", "&nbsp;")
            out.append(Paragraph(txt.replace("\n", "<br/>"), S["code"]))
            continue

        # ---- table
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) and "-" in lines[i + 1]:
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            parsed = parse_table(block)
            if parsed:
                h, b = parsed
                out.append(Spacer(1, 3))
                out.append(make_table(h, b, avail_w))
                out.append(Spacer(1, 7))
            continue

        # ---- headings
        if s.startswith("#"):
            m = re.match(r"(#+)\s*(.*)", s)
            level = len(m.group(1))
            txt = clean_inline(m.group(2))
            if level == 1:
                out.append(Paragraph(txt, S["h1"]))
            elif level == 2:
                out.append(Paragraph(txt, S["h2"]))
            else:
                out.append(Paragraph(txt, S["h3"]))
            i += 1
            continue

        # ---- horizontal rule
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", s):
            out.append(Spacer(1, 5))
            out.append(Table([[""]], colWidths=[avail_w], rowHeights=[1.2],
                             style=TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.7, RULE)])))
            out.append(Spacer(1, 7))
            i += 1
            continue

        # ---- blockquote
        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                raw = re.sub(r"^\s*>\s?", "", lines[i]).strip()
                if raw:
                    buf.append(raw)
                i += 1
            # a leading markdown heading inside the quote becomes a heading
            if buf and buf[0].startswith("#"):
                txt = clean_inline(re.sub(r"^#+\s*", "", buf[0]))
                buf = buf[1:]
                out.append(Paragraph(txt, S["h3"]))
            if buf:
                txt = "<br/>".join(clean_inline(b) for b in buf)
                out.append(Paragraph(txt, S["quote"]))
            continue

        # ---- bullets
        m = re.match(r"^(\s*)([-*+])\s+(.*)", ln)
        if m:
            indent = len(m.group(1))
            parts = [m.group(3)]
            i += 1
            # absorb wrapped continuation lines of THIS item: indented further
            # than the marker, and not themselves a new list item, heading,
            # table, fence or quote.
            while i < len(lines):
                nxt = lines[i]
                ns = nxt.strip()
                if not ns:
                    break
                nind = len(nxt) - len(nxt.lstrip())
                if nind <= indent:
                    break
                if (ns.startswith(("#", "|", ">", "```"))
                        or re.match(r"^[-*+]\s", ns) or re.match(r"^\d+[.)]\s", ns)):
                    break
                parts.append(ns)
                i += 1
            out.append(Paragraph("\u2022&nbsp;&nbsp;" + clean_inline(" ".join(parts)),
                                 S["bullet"]))
            continue

        # ---- numbered
        m = re.match(r"^(\s*)(\d+)[.)]\s+(.*)", ln)
        if m:
            indent = len(m.group(1))
            num = m.group(2)
            parts = [m.group(3)]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                ns = nxt.strip()
                if not ns:
                    break
                nind = len(nxt) - len(nxt.lstrip())
                if nind <= indent:
                    break
                if (ns.startswith(("#", "|", ">", "```"))
                        or re.match(r"^[-*+]\s", ns) or re.match(r"^\d+[.)]\s", ns)):
                    break
                parts.append(ns)
                i += 1
            out.append(Paragraph(f"{num}.&nbsp;&nbsp;" + clean_inline(" ".join(parts)),
                                 S["num"]))
            continue

        # ---- raw HTML (badges, <p align>, <sub>) - meaningless in print
        if s.startswith("<") or re.match(r"^\s*!\[", s):
            while i < len(lines) and lines[i].strip():
                i += 1
            continue

        # ---- blank
        if not s:
            i += 1
            continue

        # ---- paragraph (gather continuation lines)
        buf = [s]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", "|", ">", "```"))
                    or re.match(r"^[-*+]\s", nxt) or re.match(r"^\d+[.)]\s", nxt)):
                break
            buf.append(nxt)
            i += 1
        out.append(Paragraph(clean_inline(" ".join(buf)), S["body"]))

    return out


# ------------------------------------------------------------------ deck pages
def page_decor(canvas, doc):
    canvas.saveState()
    w, h = A4
    # header rule
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(1.9 * cm, h - 1.35 * cm, w - 1.9 * cm, h - 1.35 * cm)
    canvas.setFont("Helvetica", 7.4)
    canvas.setFillColor(GREY)
    canvas.drawString(1.9 * cm, h - 1.15 * cm, "Hospital Patient Segmentation Study")
    canvas.drawRightString(w - 1.9 * cm, h - 1.15 * cm, "Documentation Pack \u00b7 synthetic data")
    # footer
    canvas.line(1.9 * cm, 1.45 * cm, w - 1.9 * cm, 1.45 * cm)
    canvas.setFont("Helvetica", 7.4)
    canvas.drawString(1.9 * cm, 1.05 * cm, "appureddy1102-cloud/hospital-segmentation-study")
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(NAVY)
    canvas.drawRightString(w - 1.9 * cm, 1.05 * cm, str(canvas.getPageNumber()))
    canvas.restoreState()


def cover(avail_w):
    f = [
        Spacer(1, 3.4 * cm),
        Paragraph("Hospital Patient Segmentation Study", S["title"]),
        Paragraph("Documentation Pack", S["subtitle"]),
        Spacer(1, 0.4 * cm),
        Table([[""]], colWidths=[avail_w], rowHeights=[2.4],
              style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), ORANGE)])),
        Spacer(1, 0.7 * cm),
    ]
    meta = [
        ["Network", "Four community hospitals, Hyderabad \u00b7 220 beds"],
        ["Panel", "41,834 patients \u00b7 507,544 transactional records"],
        ["Methods", "RFM quantile scoring \u00b7 K-means \u00b7 PCA \u00b7 Hungarian matching"],
        ["Reproduce", "python src/run_all.py  (\u2248 3.3 minutes)"],
        ["Validate", "pytest tests/ -q  \u2192  49 passed"],
        ["Data", "SYNTHETIC \u2014 seed 20241111 \u2014 not real patient data"],
    ]
    rows = [[Paragraph(f"<b>{k}</b>", S["td"]), Paragraph(clean_inline(v), S["td"])]
            for k, v in meta]
    t = Table(rows, colWidths=[3.1 * cm, avail_w - 3.1 * cm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
    ]))
    f += [t, Spacer(1, 1.1 * cm)]

    warn = Table([[Paragraph(
        "<b>Data provenance.</b> No real hospital data was supplied with this brief. Every record is "
        "generated by <font face='Courier' size='8'>src/generate_synthetic_data.py</font> from a fixed "
        "seed and is fully reproducible. Nothing here describes a real hospital, real patients or real "
        "revenue. The methods transfer unchanged to a real extract.", S["td"])]],
        colWidths=[avail_w])
    warn.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDF2E9")),
        ("BOX", (0, 0), (-1, -1), 0.7, ORANGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    f += [warn, Spacer(1, 1.0 * cm)]

    # contents
    f.append(Paragraph("Contents", S["h2"]))
    toc = [("1.", "README \u2014 project overview, findings and reproduction steps"),
           ("2.", "Methodology \u2014 seven decisions, rejected alternatives, worked examples"),
           ("3.", "Data Provenance & Ethics \u2014 synthetic data, privacy, care constraints"),
           ("4.", "Data Dictionary \u2014 field-level schema for all five source tables"),
           ("5.", "Self-Audit \u2014 requirement-to-evidence compliance checklist")]
    for n, t_ in toc:
        f.append(Paragraph(clean_inline(t_), S["num"], bulletText=n))
    return f


def main():
    avail_w = A4[0] - 3.8 * cm
    story = [PageBreak(), ]
    story = cover(avail_w)

    files = [
        ("../README.md", "Part 1 \u2014 README"),
        ("METHODOLOGY.md", "Part 2 \u2014 Methodology Notes"),
        ("DATA_PROVENANCE.md", "Part 3 \u2014 Data Provenance, Privacy and Ethical Constraints"),
        ("DATA_DICTIONARY.md", "Part 4 \u2014 Data Dictionary"),
        ("SELF_AUDIT.md", "Part 5 \u2014 Final Self-Audit"),
        ("../dashboards/dashboard_specification.md", "Part 6 \u2014 Dashboard Specification"),
    ]
    for path, label in files:
        p = (DOCS / path).resolve()
        if not p.exists():
            print(f"  ! missing {p}")
            continue
        story.append(PageBreak())
        story += md_to_flowables(p.read_text(encoding="utf-8"), avail_w)
        print(f"  + {label}  ({p.name}, {p.stat().st_size/1024:.1f} KB)")

    doc = BaseDocTemplate(str(OUT), pagesize=A4,
                          leftMargin=1.9 * cm, rightMargin=1.9 * cm,
                          topMargin=1.75 * cm, bottomMargin=1.75 * cm,
                          title="Hospital Patient Segmentation Study — Documentation Pack",
                          author="appureddy1102-cloud",
                          subject="Documentation: methodology, provenance, data dictionary, self-audit")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=page_decor)])
    doc.build(story)
    print(f"\nsaved {OUT} ({OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
