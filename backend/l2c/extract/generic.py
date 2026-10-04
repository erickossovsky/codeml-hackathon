"""Elements of every type other than columns: beams, walls, slabs and foundations.

These sheets do not print one fixed block per element. They print many loose reinforcement
statements (`11-25M`, `10M@6" c/c`, `RANG 2: 25M@11"`, `LIG.: ...`) placed along bars and walls.
The generic extractor takes every statement, binds it to the nearest grid cell and merges the
statements of one cell into one element; the same statement printed several times in a cell is one
bar group, and the same element on several pages of a file is one element (`collapse_duplicates`).

Location is approximate (the anchor is text, not an outline), so these elements carry a lower
confidence than columns and say so in their quality flags. Nothing is dropped: a statement outside
the grid, or on a sheet without a grid, becomes an unbound element and stays visible.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import PurePath

from l2c.contract.models import Armature, ElementExt, MatchKey
from l2c.extract import quality as Q
from l2c.extract.calibrate import calibrate
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import Grid
from l2c.extract.notation import Statement, parse_statements
from l2c.extract.runs import Run, text_runs
from l2c.ingest.pages import PageData

MIN_GRID_CONF = 0.1


def _axis_positions(grid: Grid) -> tuple[list[float], list[float]]:
    return sorted(grid.rows.values()), sorted(float(v) for v in grid.cols.values())


def _inside_axis(pos: float, axis: list[float]) -> bool:
    """On the grid: within half a gridline spacing of the outermost lines."""
    if len(axis) < 2:
        return False
    half = 0.5 * (axis[-1] - axis[0]) / (len(axis) - 1)
    return axis[0] - half <= pos <= axis[-1] + half


def _bind(grid: Grid, run: Run) -> tuple[str, str, float, float] | None:
    """(row, col, grid confidence, distance to the cell centre) of the nearest cell, or None."""
    row_pos, col_pos = (run.cy, run.cx) if grid.letters_on == "y" else (run.cx, run.cy)
    rows, cols = _axis_positions(grid)
    if not _inside_axis(row_pos, rows) or not _inside_axis(col_pos, cols):
        return None
    row, dr, dr2 = grid.nearest_row(row_pos)
    col, dc, dc2 = grid.nearest_col(col_pos)
    margin = min(
        1.0 if d2 == float("inf") else (d2 - d1) / d2 if d2 > 0 else 0.0
        for d1, d2 in ((dr, dr2), (dc, dc2))
    )
    cx, cy = grid.center(row, col)
    return (
        row,
        col,
        round(max(MIN_GRID_CONF, margin), 3),
        round(((run.cx - cx) ** 2 + (run.cy - cy) ** 2) ** 0.5, 2),
    )


def _armature(statements: list[Statement]) -> list[Armature]:
    seen: dict[tuple, Armature] = {}
    for s in statements:
        key = (s.label, s.size, s.count, s.spacing_mm, s.secondary)
        label = s.label or (f"({s.secondary})" if s.secondary is not None else None)
        seen.setdefault(
            key,
            Armature(repere=label, diametre=s.size, quantite=s.count, espacement_mm=s.spacing_mm),
        )
    return sorted(
        seen.values(),
        key=lambda a: (
            a.diametre or "",
            a.quantite if a.quantite is not None else -1,
            a.espacement_mm if a.espacement_mm is not None else -1.0,
            a.repere or "",
        ),
    )


def extract_generic(
    page: PageData,
    etype: str,
    level: str,
    grid: Grid | None,
    source: str,
    config: Config = DEFAULT_CONFIG,
    type_conf: float = 0.9,
    level_conf: float = 1.0,
) -> list[ElementExt]:
    scale = calibrate(page.words, grid, config)
    runs = text_runs(page.words, gap=scale.run_gap)
    cells: dict[tuple[str, str], list[tuple[Run, list[Statement], float, float]]] = defaultdict(
        list
    )
    loose: list[tuple[Run, list[Statement], str]] = []
    for run in runs:
        statements = parse_statements(run.text, config)
        if not statements:
            continue
        hit = _bind(grid, run) if grid else None
        if hit is None:
            loose.append((run, statements, "no_grid" if grid is None else "outside_grid"))
        else:
            cells[(hit[0], hit[1])].append((run, statements, hit[2], hit[3]))
    stem = PurePath(page.fichier).stem
    sheet = page.feuillet or f"{stem}_p{page.page}"
    out: list[ElementExt] = []

    def build(
        element_id: str,
        grid_cell: str | None,
        row: str | None,
        col: float | None,
        members: list[tuple[Run, list[Statement]]],
        grid_conf: float,
        dist: float | None,
        flags: list[str],
    ) -> ElementExt:
        statements = [s for _, ss in members for s in ss]
        x0 = min(r.x0 for r, _ in members)
        y0 = min(r.y0 for r, _ in members)
        x1 = max(r.x1 for r, _ in members)
        y1 = max(r.y1 for r, _ in members)
        loc = Q.location(
            "text_only",
            grid_conf,
            anchor_dist_pt=dist,
            grid_cell=grid_cell,
            binding_method="nearest_cell" if grid_cell else "none",
        )
        attrs = {f"bars{i}": Q.attr(s.size) for i, s in enumerate(statements[:6])}
        return ElementExt(
            id=element_id,
            source=source,  # type: ignore[arg-type]
            fichier=page.fichier,
            feuillet=page.feuillet if source == "plan" else stem,
            page=page.page,
            x=round((x0 + x1) / 2, 2),
            y=round((y0 + y1) / 2, 2),
            type_element=etype,  # type: ignore[arg-type]
            element=grid_cell or element_id,
            armature=_armature(statements),
            match_key=MatchKey(type=etype, level=level, row=row, col=col),  # type: ignore[arg-type]
            grid=grid_cell,
            level=level,
            bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
            quality=Q.build_quality(
                type_conf=type_conf,
                level_conf=level_conf,
                loc=loc,
                attrs=attrs,
                passed=[],
                failed=[],
                flags=["generic_block", *flags],
            ),
            extraction_method="rules",
            raw_text=" | ".join(r.text for r, _ in members),
            provenance={
                "file": page.fichier,
                "page": page.page,
                "adapter": "generic",
                "statements": len(statements),
                # how many times the most repeated statement is printed in this cell
                "occurrences": max(
                    Counter((x.label, x.size, x.count, x.spacing_mm) for x in statements).values()
                ),
            },
        )

    for (row, col), members in sorted(cells.items()):
        cell = f"{row}-{col}"
        conf = min(m[2] for m in members)
        dist = min(m[3] for m in members)
        flags = ["weak_cell"] if conf < 0.3 else []
        out.append(
            build(
                f"{sheet}_{cell}_{etype}",
                cell,
                row,
                float(col),
                [(m[0], m[1]) for m in members],
                conf,
                dist,
                flags,
            )
        )
    for n, (run, statements, why) in enumerate(sorted(loose, key=lambda t: (t[0].y0, t[0].x0)), 1):
        out.append(
            build(
                f"{sheet}_U{n:03d}_{etype}",
                None,
                None,
                None,
                [(run, statements)],
                MIN_GRID_CONF,
                None,
                ["unbound_block", why],
            )
        )
    return out


def _signature(e: ElementExt) -> tuple:
    return (
        e.source,
        e.fichier,
        e.type_element,
        e.level,
        e.grid,
        tuple((a.repere, a.diametre, a.quantite, a.espacement_mm) for a in e.armature),
    )


def collapse_duplicates(elements: list[ElementExt]) -> list[ElementExt]:
    """One element per (file, type, level, cell, reinforcement): the same item listed several times
    in a PDF is a single element. Unbound blocks have no cell, so they only merge when their text
    is also identical. Two different files are never merged (that is a cross-file check)."""
    groups: dict[tuple, list[ElementExt]] = {}
    for e in elements:
        key = _signature(e)
        if e.grid is None:
            key += (e.raw_text,)
        groups.setdefault(key, []).append(e)
    out: list[ElementExt] = []
    for members in groups.values():
        first = members[0]
        if len(members) > 1:
            total = sum(int(m.provenance.get("occurrences", 1)) for m in members)
            pages = sorted({m.page for m in members})
            first = first.model_copy(
                update={
                    "provenance": {
                        **first.provenance,
                        "occurrences": total,
                        "pages": ",".join(str(p) for p in pages),
                    }
                }
            )
        out.append(first)
    return out


SCHEDULE_HEADER = ("TYPE",)
SCHEDULE_ARM = ("ARM",)
FOOTING_TYPE = re.compile(r"^[A-Z]$")


def read_footing_schedule(words, config: Config = DEFAULT_CONFIG) -> dict[str, list[Statement]]:
    """Footing type letter -> its bar statements (long bars first, then transverse), read from a
    schedule table with a TYPE column and ARM. columns. Empty when the page has no such table."""
    type_words = [w for w in words if w.text.upper() == "TYPE"]
    if not type_words:
        return {}
    head = type_words[0]
    arm_xs = sorted(
        w.cx
        for w in words
        if w.text.upper().startswith("ARM") and abs(w.cy - head.cy) < 3 * (head.y1 - head.y0 + 1)
    )
    if len(arm_xs) < 2:
        arm_xs = sorted(w.cx for w in words if w.text.upper().startswith("ARM") and w.cy > head.cy)[
            :2
        ]
    if len(arm_xs) < 2:
        return {}
    table = {}
    letters = [
        w
        for w in words
        if FOOTING_TYPE.match(w.text)
        and abs(w.cx - head.cx) < 2.5 * (head.x1 - head.x0)
        and w.cy > head.cy
    ]
    for letter in sorted(letters, key=lambda w: w.cy):
        row = [
            w
            for w in words
            if abs(w.cy - letter.cy) < 0.6 * (letter.y1 - letter.y0) and w.cx > letter.cx
        ]
        statements = []
        for w in sorted(row, key=lambda w: w.cx):
            for s in parse_statements(w.text, config):
                statements.append((w.cx, s))
        if not statements:
            continue
        long_bars = [s for x, s in statements if abs(x - arm_xs[0]) <= abs(x - arm_xs[1])]
        trans_bars = [s for x, s in statements if abs(x - arm_xs[1]) < abs(x - arm_xs[0])]
        table[letter.text] = long_bars[:1] + trans_bars[:1]
    return table


def _enclosing_box(boxes, w):
    """The smallest drawn rectangle that contains a word's centre, or None."""
    hits = [b for b in boxes if b.x0 <= w.cx <= b.x1 and b.y0 <= w.cy <= b.y1]
    return min(hits, key=lambda b: b.w * b.h) if hits else None


