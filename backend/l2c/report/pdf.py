"""PDF reports with ReportLab (built-in fonts only, so it works the same on every OS)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from l2c.contract import constants as C
from l2c.contract.models import ComparisonFile, Finding

STYLES = getSampleStyleSheet()
CELL = ParagraphStyle("cell", parent=STYLES["BodyText"], fontSize=7.5, leading=9)
STATUS_COLORS = {
    C.STATUS_NON_COMPLIANT: colors.HexColor("#f8d7da"),
    C.STATUS_MISSING: colors.HexColor("#fde2c8"),
    C.STATUS_ADDED: colors.HexColor("#fff3cd"),
    C.STATUS_NEEDS_REVIEW: colors.HexColor("#e2e3f3"),
}
HEADER = ["Status", "Check", "Level", "Grid", "Plan vs shop", "Confidence", "Notes"]


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.drawString(0.5 * inch, 0.35 * inch, "CONFIDENTIAL - hackathon use only")
    canvas.drawRightString(landscape(letter)[0] - 0.5 * inch, 0.35 * inch, f"page {doc.page}")
    canvas.restoreState()


def _diff_text(f: Finding) -> str:
    if f.diffs:
        return "; ".join(f"{d.field}: plan {d.plan} / shop {d.shop}" for d in f.diffs)
    return f.evidence.rule.kind.replace("_", " ")


def _counts_table(counts: dict[str, int]) -> Table:
    data = [list(C.STATUSES), [str(counts.get(s, 0)) for s in C.STATUSES]]
    t = Table(data, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return t


def _findings_table(findings: list[Finding]) -> Table:
    rows = [HEADER]
    shades: list[tuple[int, colors.Color]] = []
    shown = [f for f in findings if f.status != C.STATUS_COMPLIANT]
    for i, f in enumerate(shown, start=1):
        rows.append(
            [
                f.status,
                f.check_type,
                f.level,
                f.grid or "-",
                Paragraph(_diff_text(f), CELL),
                f"{f.confidence:.2f}",
                Paragraph(f.notes or "", CELL),
            ]
        )
        if f.status in STATUS_COLORS:
            shades.append((i, STATUS_COLORS[f.status]))
    if len(rows) == 1:
        rows.append(["none", "", "", "", "no discrepancies to report", "", ""])
    t = Table(
        rows,
        repeatRows=1,
        colWidths=[
            0.9 * inch,
            1.3 * inch,
            0.5 * inch,
            0.6 * inch,
            3.4 * inch,
            0.7 * inch,
            2.4 * inch,
        ],
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#343a40")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    style += [("BACKGROUND", (0, i), (-1, i), c) for i, c in shades]
    t.setStyle(TableStyle(style))
    return t


def _doc(path: Path, title: str) -> SimpleDocTemplate:
    path.parent.mkdir(parents=True, exist_ok=True)
    return SimpleDocTemplate(
        str(path),
        pagesize=landscape(letter),
        title=title,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.6 * inch,
    )


def write_shop_report(path: Path, comp: ComparisonFile, coverage: list[str]) -> None:
    story = [
        Paragraph(f"Shop drawing comparison: {comp.shop_file}", STYLES["Title"]),
        Paragraph(
            f"Plan sheets compared: {', '.join(comp.plan_sheets) or 'none'}", STYLES["Normal"]
        ),
        Spacer(1, 8),
        _counts_table(comp.counts),
        Spacer(1, 10),
        Paragraph("Discrepancies and items to review", STYLES["Heading2"]),
        _findings_table(comp.findings),
        Spacer(1, 10),
        Paragraph("Coverage", STYLES["Heading2"]),
        *[Paragraph(line, STYLES["Normal"]) for line in coverage],
    ]
    _doc(path, f"Comparison {comp.shop_file}").build(
        story, onFirstPage=_footer, onLaterPages=_footer
    )


def write_plan_sheet_report(
    path: Path, sections: dict[str, list[Finding]], coverage: list[str], unassigned: list[Finding]
) -> None:
    from l2c.compare.outputs import counts

    story = [Paragraph("Report by plan sheet", STYLES["Title"])]
    for sheet, fs in sections.items():
        story += [
            Paragraph(f"Sheet {sheet}", STYLES["Heading2"]),
            _counts_table(counts(fs)),
            Spacer(1, 6),
            _findings_table(fs),
            Spacer(1, 12),
        ]
    if unassigned:
        story += [
            Paragraph(
                "Plan elements not covered by any shop file (unassigned)", STYLES["Heading2"]
            ),
            _findings_table(unassigned),
            Spacer(1, 12),
        ]
    story += [
        Paragraph("Coverage", STYLES["Heading2"]),
        *[Paragraph(line, STYLES["Normal"]) for line in coverage],
    ]
    _doc(path, "Report by plan sheet").build(story, onFirstPage=_footer, onLaterPages=_footer)


def write_summary(path: Path, project: str, findings: list[Finding], coverage: list[str]) -> None:
    from l2c.compare.outputs import counts

    story = [
        Paragraph(f"L2C summary: {project}", STYLES["Title"]),
        _counts_table(counts(findings)),
        Spacer(1, 10),
        Paragraph("Coverage", STYLES["Heading2"]),
        *[Paragraph(line, STYLES["Normal"]) for line in coverage],
    ]
    _doc(path, f"Summary {project}").build(story, onFirstPage=_footer, onLaterPages=_footer)
