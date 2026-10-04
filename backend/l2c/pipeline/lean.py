"""Lean extraction: text, position and neighbours. No drawing data is read.

A PDF page is read once for its words (native text layer, or OCR words for a page without one). Words
become lines and blocks (a block is one note: lines that are close and aligned). Each block gets its
page position, grid cell, level, the drawing title it falls under, and the facts parsed from its text.

Elements are then made from blocks:
- a block that carries notation (bars, a section, a strength) is one element, with its context;
- a shop column strip chart (a grid label at the foot of each strip, notes stacked above it by level)
  gives each note the label of its strip;
- the remaining text under one detail title is one detail element (title, scale, elevations, notes).
Code groups the tight cases. Where a note could belong to two strips, or two titles, one short model
question about one note and two candidates decides.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from pathlib import Path, PurePath
from typing import Any

import pymupdf

from l2c.extract.columns_shop import assign_level, find_level_lines, split_views
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import fit_grid
from l2c.extract.runs import text_runs
from l2c.free import context as ctx
from l2c.free.layout import make_blocks, text_height
from l2c.free.facts import parse_line
from l2c.free.reader import entries
from l2c.ingest.pages import PageData, Word
from l2c.llm import prompts as P
from l2c.llm.client import LlmClient, choose_many
from l2c.llm.compact import _clip
from l2c.pipeline import pageread

MIN_WORDS = 10
STRIP_LABEL = re.compile(r"^([A-Z]{1,2}(?:\.\d)?'?)-(\d{1,2}(?:\.\d)?)$")
MIN_STRIP_LABELS = 3
AMBIGUOUS_RATIO = 1.3  # a second candidate this close to the first makes a question
DETAIL_MAX_TEXTS = 40
NOISE = re.compile(r"^(?:[A-Z]{1,2}(?:\.\d)?'?|\d{1,3}(?:\.\d)?|[-–—•.])$")  # lone grid letters, numbers


ALT_LOW, ALT_HIGH = 0.2, 0.8  # a note this far between two gridlines may belong to either


def _alt_cells(gp: dict) -> list[str]:
    """The neighbouring cells a note could belong to. A note's text box sits beside the member it
    describes, so the nearest gridline is not always the member's: when the box lies between two
    lines on an axis, the other line is a candidate too."""

    def other(axis: dict) -> str | None:
        between, frac = axis.get("between"), axis.get("fraction")
        if not between or frac is None or not (ALT_LOW <= frac <= ALT_HIGH):
            return None
        return between[0] if axis["nearest"] == between[1] else between[1]

    r, c = gp["row"], gp["col"]
    ro, co = other(r), other(c)
    cells = []
    if co:
        cells.append(f"{r['nearest']}-{co}")
    if ro:
        cells.append(f"{ro}-{c['nearest']}")
    if ro and co:
        cells.append(f"{ro}-{co}")
    return cells


GRID_REF = re.compile(r"(?<![\w.])([A-Z]{1,2}(?:\.\d)?'?)-(\d{1,2}(?:\.\d)?)(?![\d.])")
KEY_RUN = re.compile(r"^\s*(?:TYPE|TYP\.)\s*[-:]?\s*([A-Z]{1,2}\d?|\d{1,2})\s*:?\s*$", re.I)
KEY_IN_TEXT = re.compile(r"\bTYPE\s*[-:]?\s*([A-Z]{1,2}\d?|\d{1,2})\b", re.I)


def _axis_value(axis: dict, letters: bool) -> float | None:
    """A continuous position along one grid axis, in label units: between rows J and I a note at 0.3
    is J + 0.3 of the way to I. Letters use their rank (A=1, B=2, B.1 between B and C)."""
    from l2c.extract.grid import _letter_rank

    def val(label: str) -> float | None:
        try:
            return _letter_rank(label) if letters else float(label)
        except (TypeError, ValueError):
            return None

    if axis.get("between") and axis.get("fraction") is not None:
        lo, hi = (val(x) for x in axis["between"])
        if lo is not None and hi is not None:
            return round(lo + axis["fraction"] * (hi - lo), 3)
    return val(axis["nearest"])


def _named_cells(lines: list[str]) -> list[str]:
    """Grid cells the text itself names, as in `COLONNE B-4, 12X20:` or `COLONNES C-2, C-3:`. A cell
    named in the text says where the element is better than the text's position does."""
    cells: list[str] = []
    for line in lines:
        refs = GRID_REF.findall(line)
        if not refs:
            continue
        has_word = ctx.kind_of(line)[0] is not None or line.rstrip().endswith(":")
        if has_word:
            cells += [f"{r}-{c}" for r, c in refs]
    return list(dict.fromkeys(cells))


