"""Sheet context: drawing titles, level, scale, element kind, grid position.

The vocabularies here are the plain words of structural drawings (English and French). They only
supply *hints*; an element whose words are not in a list keeps its kind as None and its text intact.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from l2c.extract.grid import Grid
from l2c.extract.notation import canon_level
from l2c.extract.runs import Run

TITLE_WORDS = (
    "PLAN", "DETAIL", "ELEVATION", "ELEVATIONS", "COUPE", "SECTION", "VUE", "SERIE", "LEGENDE",
    "TABLEAU", "SCHEDULE", "VIEW", "LEGEND",
)  # fmt: skip

KIND_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("column", ("COL", "COLONNE", "COLUMN", "PILIER")),
    ("pier", ("PILASTRE", "PIER")),
    ("beam", ("POUTRE", "BEAM", "LINTEAU", "LINTEL")),
    ("shear_wall", ("REFEND", "CISAILLEMENT", "SHEAR")),
    ("wall", ("MUR", "WALL", "VOILE")),
    ("raft", ("RADIER", "RAFT")),
    ("footing", ("SEMELLE", "FOOTING", "EMPATTEMENT", "FONDATION", "FOUNDATION", "PIEU", "PILE")),
    ("slab", ("DALLE", "SLAB", "PLANCHER", "TERRASSE")),
    ("stair", ("ESCALIER", "STAIR")),
    ("opening", ("OUVERTURE", "OPENING", "TREMIE")),
)

LEVEL_RE = re.compile(
    r"(?:NIVEAU|LEVEL|NIV\.?|ETAGE|FLOOR)[\s.-]*(\d{1,2})\b|"
    r"(SOUS-SOL\s*S?\d{0,2}|BASEMENT\s*\d{0,2}|REZ-DE-CHAUSSEE|GROUND FLOOR|RDC|TOIT|ROOF|FDN|FND|FONDATIONS?|FOUNDATIONS?)\b",
    re.I,
)
SCALE_RE = re.compile(r"(?:ECH(?:ELLE)?|SCALE)\s*\.?\s*:?\s*(1\s*[:/]\s*\d+)", re.I)


def plain(text: str) -> str:
    t = unicodedata.normalize("NFD", text)
    return "".join(c for c in t if unicodedata.category(c) != "Mn").upper()


def kind_of(*texts: str | None) -> tuple[str | None, list[str]]:
    """The first kind whose word appears, preferring earlier (more specific) texts."""
    for text in texts:
        if not text:
            continue
        tokens = re.findall(r"[A-Z]+", plain(text))
        for kind, words in KIND_WORDS:
            for w in words:
                if any(t == w or (len(w) > 3 and t.startswith(w)) for t in tokens):
                    return kind, [w]
    return None, []


def leading_noun(lines: list[str]) -> str | None:
    """The object name a callout opens with, when its first line is words and no notation
    (`GARDE-CORPS 1100 HT.` -> `garde-corps`). None when the first line is a bar or a number."""
    if not lines:
        return None
    m = re.match(r"\s*([^\W\d_]{3,}(?:[-' ][^\W\d_]{2,}){0,2})", lines[0])
    if not m:
        return None
    noun = m.group(1).strip().lower()
    return noun if len(noun) >= 4 else None


SPAN_RE = re.compile(
    r"(?:NIV(?:EAU)?|LEVEL)?[\s.-]*(\d{1,2}|RDC|FDN|SS\d?|TOIT|ROOF)\s*@\s*(?:NIV(?:EAU)?|LEVEL)?[\s.-]*(\d{1,2}|RDC|FDN|SS\d?|TOIT|ROOF)",
    re.I,
)


def level_span(text: str) -> list[str]:
    """Levels named by a range such as `NIV-5@6` or `FDN@SS1` (both ends), canonical names."""
    m = SPAN_RE.search(plain(text))
    if not m:
        return []
    out = []
    for g in m.groups():
        g = g.strip()
        out.append(f"N{int(g)}" if g.isdigit() else (canon_level(g) or g.upper()))
    return out


_KIND_TOKENS = {w for _, ws in KIND_WORDS for w in ws}
_NOISE_TOKENS = {"BETON", "TYPIQUE", "ELEVATION", "ELEVATIONS", "COUPE", "DETAIL", "DETAILS", "VUE", "SERIE", "LEGENDE", "SECTION", "TABLEAU", "PLAN", "DU", "DE", "DES", "D", "LA", "LE", "PARTIE", "PART", "ARMATURES", "ARMATURE", "TITRE", "DESSIN", "PAGE"}


def level_guess(text: str, drop_first: bool = False, plan_title: bool = False) -> str | None:
    """A level name the vocabulary does not list (`MEZZANINE`): what is left of a title or file name
    after the project code, the kind words and filler words. One alphabetic word of 4 or more letters."""
    tokens = re.findall(r"[A-Z]+|\d+", plain(text))
    if plan_title and (not tokens or tokens[0] != "PLAN"):
        return None  # a drawing title names a level only as `PLAN <level> - ...`
    if drop_first and tokens:
        tokens = tokens[1:]
    left = [t for t in tokens if t not in _KIND_TOKENS and t not in _NOISE_TOKENS and not any(t.startswith(k) for k in _KIND_TOKENS if len(k) > 3)]
    words = [t for t in left if t.isalpha()]
    return words[0] if len(words) == 1 and len(words[0]) >= 4 and not [t for t in left if t.isdigit()] else None


def level_of(text: str) -> tuple[str | None, str | None]:
    """(canonical level, text as written) from a title or label."""
    m = LEVEL_RE.search(plain(text))
    if not m:
        return None, None
    written = m.group(0).strip()
    if m.group(1):
        return f"N{int(m.group(1))}", written
    if written in {"FND", "FDN"} or written.startswith(("FONDATION", "FOUNDATION")):
        return "FDN", written  # one name for the foundation level, however it is written
    return canon_level(written) or written, written


@dataclass(frozen=True)
class Title:
    text: str
    x: float
    y: float
    level: str | None
    level_text: str | None
    kind: str | None


def find_titles(runs: list[Run], h: float) -> list[Title]:
    out = []
    for r in runs:
        first = re.findall(r"[A-Z]+", plain(r.text))[:1]
        big = (r.y1 - r.y0) >= 1.2 * h
        if not first or first[0] not in TITLE_WORDS or len(r.text) < 8:
            continue
        if not (big or "-" in r.text):
            continue
        level, written = level_of(r.text)
        kind, _ = kind_of(r.text)
        out.append(Title(r.text.strip(), r.cx, r.cy, level, written, kind))
    distinct: list[Title] = []
    for t in sorted(out, key=lambda t: (t.y, t.x)):
        if all(abs(t.x - d.x) + abs(t.y - d.y) > 5 for d in distinct):
            distinct.append(t)
    return distinct


def nearest_title(titles: list[Title], x: float, y: float) -> Title | None:
    """Drawings sit above their title: prefer the nearest title below the point."""
    if not titles:
        return None
    below = [t for t in titles if t.y >= y]
    pool = below or titles
    return min(pool, key=lambda t: (t.x - x) ** 2 + (t.y - y) ** 2)


def find_scales(runs: list[Run]) -> list[str]:
    out = []
    for r in runs:
        m = SCALE_RE.search(plain(r.text))
        if m:
            out.append(m.group(1).strip())
    return out


def _axis(d: dict[str, float]) -> list[tuple[float, str]]:
    return sorted((p, k) for k, p in d.items())


def _around(axis: list[tuple[float, str]], pos: float) -> dict:
    below = [a for a in axis if a[0] <= pos]
    above = [a for a in axis if a[0] > pos]
    lo = below[-1] if below else None
    hi = above[0] if above else None
    nearest = min(axis, key=lambda a: (abs(a[0] - pos), a[1]))
    out: dict = {"nearest": nearest[1], "offset_pt": round(pos - nearest[0], 1)}
    if lo and hi:
        out["between"] = [lo[1], hi[1]]
        out["fraction"] = round((pos - lo[0]) / (hi[0] - lo[0]), 3)
    return out


def grid_position(grid: Grid | None, x: float, y: float) -> dict | None:
    if grid is None or not grid.rows or not grid.cols:
        return None
    row_pos, col_pos = (y, x) if grid.letters_on == "y" else (x, y)
    rows, cols = _axis(grid.rows), _axis(grid.cols)
    r, c = _around(rows, row_pos), _around(cols, col_pos)
    inside = rows[0][0] <= row_pos <= rows[-1][0] and cols[0][0] <= col_pos <= cols[-1][0]
    return {
        "type": "grid",
        "cell": f"{r['nearest']}-{c['nearest']}",
        "row": r,
        "col": c,
        "inside_grid": inside,
    }
