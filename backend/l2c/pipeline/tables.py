"""Find ruled tables from long lines and assign words to their cells.

A table is a set of long horizontal and vertical lines that cross each other. Its cells are the
rectangles between consecutive distinct line positions. Nothing about what the table holds is
assumed: the row and column headers of a cell are simply the text in the first column and first
row of the same table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from l2c.free.vectors import Vectors
from l2c.ingest.pages import Word

MIN_LINE_H = 8.0  # a table line is at least this many text heights long
MIN_LINES = 3  # at least this many lines per direction
MERGE_H = 0.4  # lines closer than this (in text heights) are one line
SPAN_SHARE = 0.5  # a separator crosses at least this share of the table
HEADER_REACH_H = 40.0  # a header row may sit this many text heights above the first line
HEADER_MIN_SHARE = 0.4  # ... when words sit above at least this share of the columns


@dataclass
class Table:
    id: str
    xs: list[float]
    ys: list[float]
    cells: dict[tuple[int, int], list[Word]] = field(default_factory=dict)

    @property
    def bbox(self) -> list[float]:
        return [round(self.xs[0], 2), round(self.ys[0], 2), round(self.xs[-1], 2), round(self.ys[-1], 2)]

    def cell_of(self, x: float, y: float) -> tuple[int, int] | None:
        if not (self.xs[0] <= x <= self.xs[-1] and self.ys[0] <= y <= self.ys[-1]):
            return None
        j = max(0, int(np.searchsorted(self.xs, x, side="right")) - 1)
        i = max(0, int(np.searchsorted(self.ys, y, side="right")) - 1)
        return min(i, len(self.ys) - 2), min(j, len(self.xs) - 2)

    def cell_bbox(self, i: int, j: int) -> list[float]:
        return [round(self.xs[j], 2), round(self.ys[i], 2), round(self.xs[j + 1], 2), round(self.ys[i + 1], 2)]


def _cluster(values: list[float], tol: float) -> list[float]:
    vals = sorted(values)
    out: list[list[float]] = []
    for v in vals:
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [float(np.mean(g)) for g in out]


def _extend_header(t: Table, words: list[Word], h: float) -> None:
    """A schedule often has no top line: its header row (the element names) floats above the first
    printed line. When words sit above in most columns, the table starts at the top of them."""
    above = [w for w in words if t.xs[0] <= w.cx <= t.xs[-1] and t.ys[0] - HEADER_REACH_H * h <= w.cy < t.ys[0]]
    if not above:
        return
    cols = {max(0, int(np.searchsorted(t.xs, w.cx, side="right")) - 1) for w in above}
    if len(cols) >= HEADER_MIN_SHARE * (len(t.xs) - 1):
        t.ys.insert(0, min(w.y0 for w in above) - 0.5 * h)


def find_tables(vec: Vectors, words: list[Word], h: float, page_w: float, page_h: float) -> list[Table]:
    min_len = MIN_LINE_H * h
    hl = [s for s in vec.hlines if s.x1 - s.x0 >= min_len]
    vl = [s for s in vec.vlines if s.y1 - s.y0 >= min_len]
    if len(hl) < MIN_LINES or len(vl) < MIN_LINES:
        return []
    tol = MERGE_H * h
    hy = np.array([s.y0 for s in hl])
    hx0 = np.array([s.x0 for s in hl])
    hx1 = np.array([s.x1 for s in hl])
    vx = np.array([s.x0 for s in vl])
    vy0 = np.array([s.y0 for s in vl])
    vy1 = np.array([s.y1 for s in vl])
    # h-line a crosses v-line b
    cross = (
        (hx0[:, None] - tol <= vx[None, :])
        & (vx[None, :] <= hx1[:, None] + tol)
        & (vy0[None, :] - tol <= hy[:, None])
        & (hy[:, None] <= vy1[None, :] + tol)
    )
    n_h = len(hl)
    parent = list(range(n_h + len(vl)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in zip(*np.nonzero(cross), strict=True):
        parent[find(int(a))] = find(n_h + int(b))
    comps: dict[int, tuple[list[int], list[int]]] = {}
    for i in range(n_h):
        comps.setdefault(find(i), ([], []))[0].append(i)
    for j in range(len(vl)):
        comps.setdefault(find(n_h + j), ([], []))[1].append(j)
    tables: list[Table] = []
    for hs, vs in comps.values():
        if len(hs) < MIN_LINES or len(vs) < MIN_LINES:
            continue
        top = min(hl[i].y0 for i in hs)
        bottom = max(hl[i].y0 for i in hs)
        left = min(vl[j].x0 for j in vs)
        right = max(vl[j].x0 for j in vs)
        # lines that cross most of the table separate cells; short ones are marks inside a cell
        ys = _cluster([hl[i].y0 for i in hs if hl[i].x1 - hl[i].x0 >= SPAN_SHARE * (right - left)], tol)
        xs = _cluster([vl[j].x0 for j in vs if vl[j].y1 - vl[j].y0 >= SPAN_SHARE * (bottom - top)], tol)
        if len(ys) < 3 or len(xs) < 3:
            continue
        if (xs[-1] - xs[0]) * (ys[-1] - ys[0]) > 0.95 * page_w * page_h:
            continue
        tables.append(Table("", xs, ys))
    for t in tables:
        _extend_header(t, words, h)
    tables.sort(key=lambda t: (t.ys[0], t.xs[0]))
    for k, t in enumerate(tables, 1):
        t.id = f"tb{k}"
    return tables


def assign_words(tables: list[Table], words: list[Word]) -> tuple[list[Word], set[int]]:
    """Put every word that sits inside a table into its cell. Returns the remaining words and the
    indices (into `words`) that were taken."""
    taken: set[int] = set()
    for idx, w in enumerate(words):
        for t in sorted(tables, key=lambda t: (t.xs[-1] - t.xs[0]) * (t.ys[-1] - t.ys[0])):
            c = t.cell_of(w.cx, w.cy)
            if c is not None:
                t.cells.setdefault(c, []).append(w)
                taken.add(idx)
                break
    rest = [w for i, w in enumerate(words) if i not in taken]
    return rest, taken


def cell_text(words: list[Word]) -> list[str]:
    """Lines of a cell in reading order (words on one baseline joined)."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x0)):
        if lines and abs(w.cy - lines[-1][0].cy) <= 0.6 * max(1.0, w.y1 - w.y0):
            lines[-1].append(w)
        else:
            lines.append([w])
    return [" ".join(x.text for x in sorted(line, key=lambda w: w.x0)) for line in lines]
