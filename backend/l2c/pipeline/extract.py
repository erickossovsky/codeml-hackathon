"""S0 and S1: metadata of one PDF, then its drawing items and text items as two separate lists.

Nothing is matched here. A page gives:
- `texts`: every printed text element (a callout block, a table cell or a loose note) with page
  location, source (native or OCR), facts parsed from it, and geometric hints (frame, leader, table
  cell, grid position, drawing title it falls under);
- `drawings`: filled symbols, outlines, connected linework (vector) or pixel regions (raster).
OCR is used for text only when the page has no text layer. Drawings come from the vector content,
or from the pixels when a page has no vector content.
"""

from __future__ import annotations

from pathlib import Path, PurePath
from typing import Any

import pymupdf

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import fit_grid
from l2c.extract.runs import text_runs
from l2c.free import context as ctx
from l2c.free.layout import attach_frames, bind_symbols, make_blocks, text_height
from l2c.free.reader import entries
from l2c.free.vectors import Box, Vectors
from l2c.ingest.pages import PageData, Word
from l2c.pipeline import drawings as dr
from l2c.pipeline import pageread
from l2c.pipeline import tables as tb

MIN_WORDS = 10
MIN_VECTOR_ITEMS = 50  # fewer vector items than this: treat the page as raster for drawings


def file_metadata(pdf: Path, rel: str, doc: pymupdf.Document) -> dict[str, Any]:
    meta = {k: v for k, v in (doc.metadata or {}).items() if v}
    return {
        "file": rel,
        "stem": PurePath(rel).stem,
        "size_bytes": pdf.stat().st_size,
        "pages": len(doc),
        "pdf_metadata": meta,
    }


def _facts(lines: list[str]) -> dict[str, list]:
    bars, chars, descs = entries(lines)
    return {"bars": bars, "characteristics": chars, "descriptions": descs}


def _mean_conf(words: list[Word]) -> float | None:
    confs = [w.conf for w in words if w.conf is not None]
    return round(sum(confs) / len(confs), 3) if confs else None


def _box_list(b: Box) -> list[float]:
    return [round(b.x0, 2), round(b.y0, 2), round(b.x1, 2), round(b.y1, 2)]


def _grid_of(grid, x: float, y: float) -> dict | None:
    return ctx.grid_position(grid, x, y)


def _page_title(words: list[Word], h: float) -> str | None:
    """Text after a title-block label (`Titre`, `Title`): the run to its right, else just below."""
    labels = [
        w for w in words if w.text.strip(" :.").upper() in {"TITRE", "TITLE", "DESSIN", "DRAWING"}
    ]
    runs = text_runs(words, gap=3 * h)
    for lab in sorted(labels, key=lambda w: -w.y0):
        cands = [
            r
            for r in runs
            if r.x1 > lab.x1
            and r.y0 >= lab.y0 - h
            and r.y0 <= lab.y1 + 6 * h
            and r.x0 >= lab.x0
            and len(r.text) > 3
        ]
        cands = [r for r in cands if r.text.strip(" :.").upper() not in {"TITRE", "TITLE"}]
        if cands:
            return min(cands, key=lambda r: (r.y0, r.x0)).text.strip()
    return None


