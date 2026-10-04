"""Per-page calibration: every tolerance is a multiple of the page's own geometry.

A different drawing scale, font size or grid spacing changes every distance in points; the
ratios (in Config) stay the same, so nothing here is tied to one project.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import Grid
from l2c.extract.runs import median_word_height
from l2c.ingest.pages import Word


@dataclass(frozen=True)
class PageScale:
    word_h: float
    run_gap: float  # words closer than this belong to the same printed phrase
    snap_tol: float  # distance from an outline centre to a gridline
    max_bind_dist: float  # how far a block may sit from its outline
    row_spacing: float | None
    col_spacing: float | None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _diffs(values: list[float], floor: float) -> list[float]:
    ordered = sorted(values)
    return [b - a for a, b in zip(ordered, ordered[1:], strict=False) if b - a > floor]


def calibrate(
    words: list[Word], grid: Grid | None = None, config: Config = DEFAULT_CONFIG
) -> PageScale:
    h = median_word_height(words)
    run_gap = _clamp(config.run_gap_word_heights * h, 0.5 * h, 5 * h)
    row_d = _diffs(list(grid.rows.values()), 0.1 * h) if grid else []
    col_d = _diffs([float(v) for v in grid.cols.values()], 0.1 * h) if grid else []
    row_sp = statistics.median(row_d) if row_d else None
    col_sp = statistics.median(col_d) if col_d else None
    typical = min([s for s in (row_sp, col_sp) if s is not None], default=None)
    snap = _clamp(config.snap_tol_fraction * typical, 0.75 * h, 4 * h) if typical else 1.75 * h
    bind = _clamp(config.bind_dist_col_spacings * col_sp, 8 * h, 30 * h) if col_sp else 15 * h
    return PageScale(h, run_gap, snap, bind, row_sp, col_sp)
