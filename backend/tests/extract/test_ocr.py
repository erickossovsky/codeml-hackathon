import numpy as np
import pymupdf
import pytest

from l2c.extract.config import DEFAULT_CONFIG
from l2c.ingest import ocr
from l2c.ingest.pages import Word
from l2c.ingest.snap import snap_token

pytest.importorskip("rapidocr_onnxruntime")


def raster_pdf(tmp_path, lines, rotate=0, size=14):
    """A page that has NO text layer: the notation is an embedded picture."""
    src = pymupdf.open()
    p = src.new_page(width=700, height=400)
    for i, text in enumerate(lines):
        p.insert_text((30, 60 + 50 * i), text, fontsize=size * 2, fontname="helv")
    pix = p.get_pixmap(dpi=144)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    if rotate:  # the text now runs top to bottom (rotate=90) in a portrait page
        arr = np.ascontiguousarray(np.rot90(arr, -rotate // 90))
    img = pymupdf.Pixmap(pymupdf.csRGB, arr.shape[1], arr.shape[0], arr.tobytes(), False)
    doc = pymupdf.open()
    width, height = (400, 700) if rotate else (700, 400)
    page = doc.new_page(width=width, height=height)
    page.insert_image(page.rect, pixmap=img)
    path = tmp_path / f"raster_{rotate}.pdf"
    doc.save(path)
    return path


def test_snap_repairs_confusable_characters_only_when_the_result_is_valid():
    assert snap_token("25M") == ("25M", False)
    assert snap_token("2SM") == ("25M", True)
    assert snap_token("25N") == ("25M", True)
    assert snap_token("4-2SM") == ("4-25M", True)
    assert snap_token("4-26M") == ("4-26M", False)  # not a bar size: left alone
    assert snap_token("HELLO") == ("HELLO", False)


def test_to_tile_frame_inverts_the_rotation():
    tile = np.arange(6 * 4).reshape(4, 6)  # h=4, w=6
    for rotation in (90, 270):
        turned = np.rot90(tile, rotation // 90)
        for i, j in [(0, 0), (1, 2), (turned.shape[0] - 1, turned.shape[1] - 1)]:
            # continuous coordinates of the pixel centre
            x, y = ocr.to_tile_frame(j + 0.5, i + 0.5, rotation, 6, 4)
            assert tile[int(y), int(x)] == turned[i, j], (rotation, i, j)


def test_line_to_words_splits_in_reading_direction():
    ws = ocr.line_to_words((0, 0, 100, 10), "ARM.: 4-25M", 0.9, 0)
    assert [w[4] for w in ws] == ["ARM.:", "4-25M"] and ws[0][2] <= ws[1][0]
    up = ocr.line_to_words((0, 0, 10, 100), "A BB", 0.9, 270)
    assert up[0][3] > up[1][3]  # first word is lower on the page when text reads upward


def test_ocr_reads_an_image_only_page_with_positions_in_pdf_points(tmp_path):
    path = raster_pdf(tmp_path, ["ARM.: 4-25M", 'LIG.: 10M@6" c/c'])
    with pymupdf.open(path) as doc:
        assert doc[0].get_text("words") == []
    res = ocr.ocr_pdf_page(path, 1, DEFAULT_CONFIG)
    texts = " ".join(w.text for w in res.words)
    assert "4-25M" in texts and "10M@6" in texts
    arm = next(w for w in res.words if "4-25M" in w.text)  # OCR may drop the space after "ARM.:"
    assert 0 < arm.x0 < 400 and 30 < arm.y0 < 90  # near where it was drawn (points)
    assert res.mean_conf > 0.7 and res.orientations[0] == 0


def test_vertical_text_is_read_even_without_the_orientation_probe(tmp_path):
    # RapidOCR reads vertical lines itself, so the default policy needs no extra orientations
    path = raster_pdf(tmp_path, ["VERT: 4 25M B7-01", "ETRI: 6 10M T4X21"], rotate=90)
    res = ocr.ocr_pdf_page(path, 1, DEFAULT_CONFIG)
    assert res.orientations == (0,)
    assert any("25M" in w.text for w in res.words)


def test_orientation_probe_is_available_and_prefers_upright_when_all_read_equally(tmp_path):
    import dataclasses

    cfg = dataclasses.replace(DEFAULT_CONFIG, ocr_orientation_probe=True)
    path = raster_pdf(tmp_path, ["ARM.: 4-25M", "VERT: 4 25M B7-01"])
    res = ocr.ocr_pdf_page(path, 1, cfg)
    assert 0 in res.orientations and any("25M" in w.text for w in res.words)


def test_pages_with_a_text_layer_are_not_ocrd(tmp_path):
    from tests.extract.pdfmaker import new_doc, put, save

    doc, page = new_doc()
    for i in range(20):
        put(page, 50, 50 + 20 * i, f"ARM.: 4-25M {i}")
    path = save(doc, tmp_path / "native.pdf")
    (p,) = ocr.load_with_ocr(path, "native.pdf")
    assert p.source == "native"


def test_word_defaults_keep_native_text_unchanged():
    w = Word("x", 0, 0, 1, 1)
    assert w.conf is None and w.original is None


def shop_sheet(tmp_path, scale=2.0):
    from tests.extract.pdfmaker import DisplayPage

    s = scale
    dp = DisplayPage(1200 * s, 900 * s)
    fs = 8.0 * s
    for y, el, name in [
        (100, "118' - 4\"", "NIVEAU 4"),
        (300, "108' - 6\"", "NIVEAU 3"),
        (500, "98' - 9\"", "NIVEAU 2"),
    ]:
        dp.put(60 * s, y * s, f"EL.: {el}", fs)
        dp.put(60 * s, (y + 9) * s, name, fs)
    for label, x in {"D-6": 200.0, "D-7": 360.0, "E-7": 520.0}.items():
        dp.put(x * s, 800 * s, label, fs)
        dp.put(x * s, 330 * s, "VERT: 4 25M B7-01", fs)
        dp.put(x * s, 340 * s, 'ETRI: 6 10M T4X21 @6"', fs)
    return dp.save(tmp_path / "shop_vec.pdf")


def test_image_only_shop_sheet_goes_through_ocr_into_the_normal_extractor(tmp_path):
    from l2c.extract.pipeline import extract_project
    from tests.extract.pdfmaker import rasterize

    root = tmp_path / "P"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    rasterize(shop_sheet(tmp_path), root / "DA" / "Colonnes" / "img.pdf")
    without = extract_project(root)
    assert without.elements == [] and without.sheets[0].layout == "needs_ocr"
    with_ocr = extract_project(root, use_ocr=True)
    assert with_ocr.sheets[0].layout == "shop_label_strip"
    good = [
        e
        for e in with_ocr.elements
        if e.armature[0].quantite == 4 and e.armature[0].diametre == "25M"
    ]
    assert len(good) >= 2  # OCR is imperfect; most strips must be read exactly
    sample = good[0]
    assert "ocr_text" in sample.quality.flags and sample.extraction_method == "rules+ocr"
    assert all(a.text_source == "ocr" for a in sample.quality.attributes.values())
    assert sample.quality.overall < 1.0  # OCR confidence lowers the score


def test_mark_ocr_lowers_confidence_and_flags_snapped_tokens(tmp_path):
    from l2c.extract.columns_shop import extract_shop_columns
    from l2c.extract.ocr_quality import mark_ocr
    from l2c.ingest.pages import load_pdf

    (page,) = load_pdf(shop_sheet(tmp_path, scale=1.0))
    (e, *_), _ = extract_shop_columns(page)
    words = [
        Word("25M", 0, 0, 1, 1, conf=0.8, original="2SM"),
        Word("10M", 0, 0, 1, 1, conf=0.95),
    ]
    (out, *_) = mark_ocr([e.model_copy(update={"raw_text": "VERT: 4 25M | 10M"})], words)
    assert out.quality.attributes["count"].text_source == "ocr"
    assert "ocr_snapped" in out.quality.flags and "ocr_text" in out.quality.flags
    assert out.quality.overall <= round(0.8 * 0.9, 3)
    assert out.extraction_method == "rules+ocr"