def _kind_by_line(lines: list[str]) -> tuple[str | None, list[str]]:
    """The kind a block names, read from its first line that names one (the heading), so
    `EMPATTEMENT TYPE-D: ... COLONNE B-4` is a footing that serves a column, not a column."""
    for line in lines:
        kind, basis = ctx.kind_of(line)
        if kind:
            return kind, basis
    return None, []


def _schedules(runs: list, h: float, words: list) -> tuple[dict[str, dict], list[tuple[float, float, float, float]]]:
    """Rows of a schedule keyed by a type code (`TYPE D | 8'-0" | ... | 7-20M | 7-20M`). Each cell is
    read with the column header above it as its label. Returns code -> facts, and the table regions."""
    keys = [r for r in runs if KEY_RUN.match(r.text)]
    out: dict[str, dict] = {}
    regions: list[tuple[float, float, float, float]] = []
    for k in keys:
        code = KEY_RUN.match(k.text).group(1).upper()
        cells = sorted((r for r in runs if r is not k and abs(r.cy - k.cy) <= 0.6 * h and k.x1 < r.x0 < k.x1 + 80 * h), key=lambda r: r.x0)
        if not cells:
            continue
        bars, chars, descs = [], [], []
        x0, y0, x1, y1 = k.x0, k.y0, max(c.x1 for c in cells), k.y1
        for c in cells:
            # the column header: on the nearest line above that is not another schedule row, the words
            # that sit over this column (a header row is often printed as one long run)
            cand = [
                w for w in words
                if w.y1 <= k.y0 and k.y0 - w.y1 <= 15 * h and w.x1 >= c.x0 - h and w.x0 <= c.x1 + h
                and not any(abs(w.cy - kk.cy) <= 0.6 * h for kk in keys)
            ]
            header = None
            if cand:
                top = max(w.y1 for w in cand)
                # a header word belongs to the column whose centre it is nearest
                centres = [cc.cx for cc in cells]
                line = sorted(
                    (w for w in cand if abs(w.y1 - top) <= 0.6 * h and min(centres, key=lambda x: abs(x - w.cx)) == c.cx),
                    key=lambda w: w.x0,
                )
                header = " ".join(w.text for w in line) or None
                if line:
                    y0 = min(y0, min(w.y0 for w in line))
            parsed = parse_line(c.text, header) if header else parse_line(c.text)
            bars += parsed["bars"]
            chars += parsed["characteristics"]
            if parsed["rest"]:
                chars.append({"name": (header or "value").lower().strip(" .:"), "value": parsed["rest"], "source_text": c.text})
        if bars or chars:
            out[code] = {"bars": bars, "characteristics": chars, "descriptions": descs, "key": k.text.strip()}
            regions.append((x0 - h, y0 - h, x1 + h, y1 + h))
    return out, regions


def _bbox(b) -> list[float]:
    t = b.text_bbox
    return [round(t.x0, 2), round(t.y0, 2), round(t.x1, 2), round(t.y1, 2)]


def _strip_labels(blocks: list, facts_of: dict) -> list[dict]:
    out = []
    for b in blocks:
        lines = b.lines
        if len(lines) == 1 and STRIP_LABEL.match(lines[0].strip()) and not facts_of[id(b)]["bars"]:
            t = b.text_bbox
            out.append({"cell": lines[0].strip(), "x": (t.x0 + t.x1) / 2, "y": (t.y0 + t.y1) / 2, "block": b})
    return out