def extract_page(
    page: PageData,
    vec: Vectors,
    pdf_page: pymupdf.Page,
    stem: str,
    *,
    config: Config = DEFAULT_CONFIG,
) -> dict[str, Any]:
    n = page.page
    summary: dict[str, Any] = {
        "page": n,
        "width": round(page.width, 1),
        "height": round(page.height, 1),
        "layer": page.layer,
        "text_source": page.source,
        "n_words": len(page.words),
        "n_images": page.n_images,
        "sheet": page.feuillet,
    }
    result = {"summary": summary, "texts": [], "drawings": [], "tables": []}
    if len(page.words) < MIN_WORDS:
        summary["notes"] = ["no_text"]
    h = text_height(page.words) if page.words else 8.0
    summary["text_height"] = round(h, 2)
    runs = text_runs(page.words, gap=1.6 * h) if page.words else []
    titles = ctx.find_titles(runs, h) if runs else []
    summary["titles"] = [
        {
            "text": t.text,
            "x": round(t.x, 1),
            "y": round(t.y, 1),
            "level": t.level,
            "kind_hint": t.kind,
        }
        for t in titles
    ]
    summary["page_title"] = _page_title(page.words, h) if page.words else None
    summary["scale_text"] = ctx.find_scales(runs)
    sheet_levels = sorted({t.level for t in titles if t.level})
    stem_span = ctx.level_span(stem)
    stem_level, _ = ctx.level_of(stem)
    summary["level_hints"] = {
        "from_titles": sheet_levels,
        "from_file_name": stem_span or ([stem_level] if stem_level else []),
        "from_page_title": ctx.level_span(summary["page_title"] or "")
        or [x for x in [ctx.level_of(summary["page_title"] or "")[0]] if x],
    }
    kind_words = {t.kind for t in titles if t.kind}
    page_kind = ctx.kind_of(summary["page_title"], stem)[0]
    summary["kind_hints"] = sorted(kind_words | ({page_kind} if page_kind else set()))
    grid = fit_grid(page.words, config) if len(page.words) >= MIN_WORDS else None
    if grid is not None:
        summary["grid"] = {
            "letters_on": grid.letters_on,
            "rows": {k: round(v, 1) for k, v in grid.rows.items()},
            "cols": {k: round(v, 1) for k, v in grid.cols.items()},
        }
    # drawings: vector content when there is enough, otherwise pixels
    vector_items = len(vec.lines) + len(vec.solids)
    if vector_items >= MIN_VECTOR_ITEMS:
        drawings = dr.vector_drawings(vec, h, page.width, page.height)
    else:
        drawings = dr.raster_drawings(pdf_page, h)
    summary["drawing_method"] = (
        drawings[0]["method"] if drawings else ("vector" if vector_items else "none")
    )
    for k, d in enumerate(drawings, 1):
        d["id"] = f"p{n}d{k}"
        bb = d["bbox"]
        d["x"], d["y"] = round((bb[0] + bb[2]) / 2, 2), round((bb[1] + bb[3]) / 2, 2)
        d["page"] = n
        gp = _grid_of(grid, d["x"], d["y"])
        if gp:
            d["grid"] = {"cell": gp["cell"], "inside_grid": gp["inside_grid"]}
    solid_ids = {tuple(d["bbox"]): d["id"] for d in drawings if d["shape"] == "solid"}
    # text: ruled tables first (cell by cell), then blocks from the remaining words
    tables = tb.find_tables(vec, page.words, h, page.width, page.height)
    rest_words, _ = tb.assign_words(tables, page.words)
    texts: list[dict[str, Any]] = []
    for t in tables:
        result["tables"].append(
            {"id": f"p{n}{t.id}", "bbox": t.bbox, "rows": len(t.ys) - 1, "cols": len(t.xs) - 1}
        )
        grid_text = {c: tb.cell_text(ws) for c, ws in t.cells.items()}
        for (i, j), words in sorted(t.cells.items()):
            lines = grid_text[(i, j)]
            xs0 = min(w.x0 for w in words)
            ys0 = min(w.y0 for w in words)
            xs1 = max(w.x1 for w in words)
            ys1 = max(w.y1 for w in words)
            texts.append(
                {
                    "lines": lines,
                    "bbox": [round(xs0, 2), round(ys0, 2), round(xs1, 2), round(ys1, 2)],
                    "source": page.source,
                    "ocr_conf": _mean_conf(words),
                    "cell": {
                        "table": f"p{n}{t.id}",
                        "row": i,
                        "col": j,
                        "row_header": " ".join(grid_text.get((i, 0), [])) or None,
                        "col_header": " ".join(grid_text.get((0, j), [])) or None,
                        "cell_bbox": t.cell_bbox(i, j),
                    },
                }
            )
    blocks = attach_frames(make_blocks(rest_words, h), vec, h)
    bind_symbols(blocks, vec, h)
    for b in blocks:
        bb = b.bbox
        t = {
            "lines": b.lines,
            "bbox": _box_list(bb),
            "source": page.source,
            "ocr_conf": _mean_conf([w for r in b.runs for w in r.words]),
        }
        if b.frame is not None:
            t["frame_bbox"] = _box_list(b.frame)
        if b.symbol is not None:
            t["leader"] = {
                "binding": b.binding,
                "drawing": solid_ids.get(
                    tuple(round(v, 2) for v in (b.symbol.x0, b.symbol.y0, b.symbol.x1, b.symbol.y1))
                ),
                "symbol_bbox": _box_list(b.symbol),
            }
        texts.append(t)
    texts.sort(key=lambda t: (round(t["bbox"][1]), t["bbox"][0]))
    for k, t in enumerate(texts, 1):
        t["id"] = f"p{n}t{k}"
        t["page"] = n
        bb = t["bbox"]
        t["x"], t["y"] = round((bb[0] + bb[2]) / 2, 2), round((bb[1] + bb[3]) / 2, 2)
        t["text"] = " | ".join(t["lines"])
        t["facts"] = _facts(t["lines"])
        gp = _grid_of(grid, t["x"], t["y"])
        if gp:
            t["grid"] = {
                "cell": gp["cell"],
                "row": gp["row"],
                "col": gp["col"],
                "inside_grid": gp["inside_grid"],
            }
        title = ctx.nearest_title(titles, t["x"], t["y"])
        if title:
            t["drawing_title"] = title.text
        # the text itself names the object: kept as a hint, never as a decision
        own_kind, basis = ctx.kind_of(" ".join(t["lines"]))
        if own_kind:
            t["kind_hint"] = {"kind": own_kind, "basis": basis}
        noun = ctx.leading_noun(t["lines"])
        if noun and not own_kind:
            t["kind_hint"] = {"kind": noun, "basis": ["own_text"]}
    result["texts"] = texts
    result["drawings"] = drawings
    summary["n_texts"] = len(texts)
    summary["n_drawings"] = len(drawings)
    summary["n_tables"] = len(tables)
    return result


