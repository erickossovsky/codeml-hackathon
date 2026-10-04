"""S5: one PDF report per input file listing the findings that involve that file.

Layout is code (ReportLab). The LLM writes one short sentence per flagged finding from that finding's
own property, plan value and shop value (a few dozen tokens in), never from a whole JSON. When the
model is unavailable or over budget, a fixed template sentence is used and the report says so.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from l2c.llm import prompts as P
from l2c.llm.client import LlmClient, ask_many

STATUS_ORDER = ["differs", "uncertain", "conforms", "not_in_shop", "not_in_plan"]
STATUS_TEXT = {
    "differs": "Differs",
    "not_in_shop": "Not matched: on plan, no shop counterpart found (shop drawings do not cover every element)",
    "not_in_plan": "Not matched: in shop drawings, no plan counterpart found",
    "uncertain": "Needs review (neighbouring-cell match or nothing comparable)",
    "conforms": "Conforms",
}
STATUS_COLOR = {
    "differs": colors.HexColor("#b3261e"),
    "not_in_shop": colors.HexColor("#5f6368"),
    "not_in_plan": colors.HexColor("#5f6368"),
    "uncertain": colors.HexColor("#5f6368"),
    "conforms": colors.HexColor("#1e7e34"),
}
EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {"sentence": {"type": "string"}},
    "required": ["sentence"],
}


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, list):
        return " x ".join(f"{x:g}" if isinstance(x, (int, float)) else str(x) for x in v)
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def template_sentence(f: dict, rec: dict) -> str:
    where = f"{rec.get('kind') or 'element'} at {rec['location'].get('grid') or 'unknown location'}"
    if f["result"] in {"missing", "added", "unmatched"}:
        return f"The {where} (level {rec.get('level') or 'unknown'}): no counterpart was found in the other documents."
    return f"At {where}, {f['property']} is {_fmt(f['plan'])} on the plan and {_fmt(f['shop'])} in the shop drawing."


class Explainer:
    """One short sentence per difference, written by the model. All the questions of a run are asked
    together, in parallel (`prefetch`), before any report is laid out; a difference that is the same
    property with the same two values is one question."""

    def __init__(self, client: LlmClient | None) -> None:
        self.client = client
        self.sentences: dict[str, str] = {}
        self.calls = 0

    @staticmethod
    def _prompt(f: dict) -> str:
        # no location in the prompt: the report's table already gives each place
        return f"PROPERTY: {f['property']}\nPLAN VALUE: {_fmt(f['plan'])}\nSHOP VALUE: {_fmt(f['shop'])}\nSENTENCE:"

    @staticmethod
    def _needs_model(f: dict) -> bool:
        return f["result"] not in {"missing", "added", "unmatched"}

    def prefetch(self, findings: dict) -> None:
        if self.client is None:
            return
        wanted: dict[str, None] = {}
        for rec in findings["entities"]:
            if rec["status"] in {"differs", "uncertain"}:
                for f in _review_items(rec)[:4]:
                    if self._needs_model(f):
                        wanted.setdefault(self._prompt(f), None)
        prompts = list(wanted)
        answers = ask_many(
            self.client, P.EXPLAIN_SYSTEM, prompts, EXPLAIN_SCHEMA, version=P.EXPLAIN_VERSION
        )
        self.calls = len(prompts)
        for prompt, ans in zip(prompts, answers, strict=True):
            text = str(ans.data.get("sentence", "")).strip()
            if len(text) >= 12:
                self.sentences[prompt] = text

    @property
    def used_llm(self) -> int:
        return len(self.sentences)

    def sentence(self, f: dict, rec: dict) -> str:
        if self._needs_model(f):
            hit = self.sentences.get(self._prompt(f))
            if hit:
                return hit
        return template_sentence(f, rec)


def _nat(text: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def _sheet_of(rec: dict) -> tuple[str, str]:
    """(plan sheet id, plan file) of a finding. The sheet id is the one in the title block; a page
    whose title block could not be read is named by its page."""
    m = rec["members"]["plan"][0]
    return (m.get("sheet") or f"page {m['page']}"), m["file"]


def _where(m: dict) -> str:
    return f"{Path(m['file']).name} p{m['page']}  x {m['x']:.0f}  y {m['y']:.0f}"


def _review_items(rec: dict) -> list[dict]:
    """What makes a record worth an engineer's look: its differences, or its possible differences."""
    return rec["flags"] or [i for i in rec["info"] if i.get("result") == "possible_difference"]


def _flag_text(explainer: Explainer, rec: dict) -> str:
    lines = [escape(explainer.sentence(f, rec)) for f in _review_items(rec)[:4]]
    if rec["notes"]:
        lines.append(f"<i>{escape(rec['notes'])}</i>")
    return "<br/>".join(lines)


