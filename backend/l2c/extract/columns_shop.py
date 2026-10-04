"""Extract column elements from a shop-drawing elevation sheet (convention A).

Layout (typical of sheets seen so far): grid labels like `J-12` along one edge, one column strip per
label; level bands down the page marked by `EL.: <elevation>` lines with the level name just
below; in each band every column strip holds a `VERT: <n> <size> <mark>` run and an
`ÉTRI: <n> <size> <mark> @<spacing>` run. Distances are multiples of the page's own geometry.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePath

from l2c.contract.models import Armature, ElementExt, LevelInfo, MatchKey
from l2c.extract import quality as Q
from l2c.extract.calibrate import calibrate
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.notation import (
    canon_level,
    parse_elevation,
    parse_grid_label,
    parse_shop_ties,
    parse_shop_vert,
)
from l2c.extract.runs import Run, cluster_1d, text_runs
from l2c.ingest.pages import PageData, Word

MIN_LABELS = 2
FALLBACK_STRIP_TOL_H = 7.5  # used only when there are too few labels to measure their spacing


@dataclass(frozen=True)
class LevelLine:
    level: str
    name: str
    y: float
    elevation_mm: float | None


def find_level_lines(
    page: PageData, runs: list[Run], config: Config = DEFAULT_CONFIG, word_h: float = 8.0
) -> list[LevelLine]:
    lines: list[LevelLine] = []
    for r in runs:
        if not config.starts(r.text, config.elevation_line):
            continue
        if r.x0 > config.level_x_fraction * page.width:
            continue
        below = [
            c
            for c in runs
            if 0 <= c.y0 - r.y0 <= config.level_label_below_word_heights * word_h
            and abs(c.x0 - r.x0) <= 1.5 * word_h
            and c is not r
        ]
        if not below:
            continue
        label = min(below, key=lambda c: c.y0 - r.y0)
        level = canon_level(label.text, config)
        if level is None:
            continue
        lines.append(
            LevelLine(level, label.text, round(r.y0, 2), parse_elevation(r.text.split(":", 1)[-1]))
        )
    return sorted(lines, key=lambda line: line.y)


def split_views(lines: list[LevelLine]) -> list[list[LevelLine]]:
    """Split level lines (top to bottom) into elevation views.

    A new view starts when the elevation rises or a level name repeats.
    """
    views: list[list[LevelLine]] = []
    for line in lines:
        if views:
            cur = views[-1]
            prev = cur[-1]
            rises = (
                line.elevation_mm is not None
                and prev.elevation_mm is not None
                and line.elevation_mm > prev.elevation_mm
            )
            repeats = any(c.level == line.level for c in cur)
            if not (rises or repeats):
                cur.append(line)
                continue
        views.append([line])
    return views


def assign_level(views: list[list[LevelLine]], y: float) -> tuple[str, list[str]]:
    """Level of a block at height y, plus quality flags.

    Between two level lines of one view the block belongs to the lower line's level (the column
    rises from it). Below the lowest line of a view it is a foundation dowel segment: FDN.
    """
    owner = None
    for view in views:
        if view[0].y <= y:
            owner = view
    if owner is None:
        return "UNKNOWN", ["level_unknown"]
    for upper, lower in zip(owner, owner[1:], strict=False):
        if upper.y <= y < lower.y:
            return lower.level, []
    return "FDN", ["below_lowest_level"]


def find_labels(
    words: list[Word], config: Config = DEFAULT_CONFIG, word_h: float = 8.0
) -> list[tuple[str, float, Word]]:
    cand = [(parse_grid_label(w.text, config), w) for w in words]
    cand = [(p, w) for p, w in cand if p is not None]
    if len(cand) < MIN_LABELS:
        return []
    tol = max(0.5, config.grid_align_word_heights * word_h)
    groups = cluster_1d([w.y0 for _, w in cand], tol)
    best = max(groups, key=lambda g: (len(g), -min(cand[i][1].y0 for i in g)))
    labels = [(f"{cand[i][0][0]}-{cand[i][0][1]:g}", cand[i][0][1], cand[i][1]) for i in best]
    return sorted(labels, key=lambda t: t[2].x0)


def strip_tolerance(labels: list[tuple[str, float, Word]], config: Config, word_h: float) -> float:
    xs = sorted({round(w.x0, 1) for _, _, w in labels})
    gaps = [b - a for a, b in zip(xs, xs[1:], strict=False) if b - a > 0.1 * word_h]
    if len(gaps) < 2:
        return FALLBACK_STRIP_TOL_H * word_h
    return config.strip_tol_fraction * statistics.median(gaps)


def _strip_for(run: Run, labels: list[tuple[str, float, Word]], tol: float):
    ranked = sorted(labels, key=lambda t: (abs(t[2].x0 - run.x0), t[2].x0))
    d1 = abs(ranked[0][2].x0 - run.x0)
    if d1 > tol:
        return None
    d2 = abs(ranked[1][2].x0 - run.x0) if len(ranked) > 1 else float("inf")
    margin = 1.0 if d2 == float("inf") else (d2 - d1) / d2
    return ranked[0], round(margin, 3)


def extract_shop_columns(
    page: PageData, config: Config = DEFAULT_CONFIG
) -> tuple[list[ElementExt], list[LevelInfo]]:
    scale = calibrate(page.words, None, config)
    h = scale.word_h
    runs = text_runs(page.words, gap=scale.run_gap, split_before=config.keywords())
    lines = find_level_lines(page, runs, config, h)
    views = split_views(lines)
    levels = [LevelInfo(level=ln.level, name=ln.name, elevation_mm=ln.elevation_mm) for ln in lines]
    labels = find_labels(page.words, config, h)
    if not labels:
        return [], levels
    tol = strip_tolerance(labels, config, h)
    stem = PurePath(page.fichier).stem
    verts = [
        r
        for r in runs
        if config.starts(r.text, config.shop_vert) and parse_shop_vert(r.text, config)
    ]
    ties_runs = [
        r
        for r in runs
        if config.starts(r.text, config.shop_ties) and parse_shop_ties(r.text, config)
    ]
    seen: Counter[str] = Counter()
    out: list[ElementExt] = []
    for v in sorted(verts, key=lambda r: (r.x0, r.y0)):
        strip = _strip_for(v, labels, tol)
        if strip is None:
            continue
        (grid_cell, col_num, label_word), margin = strip
        row = grid_cell.split("-", 1)[0]
        vert = parse_shop_vert(v.text, config)
        near = [
            t
            for t in ties_runs
            if abs(t.x0 - v.x0) <= config.ties_x_tol_word_heights * h
            and 0 < t.y0 - v.y0 <= config.ties_below_word_heights * h
        ]
        tie_run = min(near, key=lambda t: t.y0 - v.y0) if near else None
        tie = parse_shop_ties(tie_run.text, config) if tie_run else None
        level, flags = assign_level(views, v.y0)
        flags = list(flags)
        if tie is None:
            flags.append("ties_missing")
        elif tie.spacing_mm is None:
            flags.append("spacing_not_on_sheet")
        if margin < 0.3:
            flags.append("weak_strip_assignment")
        attrs = {"count": Q.attr(vert.count), "size": Q.attr(vert.size)}
        if tie is not None:
            attrs["tie_size"] = Q.attr(tie.size)
            attrs["tie_count"] = Q.attr(tie.count)
            if tie.spacing_mm is not None:
                attrs["spacing"] = Q.attr(tie.spacing_mm)
        passed, failed = Q.column_checks(
            vert.count, vert.size, tie.spacing_mm if tie else None, config
        )
        loc = Q.location(
            "label",
            1.0,
            grid_cell=grid_cell,
            binding_method="label_strip",
            anchor_dist_pt=round(abs(label_word.x0 - v.x0), 2),
            margin=margin,
        )
        x0 = min(v.x0, tie_run.x0 if tie_run else v.x0)
        y0 = v.y0
        x1 = max(v.x1, tie_run.x1 if tie_run else v.x1)
        y1 = max(v.y1, tie_run.y1 if tie_run else v.y1)
        base = f"{stem}_p{page.page}_{grid_cell}_{level}_shop"
        seen[base] += 1
        element_id = base if seen[base] == 1 else f"{base}_{seen[base]}"
        if seen[base] > 1:
            flags.append("duplicate_cell_level_on_page")
        armature = [Armature(repere=vert.mark, diametre=vert.size, quantite=vert.count)]
        if tie is not None:
            armature.append(
                Armature(
                    repere=tie.mark,
                    diametre=tie.size,
                    quantite=tie.count,
                    espacement_mm=tie.spacing_mm,
                )
            )
        out.append(
            ElementExt(
                id=element_id,
                source="shop",
                fichier=page.fichier,
                feuillet=stem,
                page=page.page,
                x=round((x0 + x1) / 2, 2),
                y=round((y0 + y1) / 2, 2),
                type_element="colonne",
                element=grid_cell,
                armature=armature,
                match_key=MatchKey(type="colonne", level=level, row=row, col=col_num),
                grid=grid_cell,
                level=level,
                bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                quality=Q.build_quality(
                    type_conf=1.0,
                    level_conf={"UNKNOWN": 0.3, "FDN": 0.8}.get(level, 1.0),
                    loc=loc,
                    attrs=attrs,
                    passed=passed,
                    failed=failed,
                    flags=flags,
                ),
                extraction_method="rules",
                raw_text=" | ".join(r.text for r in (v, tie_run) if r is not None),
                provenance={"file": page.fichier, "page": page.page, "adapter": "shop_label_strip"},
            )
        )
    out.sort(key=lambda e: (e.level, e.grid or "", e.id))
    return out, levels
