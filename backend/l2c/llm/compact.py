"""Compact, free-form descriptions of one or two elements for a question.

The model reads the element itself (what the page says about it), not a summary made by rules. Only
size is limited: a question stays at one or two elements and about 100 tokens.
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_TEXT = 150


def _clip(text: str, n: int = MAX_TEXT) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _dump(obj: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in obj.items() if v not in (None, [], {}, "")}, ensure_ascii=False, separators=(",", ":"))


def note_json(t: dict) -> str:
    """A text item as read from a page."""
    grid = (t.get("grid") or {}).get("cell")
    return _dump({"text": _clip(t["text"]), "grid": grid, "title": _clip(t.get("drawing_title") or "", 50)})


def drawing_json(d: dict, gap: float, leader: bool = False, inside: bool = False) -> str:
    return _dump(
        {
            "shape": d["shape"],
            "size_pt": [round(v) for v in d["size_pt"]],
            "grid": (d.get("grid") or {}).get("cell"),
            "gap_pt": round(gap),
            "leader_line_to_note": True if leader else None,
            "note_inside": True if inside else None,
        }
    )


def element_json(e: dict) -> str:
    """A unified element: kind, name, where, what it says."""
    loc = {}
    for l in e.get("locations", []):  # noqa: E741
        if l["type"] == "grid":
            loc["grid"] = l["cell"]
        elif l["type"] == "grid_cells":
            loc["grid"] = ",".join(l["cells"][:6])
        elif l["type"] == "level":
            loc["level"] = l["value"] + (f"..{l['to']}" if l.get("to") else "")
    bars = [b.get("source_text") for b in e.get("bars", [])][:3]
    chars = {c["name"]: c.get("value_mm") or c.get("value") for c in e.get("characteristics", []) if c["name"] not in {"symbol_size_pt", "size_pt", "shape"}}
    return _dump({"kind": e.get("kind"), "name": e.get("name"), **loc, "bars": bars, "chars": dict(list(chars.items())[:4])})
