"""Read one page into free-form elements. No element type is assumed: every framed callout and
every loose bar note becomes an element carrying whatever the page says about it."""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any

import pymupdf

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import Grid, fit_grid
from l2c.extract.runs import text_runs
from l2c.free import context as ctx
from l2c.free.facts import parse_line
from l2c.free.layout import attach_frames, bind_symbols, make_blocks, text_height
from l2c.free.model import FreeElement, PageSummary
from l2c.free.vectors import Vectors, read_vectors
from l2c.ingest.pages import PageData

MIN_WORDS = 10
_SECONDARY_LINE = re.compile(r"^\s*(\d{1,3})\s+((?:[A-Za-z]{1,4}\.\s?){1,3})\s*$")  # `6 r.b.`: a quantity and a short abbreviation


def entries(lines: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    """(bars, characteristics, descriptions) read from the printed lines of one block."""
    bars: list[dict] = []
    chars: list[dict] = []
    descs: list[dict] = []
    for line in lines:
        sec = _SECONDARY_LINE.match(line)
        if sec and bars and bars[-1].get("secondary_count") is None and bars[-1].get("count") is not None:
            # a lone `quantity abbreviation` line under a bar group is that group's second quantity
            bars[-1]["secondary_count"] = int(sec.group(1))
            bars[-1]["secondary_unit"] = sec.group(2).strip()
            continue
        parsed = parse_line(line)
        bars.extend(parsed["bars"])
        chars.extend(parsed["characteristics"])
        if parsed["rest"]:
            label = parsed["label"]
            if label and not parsed["bars"] and not parsed["characteristics"]:
                name = label.lower().strip(" .:")
                chars.append({"name": name, "value": parsed["rest"], "source_text": line})
            else:
                descs.append({"text": parsed["rest"], "source_text": line})
        elif not parsed["bars"] and not parsed["characteristics"]:
            descs.append({"text": line, "source_text": line})
    return bars, chars, descs


def _round(b) -> list[float]:
    return [round(b.x0, 2), round(b.y0, 2), round(b.x1, 2), round(b.y1, 2)]


def read_page(
    page: PageData,
    pdf_page: pymupdf.Page | None,
    source: str,
    config: Config = DEFAULT_CONFIG,
) -> tuple[list[FreeElement], PageSummary]:
    stem = PurePath(page.fichier).stem
    summary = PageSummary(
        file=page.fichier,
        page=page.page,
        sheet=page.feuillet,
        layer=page.layer,
        text_source=page.source,
        n_words=len(page.words),
    )
    if len(page.words) < MIN_WORDS:
        summary.notes.append("no_text: needs OCR or has no readable text")
        return [], summary
    h = text_height(page.words)
    runs = text_runs(page.words, gap=1.6 * h)
    titles = ctx.find_titles(runs, h)
    summary.drawings = [
        {"title": t.text, "x": round(t.x, 1), "y": round(t.y, 1), "level": t.level, "kind_hint": t.kind}
        for t in titles
    ]
    summary.scale_text = ctx.find_scales(runs)
    grid: Grid | None = fit_grid(page.words, config)
    if grid is not None:
        summary.grid = {
            "letters_on": grid.letters_on,
            "rows": {k: round(v, 1) for k, v in grid.rows.items()},
            "cols": {k: round(v, 1) for k, v in grid.cols.items()},
        }
    vec = read_vectors(pdf_page) if pdf_page is not None else Vectors()
    blocks = attach_frames(make_blocks(page.words, h), vec, h)
    bind_symbols(blocks, vec, h)
    sheet_levels = {(t.level, t.level_text) for t in titles if t.level}
    sheet_kinds = {t.kind for t in titles if t.kind}
    elements: list[FreeElement] = []
    for b in blocks:
        bars, chars, descs = entries(b.lines)
        bound = b.frame is not None and b.symbol is not None
        if not bars and not chars and not bound:
            continue
        if not b.frame and not bars:
            continue  # loose text with no reinforcement fact is not an element on its own
        anchor = b.symbol or b.bbox
        t = ctx.nearest_title(titles, anchor.cx, anchor.cy)
        own_kind, own_basis = ctx.kind_of(" ".join(b.lines))
        own_noun = ctx.leading_noun(b.lines)
        if own_kind:
            kind, basis = own_kind, own_basis
        elif own_noun:
            # an object the vocabulary does not know keeps the words the drawing itself uses
            kind, basis = own_noun, ["own_text"]
        else:
            kind, basis = ctx.kind_of(t.text if t else None)
            if kind is None and len(sheet_kinds) == 1:
                kind, basis = next(iter(sheet_kinds)), ["sheet_titles"]
            if kind is None:
                kind, basis = ctx.kind_of(stem)
        locations: list[dict[str, Any]] = []
        gp = ctx.grid_position(grid, anchor.cx, anchor.cy)
        if gp:
            locations.append(gp)
        if t and t.level:
            locations.append({"type": "level", "value": t.level, "text": t.level_text})
        elif len(sheet_levels) == 1:
            lv, lt = next(iter(sheet_levels))
            locations.append({"type": "level", "value": lv, "text": lt, "basis": "sheet"})
        if t:
            locations.append({"type": "drawing", "title": t.text})
        if b.symbol:
            chars.append(
                {
                    "name": "symbol_size_pt",
                    "value": [round(b.symbol.w, 1), round(b.symbol.h, 1)],
                    "note": "drawn size on the page; real size needs the drawing scale",
                }
            )
        elements.append(
            FreeElement(
                id="",
                source=source,
                file=page.fichier,
                sheet=page.feuillet,
                page=page.page,
                x=round(anchor.cx, 2),
                y=round(anchor.cy, 2),
                bbox=_round(anchor),
                kind=kind,
                locations=locations,
                bars=bars,
                descriptions=descs,
                characteristics=chars,
                quality={
                    "binding": b.binding if b.frame else "text_only",
                    "text_source": page.source,
                    "kind_basis": basis if kind else None,
                    "has_frame": b.frame is not None,
                },
                evidence=[
                    {
                        "file": page.fichier,
                        "page": page.page,
                        "bbox": _round(b.bbox),
                        "method": "callout" if b.frame else "loose_note",
                        "text": b.lines,
                    }
                ],
            )
        )
    elements.sort(key=lambda e: (round(e.y), e.x))
    for i, e in enumerate(elements, 1):
        e.id = f"{stem}_p{page.page}_{i:04d}"
    summary.n_elements = len(elements)
    return elements, summary
