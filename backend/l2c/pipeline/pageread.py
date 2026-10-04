"""Read one page exactly once: words, page facts and vector primitives.

The older loader (`ingest.pages.load_pdf`) also builds candidate outlines, boxes and bar lines that
this pipeline never uses, and reads every page of a file even when one is wanted. This reader does
the minimum and shares the single `get_cdrawings()` call with the vector step.
"""

from __future__ import annotations

import numpy as np
import pymupdf

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.free.vectors import Vectors, vectors_from_drawings
from l2c.ingest.pages import (
    PageData,
    Word,
    classify_layer,
    title_block_sheet,
    vertical_text_fraction,
)


def native_words(page: pymupdf.Page) -> list[Word]:
    raw = page.get_text("words")
    if not raw:
        return []
    m = page.rotation_matrix
    r = np.array([w[:4] for w in raw], dtype=float)
    pts = np.stack([r[:, [0, 1]], r[:, [2, 1]], r[:, [2, 3]], r[:, [0, 3]]], axis=1)
    x = m.a * pts[:, :, 0] + m.c * pts[:, :, 1] + m.e
    y = m.b * pts[:, :, 0] + m.d * pts[:, :, 1] + m.f
    box = np.stack([x.min(axis=1), y.min(axis=1), x.max(axis=1), y.max(axis=1)], axis=1).tolist()
    words = [Word(w[4], b[0], b[1], b[2], b[3]) for w, b in zip(raw, box, strict=True)]
    words.sort(key=lambda w: (round(w.y0, 1), w.x0, w.text))
    return words


def read_page(
    page: pymupdf.Page,
    rel: str,
    number: int,
    config: Config = DEFAULT_CONFIG,
    words: list[Word] | None = None,
    source: str = "native",
) -> tuple[PageData, Vectors]:
    """(page data, vectors). `words` replaces the native words (OCR text)."""
    drawings = page.get_cdrawings()
    vec = vectors_from_drawings(drawings, page.rotation_matrix)
    use = native_words(page) if words is None else words
    n_images = len(page.get_images())
    data = PageData(
        fichier=rel,
        page=number,
        width=page.rect.width,
        height=page.rect.height,
        rotation=page.rotation,
        words=use,
        n_paths=len(drawings),
        n_images=n_images,
        layer=classify_layer(len(use), len(drawings), n_images, config),
        feuillet=title_block_sheet(use, page.rect.width, page.rect.height, config),
        vertical_text=round(vertical_text_fraction(use), 3),
        source=source,
    )
    return data, vec


def word_count(page: pymupdf.Page) -> int:
    return len(page.get_text("words"))


def layer_of(page: pymupdf.Page, vec_paths: int, config: Config = DEFAULT_CONFIG) -> str:
    """The layer a page has before OCR (no words): image, vector or empty."""
    return classify_layer(0, vec_paths, len(page.get_images()), config)


def read_text_page(
    page: pymupdf.Page,
    rel: str,
    number: int,
    config: Config = DEFAULT_CONFIG,
    words: list[Word] | None = None,
    source: str = "native",
) -> PageData:
    """Words and page facts only: no drawing data is read."""
    use = native_words(page) if words is None else words
    n_images = len(page.get_images())
    layer = "text" if len(use) >= config.min_text_words else ("image" if n_images else "empty")
    return PageData(
        fichier=rel,
        page=number,
        width=page.rect.width,
        height=page.rect.height,
        rotation=page.rotation,
        words=use,
        n_images=n_images,
        layer=layer,
        feuillet=title_block_sheet(use, page.rect.width, page.rect.height, config),
        vertical_text=round(vertical_text_fraction(use), 3),
        source=source,
    )


RASTER_SHARE_MIN = (
    0.3  # a page whose images cover this share of its area has content the text layer cannot hold
)


def raster_share(page: pymupdf.Page) -> float:
    """Share of the page covered by embedded images large enough to carry drawing content."""
    area = page.rect.width * page.rect.height
    covered = 0.0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        w, h = min(x1, page.rect.width) - max(x0, 0), min(y1, page.rect.height) - max(y0, 0)
        if w > 100 and h > 100:  # stamps and logos are small
            covered += w * h
    return min(1.0, covered / area) if area else 0.0


def merge_ocr_words(native: list[Word], ocr: list[Word]) -> list[Word]:
    """Native words plus the OCR words that add something: an OCR word whose centre lies inside a
    native word is the same text read twice and is dropped."""
    if not native:
        return ocr
    boxes = np.array([[w.x0, w.y0, w.x1, w.y1] for w in native])
    extra = []
    for w in ocr:
        inside = (
            (boxes[:, 0] - 2 <= w.cx)
            & (w.cx <= boxes[:, 2] + 2)
            & (boxes[:, 1] - 2 <= w.cy)
            & (w.cy <= boxes[:, 3] + 2)
        ).any()
        if not inside:
            extra.append(w)
    return sorted([*native, *extra], key=lambda w: (round(w.y0, 1), w.x0, w.text))