def _strip_tolerance(labels: list[dict]) -> float:
    """Half the usual spacing between neighbouring labels of one row of labels."""
    rows: dict[int, list[float]] = defaultdict(list)
    for lab in labels:
        rows[round(lab["y"] / 20)].append(lab["x"])
    gaps = []
    for xs in rows.values():
        xs.sort()
        gaps += [b - a for a, b in zip(xs, xs[1:], strict=False) if b - a > 1]
    return 0.5 * statistics.median(gaps) if gaps else 0.0


def read_page_blocks(
    page: PageData, stem: str, *, config: Config = DEFAULT_CONFIG
) -> dict[str, Any]:
    """Everything one page says, as a page summary and a list of block records."""
    n = page.page
    words = page.words
    summary: dict[str, Any] = {
        "page": n,
        "layer": page.layer,
        "text_source": page.source,
        "n_words": len(words),
        "sheet": page.feuillet,
    }
    if len(words) < MIN_WORDS:
        summary["notes"] = ["no_text"]
        return {"summary": summary, "blocks": []}
    h = text_height(words)
    runs = text_runs(words, gap=1.6 * h)
    titles = [t for t in ctx.find_titles(runs, h) if "REVISION" not in ctx.plain(t.text) and "CHELLE" not in ctx.plain(t.text)[:8]]
    summary["text_height"] = round(h, 2)
    summary["titles"] = [{"text": t.text, "x": round(t.x, 1), "y": round(t.y, 1), "level": t.level} for t in titles]
    summary["scale_text"] = ctx.find_scales(runs)
    summary["page_title"] = pageread_title(words, h)
    for t in titles:
        pass
    sheet_levels = sorted({t.level or ctx.level_guess(t.text, plan_title=True) for t in titles if (t.level or ctx.level_guess(t.text, plan_title=True))})
    stem_span = ctx.level_span(stem)
    stem_level, _ = ctx.level_of(stem)
    stem_level = stem_level or ctx.level_guess(stem, drop_first=True)
    summary["level_hints"] = {
        "from_titles": sheet_levels,
        "from_file_name": stem_span or ([stem_level] if stem_level else []),
        "from_page_title": ctx.level_span(summary["page_title"] or "") or [x for x in [ctx.level_of(summary["page_title"] or "")[0]] if x],
    }
    kind_words = {t.kind for t in titles if t.kind}
    page_kind = ctx.kind_of(summary["page_title"], stem)[0]
    summary["kind_hints"] = sorted(kind_words | ({page_kind} if page_kind else set()))
    grid = fit_grid(words, config)
    blocks = make_blocks(words, h)
    facts_of = {}
    for b in blocks:
        bars, chars, descs = entries(b.lines)
        facts_of[id(b)] = {"bars": bars, "characteristics": chars, "descriptions": descs}
    schedule, regions = _schedules(runs, h, words)

    def in_region(x: float, y: float) -> bool:
        return any(a <= x <= c and b <= y <= d for a, b, c, d in regions)

    labels = _strip_labels(blocks, facts_of)
    strip_mode = len(labels) >= MIN_STRIP_LABELS
    tol = _strip_tolerance(labels) if strip_mode else 0.0
    views = []
    if strip_mode:
        try:
            views = split_views(find_level_lines(page, runs, config, h))
        except Exception:  # a sheet without level lines simply has no strip levels
            views = []
    out = []
    for b in blocks:
        f = facts_of[id(b)]
        t = b.text_bbox
        cx, cy = (t.x0 + t.x1) / 2, (t.y0 + t.y1) / 2
        has = bool(f["bars"] or f["characteristics"])
        rec: dict[str, Any] = {
            "page": n,
            "lines": b.lines,
            "text": " | ".join(b.lines),
            "bbox": _bbox(b),
            "x": round(cx, 2),
            "y": round(cy, 2),
            "has_facts": has,
            "facts": f,
            "source": page.source,
        }
        confs = [w.conf for r in b.runs for w in r.words if w.conf is not None]
        if confs:
            rec["ocr_conf"] = round(sum(confs) / len(confs), 3)
        gp = ctx.grid_position(grid, cx, cy)
        if gp:
            rec["grid"] = {"cell": gp["cell"], "inside_grid": gp["inside_grid"], "alts": _alt_cells(gp), "rc": [_axis_value(gp["row"], True), _axis_value(gp["col"], False)]}
        title = ctx.nearest_title(titles, cx, cy)
        if title:
            rec["drawing_title"] = title.text
            # a second title nearly as near: the group this note belongs to is a close call
            d1 = ((title.x - cx) ** 2 + (title.y - cy) ** 2) ** 0.5
            rivals = [
                t2
                for t2 in titles
                if t2 is not title
                and t2.y >= cy
                and ((t2.x - cx) ** 2 + (t2.y - cy) ** 2) ** 0.5 < AMBIGUOUS_RATIO * max(d1, 1.0)
                # both titles must say something, and different things: only then does the answer matter
                and ((t2.level and title.level and t2.level != title.level) or (t2.kind and title.kind and t2.kind != title.kind))
            ]
            if rivals:
                rec["title_close_call"] = [min(rivals, key=lambda t2: (t2.x - cx) ** 2 + (t2.y - cy) ** 2).text]
        if in_region(cx, cy):
            rec["schedule_part"] = True  # a schedule is a definition: its rows become elements through their tags
        named = _named_cells(b.lines)
        if named:
            rec["named_cells"] = named
        key = KEY_IN_TEXT.search(rec["text"])
        if key:
            rec["type_key"] = (key.group(1) or key.group(2)).upper()
        kind, basis = _kind_by_line(b.lines)
        if kind:
            rec["kind_hint"] = {"kind": kind, "basis": basis}
        elif has:
            noun = ctx.leading_noun(b.lines)
            if noun:
                rec["kind_hint"] = {"kind": noun, "basis": ["own_text"]}
        if strip_mode and has and not any(l["block"] is b for l in labels):  # noqa: E741
            below = [l for l in labels if l["y"] >= cy and abs(l["x"] - cx) <= tol]  # noqa: E741
            if below:
                first = min(below, key=lambda l: (abs(l["x"] - cx), l["y"] - cy))  # noqa: E741
                # the same strip drawn at several levels: its label nearest below the note
                same = [l for l in below if abs(l["x"] - first["x"]) <= 2.0]  # noqa: E741
                best = min(same, key=lambda l: l["y"] - cy)  # noqa: E741
                rec["strip_label"] = best["cell"]
                dx1 = abs(first["x"] - cx)
                other = [l for l in below if abs(l["x"] - first["x"]) > 0.25 * tol]  # noqa: E741
                if other:
                    second = min(other, key=lambda l: abs(l["x"] - cx))  # noqa: E741
                    if abs(second["x"] - cx) < AMBIGUOUS_RATIO * max(dx1, 1.0):
                        nearest_second = min((l for l in below if abs(l["x"] - second["x"]) <= 2.0), key=lambda l: l["y"] - cy)  # noqa: E741
                        rec["strip_close_call"] = [best["cell"], nearest_second["cell"]]
            if views:
                lv, _flags = assign_level(views, t.y0)
                if lv not in {"UNKNOWN"}:
                    rec["strip_level"] = lv
        out.append(rec)
    if schedule:
        lone = {id(w) for r in runs if len(r.words) == 1 for w in r.words}
        table_kind = None
        for r in runs:
            if any(b - 15 * h <= r.y1 and r.y0 <= d and a <= r.cx <= c for a, b, c, d in regions) and ctx.kind_of(r.text)[0]:
                table_kind = ctx.kind_of(r.text)[0]
        for w in words:
            code = w.text.strip().upper()
            if code not in schedule or id(w) not in lone or in_region(w.cx, w.cy):
                continue
            gp = ctx.grid_position(grid, w.cx, w.cy)
            if not gp or not gp["inside_grid"]:
                continue  # grid labels sit outside the outer gridlines; tags sit inside
            d = schedule[code]
            rec = {
                "page": n,
                "lines": [f"{d['key']} (tag {code})"],
                "text": f"{d['key']} (tag {code})",
                "bbox": [round(w.x0, 2), round(w.y0, 2), round(w.x1, 2), round(w.y1, 2)],
                "x": round(w.cx, 2),
                "y": round(w.cy, 2),
                "has_facts": True,
                "facts": {"bars": [dict(b) for b in d["bars"]], "characteristics": [dict(c) for c in d["characteristics"]], "descriptions": []},
                "source": page.source,
                "grid": {"cell": gp["cell"], "inside_grid": True, "alts": _alt_cells(gp), "rc": [_axis_value(gp["row"], True), _axis_value(gp["col"], False)]},
                "type_key": code,
                "keyed": {"code": code, "definition": d["key"]},
            }
            title = ctx.nearest_title(titles, w.cx, w.cy)
            if title:
                rec["drawing_title"] = title.text
            kind = table_kind or (title.kind if title else None)
            if kind:
                rec["kind_hint"] = {"kind": kind, "basis": ["schedule"]}
            out.append(rec)
        summary["schedules"] = {k: v["key"] for k, v in schedule.items()}
    return {"summary": summary, "blocks": out}


