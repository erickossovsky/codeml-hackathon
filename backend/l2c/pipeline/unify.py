"""S2: turn the raw drawing and text items of one file into elements, with a certainty on each match.

Rules settle the clear cases (a table column, a callout whose leader ends on a symbol, one drawing
touching a note, exact duplicate notes). The local LLM is asked one yes/no question about one pair
of items only when the geometry is ambiguous, and its probability becomes the match certainty.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from l2c.free import context as ctx
from l2c.free.facts import parse_line
from l2c.llm import prompts as P
from l2c.llm.client import LlmClient, choose_many
from l2c.llm.compact import drawing_json, note_json

GRID_CELL = re.compile(r"(?<![\w.])([A-Z1]{1,2}(?:\.\d)?'?)-(\d{1,2}(?:\.\d)?)(?!\d)")
TOUCH_H = 1.0  # a drawing this close (in text heights) to a note touches it
FAR_FACTOR = 3.0  # the next candidate must be this much farther for a rule-only match
REACH_H = {"solid": 14.0, "outline": 14.0, "linework": 8.0, "region": 8.0}
MAX_CANDIDATES = 3  # drawings asked about per note, nearest first
BUCKET = 200.0


def _gap(a: list[float], b: list[float]) -> float:
    dx = max(0.0, a[0] - b[2], b[0] - a[2])
    dy = max(0.0, a[1] - b[3], b[1] - a[3])
    return (dx * dx + dy * dy) ** 0.5


def _inside(p: tuple[float, float], bb: list[float]) -> bool:
    return bb[0] <= p[0] <= bb[2] and bb[1] <= p[1] <= bb[3]


class _Index:
    def __init__(self, drawings: list[dict]) -> None:
        self.cells: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for d in drawings:
            b = d["bbox"]
            for i in range(int(b[0] // BUCKET), int(b[2] // BUCKET) + 1):
                for j in range(int(b[1] // BUCKET), int(b[3] // BUCKET) + 1):
                    self.cells[(i, j)].append(d)

    def near(self, bb: list[float], reach: float) -> list[dict]:
        seen, out = set(), []
        for i in range(int((bb[0] - reach) // BUCKET), int((bb[2] + reach) // BUCKET) + 1):
            for j in range(int((bb[1] - reach) // BUCKET), int((bb[3] + reach) // BUCKET) + 1):
                for d in self.cells.get((i, j), []):
                    if d["id"] not in seen:
                        seen.add(d["id"])
                        out.append(d)
        return out


def describe_drawing(d: dict, h: float) -> str:
    w, ht = d["size_pt"]
    if d["shape"] == "solid":
        return f"filled {'square' if 0.6 < w / max(ht, 0.1) < 1.6 else 'bar'}, {w:g}x{ht:g} pt"
    if d["shape"] == "outline":
        return f"outline box, {w:g}x{ht:g} pt"
    if d["shape"] == "linework":
        return f"line group, {max(w, ht):g} pt long, {d.get('n_segments', '?')} segments"
    return f"{d['shape']}, {w:g}x{ht:g} pt"


def _short(text: str, n: int = 90) -> str:
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= n else text[: n - 1] + "…"


def level_info(page: dict, text: dict | None) -> tuple[list[dict], str | None]:
    """Level entries for an element and the kind hint of the sheet."""
    hints = page.get("level_hints", {})
    locs: list[dict] = []
    title_level = None
    if text and text.get("drawing_title"):
        title_level = ctx.level_of(text["drawing_title"])[0]
    if title_level:
        locs.append({"type": "level", "value": title_level, "basis": "drawing_title"})
    elif len(hints.get("from_titles", [])) == 1:
        locs.append({"type": "level", "value": hints["from_titles"][0], "basis": "sheet_titles"})
    else:
        span = hints.get("from_page_title") or hints.get("from_file_name") or []
        if span:
            locs.append(
                {
                    "type": "level",
                    "value": span[0],
                    "to": span[1] if len(span) > 1 else None,
                    "basis": "file_or_page_title",
                }
            )
    return [{k: v for k, v in loc.items() if v is not None} for loc in locs], None


def _merge_facts(texts: list[dict]) -> tuple[list, list, list]:
    bars, chars, descs = [], [], []
    seen: set[str] = set()
    for t in texts:
        f = t["facts"]
        for key, dest in (("bars", bars), ("characteristics", chars), ("descriptions", descs)):
            for item in f[key]:
                sig = f"{key}:{item.get('source_text')}:{item.get('text', '')}"
                if sig in seen:
                    continue
                seen.add(sig)
                dest.append(item)
    return bars, chars, descs


def _has_facts(t: dict) -> bool:
    f = t["facts"]
    return bool(f["bars"] or f["characteristics"])


def _kind(texts: list[dict], page: dict, header: str | None = None) -> tuple[str | None, list[str]]:
    for t in texts:
        k = t.get("kind_hint")
        if k and k["basis"] != ["own_text"]:
            return k["kind"], k["basis"]
    if header:
        kind, basis = ctx.kind_of(header)
        if kind:
            return kind, ["table_header"]
    for t in texts:
        k = t.get("kind_hint")
        if k:
            return k["kind"], k["basis"]
    for t in texts:
        if t.get("drawing_title"):
            kind, basis = ctx.kind_of(t["drawing_title"])
            if kind:
                return kind, ["drawing_title"]
    hints = page.get("kind_hints", [])
    if len(hints) == 1:
        return hints[0], ["page_hint"]
    return None, []


class _Builder:
    def __init__(self, raw: dict, client: LlmClient) -> None:
        self.raw = raw
        self.client = client
        self.stem = raw["file"]["stem"]
        self.elements: list[dict] = []
        self.llm_calls = 0
        self.llm_skipped = 0
        self.used_drawings: set[str] = set()

    # ------------------------------------------------------------------ helpers
    def _emit(self, texts: list[dict], drawings: list[dict], page: dict, method: str, **extra: Any) -> dict:
        bars, chars, descs = _merge_facts(texts)
        boxes = [t["bbox"] for t in texts] + [d["bbox"] for d in drawings]
        bbox = [
            round(min(b[0] for b in boxes), 2),
            round(min(b[1] for b in boxes), 2),
            round(max(b[2] for b in boxes), 2),
            round(max(b[3] for b in boxes), 2),
        ]
        anchor = drawings[0] if drawings else texts[0]
        kind, basis = _kind(texts, page, extra.pop("header", None))
        locations, _ = level_info(page, texts[0] if texts else None)
        if texts and texts[0].get("grid"):
            g = texts[0]["grid"]
            locations.insert(0, {"type": "grid", "cell": g["cell"], "row": g["row"], "col": g["col"], "inside_grid": g["inside_grid"]})
        elif drawings and drawings[0].get("grid"):
            locations.insert(0, {"type": "grid", "cell": drawings[0]["grid"]["cell"]})
        for t in texts:
            if t.get("drawing_title"):
                locations.append({"type": "drawing", "title": t["drawing_title"]})
                break
        for d in drawings:
            if d["shape"] == "solid":
                chars.append({"name": "symbol_size_pt", "value": d["size_pt"], "note": "drawn size on the page"})
        ocr = [t["ocr_conf"] for t in texts if t.get("ocr_conf") is not None]
        element = {
            "file": self.raw["file"]["file"],
            "page": page["page"],
            "x": anchor["x"],
            "y": anchor["y"],
            "bbox": bbox,
            "kind": kind,
            "name": extra.pop("name", None),
            "locations": locations,
            "bars": bars,
            "characteristics": chars,
            "descriptions": descs,
            "parts": {"texts": [t["id"] for t in texts], "drawings": [d["id"] for d in drawings]},
            "match": {"method": method, **extra.pop("match", {})},
            "quality": {
                "kind_basis": basis or None,
                "text_source": texts[0]["source"] if texts else None,
                "ocr_conf_min": min(ocr) if ocr else None,
                "has_facts": bool(bars or chars),
            },
            "evidence": [{"page": page["page"], "bbox": t["bbox"], "text": t["lines"]} for t in texts],
        }
        element.update(extra)
        for d in drawings:
            self.used_drawings.add(d["id"])
        self.elements.append(element)
        return element

    # ------------------------------------------------------------------ tables
    def _tables(self, page: dict, texts: list[dict]) -> set[str]:
        by_table: dict[str, list[dict]] = defaultdict(list)
        for t in texts:
            if t.get("cell"):
                by_table[t["cell"]["table"]].append(t)
        consumed: set[str] = set()
        for table_id, cells in by_table.items():
            orient = _orientation(cells)
            if orient == "columns":
                self._table_columns(page, cells)
            elif orient == "rows":
                self._table_rows(page, cells)
            else:
                continue
            consumed.update(t["id"] for t in cells)
        return consumed

    def _table_columns(self, page: dict, cells: list[dict]) -> None:
        cols: dict[int, list[dict]] = defaultdict(list)
        for t in cells:
            cols[t["cell"]["col"]].append(t)
        row_headers = {t["cell"]["row"]: t for t in cols.get(0, [])}
        header_text = " ".join(" ".join(t["lines"]) for t in sorted(cols.get(0, []), key=lambda t: t["cell"]["row"]))
        for j, members in sorted(cols.items()):
            if j == 0:
                continue
            members = sorted(members, key=lambda t: t["cell"]["row"])
            name_cell = next((t for t in members if t["cell"]["row"] == 0), None)
            name = " ".join(name_cell["lines"]) if name_cell else None
            texts = []
            for t in members:
                label = row_headers.get(t["cell"]["row"])
                # a row that spans several printed labels (VERTICALE / ETRIER / DETAIL) gives no
                # single label for a line: lines are then read on their own
                label_text = label["lines"][0] if label and len(label["lines"]) == 1 else None
                parsed = _reparse(t, label_text)
                texts.append(parsed)
            if not any(_has_facts(t) for t in texts):
                continue
            # OCR reads the row letter I as 1 (`1.2-10`); a row label never starts with a digit
            cells_found = [
                f"{('I' + r[1:]) if r.startswith('1') else r}-{c}" for r, c in GRID_CELL.findall(name or "")
            ]
            el = self._emit(
                texts, [], page, "table_column",
                name=name,
                header=header_text,
                match={"rule_certainty": 0.95, "table": members[0]["cell"]["table"], "column": j},
            )
            if cells_found:
                el["locations"].insert(0, {"type": "grid_cells", "cells": cells_found})
            quantity = _quantity(members)
            if quantity is not None:
                el["characteristics"].append({"name": "quantity_required", "value": quantity})

    def _table_rows(self, page: dict, cells: list[dict]) -> None:
        rows: dict[int, list[dict]] = defaultdict(list)
        for t in cells:
            rows[t["cell"]["row"]].append(t)
        for i, members in sorted(rows.items()):
            if i == 0:
                continue
            texts = []
            for t in sorted(members, key=lambda t: t["cell"]["col"]):
                header = t["cell"].get("col_header")
                value = " ".join(t["lines"])
                tt = dict(t)
                tt["facts"] = {
                    "bars": parse_line(value, header)["bars"] if header else parse_line(value)["bars"],
                    "characteristics": [{"name": (header or f"col{t['cell']['col']}").lower(), "value": value, "source_text": value}],
                    "descriptions": [],
                }
                texts.append(tt)
            self._emit(texts, [], page, "table_row", name=" ".join(texts[0]["lines"]),
                       match={"rule_certainty": 0.95, "table": members[0]["cell"]["table"], "row": i})

    # ------------------------------------------------------------------ callouts and loose notes
    def _candidates(self, text: dict, index: _Index, h: float, by_id: dict) -> list[tuple[float, dict, bool, bool]]:
        """Drawings worth asking about for one note: the one a leader line reaches, if any, then the
        nearest others within reach. This only lists candidates; the model decides."""
        out: list[tuple[float, dict, bool, bool]] = []
        seen: set[str] = set()
        lead = text.get("leader")
        if lead and lead.get("drawing") in by_id:
            d = by_id[lead["drawing"]]
            out.append((_gap(text["bbox"], d["bbox"]), d, True, False))
            seen.add(d["id"])
        rest = []
        for d in index.near(text["bbox"], 14 * h):
            if d["id"] in seen:
                continue
            g = _gap(text["bbox"], d["bbox"])
            if g <= REACH_H.get(d["shape"], 8.0) * h:
                inside = _inside((text["x"], text["y"]), d["bbox"]) and d["shape"] == "outline"
                rest.append((0.0 if inside else g, d, False, inside))
        rest.sort(key=lambda c: (c[0], c[1]["id"]))
        return (out + rest)[:MAX_CANDIDATES]

    def _resolve(self, jobs: list[dict]) -> None:
        """Ask the model, in parallel, whether each note describes its first candidate drawing; a note
        that gets `no` is asked about its next candidate, and so on. Every answer is one question about
        one note and one drawing."""
        for round_no in range(MAX_CANDIDATES):
            pending = [j for j in jobs if j["result"] is None and len(j["cands"]) > round_no]
            if not pending:
                return
            users = []
            for j in pending:
                g, d, leader, inside = j["cands"][round_no]
                users.append(f"NOTE: {note_json(j['text'])}\nOBJECT: {drawing_json(d, g, leader, inside)}\nANSWER:")
            answers = choose_many(self.client, P.LINK_SYSTEM, users, P.OPTIONS, version=P.LINK_VERSION)
            self.llm_calls += len(users)
            for j, ans in zip(pending, answers, strict=True):
                if ans.option == "yes":
                    g, d, leader, _ = j["cands"][round_no]
                    j["result"] = ([d], {"method": "llm_link", "llm_certainty": ans.certainty, "gap_pt": round(g, 1), "leader_line": leader, "candidate_rank": round_no + 1})

    def _texts_and_drawings(self, page: dict, texts: list[dict], drawings: list[dict]) -> None:
        h = page.get("text_height", 8.0)
        by_id = {d["id"]: d for d in drawings}
        index = _Index(drawings)
        loose: list[dict] = []
        for t in texts:
            if _has_facts(t) or t.get("frame_bbox") or t.get("leader"):
                loose.append(t)
            else:
                self._emit([t], [], page, "text_only", role="annotation", match={"rule_certainty": 1.0})
        dup_groups: dict[tuple, list[dict]] = defaultdict(list)
        for t in loose:
            sig = _signature(t)
            cell = (t.get("grid") or {}).get("cell")
            dup_groups[(sig, cell if cell else (round(t["x"] / 40), round(t["y"] / 40)))].append(t)
        jobs = []
        for members in dup_groups.values():
            members.sort(key=lambda t: (t["y"], t["x"]))
            lead = members[0]
            cands = self._candidates(lead, index, h, by_id)
            jobs.append({"members": members, "text": lead, "cands": cands, "result": None if cands else ([], {"method": "text_only", "rule_certainty": 1.0})})
        self._resolve(jobs)
        for j in jobs:
            ds, m = j["result"] or ([], {"method": "text_only", "unconfirmed_candidates": [c[1]["id"] for c in j["cands"]]})
            members = j["members"]
            el = self._emit(members, ds, page, m.pop("method"), match=m)
            if len(members) > 1:
                el["match"]["duplicates_merged"] = [t["id"] for t in members[1:]]
                el["match"]["duplicate_method"] = "identical text in the same cell"

    # ------------------------------------------------------------------ entry
    def run(self) -> dict:
        pages = {p["page"]: p for p in self.raw["pages"]}
        texts_by = defaultdict(list)
        draws_by = defaultdict(list)
        for t in self.raw["texts"]:
            texts_by[t["page"]].append(t)
        for d in self.raw["drawings"]:
            draws_by[d["page"]].append(d)
        for n, page in sorted(pages.items()):
            page_texts = texts_by.get(n, [])
            consumed = self._tables(page, page_texts)
            rest = [t for t in page_texts if t["id"] not in consumed and not t.get("cell")]
            cell_rest = [t for t in page_texts if t.get("cell") and t["id"] not in consumed]
            self._texts_and_drawings(page, rest + cell_rest, draws_by.get(n, []))
        # drawings with no text: symbol-like ones are elements, the rest stay as a compact list
        unattached = []
        for d in self.raw["drawings"]:
            if d["id"] in self.used_drawings:
                continue
            if d["shape"] in {"solid", "outline"}:
                self._drawing_only(pages[d["page"]], d)
            else:
                unattached.append({k: d[k] for k in ("id", "page", "shape", "bbox", "size_pt", "x", "y") if k in d})
        self.elements.sort(key=lambda e: (e["page"], round(e["y"]), e["x"]))
        for i, e in enumerate(self.elements, 1):
            e["id"] = f"{self.stem}_e{i:05d}"
            e["source"] = self.raw.get("source")
        return {
            "file": self.raw["file"],
            "source": self.raw.get("source"),
            "pages": self.raw["pages"],
            "elements": self.elements,
            "unattached_drawings": unattached,
            "stats": {
                "elements": len(self.elements),
                "with_facts": sum(e["quality"]["has_facts"] for e in self.elements),
                "llm_calls": self.llm_calls,
                                "model": getattr(self.client, "model_id", None),
            },
        }

    def _drawing_only(self, page: dict, d: dict) -> None:
        bb = d["bbox"]
        self.elements.append(
            {
                "file": self.raw["file"]["file"],
                "page": page["page"],
                "x": d["x"],
                "y": d["y"],
                "bbox": bb,
                "kind": None,
                "name": None,
                "role": "drawing",
                "locations": ([{"type": "grid", "cell": d["grid"]["cell"]}] if d.get("grid") else []),
                "bars": [],
                "characteristics": [{"name": "size_pt", "value": d["size_pt"]}, {"name": "shape", "value": d["shape"]}],
                "descriptions": [],
                "parts": {"texts": [], "drawings": [d["id"]]},
                "match": {"method": "drawing_only"},
                "quality": {"has_facts": False, "kind_basis": None},
                "evidence": [{"page": page["page"], "bbox": bb, "text": []}],
            }
        )


def _signature(t: dict) -> tuple:
    f = t["facts"]
    return (
        tuple(sorted(f"{b.get('count')}|{b.get('size')}|{b.get('spacing_mm')}|{b.get('secondary_count')}" for b in f["bars"])),
        tuple(sorted(json_key(c) for c in f["characteristics"])),
        re.sub(r"\s+", " ", t["text"].lower()) if not (f["bars"] or f["characteristics"]) else "",
    )


def json_key(c: dict) -> str:
    return f"{c.get('name')}={c.get('value')}"


def _reparse(t: dict, label: str | None) -> dict:
    """Re-read a table cell using its row header as the label of every line."""
    if not label:
        return t
    bars, chars, descs = [], [], []
    for line in t["lines"]:
        p = parse_line(line, label)
        bars += p["bars"]
        chars += p["characteristics"]
        if p["rest"]:
            descs.append({"text": p["rest"], "source_text": line, "row_header": label})
        elif not p["bars"] and not p["characteristics"]:
            descs.append({"text": line, "source_text": line, "row_header": label})
    tt = dict(t)
    tt["facts"] = {"bars": bars, "characteristics": chars, "descriptions": descs}
    return tt


def _quantity(members: list[dict]) -> int | None:
    for t in members:
        for line in t["lines"]:
            m = re.match(r"^\s*(\d+)\s*(?:REQUIS|REQ\.?|QTY|PCS)\b", line, re.I)
            if m:
                return int(m.group(1))
    return None


def _orientation(cells: list[dict]) -> str | None:
    """`columns` when the first column holds property names and the first row element names;
    `rows` when the first row holds property names and the first column element names."""
    first_col = [" ".join(t["lines"]) for t in cells if t["cell"]["col"] == 0 and t["cell"]["row"] > 0]
    first_row = [" ".join(t["lines"]) for t in cells if t["cell"]["row"] == 0 and t["cell"]["col"] > 0]
    if not first_col or not first_row:
        return None

    def wordy(items: list[str]) -> float:
        return sum(1 for s in items if re.fullmatch(r"[^\W\d_][^\d]*", s.strip())) / len(items)

    col_w, row_w = wordy(first_col), wordy(first_row)
    if col_w >= 0.6 and row_w < col_w:
        return "columns"
    if row_w >= 0.6 and col_w < row_w:
        return "rows"
    return None


def unify_raw(raw: dict, client: LlmClient) -> dict:
    return _Builder(raw, client).run()
