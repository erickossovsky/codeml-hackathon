"""Group words into text blocks, find the frame drawn around a block and the symbol it points at.

Sizes are multiples of the page's own text height `h`; nothing is fixed in points.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from l2c.extract.runs import Run, median_word_height, text_runs
from l2c.free.vectors import Box, Seg, Vectors
from l2c.ingest.pages import Word

LINE_GAP_H = 0.9  # vertical gap between two lines of one block, in text heights
ALIGN_H = 2.0  # left edges of one block's lines agree within this many text heights
FRAME_PAD_H = 1.6  # a frame edge lies this close to its text
LEADER_TOL_H = 0.8  # a leader ends this close to the frame edge
SYMBOL_REACH_H = 1.5  # a leader ends this close to the symbol it points at
PROXIMITY_REACH_H = 14.0  # without a leader, a symbol this near may still be the target
MAX_FRAME_H = 12.0  # taller or wider than this many text heights is not a callout frame


@dataclass
class Block:
    runs: list[Run]
    frame: Box | None = None
    frame_color: tuple | None = None
    symbol: Box | None = None
    binding: str = "none"  # leader | proximity | none
    leader: list[Seg] = field(default_factory=list)

    @property
    def text_bbox(self) -> Box:
        return Box(
            min(r.x0 for r in self.runs),
            min(r.y0 for r in self.runs),
            max(r.x1 for r in self.runs),
            max(r.y1 for r in self.runs),
        )

    @property
    def bbox(self) -> Box:
        return self.frame or self.text_bbox

    @property
    def lines(self) -> list[str]:
        return [r.text for r in sorted(self.runs, key=lambda r: (r.y0, r.x0))]


def text_height(words: list[Word]) -> float:
    return median_word_height(words)


def _is_label(word: Word) -> bool:
    t = word.text.strip()
    return len(t) >= 3 and t.endswith(":") and any(c.isalpha() for c in t)


def split_label_runs(runs: list[Run]) -> list[Run]:
    """A printed run holds one statement. When two statements sit side by side close enough to join
    (`LONG: 9 20M ... LONG: 9 20M ...` for two neighbouring groups), split before the second label."""
    out: list[Run] = []
    for r in runs:
        group: list[Word] = []
        for w in r.words:
            if group and _is_label(w) and any(_is_label(g) for g in group):
                out.append(_run_of(group))
                group = []
            group.append(w)
        if group:
            out.append(_run_of(group))
    return out


def _run_of(words: list[Word]) -> Run:
    return Run(
        " ".join(w.text for w in words),
        min(w.x0 for w in words),
        min(w.y0 for w in words),
        max(w.x1 for w in words),
        max(w.y1 for w in words),
        tuple(words),
    )


def make_blocks(words: list[Word], h: float) -> list[Block]:
    runs = split_label_runs(text_runs(words, gap=1.6 * h))
    parent = list(range(len(runs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(runs)), key=lambda i: runs[i].y0)
    for a_pos, i in enumerate(order):
        a = runs[i]
        for j in order[a_pos + 1 :]:
            b = runs[j]
            if b.y0 - a.y0 > 4 * h:
                break
            if b.y0 - a.y1 > LINE_GAP_H * h or b.y0 - a.y0 < 0.5 * h:
                continue
            if abs(a.x0 - b.x0) <= ALIGN_H * h:
                parent[find(j)] = find(i)
    groups: dict[int, list[Run]] = defaultdict(list)
    for i, r in enumerate(runs):
        groups[find(i)].append(r)
    return [Block(sorted(g, key=lambda r: (r.y0, r.x0))) for g in groups.values()]


class _Sorted:
    """Axis-aligned segments sorted by their position, so the segments near a text block are a small
    slice found by binary search instead of a scan of every line on the page. The sort is stable, so
    among segments at equal positions the first in page order still wins."""

    def __init__(self, segs: list[Seg], horizontal: bool, colors: dict) -> None:
        self.segs = segs
        if not segs:
            self.pos = np.zeros(0)
            self.a = self.b = np.zeros(0)
            self.cid = np.zeros(0, dtype=int)
            self.order = np.zeros(0, dtype=int)
            return
        cid = np.array([colors.setdefault(s.color, len(colors)) for s in segs])
        if horizontal:
            pos = np.array([s.y0 for s in segs])
            lo = np.array([s.x0 for s in segs])
            hi = np.array([s.x1 for s in segs])
        else:
            pos = np.array([s.x0 for s in segs])
            lo = np.array([s.y0 for s in segs])
            hi = np.array([s.y1 for s in segs])
        order = np.argsort(pos, kind="stable")
        self.order, self.pos, self.a, self.b, self.cid = (
            order,
            pos[order],
            lo[order],
            hi[order],
            cid[order],
        )

    def candidates(
        self, lo: float, hi: float, c_lo: float, c_hi: float
    ) -> tuple[np.ndarray, np.ndarray]:
        """(indices into the sorted arrays, colour ids) of segments positioned in [lo, hi] that span [c_lo, c_hi]."""
        if not len(self.pos):
            return np.zeros(0, dtype=int), np.zeros(0, dtype=int)
        i0 = int(np.searchsorted(self.pos, lo, side="left"))
        i1 = int(np.searchsorted(self.pos, hi, side="right"))
        idx = np.arange(i0, i1)
        keep = (self.a[idx] <= c_hi) & (self.b[idx] >= c_lo)
        idx = idx[keep]
        return idx, self.cid[idx]

    def pick(self, idx: np.ndarray, cids: np.ndarray, color: int, pick_max: bool):
        sel = idx[cids == color]
        if not len(sel):
            return None
        k = sel[np.argmax(self.pos[sel])] if pick_max else sel[np.argmin(self.pos[sel])]
        return self.segs[int(self.order[k])]


def attach_frames(blocks: list[Block], vec: Vectors, h: float) -> list[Block]:
    """A block with drawn edges on at least three sides sits in a frame. The edges are separate
    line segments (a frame is rarely one rectangle object), so they are searched around the text.
    Blocks that share one frame merge into one."""
    colors: dict = {}
    hs, vs = _Sorted(vec.hlines, True, colors), _Sorted(vec.vlines, False, colors)
    pad = FRAME_PAD_H * h
    by_frame: dict[tuple, Block] = {}
    out: list[Block] = []
    for b in blocks:
        t = b.text_bbox
        # bottom/top edges must span the middle half of the text; side edges likewise
        mx0, mx1 = t.x0 + 0.25 * t.w, t.x1 - 0.25 * t.w
        my0, my1 = t.y0 + 0.25 * t.h, t.y1 - 0.25 * t.h
        top_c = hs.candidates(t.y0 - pad, t.y0 + 0.3 * h, mx0, mx1)
        bot_c = hs.candidates(t.y1 - 0.3 * h, t.y1 + pad, mx0, mx1)
        left_c = vs.candidates(t.x0 - pad, t.x0 + 0.3 * h, my0, my1)
        right_c = vs.candidates(t.x1 - 0.3 * h, t.x1 + pad, my0, my1)
        present = sorted({int(c) for part in (top_c, bot_c, left_c, right_c) for c in part[1]})
        best = None
        for cid in present:
            cand = (
                hs.pick(*top_c, cid, True),
                hs.pick(*bot_c, cid, False),
                vs.pick(*left_c, cid, True),
                vs.pick(*right_c, cid, False),
            )
            n = sum(c is not None for c in cand)
            if n >= 3 and (best is None or n > best[0]):
                best = (n, cand)
        top, bottom, left, right = best[1] if best else (None, None, None, None)
        sides = [s for s in (top, bottom, left, right) if s is not None]
        if len(sides) < 3:
            out.append(b)
            continue
        x0 = left.x0 if left else t.x0 - 0.3 * h
        x1 = right.x0 if right else t.x1 + 0.3 * h
        y0 = top.y0 if top else t.y0 - 0.3 * h
        y1 = bottom.y0 if bottom else t.y1 + 0.3 * h
        frame = Box(x0, y0, x1, y1)
        if (
            frame.w > MAX_FRAME_H * 8 * h
            or frame.h > MAX_FRAME_H * h
            or not _closed(frame, top, bottom, left, right, h)
        ):
            out.append(b)
            continue
        key = tuple(round(v, 1) for v in (x0, y0, x1, y1))
        side_colors = [s.color for s in sides if s.color is not None]
        color = max(set(side_colors), key=side_colors.count) if side_colors else None
        if key in by_frame:
            by_frame[key].runs.extend(b.runs)
        else:
            nb = Block(list(b.runs), frame=frame, frame_color=color)
            by_frame[key] = nb
            out.append(nb)
    for nb in by_frame.values():
        nb.runs.sort(key=lambda r: (r.y0, r.x0))
    return out


def _closed(f: Box, top, bottom, left, right, h: float) -> bool:
    """Real frame edges meet at the corners and stop there; a bar line that merely passes the text
    runs on far beyond it."""
    slack = 0.8 * h
    for seg, horizontal in ((top, True), (bottom, True), (left, False), (right, False)):
        if seg is None:
            continue
        if horizontal:
            if seg.x0 < f.x0 - slack or seg.x1 > f.x1 + slack or seg.x1 - seg.x0 < 0.6 * f.w:
                return False
        else:
            if seg.y0 < f.y0 - slack or seg.y1 > f.y1 + slack or seg.y1 - seg.y0 < 0.6 * f.h:
                return False
    return True


class _EndIndex:
    def __init__(self, lines: list[Seg], cell: float) -> None:
        self.cell = cell
        self.by_cell: dict[tuple[int, int], list[tuple[Seg, int]]] = defaultdict(list)
        for s in lines:
            self.by_cell[self._key(s.x0, s.y0)].append((s, 0))
            self.by_cell[self._key(s.x1, s.y1)].append((s, 1))

    def _key(self, x: float, y: float) -> tuple[int, int]:
        return int(x // self.cell), int(y // self.cell)

    def near(self, x: float, y: float, tol: float) -> list[tuple[Seg, int]]:
        kx, ky = self._key(x, y)
        out = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for s, end in self.by_cell.get((kx + dx, ky + dy), []):
                    px, py = (s.x0, s.y0) if end == 0 else (s.x1, s.y1)
                    if abs(px - x) <= tol and abs(py - y) <= tol:
                        out.append((s, end))
        return out

    def in_rect(self, r: Box, pad: float) -> list[tuple[Seg, int]]:
        out = []
        kx0, ky0 = self._key(r.x0 - pad, r.y0 - pad)
        kx1, ky1 = self._key(r.x1 + pad, r.y1 + pad)
        for kx in range(kx0, kx1 + 1):
            for ky in range(ky0, ky1 + 1):
                out.extend(self.by_cell.get((kx, ky), []))
        return out


def _end(s: Seg, end: int) -> tuple[float, float]:
    return (s.x0, s.y0) if end == 0 else (s.x1, s.y1)


def _perimeter_dist(f: Box, x: float, y: float) -> float:
    """Distance from a point to the frame border (0 on the border, positive off it either side)."""
    dx = max(f.x0 - x, 0.0, x - f.x1)
    dy = max(f.y0 - y, 0.0, y - f.y1)
    if dx or dy:
        return (dx * dx + dy * dy) ** 0.5  # outside
    return min(x - f.x0, f.x1 - x, y - f.y0, f.y1 - y)  # inside


def bind_symbols(blocks: list[Block], vec: Vectors, h: float) -> None:
    """Find the solid symbol each framed block points at: through a leader line when one starts at
    the frame (same stroke colour as the frame), else by proximity (the weaker, flagged binding)."""
    idx = _EndIndex(vec.lines, cell=max(8.0, 3 * h))
    tol = LEADER_TOL_H * h
    reach = SYMBOL_REACH_H * h
    for b in blocks:
        f = b.frame
        if f is None:
            continue
        best = None
        for seg, end in idx.in_rect(f, tol):
            if b.frame_color is not None and seg.color != b.frame_color:
                continue
            px, py = _end(seg, end)
            ox, oy = _end(seg, 1 - end)
            if _perimeter_dist(f, px, py) > tol or _perimeter_dist(f, ox, oy) <= tol:
                continue  # not leaving the frame border
            if f.contains(ox, oy):
                continue
            chain = [seg]
            ex, ey = ox, oy
            for _ in range(4):  # a leader may bend: follow connected segments
                if _hit(vec.solids, ex, ey, reach) is not None:
                    break
                nxt = [
                    (s, e)
                    for s, e in idx.near(ex, ey, tol)
                    if s not in chain and (b.frame_color is None or s.color == b.frame_color)
                ]
                if not nxt:
                    break
                s, e = nxt[0]
                chain.append(s)
                ex, ey = _end(s, 1 - e)
            sym = _hit(vec.solids, ex, ey, reach)
            if sym is not None and not f.contains(sym.cx, sym.cy):
                length = sum(c.length for c in chain)
                if best is None or length < best[0]:
                    best = (length, sym, chain)
        if best is not None:
            b.symbol, b.leader, b.binding = best[1], best[2], "leader"
    for b in blocks:
        if b.frame is None or b.symbol is not None:
            continue
        cands = [
            (_gap(b.frame, s), s)
            for s in vec.solids
            if _gap(b.frame, s) <= PROXIMITY_REACH_H * h and not b.frame.contains(s.cx, s.cy)
        ]
        if cands:
            cands.sort(key=lambda t: (t[0], t[1].cy, t[1].cx))
            b.symbol, b.binding = cands[0][1], "proximity"


def _hit(solids: list[Box], x: float, y: float, tol: float) -> Box | None:
    hits = [s for s in solids if s.contains(x, y, tol)]
    return min(hits, key=lambda s: s.w * s.h) if hits else None


def _gap(a: Box, b: Box) -> float:
    dx = max(0.0, a.x0 - b.x1, b.x0 - a.x1)
    dy = max(0.0, a.y0 - b.y1, b.y0 - a.y1)
    return (dx * dx + dy * dy) ** 0.5
