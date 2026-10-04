"""Vector primitives of a page: solid symbols, drawn frames and straight lines.

Everything is in the displayed frame (rotation applied), origin top-left. No sizes are fixed in
points; callers compare against the page's own text height or grid spacing.

The page's drawing commands are read once (`page.get_cdrawings()`), sorted into plain coordinate
lists, and moved into the displayed frame with one array operation (no per-shape Rect/Matrix
objects, which dominated the time on dense sheets).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pymupdf

SOLID_MAX_LUM = 0.75  # fills lighter than this are backgrounds and hatches, not symbols
AXIS_TOL = 0.3
MAX_ITEMS = 12  # a symbol or frame path has only a few items


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def contains(self, x: float, y: float, pad: float = 0.0) -> bool:
        return self.x0 - pad <= x <= self.x1 + pad and self.y0 - pad <= y <= self.y1 + pad


@dataclass(frozen=True)
class Seg:
    x0: float
    y0: float
    x1: float
    y1: float
    color: tuple | None = None

    @property
    def length(self) -> float:
        return ((self.x1 - self.x0) ** 2 + (self.y1 - self.y0) ** 2) ** 0.5


@dataclass
class Vectors:
    solids: list[Box] = field(default_factory=list)  # filled shapes: column and pier symbols
    frames: list[Box] = field(default_factory=list)  # stroked rectangles: callout and detail frames
    lines: list[Seg] = field(default_factory=list)  # straight segments, any length
    hlines: list[Seg] = field(default_factory=list)  # horizontal segments (frame edges, leaders)
    vlines: list[Seg] = field(default_factory=list)  # vertical segments


def _lum(fill) -> float:
    return sum(fill[:3]) / 3 if len(fill) >= 3 else float(fill[0])


def _to_page(coords: np.ndarray, m: pymupdf.Matrix) -> np.ndarray:
    """Move (n, 2k) point coordinates through the page's rotation matrix."""
    if coords.size == 0:
        return coords
    x, y = coords[:, 0::2], coords[:, 1::2]
    out = np.empty_like(coords)
    out[:, 0::2] = m.a * x + m.c * y + m.e
    out[:, 1::2] = m.b * x + m.d * y + m.f
    return out


def _rect_to_page(rects: np.ndarray, m: pymupdf.Matrix) -> np.ndarray:
    """(n, 4) rectangles x0,y0,x1,y1 -> bounding rectangles in the displayed frame."""
    if rects.size == 0:
        return rects
    pts = np.stack(
        [rects[:, [0, 1]], rects[:, [2, 1]], rects[:, [2, 3]], rects[:, [0, 3]]], axis=1
    )  # n,4,2
    x = m.a * pts[:, :, 0] + m.c * pts[:, :, 1] + m.e
    y = m.b * pts[:, :, 0] + m.d * pts[:, :, 1] + m.f
    return np.stack([x.min(axis=1), y.min(axis=1), x.max(axis=1), y.max(axis=1)], axis=1)


def vectors_from_drawings(drawings: list[dict], m: pymupdf.Matrix) -> Vectors:
    solids: list[tuple] = []
    frames: list[tuple] = []
    seg_xy: list[tuple] = []
    seg_color: list[tuple] = []
    for d in drawings:
        items = d["items"]
        x0, y0, x1, y1 = d["rect"]
        w, h = x1 - x0, y1 - y0
        fill = d.get("fill")
        color = d.get("color")
        filled = fill is not None and _lum(fill) < SOLID_MAX_LUM
        stroked = color is not None
        if len(items) <= MAX_ITEMS and w > 0.5 and h > 0.5:
            if filled and (not stroked or (w < 60 and h < 60)):
                solids.append((x0, y0, x1, y1))
            elif stroked and not filled and _is_rect(items):
                frames.append((x0, y0, x1, y1))
        if color is None:
            continue
        c = tuple(color)
        for it in items:
            kind = it[0]
            if kind == "l":
                seg_xy.append((it[1][0], it[1][1], it[2][0], it[2][1]))
                seg_color.append(c)
            elif kind == "re":
                r = it[1]
                rx0, ry0, rx1, ry1 = (
                    min(r[0], r[2]),
                    min(r[1], r[3]),
                    max(r[0], r[2]),
                    max(r[1], r[3]),
                )
                seg_xy += [
                    (rx0, ry0, rx1, ry0),
                    (rx1, ry0, rx1, ry1),
                    (rx1, ry1, rx0, ry1),
                    (rx0, ry1, rx0, ry0),
                ]
                seg_color += [c, c, c, c]
    out = Vectors()
    for r in _rect_to_page(np.array(solids, dtype=float).reshape(-1, 4), m):
        out.solids.append(Box(*map(float, r)))
    for r in _rect_to_page(np.array(frames, dtype=float).reshape(-1, 4), m):
        out.frames.append(Box(*map(float, r)))
    segs = _to_page(np.array(seg_xy, dtype=float).reshape(-1, 4), m)
    if len(segs):
        dx = np.abs(segs[:, 2] - segs[:, 0])
        dy = np.abs(segs[:, 3] - segs[:, 1])
        horiz = (dy < AXIS_TOL) & (dx > AXIS_TOL)
        vert = (dx < AXIS_TOL) & (dy > AXIS_TOL)
        rows = segs.tolist()
        out.lines = [Seg(r[0], r[1], r[2], r[3], c) for r, c in zip(rows, seg_color, strict=True)]
        for i in np.nonzero(horiz)[0]:
            r = rows[i]
            out.hlines.append(Seg(min(r[0], r[2]), r[1], max(r[0], r[2]), r[1], seg_color[i]))
        for i in np.nonzero(vert)[0]:
            r = rows[i]
            out.vlines.append(Seg(r[0], min(r[1], r[3]), r[0], max(r[1], r[3]), seg_color[i]))
    return out


def read_vectors(page: pymupdf.Page) -> Vectors:
    return vectors_from_drawings(page.get_cdrawings(), page.rotation_matrix)


def _is_rect(items) -> bool:
    kinds = [it[0] for it in items]
    return kinds == ["re"] or (kinds.count("l") in (4, 5) and set(kinds) <= {"l"})
