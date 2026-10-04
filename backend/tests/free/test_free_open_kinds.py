"""An object type the reader has never heard of still becomes an element, on plan or shop."""

from pathlib import Path

import pymupdf

from l2c.free.reader import read_page
from l2c.ingest.pages import load_pdf


def _pdf(tmp_path: Path, title: str, lines: list[str]) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=600)
    page.insert_text((60, 540), title, fontsize=14)
    for i in range(12):  # enough words for the reader's minimum
        page.insert_text((60 + i * 40, 580), f"N{i}", fontsize=8)
    x0, y0, x1, y1 = 300, 200, 420, 260
    page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=0.8)
    for i, line in enumerate(lines):
        page.insert_text((x0 + 4, y0 + 12 + i * 11), line, fontsize=8)
    page.draw_line((x0, 230), (200, 230), color=(0, 0, 0), width=0.8)
    page.draw_rect(pymupdf.Rect(190, 222, 200, 238), color=(0, 0, 0), fill=(0, 0, 0))
    path = tmp_path / "t.pdf"
    doc.save(path)
    return path


def test_unknown_object_type_is_kept_with_its_own_words(tmp_path):
    pdf = _pdf(tmp_path, "PLAN NIVEAU 2", ["GARDE-CORPS 1100 HT.", "MAT.: ACIER", "ANCRAGE: 4-15M"])
    page = load_pdf(pdf, "t.pdf")[0]
    with pymupdf.open(pdf) as doc:
        elements, _ = read_page(page, doc[0], "plan")
    assert len(elements) == 1
    e = elements[0]
    assert e.kind == "garde-corps"  # not forced into a known type
    assert e.quality["kind_basis"] == ["own_text"]
    names = {c["name"] for c in e.characteristics}
    assert "mat" in names  # free-form label became a characteristic
    assert e.bars and e.bars[0]["size"] == "15M"