def _page_task(args: tuple) -> tuple[str, int, dict[str, Any]]:
    """One page, in a worker process: a single read, then the whole extraction. Nothing here loads
    the OCR engine or the language model."""
    pdf, rel, index, words, config = args
    with pymupdf.open(pdf) as doc:
        pdf_page = doc[index]
        data, vec = pageread.read_page(
            pdf_page,
            rel,
            index + 1,
            config,
            words=words,
            source="ocr" if words is not None else "native",
        )
        if words is not None:
            data.layer = pageread.layer_of(pdf_page, vec_paths=data.n_paths, config=config)
        return rel, index, extract_page(data, vec, pdf_page, PurePath(rel).stem, config=config)


def extract_many(
    items: list[tuple[Path, str]],
    *,
    ocr: bool = True,
    config: Config = DEFAULT_CONFIG,
    pages: set[int] | None = None,
    workers: int = 1,
    ocr_cache: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Raw items for several PDFs at once.

    1. serial, cheap: which pages have no text layer (they need OCR);
    2. serial, in this process: OCR for those pages, through the on-disk cache. OCR is never run in
       worker processes (the engine already uses every core, and workers deadlocked on it);
    3. a process pool over every page of every file: one read of the page, then extraction.
    Results are collected in submission order, so the output does not depend on `workers`.
    """
    tasks: list[tuple] = []
    metas: dict[str, dict[str, Any]] = {}
    ocr_pages: list[tuple[Path, str, int]] = []
    for pdf, rel in items:
        with pymupdf.open(pdf) as doc:
            metas[rel] = file_metadata(pdf, rel, doc)
            for index in range(len(doc)):
                if pages and (index + 1) not in pages:
                    continue
                needs = ocr and pageread.word_count(doc[index]) < MIN_WORDS
                if needs:
                    ocr_pages.append((pdf, rel, index))
                tasks.append([pdf, rel, index, None, config])
    ocr_words: dict[tuple[str, int], list[Word]] = {}
    if ocr_pages:
        from l2c.ingest.ocr import cached_ocr_page

        for pdf, rel, index in ocr_pages:
            ocr_words[(rel, index)] = cached_ocr_page(pdf, index + 1, config, ocr_cache).words
    for t in tasks:
        t[3] = ocr_words.get((t[1], t[2]))
    tasks = [tuple(t) for t in tasks]
    if workers > 1 and len(tasks) > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(workers) as pool:
            results = list(pool.map(_page_task, tasks, chunksize=1))
    else:
        results = [_page_task(t) for t in tasks]
    out: dict[str, dict[str, Any]] = {
        rel: {"file": metas[rel], "pages": [], "texts": [], "drawings": [], "tables": []}
        for _, rel in items
    }
    for rel, _, res in results:
        o = out[rel]
        o["pages"].append(res["summary"])
        o["texts"] += res["texts"]
        o["drawings"] += res["drawings"]
        o["tables"] += res["tables"]
    return out


def extract_pdf(
    pdf: Path,
    rel: str,
    *,
    ocr: bool = True,
    config: Config = DEFAULT_CONFIG,
    pages: set[int] | None = None,
    workers: int = 1,
    ocr_cache: Path | None = None,
) -> dict[str, Any]:
    return extract_many(
        [(pdf, rel)], ocr=ocr, config=config, pages=pages, workers=workers, ocr_cache=ocr_cache
    )[rel]
