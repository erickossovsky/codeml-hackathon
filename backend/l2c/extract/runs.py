"""Group words into lines and text runs (words that belong to one printed phrase)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from l2c.ingest.pages import Word

DEFAULT_WORD_H = 8.0
LINE_TOL_WORD_HEIGHTS = 0.375  # baseline jitter allowed within one text line


def median_word_height(words: list[Word]) -> float:
    heights = [w.y1 - w.y0 for w in words if len(w.text) >= 2 and w.y1 > w.y0]
    return statistics.median(heights) if heights else DEFAULT_WORD_H


@dataclass(frozen=True)
class Run:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    words: tuple[Word, ...]

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def text_runs(
    words: list[Word],
    gap: float = 12.0,
    line_tol: float | None = None,
    split_before: tuple[str, ...] = (),
) -> list[Run]:
    """Words on the same baseline, split where the horizontal gap exceeds `gap` points.

    `split_before` lists keywords (upper case); a word starting with one of them begins a new
    run even when it follows closely, so two annotation blocks that nearly touch stay separate.
    """
    if line_tol is None:  # words on one baseline differ by a fraction of their own height
        line_tol = LINE_TOL_WORD_HEIGHTS * median_word_height(words)
    ordered = sorted(words, key=lambda w: (w.y0, w.x0))
    lines: list[list[Word]] = []
    for w in ordered:
        if lines and abs(w.y0 - lines[-1][0].y0) <= line_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    runs: list[Run] = []
    for line in lines:
        line.sort(key=lambda w: w.x0)
        group: list[Word] = [line[0]]
        for w in line[1:]:
            starts_keyword = bool(split_before) and w.text.upper().startswith(split_before)
            if w.x0 - group[-1].x1 > gap or starts_keyword:
                runs.append(_make(group))
                group = [w]
            else:
                group.append(w)
        runs.append(_make(group))
    runs.sort(key=lambda r: (round(r.y0, 1), r.x0))
    return runs


def _make(group: list[Word]) -> Run:
    return Run(
        text=" ".join(w.text for w in group),
        x0=min(w.x0 for w in group),
        y0=min(w.y0 for w in group),
        x1=max(w.x1 for w in group),
        y1=max(w.y1 for w in group),
        words=tuple(group),
    )


def cluster_1d(values: list[float], tol: float) -> list[list[int]]:
    """Indices grouped by position: a new group starts where the gap to the previous value
    exceeds `tol` (single linkage, so it does not depend on where bucket edges happen to fall)."""
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    groups: list[list[int]] = []
    for i in order:
        if groups and values[i] - values[groups[-1][-1]] <= tol:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups
