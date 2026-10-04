"""Read a PDF into plain page data: words, small closed shapes, layer kind, sheet id.

All coordinates are in PDF points of the page *as displayed* (rotation applied once here),
origin top-left, y downward. Every other module works in this frame.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from l2c.extract.config import DEFAULT_CONFIG, Config

# Candidate column outlines are small shapes: between these shares of the page width. The exact
# size is then learned per sheet (anchor.find_outlines), so no fixed point size is assumed.
SHAPE_MIN_PAGE_FRACTION = 0.001
SHAPE_MAX_PAGE_FRACTION = 0.05
MAX_SHAPE_PATH_ITEMS = 8  # a closed rectangle-like path has only a few segments


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float | None = None  # OCR confidence 0..1; None for native text
    original: str | None = None  # text before vocabulary snapping, when it was changed

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class Shape:
    """Bounding box of a small closed vector shape (candidate column outline)."""

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


@dataclass
class PageData:
    fichier: str
    page: int  # 1-based
    width: float
    height: float
    rotation: int
    words: list[Word] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    n_paths: int = 0
    n_images: int = 0
    layer: str = "empty"  # text | vector | image | empty
    feuillet: str | None = None
    vertical_text: float = 0.0  # share of words that are taller than wide (rotated text)
    source: str = "native"  # native | ocr


def classify_layer(
    n_words: int, n_paths: int, n_images: int, config: Config = DEFAULT_CONFIG
) -> str:
    if n_words >= config.min_text_words:
        return "text"
    if n_images > 0 and n_paths < 10 * config.min_vector_paths:
        return "image"
    if n_paths >= config.min_vector_paths:
        return "vector"
    return "empty"


def vertical_text_fraction(words: list[Word]) -> float:
    long = [w for w in words if len(w.text) >= 3]
    if not long:
        return 0.0
    return sum(1 for w in long if (w.y1 - w.y0) > 1.5 * (w.x1 - w.x0)) / len(long)


def title_block_sheet(
    words: list[Word], width: float, height: float, config: Config = DEFAULT_CONFIG
) -> str | None:
    """Sheet id from the title block (pattern in config): the bottom-most, right-most match."""
    sheet_re = re.compile(config.sheet_id_pattern)
    hits = [
        w for w in words if sheet_re.match(w.text) and w.x0 > 0.6 * width and w.y0 > 0.7 * height
    ]
    if not hits:
        return None
    return max(hits, key=lambda w: (round(w.y0), w.x0)).text


def _rect_through(matrix: pymupdf.Matrix, r: pymupdf.Rect) -> pymupdf.Rect:
    out = pymupdf.Rect(r) * matrix
    out.normalize()
    return out


def _read_page(page: pymupdf.Page, fichier: str, number: int, config: Config) -> PageData:
    m = page.rotation_matrix
    words = []
    for w in page.get_text("words"):
        r = _rect_through(m, pymupdf.Rect(w[:4]))
        words.append(Word(w[4], r.x0, r.y0, r.x1, r.y1))
    words.sort(key=lambda w: (round(w.y0, 1), w.x0, w.text))
    # raw drawing records (plain tuples): the object-building variant is about 6x slower on the
    # large vector sheets, and only each path's bounding box and segment count are needed here
    drawings = page.get_cdrawings()
    lo = SHAPE_MIN_PAGE_FRACTION * page.rect.width
    hi = SHAPE_MAX_PAGE_FRACTION * page.rect.width
    shapes: list[Shape] = []
    for d in drawings:
        x0, y0, x1, y1 = d["rect"]
        if lo <= x1 - x0 <= hi and lo <= y1 - y0 <= hi and len(d["items"]) <= MAX_SHAPE_PATH_ITEMS:
            t = _rect_through(m, pymupdf.Rect(x0, y0, x1, y1))
            shapes.append(Shape(t.x0, t.y0, t.x1, t.y1))
    shapes.sort(key=lambda s: (round(s.cy, 1), s.cx))
    n_images = len(page.get_images())
    return PageData(
        fichier=fichier,
        page=number,
        width=page.rect.width,
        height=page.rect.height,
        rotation=page.rotation,
        words=words,
        shapes=shapes,
        n_paths=len(drawings),
        n_images=n_images,
        layer=classify_layer(len(words), len(drawings), n_images, config),
        feuillet=title_block_sheet(words, page.rect.width, page.rect.height, config),
        vertical_text=round(vertical_text_fraction(words), 3),
    )


def _load_page_task(args: tuple[Path, str, int, Config]) -> PageData:
    path, name, index, config = args
    with pymupdf.open(path) as doc:
        return _read_page(doc[index], name, index + 1, config)


def load_pdf(
    path: Path, fichier: str | None = None, config: Config = DEFAULT_CONFIG, pool=None
) -> list[PageData]:
    """Every page of a PDF. With a process pool the pages are read in parallel (same result,
    same order); a file that cannot be opened raises either way."""
    name = fichier or path.name
    with pymupdf.open(path) as doc:
        count = len(doc)
        if pool is None or count < 2:
            return [_read_page(p, name, i + 1, config) for i, p in enumerate(doc)]
    return list(pool.map(_load_page_task, [(path, name, i, config) for i in range(count)]))
