"""Split a plan page that holds several drawings into one page per drawing.

A sheet can print several plans, each with its own grid (for example `PLAN FONDATION - RADIER #1`
to `#5`). Fitting one grid to the whole sheet loses the others, so each drawing is read with its
own grid. A word belongs to the nearest title below it (drawings sit above their titles), or to the nearest
title when none is below. A page without two or more
numbered titles is returned unchanged.
"""

from __future__ import annotations

import dataclasses

from l2c.ingest.pages import PageData, Word

TITLE_WORD = "PLAN"
NUMBER_MARK = "#"
TITLE_REACH_PT = 900.0  # how far right of "PLAN" the "#n" of the same title may sit


def _title_anchors(words: list[Word]) -> list[tuple[float, float]]:
    anchors = []
    for w in words:
        if w.text.upper() != TITLE_WORD:
            continue
        same_line = [
            v
            for v in words
            if abs(v.cy - w.cy) < 1.5 * (w.y1 - w.y0) and 0 < v.x0 - w.x1 <= TITLE_REACH_PT
        ]
        if any(NUMBER_MARK in v.text for v in same_line):
            anchors.append((w.cx, w.cy))
    return anchors


def drawing_regions(page: PageData) -> list[PageData]:
    anchors = _title_anchors(page.words)
    # one title can be matched twice (a word of its line may start with "PLAN"); keep distinct spots
    distinct: list[tuple[float, float]] = []
    for a in anchors:
        if all(abs(a[0] - b[0]) + abs(a[1] - b[1]) > 5 for b in distinct):
            distinct.append(a)
    if len(distinct) < 2:
        return [page]

    def nearest(x: float, y: float) -> int:
        # drawings sit above their title: prefer the nearest title below the point
        below = [i for i in range(len(distinct)) if distinct[i][1] >= y]
        pool = below or range(len(distinct))
        return min(pool, key=lambda i: (distinct[i][0] - x) ** 2 + (distinct[i][1] - y) ** 2)

    words: list[list[Word]] = [[] for _ in distinct]
    for w in page.words:
        words[nearest(w.cx, w.cy)].append(w)
    boxes: list[list] = [[] for _ in distinct]
    for b in page.boxes:
        boxes[nearest((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)].append(b)
    return [
        dataclasses.replace(page, words=ws, boxes=bs, shapes=[])
        for ws, bs in zip(words, boxes, strict=True)
        if ws
    ]
