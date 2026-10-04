"""Drawing items of a page: filled symbols, outlines and connected linework.

Vector pages are read from the PDF drawing commands. A page with no usable vector content (a scan or
an embedded image) is segmented from its pixels with OpenCV. Both give the same item shape, so
later steps do not care which method produced a drawing.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pymupdf

from l2c.free.vectors import Seg, Vectors

MIN_LINEWORK_H = 6.0  # total line length of a linework item, in text heights
MAX_PAGE_SHARE = 0.6  # an item wider or taller than this share of the page is a frame or grid
MAX_LINEWORK_ITEMS = 700
MAX_RASTER_ITEMS = 700
SNAP = 1.0  # endpoints closer than this (points) are one joint
RASTER_DPI = 100


def _bbox(segs: list[Seg]) -> list[float]:
    xs = [v for s in segs for v in (s.x0, s.x1)]
    ys = [v for s in segs for v in (s.y0, s.y1)]
    return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]


def _color(c) -> str | None:
    return None if c is None else "#" + "".join(f"{int(round(v * 255)):02x}" for v in c[:3])


def vector_drawings(vec: Vectors, h: float, page_w: float, page_h: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in vec.solids:
        out.append(
            {
                "shape": "solid",
                "bbox": [round(b.x0, 2), round(b.y0, 2), round(b.x1, 2), round(b.y1, 2)],
                "size_pt": [round(b.w, 1), round(b.h, 1)],
                "method": "vector",
            }
        )
    for b in vec.frames:
        if b.w >= MAX_PAGE_SHARE * page_w or b.h >= MAX_PAGE_SHARE * page_h:
            continue
        out.append(
            {
                "shape": "outline",
                "bbox": [round(b.x0, 2), round(b.y0, 2), round(b.x1, 2), round(b.y1, 2)],
                "size_pt": [round(b.w, 1), round(b.h, 1)],
                "method": "vector",
            }
        )
    out.extend(_linework(vec.lines, h, page_w, page_h))
    return out


def _linework(lines: list[Seg], h: float, page_w: float, page_h: float) -> list[dict[str, Any]]:
    """Connected groups of line segments (walls, bars, rails). Gridlines and sheet frames are dropped
    by size; short fragments (hatch ticks, dashes) by total length."""
    if not lines:
        return []
    parent = list(range(len(lines)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    joint: dict[tuple[int, int], int] = {}

    def key(x: float, y: float) -> tuple[int, int]:
        return int(round(x / SNAP)), int(round(y / SNAP))

    for i, s in enumerate(lines):
        for x, y in ((s.x0, s.y0), (s.x1, s.y1)):
            k = key(x, y)
            if k in joint:
                parent[find(i)] = find(joint[k])
            else:
                joint[k] = i
    groups: dict[int, list[Seg]] = defaultdict(list)
    for i, s in enumerate(lines):
        groups[find(i)].append(s)
    items = []
    for segs in groups.values():
        total = sum(s.length for s in segs)
        if total < MIN_LINEWORK_H * h:
            continue
        bb = _bbox(segs)
        w, ht = bb[2] - bb[0], bb[3] - bb[1]
        if w >= MAX_PAGE_SHARE * page_w or ht >= MAX_PAGE_SHARE * page_h:
            continue
        colors = [s.color for s in segs if s.color is not None]
        items.append(
            {
                "shape": "linework",
                "bbox": bb,
                "size_pt": [round(w, 1), round(ht, 1)],
                "n_segments": len(segs),
                "total_length_pt": round(total, 1),
                "stroke": _color(max(set(colors), key=colors.count)) if colors else None,
                "method": "vector",
            }
        )
    items.sort(key=lambda d: -d["total_length_pt"])
    return items[:MAX_LINEWORK_ITEMS]


def raster_drawings(page: pymupdf.Page, h: float) -> list[dict[str, Any]]:
    """Segment dark connected regions from the rendered page. Used when the page has no vector
    content. Coordinates are mapped back to the displayed frame in points."""
    import cv2

    zoom = RASTER_DPI / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = cv2.dilate(binary, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_px = MIN_LINEWORK_H * h * zoom / 2
    items = []
    for c in contours:
        x, y, w, ht = cv2.boundingRect(c)
        if (
            max(w, ht) < min_px
            or w >= MAX_PAGE_SHARE * pix.width
            or ht >= MAX_PAGE_SHARE * pix.height
        ):
            continue
        area = float(cv2.contourArea(c))
        items.append(
            {
                "shape": "region",
                "bbox": [
                    round(x / zoom, 2),
                    round(y / zoom, 2),
                    round((x + w) / zoom, 2),
                    round((y + ht) / zoom, 2),
                ],
                "size_pt": [round(w / zoom, 1), round(ht / zoom, 1)],
                "fill_ratio": round(area / max(1.0, w * ht), 3),
                "method": "raster",
            }
        )
    items.sort(key=lambda d: -(d["size_pt"][0] * d["size_pt"][1]))
    return items[:MAX_RASTER_ITEMS]
