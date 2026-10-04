"""Find the structural grid on a sheet: letter rows down one edge, number columns along another.

Grid labels are told apart from other small numbers and letters by structure, not by position:
an axis is the group of labels that (1) sit on one line, (2) form a monotonic sequence, and
(3) are repeated on the opposite edge of the sheet, as grid bubbles usually are.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.runs import cluster_1d, median_word_height
from l2c.ingest.pages import Word

TIGHT_FRACTION = 0.43  # "exactly on the line" is within this share of the snap tolerance
MIRROR_WORD_HEIGHTS = 10.0  # a mirrored label sits at least this far away on the other edge
ALIGN_WORD_HEIGHTS = 1.0  # ... and lines up with the first within this distance


@dataclass
class Grid:
    """Letters name rows, numbers name columns. Where they sit on the page depends on the sheet:
    letters_on="y": letters run down an edge (y positions), numbers along an edge (x positions);
    letters_on="x": the transposed convention (letters along the top, numbers down the side).
    """

    rows: dict[str, float] = field(default_factory=dict)  # letter -> position on its axis (pt)
    cols: dict[str, float] = field(default_factory=dict)  # number label -> position on its axis
    letters_on: str = "y"

    def center(self, row: str, col: str) -> tuple[float, float]:
        """Page (x, y) of the intersection of a letter and a number."""
        if self.letters_on == "y":
            return self.cols[col], self.rows[row]
        return self.rows[row], self.cols[col]

    def nearest_row(self, pos: float) -> tuple[str, float, float]:
        """(letter, distance to it, distance to the runner-up) for a position on the letter axis."""
        return _nearest(self.rows, pos)

    def nearest_col(self, pos: float) -> tuple[str, float, float]:
        return _nearest(self.cols, pos)

    def snap(self, cx: float, cy: float, tol: float) -> tuple[str, str, float] | None:
        """Snap a page point to a grid intersection: (row letter, col label, grid confidence)."""
        if not self.rows or not self.cols:
            return None
        row_pos, col_pos = (cy, cx) if self.letters_on == "y" else (cx, cy)
        row, dr, dr2 = self.nearest_row(row_pos)
        col, dc, dc2 = self.nearest_col(col_pos)
        if dr > tol or dc > tol:
            return None
        if dr < TIGHT_FRACTION * tol and dc < TIGHT_FRACTION * tol:
            conf = 1.0
        else:
            conf = max(0.0, min(_margin(dr, dr2), _margin(dc, dc2)))
        return row, col, round(conf, 3)


def _nearest(axis: dict[str, float], v: float) -> tuple[str, float, float]:
    ranked = sorted(
        ((abs(pos - v), name) for name, pos in axis.items()), key=lambda t: (t[0], t[1])
    )
    best = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else float("inf")
    return best[1], best[0], second


def _margin(d1: float, d2: float) -> float:
    if d2 == float("inf"):
        return 1.0
    return (d2 - d1) / d2 if d2 > 0 else 0.0


def _letter_rank(text: str) -> float:
    """A..Z -> 1..26, then AA, BB, ... -> 27.. : monotonic along an axis in either style."""
    return float(26 * (len(text) - 1) + ord(text[-1]) - 64)


def _lis(values: list[float]) -> int:
    """Length of the longest strictly increasing subsequence."""
    tails: list[float] = []
    for v in values:
        i = bisect.bisect_left(tails, v)
        if i == len(tails):
            tails.append(v)
        else:
            tails[i] = v
    return len(tails)


def _monotonic_length(values: list[float]) -> int:
    return max(_lis(values), _lis([-v for v in values]))


def _pick_axis(
    labels: list[tuple[Word, float]], across: bool, align_tol: float, word_h: float
) -> tuple[list[tuple[Word, float]], tuple[int, int, int]]:
    """Choose the best line of labels. `across` is True for a horizontal axis (numbers).

    A line is a cluster of labels sharing one y (numbers) or one x (letters). Score: how many have
    a mirrored twin on the opposite edge, then the longest monotonic run, then the plain count.
    """
    coords = [w.y0 if across else w.x0 for w, _ in labels]
    groups = [[labels[i] for i in g] for g in cluster_1d(coords, align_tol)]
    best_score: tuple[int, int, int] | None = None
    best: list[tuple[Word, float]] = []
    for members in groups:
        ordered = sorted(members, key=lambda t: t[0].cx if across else t[0].cy)
        mono = _monotonic_length([v for _, v in ordered])
        mirrored = 0
        for w, v in members:
            for w2, v2 in labels:
                if v2 != v or w2 is w:
                    continue
                gap = (w2.y0 - w.y0) if across else (w2.x0 - w.x0)
                off = (w2.cx - w.cx) if across else (w2.cy - w.cy)
                if (
                    abs(gap) >= MIRROR_WORD_HEIGHTS * word_h
                    and abs(off) <= ALIGN_WORD_HEIGHTS * word_h
                ):
                    mirrored += 1
                    break
        score = (mirrored, mono, len(members))
        if best_score is None or score > best_score:
            best_score, best = score, members
    return best, best_score or (0, 0, 0)


def _axis_dict(axis: list[tuple[Word, float]], along_x: bool, as_number: bool) -> dict[str, float]:
    out: dict[str, float] = {}
    for w, _ in sorted(axis, key=lambda t: t[0].cx if along_x else t[0].cy):
        key = f"{float(w.text):g}" if as_number else w.text
        out.setdefault(key, round(w.cx if along_x else w.cy, 2))
    return out


def fit_grid(words: list[Word], config: Config = DEFAULT_CONFIG) -> Grid | None:
    """Rows from letters, columns from small numbers; the orientation is detected per sheet.

    Both conventions are tried (letters down an edge / letters along an edge) and the one whose
    labels are better structured (mirrored on the opposite edge, monotonic, numerous) wins.
    Returns None when fewer than config.grid_min_labels of either kind form an axis.
    """
    letter_re = re.compile(config.grid_letter_pattern)
    number_re = re.compile(config.grid_number_pattern)
    letters = [(w, _letter_rank(w.text)) for w in words if letter_re.match(w.text)]
    numbers = [(w, float(w.text)) for w in words if number_re.match(w.text)]
    if len(letters) < config.grid_min_labels or len(numbers) < config.grid_min_labels:
        return None
    word_h = median_word_height(words)
    tol = max(0.5, config.grid_align_word_heights * word_h)
    best: tuple[tuple[int, int, int], Grid] | None = None
    for letters_on in ("y", "x"):
        # letters_on="y": letters share an x (a vertical line) and vary in y; numbers the reverse
        l_axis, l_score = _pick_axis(
            letters, across=(letters_on == "x"), align_tol=tol, word_h=word_h
        )
        n_axis, n_score = _pick_axis(
            numbers, across=(letters_on == "y"), align_tol=tol, word_h=word_h
        )
        rows = _axis_dict(l_axis, along_x=(letters_on == "x"), as_number=False)
        cols = _axis_dict(n_axis, along_x=(letters_on == "y"), as_number=True)
        if len(rows) < config.grid_min_labels or len(cols) < config.grid_min_labels:
            continue
        score = tuple(a + b for a, b in zip(l_score, n_score, strict=True))
        if best is None or score > best[0]:
            best = (score, Grid(rows=rows, cols=cols, letters_on=letters_on))
    return best[1] if best else None
