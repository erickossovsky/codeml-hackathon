from l2c.ingest.pages import classify_layer, load_pdf, title_block_sheet
from tests.extract.pdfmaker import new_doc, put, rect, save


def test_classify_layer():
    assert classify_layer(200, 0, 0) == "text"
    assert classify_layer(10, 500, 0) == "vector"
    assert classify_layer(10, 100, 2) == "image"
    assert classify_layer(0, 5, 0) == "empty"


def test_words_and_title_block_sheet(tmp_path):
    doc, page = new_doc()
    put(page, 100, 100, "ARM.: 4-25M")
    put(page, 1050, 850, "S-517")
    pdf = save(doc, tmp_path / "plan.pdf")
    (p,) = load_pdf(pdf)
    assert p.feuillet == "S-517"
    assert any(w.text == "4-25M" for w in p.words)
    assert (p.width, p.height, p.rotation) == (1200, 900, 0)


def test_rotation_is_applied_once_to_words_and_shapes(tmp_path):
    def build(rotate: bool):
        doc, page = new_doc(600, 400)
        put(page, 50, 60, "HELLO", size=20)
        rect(page, 100, 200)
        if rotate:
            page.set_rotation(90)
        return save(doc, tmp_path / ("rot.pdf" if rotate else "flat.pdf"))

    (flat,) = load_pdf(build(False))
    (rot,) = load_pdf(build(True))
    assert (flat.width, flat.height) == (600, 400)
    assert (rot.width, rot.height) == (400, 600)  # displayed size swaps
    fw = next(w for w in flat.words if w.text == "HELLO")
    rw = next(w for w in rot.words if w.text == "HELLO")
    # 90 degree clockwise display: (x, y) -> (H - y, x) with H = unrotated height 400
    assert abs(rw.cx - (400 - fw.cy)) < 0.5 and abs(rw.cy - fw.cx) < 0.5
    fs, rs = flat.shapes[0], rot.shapes[0]
    assert abs(rs.cx - (400 - fs.cy)) < 0.5 and abs(rs.cy - fs.cx) < 0.5


def test_title_block_ignores_matches_outside_corner():
    from l2c.ingest.pages import Word

    words = [Word("S-100", 10, 10, 40, 20), Word("S-500", 1000, 850, 1040, 860)]
    assert title_block_sheet(words, 1200, 900) == "S-500"
    assert title_block_sheet([Word("S-100", 10, 10, 40, 20)], 1200, 900) is None