def extract_footings(
    page: PageData,
    level: str,
    grid: Grid | None,
    source: str,
    config: Config = DEFAULT_CONFIG,
) -> list[ElementExt]:
    """Foundations: each footing is marked with its type letter on the plan; its bars are the
    schedule row of that letter. A footing whose letter has no schedule row is kept and flagged."""
    table = read_footing_schedule(page.words, config)
    if not table or grid is None:
        return []
    sheet = page.feuillet or f"{PurePath(page.fichier).stem}_p{page.page}"
    out: list[ElementExt] = []
    rows, cols = _axis_positions(grid)
    for w in page.words:
        if not FOOTING_TYPE.match(w.text):
            continue
        # a footing sits between the outer gridlines; grid row letters sit outside them
        if not (rows[0] <= w.cy <= rows[-1] and cols[0] <= w.cx <= cols[-1]):
            continue
        # the footing is the square around its marker: bind the square's centre, not the letter
        anchor = _enclosing_box(page.boxes, w)
        at = Run(w.text, w.x0, w.y0, w.x1, w.y1, (w,))
        if anchor is not None:
            at = Run(w.text, anchor.cx, anchor.cy, anchor.cx, anchor.cy, (w,))
        hit = _bind(grid, at)
        if hit is None:
            continue
        row, col, conf, dist = hit
        cell = f"{row}-{col}"
        bars = table.get(w.text, [])
        flags = ["footing_schedule"]
        if w.text not in table:
            flags.append("type_not_in_schedule")
        out.append(
            ElementExt(
                id=f"{sheet}_{cell}_fondation",
                source=source,  # type: ignore[arg-type]
                fichier=page.fichier,
                feuillet=page.feuillet if source == "plan" else PurePath(page.fichier).stem,
                page=page.page,
                x=round(w.cx, 2),
                y=round(w.cy, 2),
                type_element="fondation",
                element=cell,
                armature=_armature(bars),
                match_key=MatchKey(type="fondation", level=level, row=row, col=float(col)),
                grid=cell,
                level=level,
                bbox=(round(w.x0, 2), round(w.y0, 2), round(w.x1, 2), round(w.y1, 2)),
                quality=Q.build_quality(
                    type_conf=1.0,
                    level_conf=1.0,
                    loc=Q.location(
                        "label",
                        conf,
                        anchor_dist_pt=dist,
                        grid_cell=cell,
                        binding_method="nearest_cell",
                    ),
                    attrs={"bars": Q.attr(len(bars))},
                    passed=[],
                    failed=[],
                    flags=flags,
                ),
                extraction_method="rules",
                raw_text=w.text,
                provenance={
                    "file": page.fichier,
                    "page": page.page,
                    "adapter": "footing_schedule",
                    "footing_type": w.text,
                    "occurrences": 1,
                },
            )
        )
    return out
