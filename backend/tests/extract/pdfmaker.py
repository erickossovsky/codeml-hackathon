"""Build small synthetic PDFs for tests. No real drawing data is ever used in tests."""

from pathlib import Path

import pymupdf


def new_doc(width: float = 1200, height: float = 900):
    doc = pymupdf.open()
    return doc, doc.new_page(width=width, height=height)


def put(page, x: float, y: float, text: str, size: float = 8.0) -> None:
    """Insert text with its top-left near (x, y)."""
    page.insert_text((x, y + size), text, fontsize=size, fontname="helv")


def rect(page, cx: float, cy: float, w: float = 12.0, h: float = 18.0) -> None:
    page.draw_rect(pymupdf.Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), color=(0, 0, 0))


def save(doc, path: Path) -> Path:
    doc.save(path)
    doc.close()
    return path


class DisplayPage:
    """Draw in *displayed* coordinates on a page whose /Rotate may be 0, 90, 180 or 270.

    Real sheets are often stored rotated; content is drawn so that it looks upright once the
    viewer applies the rotation. This maps displayed coordinates back to the stored page.
    """

    def __init__(self, width: float, height: float, rotation: int = 0):
        self.doc = pymupdf.open()
        stored_w, stored_h = (height, width) if rotation in (90, 270) else (width, height)
        self.page = self.doc.new_page(width=stored_w, height=stored_h)
        self.page.set_rotation(rotation)
        self.rotation = rotation
        self.inverse = ~self.page.rotation_matrix

    def _stored(self, x: float, y: float) -> pymupdf.Point:
        return pymupdf.Point(x, y) * self.inverse

    def put(self, x: float, y: float, text: str, size: float = 8.0) -> None:
        # baseline is size below the displayed top-left, as in `put`
        p = self._stored(x, y + size)
        self.page.insert_text(p, text, fontsize=size, fontname="helv", rotate=self.rotation)

    def rect(self, cx: float, cy: float, w: float = 12.0, h: float = 18.0) -> None:
        a = self._stored(cx - w / 2, cy - h / 2)
        b = self._stored(cx + w / 2, cy + h / 2)
        self.page.draw_rect(pymupdf.Rect(a, b).normalize(), color=(0, 0, 0))

    def save(self, path: Path) -> Path:
        self.doc.save(path)
        self.doc.close()
        return path


def rasterize(pdf: Path, out: Path, dpi: int = 150) -> Path:
    """Replace every page of `pdf` by a picture of it: same look, no text layer."""
    import pymupdf as mu

    src = mu.open(pdf)
    doc = mu.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi, colorspace=mu.csRGB, alpha=False)
        new = doc.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=pix)
    doc.save(out)
    return out