def pageread_title(words: list[Word], h: float) -> str | None:
    from l2c.pipeline.extract import _page_title

    return _page_title(words, h)


# ---------------------------------------------------------------------------- pooled reading
def _page_task(args: tuple) -> tuple[str, int, dict[str, Any]]:
    pdf, rel, index, words, config = args
    with pymupdf.open(pdf) as doc:
        page = doc[index]
        if words is not None and pageread.word_count(page) >= MIN_WORDS:
            # a raster-heavy page that also has a text layer: keep the native words, add the OCR words that are new
            words = pageread.merge_ocr_words(pageread.native_words(page), words)
            source = "native+ocr"
        else:
            source = "ocr" if words is not None else "native"
        data = pageread.read_text_page(page, rel, index + 1, config, words=words, source=source)
        try:
            return rel, index, read_page_blocks(data, PurePath(rel).stem, config=config)
        except Exception as exc:  # one unreadable page must not stop the project: it is reported instead
            return rel, index, {"summary": {"page": index + 1, "sheet": data.feuillet, "notes": [f"error: {type(exc).__name__}: {exc}"]}, "blocks": []}


def read_many(
    items: list[tuple[Path, str]],
    *,
    ocr: bool = True,
    config: Config = DEFAULT_CONFIG,
    pages: set[int] | None = None,
    workers: int = 1,
    ocr_cache: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Block records for several PDFs. Pages without text are read through OCR in this process, one
    at a time (through the disk cache); everything else runs across a process pool."""
    tasks: list[list] = []
    metas: dict[str, dict[str, Any]] = {}
    ocr_pages: list[tuple[Path, str, int]] = []
    for pdf, rel in items:
        with pymupdf.open(pdf) as doc:
            metas[rel] = {"file": rel, "stem": PurePath(rel).stem, "pages": len(doc), "size_bytes": pdf.stat().st_size}
            for index in range(len(doc)):
                if pages and (index + 1) not in pages:
                    continue
                if ocr and (pageread.word_count(doc[index]) < MIN_WORDS or pageread.raster_share(doc[index]) >= pageread.RASTER_SHARE_MIN):
                    ocr_pages.append((pdf, rel, index))
                tasks.append([pdf, rel, index, None, config])
    ocr_words: dict[tuple[str, int], list[Word]] = {}
    if ocr_pages:
        from l2c.ingest.ocr import cached_ocr_page

        for pdf, rel, index in ocr_pages:
            ocr_words[(rel, index)] = cached_ocr_page(pdf, index + 1, config, ocr_cache).words
    for t in tasks:
        t[3] = ocr_words.get((t[1], t[2]))
    tasks_t = [tuple(t) for t in tasks]
    if workers > 1 and len(tasks_t) > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(workers) as pool:
            results = list(pool.map(_page_task, tasks_t, chunksize=1))
    else:
        results = [_page_task(t) for t in tasks_t]
    out = {rel: {"file": metas[rel], "pages": [], "blocks": []} for _, rel in items}
    for rel, _, res in results:
        out[rel]["pages"].append(res["summary"])
        out[rel]["blocks"] += res["blocks"]
    return out


# ---------------------------------------------------------------------------- elements
def _compact_note(b: dict) -> str:
    import json

    return json.dumps({"text": _clip(b["text"]), "grid": (b.get("grid") or {}).get("cell")}, ensure_ascii=False, separators=(",", ":"))


def build_elements(read: dict[str, Any], source: str, client: LlmClient) -> dict[str, Any]:
    """Elements of one file from its blocks. Questions only for the close calls."""
    stem = read["file"]["stem"]
    pages = {p["page"]: p for p in read["pages"]}
    blocks = read["blocks"]
    # (block, kind of call, candidate A, candidate B): one note and two candidates per question
    questions: list[tuple[dict, str, str, str]] = []
    for b in blocks:
        if b.get("strip_close_call") and len(b["strip_close_call"]) > 1:
            questions.append((b, "strip", b["strip_close_call"][0], b["strip_close_call"][1]))
        if b.get("title_close_call") and b["has_facts"]:
            questions.append((b, "title", b["drawing_title"], b["title_close_call"][0]))
    users = [
        f"NOTE: {_compact_note(b)}\nCANDIDATE A: {a}\nCANDIDATE B: {c}\nDoes the note belong to candidate A? ANSWER:"
        for b, _, a, c in questions
    ]
    got = choose_many(client, P.GROUP_SYSTEM, users, P.OPTIONS, version=P.GROUP_VERSION)
    answers: dict[tuple[int, str], tuple[str, float | None]] = {
        (id(b), kind): (ans.option, ans.certainty) for (b, kind, _, _), ans in zip(questions, got, strict=True)
    }
    elements: list[dict] = []
    detail: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for b in blocks:
        page = pages[b["page"]]
        if b.get("schedule_part"):
            continue
        if not b["has_facts"]:
            title = b.get("drawing_title")
            if title and not NOISE.match(b["text"].strip()) and len(b["text"]) > 3:
                detail[(b["page"], title)].append(b)
            continue
        elements.append(_fact_element(b, page, read, answers))
    for (pg, title), members in sorted(detail.items()):
        elements.append(_detail_element(pg, title, members, pages[pg], read))
    elements.sort(key=lambda e: (e["page"], round(e["y"]), e["x"]))
    for i, e in enumerate(elements, 1):
        e["id"] = f"{stem}_e{i:05d}"
        e["source"] = source
    return {
        "file": read["file"],
        "source": source,
        "pages": read["pages"],
        "elements": elements,
        "stats": {
            "elements": len(elements),
            "with_facts": sum(e["quality"]["has_facts"] for e in elements),
            "group_questions": len(users),
            "model": getattr(client, "model_id", None),
        },
    }


def _locations(b: dict, page: dict, answers: dict) -> tuple[list[dict], str | None]:
    locs: list[dict] = []
    name = None
    label = b.get("strip_label")
    if b.get("strip_close_call"):
        opt, cert = answers.get((id(b), "strip"), (None, None))
        if opt == "no" and len(b["strip_close_call"]) > 1:
            label = b["strip_close_call"][1]
    if b.get("named_cells"):
        locs.append({"type": "grid_cells", "cells": b["named_cells"], "basis": "named_in_text"})
        name = ", ".join(b["named_cells"])
    elif label:
        locs.append({"type": "grid", "cell": label, "basis": "strip_label"})
        name = label
    elif b.get("grid"):
        loc = {"type": "grid", "cell": b["grid"]["cell"], "inside_grid": b["grid"]["inside_grid"]}
        if b["grid"].get("alts"):
            loc["alt_cells"] = b["grid"]["alts"]
        if b["grid"].get("rc") and None not in b["grid"]["rc"]:
            loc["rc"] = b["grid"]["rc"]
        locs.append(loc)
    hints = page.get("level_hints", {})
    if b.get("title_close_call") and answers.get((id(b), "title"), (None, None))[0] == "no":
        b = {**b, "drawing_title": b["title_close_call"][0]}
    title_level = (ctx.level_of(b["drawing_title"])[0] or ctx.level_guess(b["drawing_title"], plan_title=True)) if b.get("drawing_title") else None
    if b.get("strip_level"):
        locs.append({"type": "level", "value": b["strip_level"], "basis": "strip_level_line"})
    elif title_level:
        locs.append({"type": "level", "value": title_level, "basis": "drawing_title"})
    elif len(hints.get("from_titles", [])) == 1:
        locs.append({"type": "level", "value": hints["from_titles"][0], "basis": "sheet_titles"})
    else:
        span = hints.get("from_page_title") or hints.get("from_file_name") or []
        if span:
            loc = {"type": "level", "value": span[0], "basis": "file_or_page_title"}
            if len(span) > 1:
                loc["to"] = span[1]
            locs.append(loc)
    if b.get("drawing_title"):
        locs.append({"type": "drawing", "title": b["drawing_title"]})
    return locs, name


def _kind(b: dict, page: dict) -> tuple[str | None, list[str] | None]:
    k = b.get("kind_hint")
    if k and k["basis"] != ["own_text"]:
        return k["kind"], k["basis"]
    if b.get("drawing_title"):
        kind, basis = ctx.kind_of(b["drawing_title"])
        if kind:
            return kind, ["drawing_title"]
    hints = page.get("kind_hints", [])
    if len(hints) == 1:
        return hints[0], ["page_hint"]
    if k:
        return k["kind"], k["basis"]
    return None, None


def _fact_element(b: dict, page: dict, read: dict, answers: dict) -> dict:
    locs, name = _locations(b, page, answers)
    kind, basis = _kind(b, page)
    f = b["facts"]
    return {
        "file": read["file"]["file"],
        "sheet": page.get("sheet"),
        "page": b["page"],
        "x": b["x"],
        "y": b["y"],
        "bbox": b["bbox"],
        "kind": kind,
        "name": name,
        "locations": locs,
        "bars": f["bars"],
        "characteristics": f["characteristics"],
        "descriptions": f["descriptions"],
        "match": {"method": "schedule_tag" if b.get("keyed") else "text_block", **({"keyed": b["keyed"]} if b.get("keyed") else {})},
        **({"type_key": b["type_key"]} if b.get("type_key") else {}),
        "quality": {"has_facts": True, "kind_basis": basis, "text_source": b["source"], "ocr_conf": b.get("ocr_conf")},
        "evidence": [{"page": b["page"], "bbox": b["bbox"], "text": b["lines"]}],
    }


def _detail_element(pg: int, title: str, members: list[dict], page: dict, read: dict) -> dict:
    members = sorted(members, key=lambda m: (m["y"], m["x"]))[:DETAIL_MAX_TEXTS]
    xs = [m["x"] for m in members]
    ys = [m["y"] for m in members]
    bb = [min(m["bbox"][0] for m in members), min(m["bbox"][1] for m in members), max(m["bbox"][2] for m in members), max(m["bbox"][3] for m in members)]
    level, written = ctx.level_of(title)
    kind, _ = ctx.kind_of(title)
    locs: list[dict] = [{"type": "drawing", "title": title}]
    if level:
        locs.append({"type": "level", "value": level, "text": written, "basis": "drawing_title"})
    return {
        "file": read["file"]["file"],
        "sheet": page.get("sheet"),
        "page": pg,
        "x": round(statistics.mean(xs), 2),
        "y": round(statistics.mean(ys), 2),
        "bbox": [round(v, 2) for v in bb],
        "kind": kind,
        "name": title,
        "role": "detail",
        "locations": locs,
        "bars": [],
        "characteristics": [],
        "descriptions": [{"text": m["text"]} for m in members],
        "match": {"method": "detail_title"},
        "quality": {"has_facts": False, "kind_basis": ["drawing_title"] if kind else None},
        "evidence": [{"page": pg, "bbox": bb, "text": [m["text"] for m in members][:6]}],
    }