def _table(data: list[list], widths: list[float], header_color) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 0), (-1, 0), header_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t


def build_project_report(
    findings: dict,
    out: Path,
    explainer: Explainer,
    project: str = "project",
    notes: list[str] | None = None,
    banner: str | None = None,
) -> Path:
    """One PDF for the whole project, organised by plan sheet: for each sheet the number of
    conformities and non-conformities, then the detailed list of discrepancies with the page and
    X, Y position on both documents."""
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=7.5, leading=9)
    doc = SimpleDocTemplate(
        str(out),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Plan and shop drawing verification: {project}",
    )
    recs = findings["entities"]
    plan_recs = [r for r in recs if r["members"]["plan"]]
    shop_only = [r for r in recs if not r["members"]["plan"]]
    by_sheet: dict[tuple[str, str], list[dict]] = {}
    for r in plan_recs:
        by_sheet.setdefault(_sheet_of(r), []).append(r)

    def counts(rows: list[dict]) -> dict[str, int]:
        c = {"compliant": 0, "non": 0, "verify": 0, "unclear": 0, "missing": 0}
        for r in rows:
            if r["status"] == "conforms":
                c["compliant"] += 1
            elif r["status"] == "differs":
                c["non"] += 1
            elif r["status"] == "uncertain":
                c["verify" if _review_items(r) else "unclear"] += 1
            elif r["status"] == "not_in_shop":
                c["missing"] += 1
        return c

    total = counts(plan_recs)
    story: list = [
        Paragraph(f"Plan and shop drawing verification: {escape(project)}", styles["Title"])
    ]
    if banner:
        story.append(
            Paragraph(
                f"<b>{escape(banner)}</b>",
                ParagraphStyle(
                    "banner", parent=styles["BodyText"], textColor=colors.HexColor("#8a6d00")
                ),
            )
        )
    story.append(
        Paragraph(
            "Each plan element was matched with its equivalent in the shop drawings and its reinforcement "
            "attributes were compared. The final decision remains the engineer's.",
            styles["BodyText"],
        )
    )
    head = ["", "Elements"]
    summary = [
        head,
        ["Compliant", total["compliant"]],
        ["Non-compliant", total["non"]],
        [
            "Possible non-compliance, to verify (the pairing or the agreeing values are too weak to be sure)",
            total["verify"],
        ],
        [
            "  of which in systematic differences (the same difference at several places, listed once)",
            sum(1 for r in plan_recs if r.get("group")),
        ],
        ["Matched, nothing comparable", total["unclear"]],
        ["Missing from the shop drawings (on the plan, no equivalent found)", total["missing"]],
        ["Added in the shop drawings (no plan equivalent found)", len(shop_only)],
    ]
    t = Table(summary, colWidths=[150 * mm, 25 * mm])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ]
        )
    )
    story += [
        Spacer(1, 4 * mm),
        t,
        Spacer(1, 6 * mm),
        Paragraph("Per plan sheet", styles["Heading2"]),
    ]
    rows = [
        [
            "Plan sheet",
            "Plan file",
            "Compliant",
            "Non-compliant",
            "To verify",
            "Nothing comparable",
            "Missing from shop drawings",
        ]
    ]
    for (sheet, file), items in sorted(by_sheet.items(), key=lambda kv: (_nat(kv[0][0]), kv[0][1])):
        c = counts(items)
        rows.append(
            [
                sheet,
                Paragraph(escape(Path(file).name), small),
                c["compliant"],
                c["non"],
                c["verify"],
                c["unclear"],
                c["missing"],
            ]
        )
    story.append(
        _table(
            rows,
            [28 * mm, 70 * mm, 24 * mm, 28 * mm, 22 * mm, 30 * mm, 38 * mm],
            colors.HexColor("#37474f"),
        )
    )

    for (sheet, _file), items in sorted(
        by_sheet.items(), key=lambda kv: (_nat(kv[0][0]), kv[0][1])
    ):
        bad = [r for r in items if r["status"] == "differs"]
        verify = [
            r
            for r in items
            if r["status"] == "uncertain" and _review_items(r) and not r.get("group")
        ]  # groups are listed once, below
        if not (bad or verify):
            continue
        story += [
            Spacer(1, 6 * mm),
            Paragraph(f"Sheet {escape(sheet)}: discrepancies", styles["Heading2"]),
        ]
        data = [["Element", "Level", "Plan position", "Shop drawing position", "Discrepancy"]]
        for label, group in (("Non-compliant", bad), ("To verify", verify)):
            for r in group:
                pm = r["members"]["plan"][0]
                # the sheet the difference was found on, when the member is printed on several
                sm = next((f["shop_ref"] for f in _review_items(r) if f.get("shop_ref")), None) or (
                    r["members"]["shop"][0] if r["members"]["shop"] else None
                )
                ident = f"{escape(str(r.get('kind') or 'element'))} {escape(str(r['location'].get('grid') or ''))}<br/><b>{label}</b>"
                data.append(
                    [
                        Paragraph(ident, small),
                        r.get("level") or "-",
                        Paragraph(escape(_where(pm)), small),
                        Paragraph(escape(_where(sm)) if sm else "-", small),
                        Paragraph(_flag_text(explainer, r), small),
                    ]
                )
        story.append(
            _table(data, [38 * mm, 16 * mm, 52 * mm, 56 * mm, 100 * mm], colors.HexColor("#b3261e"))
        )

    groups = findings.get("systematic") or []
    if groups:
        story += [
            Spacer(1, 8 * mm),
            Paragraph("Systematic differences", styles["Heading2"]),
            Paragraph(
                "The same difference found at several places. Real non-conformities are usually few and varied, so a repeated difference is more often a drawing convention or a reading artifact; it is listed once, with every place, for one check.",
                small,
            ),
        ]
        data = [["Group", "Difference", "Places", "Where (grid, level)"]]
        for g in groups:
            where = ", ".join(f"{p['grid'] or '?'} {p['level'] or ''}".strip() for p in g["places"])
            data.append(
                [
                    g["group"],
                    Paragraph(escape(f"{g['property']}: {g['relation']}"), small),
                    g["count"],
                    Paragraph(escape(where), small),
                ]
            )
        story.append(
            _table(data, [16 * mm, 80 * mm, 16 * mm, 150 * mm], colors.HexColor("#8a6d00"))
        )

    missing_rows = [r for r in plan_recs if r["status"] == "not_in_shop"]
    if missing_rows:
        story += [
            Spacer(1, 8 * mm),
            Paragraph("Missing from the shop drawings", styles["Heading2"]),
            Paragraph(
                "Shop drawings do not cover every plan element, so an element listed here is not necessarily an error. The note says why no counterpart was paired.",
                small,
            ),
        ]
        data = [["Plan sheet", "Element", "Level", "Plan position", "Note"]]
        for r in sorted(
            missing_rows,
            key=lambda r: (
                _nat(_sheet_of(r)[0]),
                r["members"]["plan"][0]["page"],
                r["members"]["plan"][0]["y"],
            ),
        ):
            pm = r["members"]["plan"][0]
            data.append(
                [
                    _sheet_of(r)[0],
                    Paragraph(
                        f"{escape(str(r.get('kind') or 'element'))} {escape(str(r['location'].get('grid') or ''))}",
                        small,
                    ),
                    r.get("level") or "-",
                    Paragraph(escape(_where(pm)), small),
                    Paragraph(escape(r["notes"] or ""), small),
                ]
            )
        story.append(
            _table(data, [24 * mm, 48 * mm, 18 * mm, 66 * mm, 106 * mm], colors.HexColor("#5f6368"))
        )

    if shop_only:
        story += [
            Spacer(1, 8 * mm),
            Paragraph("Added in the shop drawings", styles["Heading2"]),
            Paragraph("Elements found in the shop drawings with no equivalent on the plan.", small),
        ]
        data = [["Shop file", "Element", "Level", "Shop drawing position"]]
        for r in sorted(
            shop_only,
            key=lambda r: (
                r["members"]["shop"][0]["file"],
                r["members"]["shop"][0]["page"],
                r["members"]["shop"][0]["y"],
            ),
        ):
            sm = r["members"]["shop"][0]
            data.append(
                [
                    Paragraph(escape(Path(sm["file"]).name), small),
                    Paragraph(
                        f"{escape(str(r.get('kind') or 'element'))} {escape(str(r['location'].get('grid') or ''))}",
                        small,
                    ),
                    r.get("level") or "-",
                    Paragraph(escape(_where(sm)), small),
                ]
            )
        story.append(_table(data, [70 * mm, 60 * mm, 20 * mm, 94 * mm], colors.HexColor("#5f6368")))

    story += [Spacer(1, 8 * mm), Paragraph("Method and limits", styles["Heading2"])]
    method = [
        "Text and its page position are read from the PDFs; pages without a text layer, or mostly raster, are read with OCR on this machine. Nothing leaves the machine.",
        "Elements are grouped from nearby text. A note's grid cell comes from the position of its text, which can sit one gridline away from the member it describes, so notes are also tried against neighbouring cells; such pairings are marked 'to verify'.",
        "Units are converted before comparing: the same value written in inches and in millimetres is compliant.",
        "A bar group counts as a non-conformity only when the rest of the group agrees; groups that share nothing are treated as different notes.",
        f"The local model answered {findings.get('llm_calls', 0)} questions on pairing and comparison and wrote the sentences in this report ({explainer.used_llm} distinct differences).",
    ] + (notes or [])
    for line in method:
        story.append(Paragraph("&bull; " + escape(line), small))
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)
    return out
