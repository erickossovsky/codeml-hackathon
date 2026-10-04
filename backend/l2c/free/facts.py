"""Turn one printed line into open-ended facts, without a fixed list of labels.

A line is `[label] content`. The label is whatever word comes first when it ends in `:` or `.` (or
is followed by a dimension), so `ARM.:`, `LIG.:`, `COL.`, `HORZ:`, `VERT:` are all read the same
way and the label text itself becomes the role or name. The content is searched for notations that
are standard across detailers (bar groups, spacings, sections, strengths, lengths). Whatever is not
recognized is kept as text; nothing is dropped.
"""

from __future__ import annotations

import re
from typing import Any

INCH_MM = 25.4
MAX_PLAUSIBLE_COUNT = 60  # a bar group larger than this in one element is read noise
FOOT_MM = 304.8
_Q = "\"”″“"
_UNIT = rf"(?:mm|cm|m|[{_Q}]|''|in|ft|')"

# bar designations: metric 10M..., imperial #4, diameter marks Ø16 / 16mm
SIZE = r"(?:\d{1,2}M|#\d{1,2}|[ØøΦ⌀]\s?\d{1,3}(?:\.\d+)?(?:\s?mm)?)"

BAR_COUNT = re.compile(rf"(?<![\w.])(\d{{1,3}})\s*(?:\((\d{{1,3}})\))?\s*[-–x×]\s*({SIZE})(?!\w)", re.I)
BAR_SPACED = re.compile(rf"(?<![\w.])({SIZE})\s*@\s*(\d+(?:\.\d+)?)\s*({_UNIT})?", re.I)
MULT_BAR = re.compile(
    rf"(?<![\w.])(\d{{1,3}})\s*[xX×]\s*(\d{{1,3}})\s+({SIZE})(?:\s+([A-Za-z]\w*(?:[-.]\w+)*))?(?!\w)", re.I
)
COUNT_SIZE_MARK = re.compile(rf"(?<![\w.])(\d{{1,3}})\s+({SIZE})(?:\s+([A-Za-z]\w*(?:[-.]\w+)*))?(?!\w)", re.I)
MARK = re.compile(r"(?<![\w.])(\d{2})([A-Z])(\d{3,5})(?![\w])")  # `20Z3150`: size 20, shape Z, length 3150
COUNT_MARK = re.compile(r"^\s*(\d{1,3})\s+(\d{2})([A-Z]{1,2})([\dX]{1,6}(?:-\d{1,2})?)(?![\w])")  # `3 15UJ2-05`: count, size 15, mark
SUM_COUNT = re.compile(rf"(?<![\w.])(\d{{1,3}})\s*\+\s*(\d{{1,3}})\s+({SIZE})(?!\w)", re.I)  # `3 + 12 15M`: 15 bars
COUNT_PAIR = re.compile(r"(?<![\w.])(\d{1,3})\s*\((\d{1,3})\)(?![\w-])")
SECTION = re.compile(
    rf"(?<![\w.])(\d+(?:\.\d+)?)\s*({_UNIT})?\s*[xX×]\s*(\d+(?:\.\d+)?)\s*({_UNIT})?(?![\w.])"
)
STRENGTH = re.compile(r"(?<![\w.])(\d{2,3})\s*MPa\b", re.I)
FEET_INCHES = re.compile(rf"(\d+)\s*'\s*-?\s*(\d+(?:\.\d+)?)?\s*[{_Q}]?")
LENGTH_MM = re.compile(r"(?<![\w.])(\d{3,6})\s*mm\b", re.I)
EACH_WAY = re.compile(r"\b(each way|both ways|chaque sens|dans les deux sens|e\.w\.|typ\.?|c/c|o\.c\.)", re.I)
LABEL = re.compile(r"^\s*([^\W\d_][^\W_]*(?:[ ./\-][^\W_]+){0,2}?)\s*(?:[:]|\.\s*:|\.(?=\s))\s*(.*)$", re.S)
SOFT_LABEL = re.compile(r"^\s*([^\W\d_][^\W_]{1,11}\.?)\s+(?=\d+(?:\.\d+)?\s*[xX×])")

# non-binding hint only: a label word that usually announces a kind of bar group
ROLE_HINTS = (
    ("dowel", ("gouj", "dowel", "tige", "attente")),
    ("main", ("arm", "vert", "long", "main", "reinf", "bars")),
    ("ties", ("lig", "etri", "étri", "tie", "stirrup", "cadre", "trans")),
)


def to_mm(value: float, unit: str | None, default: str | None = None) -> float | None:
    u = (unit or default or "").lower()
    if u == "mm":
        return round(value, 3)
    if u == "cm":
        return round(value * 10, 3)
    if u == "m":
        return round(value * 1000, 3)
    if u in ("ft", "'"):
        return round(value * FOOT_MM, 3)
    if u in ("in", "''") or (u and u in _Q):
        return round(value * INCH_MM, 3)
    return None


def _unit_name(unit: str) -> str:
    return "in" if unit in _Q or unit == "''" else unit


def role_hint(label: str | None) -> str | None:
    if not label:
        return None
    low = label.lower().strip(" .:")
    for hint, words in ROLE_HINTS:
        if any(low.startswith(w) for w in words):
            return hint
    return None


def feet_inches_mm(text: str) -> float | None:
    m = FEET_INCHES.search(text)
    if not m:
        return None
    return round(int(m.group(1)) * FOOT_MM + float(m.group(2) or 0) * INCH_MM, 3)


