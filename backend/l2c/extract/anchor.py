"""Anchor annotation blocks to column outlines.

Text position alone is ambiguous near close gridlines (they can be only tens of points
apart), so the anchor is the column *outline* found in the vector geometry. Blocks are bound
to outlines one-to-one (Hungarian assignment) after learning the sheet's recurring block
offsets.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from l2c.extract.grid import Grid
from l2c.ingest.pages import Shape

SIZE_BUCKET_FRACTION = 0.15  # shape sizes are grouped in buckets of 15% of the modal size
MIN_SNAPPED_FOR_MODE = 3
MIN_BLOCKS_FOR_OFFSET = 3
MIN_MODE_COUNT = 3
MODE_BIN_FRACTION = 0.1  # offset bins are a tenth of the binding radius
SECOND_PASS_RADIUS = 1.67  # second pass looks this many times further
SECOND_PASS_MARGIN_FACTOR = 0.5


@dataclass(frozen=True)
class Outline:
    row: str
    col: str
    shape: Shape
    grid_conf: float


@dataclass(frozen=True)
class Binding:
    row: str
    col: str
    cost: float
    margin: float  # 0..1, how much better than the runner-up outline
    grid_conf: float
    second_pass: bool = False


def find_outlines(
    shapes: list[Shape], grid: Grid, tol: float, size_tolerance: float = 0.4
) -> dict[tuple[str, str], Outline]:
    """Small closed shapes whose centre snaps to a grid intersection; one per cell.

    Column outlines share one size on a sheet, so the size is learned from the data: shapes far
    from the most common snapped size (within `size_tolerance`) are dropped. No fixed point sizes.
    """
    snapped: list[tuple[Shape, str, str, float]] = []
    for s in shapes:
        hit = grid.snap(s.cx, s.cy, tol)
        if hit is not None:
            snapped.append((s, hit[0], hit[1], hit[2]))
    if len(snapped) >= MIN_SNAPPED_FOR_MODE:
        step = _size_step(snapped)
        keys = Counter(_size_key(s, step) for s, *_ in snapped)
        lo, hi = sorted(keys.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        snapped = [
            t
            for t in snapped
            if abs(min(t[0].w, t[0].h) - lo) <= size_tolerance * lo
            and abs(max(t[0].w, t[0].h) - hi) <= size_tolerance * hi
        ]
    best: dict[tuple[str, str], tuple[float, Outline]] = {}
    for s, row, col, conf in snapped:
        gx, gy = grid.center(row, col)
        dist = math.hypot(s.cx - gx, s.cy - gy)
        key = (row, col)
        rank = (dist, s.cx, s.cy)
        if key not in best or rank < (best[key][0], best[key][1].shape.cx, best[key][1].shape.cy):
            best[key] = (dist, Outline(row, col, s, conf))
    return {k: v[1] for k, v in sorted(best.items())}


def _size_step(snapped: list[tuple[Shape, str, str, float]]) -> float:
    """Bucket width: a fraction of the median shape size, so it scales with the drawing."""
    sizes = sorted(min(s.w, s.h) for s, *_ in snapped)
    return max(0.5, SIZE_BUCKET_FRACTION * sizes[len(sizes) // 2])


def _size_key(s: Shape, step: float) -> tuple[float, float]:
    lo, hi = sorted((s.w, s.h))
    return (round(lo / step) * step, round(hi / step) * step)


def offset_modes(pts: np.ndarray, centers: np.ndarray, max_dist: float) -> list[np.ndarray]:
    """Recurring (dx, dy) offsets between blocks and their nearest outlines.

    Real sheets place a block either left or right of its column, so there are usually two
    offset modes, not one. A mode needs at least MIN_MODE_COUNT blocks and 10% of all blocks.
    """
    raw = np.linalg.norm(pts[:, None, :] - centers[None, :, :], axis=2)
    nearest = raw.argmin(axis=1)
    near = raw.min(axis=1) <= max_dist
    if near.sum() < MIN_BLOCKS_FOR_OFFSET:
        return []
    offs = pts[near] - centers[nearest[near]]
    bin_pt = max(1.0, MODE_BIN_FRACTION * max_dist)
    bins: dict[tuple[int, int], list[int]] = {}
    for idx, (dx, dy) in enumerate(offs):
        bins.setdefault((round(dx / bin_pt), round(dy / bin_pt)), []).append(idx)
    need = max(MIN_MODE_COUNT, int(0.1 * len(offs)))
    modes = [offs[ids].mean(axis=0) for _, ids in sorted(bins.items()) if len(ids) >= need]
    return modes


def bind_blocks(
    anchors: list[tuple[float, float]],
    outlines: dict[tuple[str, str], Outline],
    max_dist: float = 120.0,
) -> list[Binding | None]:
    """Bind each block anchor point to at most one outline, each outline to at most one block.

    The cost of pairing block i with outline j is the distance from the block to the nearest
    *expected block position* of that outline (outline centre plus one of the sheet's offset modes).
    """
    if not anchors or not outlines:
        return [None] * len(anchors)
    cells = list(outlines)
    centers = np.array([[outlines[c].shape.cx, outlines[c].shape.cy] for c in cells])
    pts = np.array(anchors, dtype=float)
    # Always keep the zero offset as a candidate so this is never worse than nearest-outline.
    modes = [np.zeros(2), *offset_modes(pts, centers, max_dist)]
    cost = np.min(
        [np.linalg.norm(pts[:, None, :] - (centers[None, :, :] + m), axis=2) for m in modes], axis=0
    )
    result: list[Binding | None] = [None] * len(anchors)
    _assign(
        cost,
        list(range(len(anchors))),
        list(range(len(cells))),
        max_dist,
        cells,
        outlines,
        result,
        False,
    )
    left_i = [i for i, r in enumerate(result) if r is None]
    used = {(r.row, r.col) for r in result if r is not None}
    left_j = [j for j, c in enumerate(cells) if c not in used]
    if left_i and left_j:
        plain = np.linalg.norm(pts[:, None, :] - centers[None, :, :], axis=2)
        _assign(plain, left_i, left_j, SECOND_PASS_RADIUS * max_dist, cells, outlines, result, True)
    return result


def _assign(
    cost: np.ndarray,
    rows: list[int],
    cols: list[int],
    limit: float,
    cells: list[tuple[str, str]],
    outlines: dict[tuple[str, str], Outline],
    result: list[Binding | None],
    second_pass: bool,
) -> None:
    sub = cost[np.ix_(rows, cols)]
    ri, cj = linear_sum_assignment(sub)
    for a, b in zip(ri, cj, strict=True):
        i, j = rows[a], cols[b]
        c = float(cost[i, j])
        if c > limit:
            continue
        others = np.delete(cost[i], j)
        runner = float(others.min()) if others.size else math.inf
        margin = (
            1.0 if math.isinf(runner) else (max(0.0, (runner - c) / runner) if runner > 0 else 0.0)
        )
        if second_pass:
            margin *= SECOND_PASS_MARGIN_FACTOR
        o = outlines[cells[j]]
        result[i] = Binding(o.row, o.col, round(c, 3), round(margin, 3), o.grid_conf, second_pass)
