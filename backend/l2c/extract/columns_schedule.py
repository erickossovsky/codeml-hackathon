"""Extract column elements from a shop-drawing *schedule table* (convention B).

Layout: the sheet is a table with one table column per distinct reinforcement. A table column lists
the grid cells it covers (`D-6, D-7, ...`), a vertical-bars line (`3x4 25M MARK`: 3 identical
columns with 4 bars each) and a ties line (`3x18 10M MARK @150`). The level comes from the title
(`... NIV3@NIV4`: the columns rise from level 3). Every listed cell gets the column's reinforcement.

Distances are multiples of the page's own geometry, like the other adapters; the text may come from
OCR, which glues tokens and merges neighbouring columns into one line, so specifications are found
by pattern inside each text run and located by their character offset.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePath

from l2c.contract.models import Armature, ElementExt, LevelInfo, MatchKey
from l2c.extract import quality as Q
from l2c.extract.calibrate import calibrate
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.notation import (
    ScheduleSpec,
    parse_grid_label,
    parse_schedule_specs,
    schedule_level,
)
from l2c.extract.runs import Run, text_runs
from l2c.ingest.pages import PageData, Word

MIN_COLUMNS = 2
ROW_GAP_WORD_HEIGHTS = 2.0  # specs closer than this (in word heights) share a table row
FALLBACK_PITCH_WORD_HEIGHTS = 24.0  # column pitch when only one column can be measured
CONFUSED_I = re.compile(r"^1((?:\.\d)?-\d)")  # OCR reads the row letter I as the digit 1


@dataclass(frozen=True)
class Located:
    spec: ScheduleSpec
    x0: float
    y0: float
    run: Run


@dataclass(frozen=True)
class Label:
    text: str  # normalised cell label, e.g. "D-6"
    row: str
    col: float
    word: Word
    run: Run
    snapped: bool


def _x_at(run: Run, offset: int) -> float:
    """Page x of a character offset inside a run (words are joined by single spaces)."""
    cursor = 0
    for w in run.words:
        end = cursor + len(w.text)
        if offset <= end:
            frac = (offset - cursor) / max(len(w.text), 1)
            return w.x0 + max(0.0, min(1.0, frac)) * (w.x1 - w.x0)
        cursor = end + 1
    return run.x1


def _located_specs(runs: list[Run], config: Config) -> list[Located]:
    out: list[Located] = []
    for r in runs:
        for spec in parse_schedule_specs(r.text, config):
            out.append(Located(spec, _x_at(r, spec.start), r.y0, r))
    return out


def _labels(runs: list[Run], config: Config) -> list[Label]:
    out: list[Label] = []
    for r in runs:
        for w in r.words:
            for piece in w.text.split(","):
                piece = piece.strip()
                if not piece:
                    continue
                snapped = False
                parsed = parse_grid_label(piece, config)
                if parsed is None:
                    fixed = CONFUSED_I.sub(r"I\1", piece)
                    parsed = parse_grid_label(fixed, config) if fixed != piece else None
                    snapped = parsed is not None
                if parsed is None:
                    continue
                row, col = parsed
                out.append(Label(f"{row}-{col:g}", row, col, w, r, snapped))
    return out


def _title_level(page: PageData, config: Config) -> str | None:
    text = " ".join(w.text for w in page.words)
    return schedule_level(text, config) or schedule_level(PurePath(page.fichier).stem, config)


def _split_rows(specs: list[Located], word_h: float) -> tuple[list[Located], list[Located]]:
    """(vertical-bars specs, ties specs): ties sit in the row below the bars.

    Damaged OCR text loses the `@spacing` of a tie line, so the printed spacing is only used to find
    which row holds the ties (the row with the most spacings); every specification in that row is a
    tie and everything above it is a bar line. Without any spacing, all specs are bar lines.
    """
    from l2c.extract.runs import cluster_1d

    if not specs:
        return [], []
    rows = cluster_1d([s.y0 for s in specs], ROW_GAP_WORD_HEIGHTS * word_h)
    members = [[specs[i] for i in g] for g in rows]
    with_spacing = [sum(s.spec.spacing_mm is not None for s in m) for m in members]
    if max(with_spacing) == 0:
        return specs, []
    tie_row = max(range(len(members)), key=lambda k: (with_spacing[k], k))
    ties = members[tie_row]
    verts = [s for k, m in enumerate(members) if k < tie_row for s in m]
    return verts, ties


def _analyse(page: PageData, config: Config):
    scale = calibrate(page.words, None, config)
    runs = text_runs(page.words, gap=scale.run_gap)
    verts, ties = _split_rows(_located_specs(runs, config), scale.word_h)
    return scale, runs, verts, ties, _labels(runs, config)


def is_schedule_page(page: PageData, config: Config = DEFAULT_CONFIG) -> bool:
    if len(page.words) < config.min_words_native or _title_level(page, config) is None:
        return False
    _, _, verts, _, labels = _analyse(page, config)
    return len(verts) >= MIN_COLUMNS and len(labels) >= MIN_COLUMNS


def _pitch(verts: list[Located], word_h: float) -> float:
    xs = sorted(v.x0 for v in verts)
    gaps = [b - a for a, b in zip(xs, xs[1:], strict=False) if b - a > word_h]
    return statistics.median(gaps) if gaps else FALLBACK_PITCH_WORD_HEIGHTS * word_h


def _nearest(items: list[Located], x: float, limit: float, used: set[int]):
    ranked = sorted(
        ((abs(it.x0 - x), i) for i, it in enumerate(items) if i not in used), key=lambda t: t
    )
    if not ranked or ranked[0][0] > limit:
        return None
    return ranked[0][1], ranked[0][0]


def extract_schedule_columns(
    page: PageData, config: Config = DEFAULT_CONFIG
) -> tuple[list[ElementExt], list[LevelInfo]]:
    level = _title_level(page, config)
    if level is None or len(page.words) < config.min_words_native:
        return [], []
    scale, _, verts, ties, labels = _analyse(page, config)
    if len(verts) < MIN_COLUMNS or len(labels) < MIN_COLUMNS:
        return [], []
    pitch = _pitch(verts, scale.word_h)
    limit = 0.5 * pitch
    vert_y = statistics.median(v.y0 for v in verts)
    above = [lb for lb in labels if lb.run.y0 < vert_y]
    # one table column per vertical-bars line; each label joins the nearest one
    groups: dict[int, list[Label]] = {}
    loose: list[Label] = []
    for lb in above:
        hit = _nearest(verts, lb.run.x0, limit, set())
        if hit is None:
            loose.append(lb)
        else:
            groups.setdefault(hit[0], []).append(lb)
    tie_for: dict[int, int] = {}
    taken: set[int] = set()
    for vi in sorted(groups, key=lambda i: verts[i].x0):
        below = [(j, t) for j, t in enumerate(ties) if t.y0 > verts[vi].y0]
        pool = [t for _, t in below]
        idx_map = [j for j, _ in below]
        hit = _nearest(pool, verts[vi].x0, limit, {k for k, j in enumerate(idx_map) if j in taken})
        if hit is not None:
            tie_for[vi] = idx_map[hit[0]]
            taken.add(idx_map[hit[0]])
    stem = PurePath(page.fichier).stem
    seen: Counter[str] = Counter()
    out: list[ElementExt] = []

    def build(lb: Label, vi: int | None, count: int) -> None:
        v = verts[vi] if vi is not None else None
        t = ties[tie_for[vi]] if vi is not None and vi in tie_for else None
        flags = ["schedule_table"]
        attrs: dict = {}
        if v is not None:
            attrs["count"] = Q.attr(v.spec.count)
            attrs["size"] = Q.attr(v.spec.size)
        else:
            attrs["count"] = Q.missing_attr()
            attrs["size"] = Q.missing_attr()
            flags.append("bars_not_found")
        if t is not None:
            attrs["tie_size"] = Q.attr(t.spec.size)
            attrs["tie_count"] = Q.attr(t.spec.count)
            attrs["spacing"] = Q.attr(t.spec.spacing_mm)
        else:
            flags.append("ties_missing")
        if v is not None and v.spec.mult is not None and v.spec.mult != count:
            flags.append("cell_count_mismatch")
        if lb.snapped:
            flags.append("label_snapped")
        dx = abs(lb.run.x0 - v.x0) if v is not None else limit
        margin = round(max(0.0, min(1.0, (limit - dx) / limit)), 3) if limit > 0 else 1.0
        loc = Q.location(
            "label",
            0.9 if lb.snapped else 1.0,
            grid_cell=lb.text,
            binding_method="schedule_column",
            anchor_dist_pt=round(dx, 2),
            margin=margin if v is not None else 0.0,
        )
        passed, failed = Q.column_checks(
            v.spec.count if v else None,
            v.spec.size if v else None,
            t.spec.spacing_mm if t else None,
            config,
        )
        base = f"{stem}_p{page.page}_{lb.text}_{level}_shop"
        seen[base] += 1
        element_id = base if seen[base] == 1 else f"{base}_{seen[base]}"
        if seen[base] > 1:
            flags.append("duplicate_cell_level_on_page")
        armature = [
            Armature(
                repere=v.spec.mark if v else None,
                diametre=v.spec.size if v else None,
                quantite=v.spec.count if v else None,
            )
        ]
        if t is not None:
            armature.append(
                Armature(
                    repere=t.spec.mark,
                    diametre=t.spec.size,
                    quantite=t.spec.count,
                    espacement_mm=t.spec.spacing_mm,
                )
            )
        w = lb.word
        out.append(
            ElementExt(
                id=element_id,
                source="shop",
                fichier=page.fichier,
                feuillet=stem,
                page=page.page,
                x=round(w.cx, 2),
                y=round(w.cy, 2),
                type_element="colonne",
                element=lb.text,
                armature=armature,
                match_key=MatchKey(type="colonne", level=level, row=lb.row, col=lb.col),
                grid=lb.text,
                level=level,
                bbox=(round(w.x0, 2), round(w.y0, 2), round(w.x1, 2), round(w.y1, 2)),
                quality=Q.build_quality(
                    type_conf=1.0,
                    level_conf=1.0,
                    loc=loc,
                    attrs=attrs,
                    passed=passed,
                    failed=failed,
                    flags=flags,
                ),
                extraction_method="rules",
                raw_text=" | ".join(x.run.text for x in (v, t) if x is not None),
                provenance={"file": page.fichier, "page": page.page, "adapter": "shop_schedule"},
            )
        )

    for vi, members in sorted(groups.items(), key=lambda kv: verts[kv[0]].x0):
        for lb in sorted(members, key=lambda b: (b.run.y0, b.word.x0)):
            build(lb, vi, len(members))
    for lb in loose:
        build(lb, None, 1)
    out.sort(key=lambda e: (e.level, e.grid or "", e.id))
    return out, [LevelInfo(level=level, name=level)]