def split_label(text: str) -> tuple[str | None, str]:
    m = LABEL.match(text)
    if m and len(m.group(1)) <= 24:
        return m.group(1).strip(), m.group(2).strip()
    m = SOFT_LABEL.match(text)
    if m:
        return m.group(1).strip(" ."), text[m.end() :].strip()
    return None, text.strip()


def _blank(text: str, span: tuple[int, int]) -> str:
    return text[: span[0]] + " " * (span[1] - span[0]) + text[span[1] :]


def parse_line(text: str, label: str | None = None) -> dict[str, Any]:
    """{'label', 'bars', 'characteristics', 'rest'}; every list may be empty. A caller that already
    knows the label (a table's row header) passes it and the line is read as that label's content."""
    if label is not None:
        body = text.strip()
    else:
        label, body = split_label(text)
    work = body
    bars: list[dict[str, Any]] = []
    chars: list[dict[str, Any]] = []
    quals = [m.group(0) for m in EACH_WAY.finditer(body)]

    def add_bar(**kw: Any) -> None:
        bar = {"role": label.lower().strip(" .:") if label else None, **kw}
        hint = role_hint(label)
        if hint:
            bar["role_hint"] = hint
        if quals:
            bar["qualifiers"] = quals
        bar["source_text"] = text.strip()
        bars.append({k: v for k, v in bar.items() if v is not None})

    for m in EACH_WAY.finditer(work):
        work = _blank(work, m.span())
    for m in BAR_SPACED.finditer(work):
        sp = float(m.group(2))
        unit = (m.group(3) or "").lower()
        mm = to_mm(sp, unit, None if unit else "in" if sp < 30 else "mm")
        add_bar(size=m.group(1).upper(), spacing=sp, spacing_unit=unit or None, spacing_mm=mm)
        work = _blank(work, m.span())
    for m in BAR_COUNT.finditer(work):
        add_bar(
            count=int(m.group(1)),
            secondary_count=int(m.group(2)) if m.group(2) else None,
            size=m.group(3).upper(),
        )
        work = _blank(work, m.span())
    for m in MULT_BAR.finditer(work):  # `3x4 25M`: 3 groups of 4 bars
        add_bar(groups=int(m.group(1)), count=int(m.group(2)), size=m.group(3).upper(), mark=m.group(4))
        work = _blank(work, m.span())
    for m in SUM_COUNT.finditer(work):
        a, b2 = int(m.group(1)), int(m.group(2))
        add_bar(count=a + b2, count_parts=[a, b2], size=m.group(3).upper())
        work = _blank(work, m.span())
    if not bars:
        for m in COUNT_SIZE_MARK.finditer(work):
            count = int(m.group(1))
            if count > MAX_PLAUSIBLE_COUNT:  # OCR often glues a count to its neighbour (`6 20M` -> `620`)
                add_bar(size=m.group(2).upper(), mark=m.group(3), count_suspect=count)
            else:
                add_bar(count=count, size=m.group(2).upper(), mark=m.group(3))
            work = _blank(work, m.span())
    cm = COUNT_MARK.match(work)
    if cm and not bars:
        add_bar(count=int(cm.group(1)), size=f"{cm.group(2)}M", mark=f"{cm.group(2)}{cm.group(3)}{cm.group(4)}", mark_shape=cm.group(3), derived_from_mark=True)
        work = _blank(work, cm.span())
    for m in MARK.finditer(work):
        mark = m.group(0)
        target = next((b for b in bars if b.get("size", "").startswith(m.group(1)) and "mark" not in b), None)
        info = {"mark": mark, "mark_shape": m.group(2), "mark_length_mm": int(m.group(3))}
        if target is not None:
            target.update(info)
        elif not bars:
            add_bar(size=f"{m.group(1)}M", derived_from_mark=True, **info)
        work = _blank(work, m.span())
    lone_spacing = re.search(rf"@\s*(\d+(?:\.\d+)?)\s*({_UNIT})?", work)
    if lone_spacing and bars and "spacing" not in bars[-1]:
        sp = float(lone_spacing.group(1))
        unit = (lone_spacing.group(2) or "").lower()
        bars[-1].update(spacing=sp, spacing_mm=to_mm(sp, unit, None if unit else "in" if sp < 30 else "mm"))
        if unit:
            bars[-1]["spacing_unit"] = unit
        work = _blank(work, lone_spacing.span())
    for m in COUNT_PAIR.finditer(work):
        add_bar(count=int(m.group(1)), secondary_count=int(m.group(2)))
        work = _blank(work, m.span())
    for m in SECTION.finditer(work):
        a, ua, b, ub = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4)
        unit = ua or ub
        default = "in" if (a < 100 and b < 100) else "mm"
        if not unit and default == "in" and (a < 6 or b < 6):
            continue  # `3x4` is a bar multiplier or a count, not a section
        if not unit and default == "mm" and (a < 100 or b < 100):
            continue
        chars.append(
            {
                "name": "section",
                "value": [a, b],
                "unit": _unit_name(unit or default),
                "value_mm": [to_mm(a, unit, default), to_mm(b, unit, default)],
                "source_text": m.group(0).strip(),
            }
        )
        work = _blank(work, m.span())
    for m in STRENGTH.finditer(work):
        chars.append({"name": "concrete_strength", "value": int(m.group(1)), "unit": "MPa", "source_text": m.group(0)})
        work = _blank(work, m.span())
    for m in LENGTH_MM.finditer(work):
        chars.append({"name": "length", "value": int(m.group(1)), "unit": "mm", "value_mm": float(m.group(1)), "source_text": m.group(0)})
        work = _blank(work, m.span())
    rest = re.sub(r"\s+", " ", work).strip(" ,;:/|-")
    return {"label": label, "bars": bars, "characteristics": chars, "rest": rest}
