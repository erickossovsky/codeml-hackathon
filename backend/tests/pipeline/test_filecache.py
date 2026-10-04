"""A file read once is not read again; a changed file is (synthetic PDFs only)."""

import json

import pymupdf

from l2c.pipeline import filecache as FC


def _pdf(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    for i, text in enumerate(lines):
        page.insert_text((40, 40 + 18 * i), text, fontsize=10)
    doc.save(path)
    doc.close()


def test_status_tells_new_cached_and_changed(tmp_path):
    cache = FC.FileCache(tmp_path / "cache")
    assert cache.status("a.pdf", "d1", "shop") == "new"
    cache.put("d1", "shop", "DA/a.pdf", {"pages": 1, "ocr_pages": 0, "size": 10}, {"elements": []})
    assert cache.status("a.pdf", "d1", "shop") == "cached"
    assert cache.status("a.pdf", "d2", "shop") == "changed"  # same name, other content
    again = FC.FileCache(tmp_path / "cache")  # the index survives
    assert again.status("a.pdf", "d2", "shop") == "changed"


def test_an_entry_from_another_reader_version_is_ignored(tmp_path, monkeypatch):
    cache = FC.FileCache(tmp_path / "cache")
    cache.put("d1", "plan", "p.pdf", {"pages": 1, "ocr_pages": 0, "size": 10}, {"elements": []})
    monkeypatch.setattr(FC, "VERSION", "999")
    assert cache.get("d1", "plan") is None


def test_second_run_reads_only_what_is_new(tmp_path):
    from l2c.pipeline.stream import run

    words = "NOTE GENERALE BETON ARME ACIER 400W RECOUVREMENT SELON DEVIS ET PLANS STRUCTURE"
    project = tmp_path / "proj"
    _pdf(project / "PLAN_S.pdf", ["COLONNE B-3", "ARM.: 4-20M", words, words])
    _pdf(project / "DA" / "C1.pdf", ["COLONNE B-3", "VERT: 4 20M 20Z3150", words, words])
    kw = {
        "llm": "none",
        "workers": 1,
        "partial_every": 0.0,
        "ocr_cache": tmp_path / "ocr",
        "file_cache": tmp_path / "files",
    }
    run(project, tmp_path / "out1", **kw)
    _pdf(project / "DA" / "C2.pdf", ["COLONNE B-4", "VERT: 6 20M 20Z3150", words, words])
    run(project, tmp_path / "out2", **kw)
    progress = json.loads((tmp_path / "out2" / "progress.json").read_text(encoding="utf-8"))
    state = {f["file"]: f["cache"] for f in progress["files"]}
    assert state == {"PLAN_S.pdf": "cached", "DA/C1.pdf": "cached", "DA/C2.pdf": "new"}
    assert (
        tmp_path / "out2" / "elements" / "elements.C1.json"
    ).is_file()  # cached files still listed
    assert (tmp_path / "out2" / "findings.json").is_file()
