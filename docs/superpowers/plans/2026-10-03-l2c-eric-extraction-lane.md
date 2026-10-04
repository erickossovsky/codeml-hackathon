# L2C Extraction Lane (PDF to Metadata) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn plan PDFs and shop-drawing PDFs into the metadata bundle (`elements.json` in Appendix A form, `elements.ext.json` with quality, grid, levels, sheets, ids) deterministically, with every page's outcome reported, and without anything tied to one project's scale, language, rotation or grid style.

**Architecture:** `ingest` reads pages into words and small vector shapes in displayed coordinates. `extract` finds the sheet grid (either orientation), learns each page's own geometry (`calibrate`), anchors annotation blocks to column outlines with a one-to-one assignment, parses notation with regexes driven by a `Config`, scores quality with fixed formulas, and records per page which adapter ran or why none did. OCR (RapidOCR) is a second-tier path for pages without a text layer and feeds the same extractors. No ML in the core lane.

**Tech Stack:** Python 3.12, PyMuPDF, SciPy (Hungarian assignment), pydantic v2, RapidOCR (ONNX) for the second tier.

**Spec:** `docs/superpowers/specs/2026-10-03-l2c-design.md` (sections 4.1 to 4.2, 9.1, 10.2, 10.10, 10.15 to 10.19, 10.21 to 10.23).

**Prerequisite:** Plan 00 (`docs/superpowers/plans/2026-10-03-l2c-00-shared-foundation.md`) tasks F1 to F3 are merged on `dev` (scaffold, guard, contract, schemas). Ian's Task F4 (mock elements) is needed only by Task E13's witness test.

**Tiers and timing (starting about 9 PM):** E1 to E4 about 60 min; E5 to E8 about 90 min; E9 to E10 about 60 min (label learning is part of the core pipeline); E11 about 30 min, at which point the first real bundle of the fully-text project exists for Ian. That is the core gate (target about midnight to 1 AM for plan columns, about 3 AM with Ian's integration). E12 (OCR) and E13 (binding witness, hardening, calibration) are second tier and start only after the core gate.

## Global Constraints

- Python core, **Python 3.12** managed with `uv`; all code uses `pathlib` and writes text with `newline="\n"` (works on macOS and Windows).
- Output JSON must conform to the provided Appendix A schema: strict `elements.json` records contain exactly `id, source, fichier, feuillet, page, x, y, type_element, element, armature` and nothing else; extras live in `elements.ext.json`.
- Coordinates are PDF points of the page **as displayed** (rotation applied once), origin top-left, y downward; `x, y` is the centre of the annotation.
- Spacings written with a quote mark or bare number are inches (`config.default_spacing_unit`); `mm` is always explicit; stored as `espacement_mm`. Bar sizes come from `config.bar_sizes` (default `10M 15M 20M 25M 30M 35M`).
- `contract_version` is `"0.1.0"`; every metadata folder has a `manifest.json`; loaders fail loudly on a mismatch.
- Same input must give byte-identical output (sorted keys, no randomness without a fixed seed).
- **Nothing is hard-coded to one project**: distances are multiples of the page's own word height or gridline spacing (`calibrate.py`); language, notation, units and ratios live in `Config` and can be overridden with `--config file.json`.
- **Analysis is allowed; hard-coding what analysis finds is not.** Code, tests, fixtures, the spec and the plans contain no project names, sheet ids, grid cells, marks, real values or real notation strings (only published standard forms such as bar sizes `10M`..`35M`). Data-derived numbers and examples live only in the git-ignored `docs/private/` notes, which `scripts/guard.py` refuses to commit. Every behaviour must work on a synthetic document built differently (scale, rotation, language, labels, grid orientation, bar-size system).
- No document may be sent to any cloud service or external AI API; the pipeline imports no network library and runs offline. Confidential data (PDFs, derived JSON/XLSX/PDF outputs, models) is never committed: `data/`, `deliverables/`, `demo/` are git-ignored and `scripts/guard.py` blocks them in the pre-commit hook. Tests use synthetic data only.
- No commercially licensed software; dependencies are open source (PyMuPDF is AGPL-3.0: the source ships with the submission). `THIRD_PARTY.md` lists every dependency and license.
- Each lane edits only its own folders (`.github/CODEOWNERS`); `shared/` and `backend/l2c/contract/` change only through a contract PR reviewed by both people, which also regenerates `shared/schemas/` and `shared/fixtures/` in the same commit.
- Commits: short imperative subject; **no `Co-Authored-By` trailer and no "Generated with" line**. Do not push until Eric lifts the current no-push rule and `git log --all --stat` shows no PDF/XLSX/DXF/IFC/BCF/zip files.

## Review Focus

- A different project: another drawing scale, a stored page rotation, another language **and other labels (learned from the page, not assumed)**, the transposed grid, another bar-size system, another unit. Pinned by `test_robustness.py` (Task E10), the learning tests with an invented vocabulary (E9), the transposed-grid test (E4) and the config tests (E1).
- A file that cannot be opened, a page with no text or no grid, a page that raises: the run continues and the page carries the reason in `SheetInfo.layout`. Pinned in `test_pipeline.py` (E9) and `test_robustness.py` (E10).
- Annotation blocks that sit on either side of their column and next to gridlines only tens of points apart: bound one-to-one, not by nearest outline. Pinned in `test_anchor.py` (E5); measured on the fully-text project in Task E11.
- OCR output that drops spaces and dots, glues the mark to the spacing, or writes `LEVEL4` for `LEVEL 4`: the parsers must still read it. Pinned in `test_notation.py` (E3) and `test_ocr.py` (E12).
- Several elevation views on one shop page and blocks below the lowest level line; shop files whose names contain spaces and accents. Pinned in `test_columns_shop.py` (E8) and `test_pipeline.py` (E9).

---

### Task E1: Config: vocabulary, notation and tuning ratios in one place

**Files:**
- Create: `backend/l2c/extract/__init__.py` (empty), `backend/l2c/extract/config.py`
- Test: `backend/tests/extract/__init__.py` (empty), `backend/tests/extract/test_config.py`

**Interfaces:**
- Produces: `Config` (frozen, hashable dataclass) with vocabulary (`plan_column_titles`, `block_start`, `section_line`, `ties_line`, `end_line`, `shop_vert`, `shop_ties`, `elevation_line`, `level_names`, `level_numbered`), notation (`bar_size_pattern`, `bar_sizes`, `grid_letter_pattern`, `grid_number_pattern`, `grid_label_pattern`, `sheet_id_pattern`, `default_spacing_unit`), tuning ratios (`run_gap_word_heights`, `snap_tol_fraction`, `bind_dist_col_spacings`, `x_align_word_heights`, `col_above_word_heights`, `block_below_word_heights`, `line_gap_word_heights`, `strip_tol_fraction`, `ties_below_word_heights`, `ties_x_tol_word_heights`, `level_label_below_word_heights`, `level_x_fraction`, `grid_align_word_heights`, `grid_min_labels`, `outline_size_tolerance`), OCR knobs (`ocr_dpi`, `ocr_tile_px`, `ocr_overlap_fraction`, `ocr_orientation_probe`, `ocr_min_orientation_share`, `ocr_probe_tiles`, `ocr_min_conf`) and page heuristics (`min_text_words`, `min_vector_paths`, `min_words_native`). Methods: `starts(text, words) -> bool` (case-insensitive prefix test), `keywords() -> tuple[str, ...]`, `plan_title_regex() -> re.Pattern`. Module constants `DEFAULT_CONFIG`, function `load_config(path: Path | None) -> Config` (JSON overrides; unknown keys raise `ValueError`).

Why first: every later task reads its language, units and tolerances from here, so an unseen project in another language or notation needs a JSON file, not a code change.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev && git pull
git switch -c eric/e1-config
```

Create empty `backend/l2c/extract/__init__.py` and `backend/tests/extract/__init__.py`, then:

Create `backend/tests/extract/test_config.py`:

```python
import dataclasses
import json

import pytest

from l2c.extract.config import DEFAULT_CONFIG, Config, load_config


def test_defaults_cover_french_and_english_keywords():
    c = DEFAULT_CONFIG
    assert c.starts("ARM.: 4-25M", c.block_start) and c.starts("REINF.: 4-25M", c.block_start)
    assert c.starts("béton: 25MPa", c.end_line)  # matching ignores case
    assert c.starts("BÉTON: 25MPa", c.end_line) and c.starts("BETON: 25MPa", c.end_line)
    assert "ARM" in c.keywords() and "VERT" in c.keywords() and "EL:" in c.keywords()


def test_config_is_hashable_so_parsers_can_cache_per_config():
    assert hash(DEFAULT_CONFIG) == hash(Config())
    assert hash(dataclasses.replace(DEFAULT_CONFIG, default_spacing_unit="mm")) != hash(
        DEFAULT_CONFIG
    )


def test_json_overrides_replace_only_the_given_keys(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(
        json.dumps({"ties_line": ["STIRRUPS"], "level_names": {"BASEMENT": "SS"}}), encoding="utf-8"
    )
    c = load_config(f)
    assert c.ties_line == ("STIRRUPS",) and c.level_names == (("BASEMENT", "SS"),)
    assert c.block_start == DEFAULT_CONFIG.block_start  # untouched


def test_unknown_keys_fail_loudly(tmp_path):
    f = tmp_path / "c.json"
    f.write_text('{"ties_lines": ["x"]}', encoding="utf-8")  # typo
    with pytest.raises(ValueError, match="unknown config keys"):
        load_config(f)


def test_no_config_means_defaults():
    assert load_config(None) is DEFAULT_CONFIG
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest backend/tests/extract/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.extract.config'`.

- [ ] **Step 3: Write the config**

Create `backend/l2c/extract/config.py`:

```python
"""One place for everything that may differ between projects, languages and detailers.

Two kinds of values live here:
- *vocabulary and notation* (keywords, level names, bar-size and grid-label patterns, units):
  override per project with a JSON file (`--config`), no code change;
- *tuning ratios* (multiples of a page's own word height or gridline spacing): the defaults
  worked on the development projects, but they are ratios, so a different drawing scale or font
  size changes nothing.
Nothing in the extraction code uses a fixed distance in points.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

LEVEL_NAMES: tuple[tuple[str, str], ...] = (
    ("SOUS-SOL", "SS"),
    ("BASEMENT", "SS"),
    ("REZ-DE-CHAUSSEE", "RDC"),
    ("RDC", "RDC"),
    ("GROUND FLOOR", "RDC"),
    ("GROUND", "RDC"),
    ("TOIT APPENTIS", "TOIT_APP"),
    ("TOIT", "TOIT"),
    ("ROOF", "TOIT"),
)


@dataclass(frozen=True)
class Config:
    # ---- vocabulary (case-insensitive, accents ignored where noted)
    plan_column_titles: tuple[str, ...] = ("PLAN DES COLONNES", "COLUMN PLAN", "COLUMNS PLAN")
    block_start: tuple[str, ...] = ("ARM", "REINF")
    section_line: tuple[str, ...] = ("COL.", "COL ", "COLUMN ")
    ties_line: tuple[str, ...] = ("LIG", "TIES", "STIRRUPS")
    end_line: tuple[str, ...] = ("BÉTON", "BETON", "CONCRETE")
    shop_vert: tuple[str, ...] = ("VERT",)
    shop_ties: tuple[str, ...] = ("ÉTRI", "ETRI", "TIES", "STIRRUP")
    elevation_line: tuple[str, ...] = ("EL.", "EL:", "ELEV.", "EL ")  # OCR often drops the dot
    level_names: tuple[tuple[str, str], ...] = LEVEL_NAMES
    level_numbered: tuple[str, ...] = ("NIVEAU", "LEVEL", "FLOOR")
    # ---- notation
    bar_size_pattern: str = r"(?:10|15|20|25|30|35)M"
    bar_sizes: tuple[str, ...] = ("10M", "15M", "20M", "25M", "30M", "35M")
    grid_letter_pattern: str = r"^[A-Z]{1,2}$"  # rows may continue past Z: AA, BB, ...
    grid_number_pattern: str = r"^\d{1,2}(?:\.\d)?$"
    grid_label_pattern: str = (
        r"^([A-Z])-([1-9]\d?(?:\.\d)?)$"  # a grid cell like J-12; C-01 is a mark, not a cell
    )
    sheet_id_pattern: str = r"^S-\d{3}$"
    default_spacing_unit: str = "in"  # a bare number after @ is inches; "mm" is always explicit
    # ---- tuning ratios (multiples of the page's own geometry)
    run_gap_word_heights: float = 1.6
    snap_tol_fraction: float = 0.25  # of the typical (median) gridline spacing
    bind_dist_col_spacings: float = 2.5
    x_align_word_heights: float = 0.5
    col_above_word_heights: float = 1.8
    block_below_word_heights: float = 5.6
    line_gap_word_heights: float = 2.0
    strip_tol_fraction: float = 0.54  # of the median label spacing
    ties_below_word_heights: float = 2.5
    ties_x_tol_word_heights: float = 0.75
    level_label_below_word_heights: float = 1.8
    level_x_fraction: float = 0.15  # level names sit in the left strip of the sheet
    grid_align_word_heights: float = 0.6  # labels on one axis line up within this distance
    grid_min_labels: int = 4
    outline_size_tolerance: float = 1.0  # reject shapes more than 2x the typical outline size
    # ---- OCR (only for pages without a text layer)
    ocr_dpi: int = 200
    ocr_tile_px: int = 2000
    ocr_overlap_fraction: float = 0.1
    ocr_orientation_probe: bool = False  # RapidOCR reads vertical text itself; probing is 4x slower
    ocr_min_orientation_share: float = 0.5  # (probe only) also read an orientation with this share
    ocr_probe_tiles: int = 3
    ocr_min_conf: float = 0.3
    # ---- page classification (heuristics for choosing OCR, not for extraction)
    min_text_words: int = 150
    min_vector_paths: int = 300
    min_words_native: int = 10

    # helpers -----------------------------------------------------------------------
    def starts(self, text: str, words: tuple[str, ...]) -> bool:
        up = text.upper().lstrip()
        return any(up.startswith(w.upper()) for w in words)

    def keywords(self) -> tuple[str, ...]:
        """Words that start a labelled run on a sheet (stripped, upper case)."""
        groups = (
            self.block_start,
            self.section_line,
            self.ties_line,
            self.end_line,
            self.shop_vert,
            self.shop_ties,
            self.elevation_line,
        )
        return tuple(sorted({w.strip().upper() for g in groups for w in g if w.strip()}))

    def plan_title_regex(self) -> re.Pattern[str]:
        titles = "|".join(re.escape(t) for t in self.plan_column_titles)
        names = "|".join(
            sorted(
                (re.escape(n).replace("\\ ", r"\s+") for n, _ in self.level_names),
                key=len,
                reverse=True,
            )
        )
        numbered = "|".join(re.escape(n) for n in self.level_numbered)
        return re.compile(
            rf"(?:{titles})\s*-\s*((?:{numbered})\s*\d+|{names}|REZ-DE-CHAUSS[ÉE]E)", re.IGNORECASE
        )


DEFAULT_CONFIG = Config()


def load_config(path: Path | None) -> Config:
    """Defaults, overridden by any keys present in a JSON file. Unknown keys are an error."""
    if path is None:
        return DEFAULT_CONFIG
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Config)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    merged = asdict(DEFAULT_CONFIG)
    for key, value in raw.items():
        if key == "level_names":
            merged[key] = tuple(
                (str(a), str(b)) for a, b in (value.items() if isinstance(value, dict) else value)
            )
        elif isinstance(value, list):
            merged[key] = tuple(value)
        else:
            merged[key] = value
    return Config(**merged)
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_config.py -v
python scripts/check.py
```

Expected: 5 passed; `CHECK PASSED`.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/extract backend/tests/extract
git commit -m "Add extraction config"
```

```bash
git switch dev && git merge --no-ff eric/e1-config
```


---

### Task E2: Ingest: PDF pages to words, shapes, layer kind and sheet id

**Files:**
- Create: `backend/l2c/ingest/__init__.py` (empty), `backend/l2c/ingest/pages.py`
- Create: `backend/tests/extract/pdfmaker.py` (synthetic-PDF helpers used by almost every later test)
- Test: `backend/tests/extract/test_ingest.py`

**Interfaces:**
- Consumes: `Config`, `DEFAULT_CONFIG` (E1).
- Produces: `Word(text, x0, y0, x1, y1, conf=None, original=None)` with `.cx`, `.cy`; `Shape(x0, y0, x1, y1)` with `.w .h .cx .cy`; `PageData(fichier, page, width, height, rotation, words, shapes, n_paths, n_images, layer, feuillet, vertical_text, source)`; `load_pdf(path, fichier=None, config=DEFAULT_CONFIG) -> list[PageData]`; `classify_layer(n_words, n_paths, n_images, config) -> "text"|"vector"|"image"|"empty"`; `title_block_sheet(words, width, height, config) -> str | None`; `vertical_text_fraction(words) -> float`. All coordinates are in PDF points of the page **as displayed**: `load_pdf` applies `page.rotation_matrix` once (PyMuPDF returns unrotated coordinates).
- `pdfmaker.py` produces: `new_doc(width, height)`, `put(page, x, y, text, size=8.0)` (top-left anchored), `rect(page, cx, cy, w=12, h=18)`, `save(doc, path)`, `DisplayPage(width, height, rotation)` (draw in displayed coordinates on a page stored with /Rotate 0/90/180/270), `rasterize(pdf, out, dpi)` (turn every page into a picture with no text layer).

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev && git pull
git switch -c eric/e2-ingest
```

Create empty `backend/l2c/ingest/__init__.py`, then:

Create `backend/tests/extract/pdfmaker.py`:

```python
"""Build small synthetic PDFs for tests. No real drawing data is ever used in tests."""

from pathlib import Path

import pymupdf


def new_doc(width: float = 1200, height: float = 900):
    doc = pymupdf.open()
    return doc, doc.new_page(width=width, height=height)


def put(page, x: float, y: float, text: str, size: float = 8.0) -> None:
    """Insert text with its top-left near (x, y)."""
    page.insert_text((x, y + size), text, fontsize=size, fontname="helv")


def rect(page, cx: float, cy: float, w: float = 12.0, h: float = 18.0) -> None:
    page.draw_rect(pymupdf.Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), color=(0, 0, 0))


def save(doc, path: Path) -> Path:
    doc.save(path)
    doc.close()
    return path


class DisplayPage:
    """Draw in *displayed* coordinates on a page whose /Rotate may be 0, 90, 180 or 270.

    Real sheets are often stored rotated; content is drawn so that it looks upright once the
    viewer applies the rotation. This maps displayed coordinates back to the stored page.
    """

    def __init__(self, width: float, height: float, rotation: int = 0):
        self.doc = pymupdf.open()
        stored_w, stored_h = (height, width) if rotation in (90, 270) else (width, height)
        self.page = self.doc.new_page(width=stored_w, height=stored_h)
        self.page.set_rotation(rotation)
        self.rotation = rotation
        self.inverse = ~self.page.rotation_matrix

    def _stored(self, x: float, y: float) -> pymupdf.Point:
        return pymupdf.Point(x, y) * self.inverse

    def put(self, x: float, y: float, text: str, size: float = 8.0) -> None:
        # baseline is size below the displayed top-left, as in `put`
        p = self._stored(x, y + size)
        self.page.insert_text(p, text, fontsize=size, fontname="helv", rotate=self.rotation)

    def rect(self, cx: float, cy: float, w: float = 12.0, h: float = 18.0) -> None:
        a = self._stored(cx - w / 2, cy - h / 2)
        b = self._stored(cx + w / 2, cy + h / 2)
        self.page.draw_rect(pymupdf.Rect(a, b).normalize(), color=(0, 0, 0))

    def save(self, path: Path) -> Path:
        self.doc.save(path)
        self.doc.close()
        return path


def rasterize(pdf: Path, out: Path, dpi: int = 150) -> Path:
    """Replace every page of `pdf` by a picture of it: same look, no text layer."""
    import pymupdf as mu

    src = mu.open(pdf)
    doc = mu.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi, colorspace=mu.csRGB, alpha=False)
        new = doc.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=pix)
    doc.save(out)
    return out
```

Create `backend/tests/extract/test_ingest.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest backend/tests/extract/test_ingest.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.ingest.pages'`.

- [ ] **Step 3: Write ingest**

Create `backend/l2c/ingest/pages.py`:

```python
"""Read a PDF into plain page data: words, small closed shapes, layer kind, sheet id.

All coordinates are in PDF points of the page *as displayed* (rotation applied once here),
origin top-left, y downward. Every other module works in this frame.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from l2c.extract.config import DEFAULT_CONFIG, Config

# Candidate column outlines are small shapes: between these shares of the page width. The exact
# size is then learned per sheet (anchor.find_outlines), so no fixed point size is assumed.
SHAPE_MIN_PAGE_FRACTION = 0.001
SHAPE_MAX_PAGE_FRACTION = 0.05
MAX_SHAPE_PATH_ITEMS = 8  # a closed rectangle-like path has only a few segments


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float | None = None  # OCR confidence 0..1; None for native text
    original: str | None = None  # text before vocabulary snapping, when it was changed

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class Shape:
    """Bounding box of a small closed vector shape (candidate column outline)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class PageData:
    fichier: str
    page: int  # 1-based
    width: float
    height: float
    rotation: int
    words: list[Word] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    n_paths: int = 0
    n_images: int = 0
    layer: str = "empty"  # text | vector | image | empty
    feuillet: str | None = None
    vertical_text: float = 0.0  # share of words that are taller than wide (rotated text)
    source: str = "native"  # native | ocr


def classify_layer(
    n_words: int, n_paths: int, n_images: int, config: Config = DEFAULT_CONFIG
) -> str:
    if n_words >= config.min_text_words:
        return "text"
    if n_images > 0 and n_paths < 10 * config.min_vector_paths:
        return "image"
    if n_paths >= config.min_vector_paths:
        return "vector"
    return "empty"


def vertical_text_fraction(words: list[Word]) -> float:
    long = [w for w in words if len(w.text) >= 3]
    if not long:
        return 0.0
    return sum(1 for w in long if (w.y1 - w.y0) > 1.5 * (w.x1 - w.x0)) / len(long)


def title_block_sheet(
    words: list[Word], width: float, height: float, config: Config = DEFAULT_CONFIG
) -> str | None:
    """Sheet id from the title block (pattern in config): the bottom-most, right-most match."""
    sheet_re = re.compile(config.sheet_id_pattern)
    hits = [
        w for w in words if sheet_re.match(w.text) and w.x0 > 0.6 * width and w.y0 > 0.7 * height
    ]
    if not hits:
        return None
    return max(hits, key=lambda w: (round(w.y0), w.x0)).text


def _rect_through(matrix: pymupdf.Matrix, r: pymupdf.Rect) -> pymupdf.Rect:
    out = pymupdf.Rect(r) * matrix
    out.normalize()
    return out


def _read_page(page: pymupdf.Page, fichier: str, number: int, config: Config) -> PageData:
    m = page.rotation_matrix
    words = []
    for w in page.get_text("words"):
        r = _rect_through(m, pymupdf.Rect(w[:4]))
        words.append(Word(w[4], r.x0, r.y0, r.x1, r.y1))
    words.sort(key=lambda w: (round(w.y0, 1), w.x0, w.text))
    drawings = page.get_drawings()
    lo = SHAPE_MIN_PAGE_FRACTION * page.rect.width
    hi = SHAPE_MAX_PAGE_FRACTION * page.rect.width
    shapes: list[Shape] = []
    for d in drawings:
        r = d["rect"]
        if lo <= r.width <= hi and lo <= r.height <= hi and len(d["items"]) <= MAX_SHAPE_PATH_ITEMS:
            t = _rect_through(m, r)
            shapes.append(Shape(t.x0, t.y0, t.x1, t.y1))
    shapes.sort(key=lambda s: (round(s.cy, 1), s.cx))
    n_images = len(page.get_images())
    return PageData(
        fichier=fichier,
        page=number,
        width=page.rect.width,
        height=page.rect.height,
        rotation=page.rotation,
        words=words,
        shapes=shapes,
        n_paths=len(drawings),
        n_images=n_images,
        layer=classify_layer(len(words), len(drawings), n_images, config),
        feuillet=title_block_sheet(words, page.rect.width, page.rect.height, config),
        vertical_text=round(vertical_text_fraction(words), 3),
    )


def load_pdf(
    path: Path, fichier: str | None = None, config: Config = DEFAULT_CONFIG
) -> list[PageData]:
    name = fichier or path.name
    with pymupdf.open(path) as doc:
        return [_read_page(p, name, i + 1, config) for i, p in enumerate(doc)]
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_ingest.py -v
```

Expected: 4 passed, including `test_rotation_is_applied_once_to_words_and_shapes` (the displayed position of text on a /Rotate 90 page equals the rotation of its unrotated position).

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/ingest backend/tests/extract
git commit -m "Add PDF ingest with rotation handling"
```

```bash
git switch dev && git merge --no-ff eric/e2-ingest
```


---

### Task E3: Notation: bar sizes, spacings, shop lines, levels

**Files:**
- Create: `backend/l2c/extract/notation.py`
- Test: `backend/tests/extract/test_notation.py`

**Interfaces:**
- Consumes: `Config`, `DEFAULT_CONFIG` (E1); `FOOT_MM`, `INCH_MM` from `l2c.contract.constants`.
- Produces (all take an optional `config` last argument): `parse_count_size(text) -> CountSize(count, size) | None` (`4-25M`), `parse_size_spacing(text) -> SizeSpacing(size, spacing_mm) | None` (`10M@6" c/c` is 152.4 mm; `@200mm` is 200; bare numbers use `config.default_spacing_unit`), `parse_section(text) -> (mm, mm) | None`, `parse_elevation(text) -> mm | None` (`157' - 9"`, `12.5 m`), `parse_shop_vert(text) -> ShopVert(count, size, mark) | None`, `parse_shop_ties(text) -> ShopTies(count, size, mark, spacing_mm | None) | None`, `parse_grid_label(text) -> (letter, number) | None` (`J-12`; `C-01` is a mark, not a cell), `canon_level(text) -> "SS"|"RDC"|"N<k>"|"TOIT"|"TOIT_APP"| None`, `plan_column_level(page_text) -> level | None`, `inches_to_mm`. The shop regexes tolerate what OCR does to text (dropped spaces, dropped quote mark, mark glued to the spacing).

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev && git pull
git switch -c eric/e3-notation
```

Create `backend/tests/extract/test_notation.py`:

```python
import pytest

from l2c.extract import notation as N


def test_count_size():
    assert N.parse_count_size("ARM.: 4-25M") == N.CountSize(4, "25M")
    assert N.parse_count_size("ARM.: 12 - 35M +GOUJ.") == N.CountSize(12, "35M")
    assert N.parse_count_size("ARM.: 4-26M") is None
    assert N.parse_count_size("25MPa") is None


@pytest.mark.parametrize(
    "text, size, mm",
    [
        ('LIG.: 10M@6" c/c', "10M", 152.4),
        ("LIG.: 15M@8'' c/c", "15M", 203.2),
        ("H.:15M@200mm c/c", "15M", 200.0),
        ("10M @ 4”", "10M", 101.6),
    ],
)
def test_size_spacing(text, size, mm):
    assert N.parse_size_spacing(text) == N.SizeSpacing(size, mm)


def test_section_and_feet_inches():
    assert N.parse_section('COL. 18"x20"') == (457.2, 508.0)
    assert N.parse_feet_inches("143' - 3\"") == pytest.approx(143 * 304.8 + 3 * 25.4)
    assert N.parse_feet_inches("90' - 0\"") == pytest.approx(27432.0)
    assert N.parse_feet_inches("no numbers") is None


def test_shop_vert_and_ties():
    assert N.parse_shop_vert("VERT: 4 25M B7-01") == N.ShopVert(4, "25M", "B7-01")
    t = N.parse_shop_ties('ÉTRI: 25 10M T4X21 @6"')
    assert t == N.ShopTies(25, "10M", "T4X21", 152.4)
    assert N.parse_shop_ties("ÉTRI: 6 10M T4X21").spacing_mm is None
    assert N.parse_shop_vert("VERTICALES") is None


def test_grid_label_and_levels():
    assert N.parse_grid_label("J-12") == ("J", 12.0)
    assert N.parse_grid_label("A-7.5") == ("A", 7.5)
    assert N.parse_grid_label("C-01") is None  # element mark, not a grid cell
    assert N.canon_level("NIVEAU 4") == "N4"
    assert N.canon_level("REZ-DE-CHAUSSÉE") == "RDC"
    assert N.canon_level("SOUS-SOL") == "SS"
    assert N.canon_level("TOIT APPENTIS") == "TOIT_APP"
    assert N.canon_level("TOIT") == "TOIT"
    assert N.canon_level("ECHELLE") is None
    assert N.plan_column_level("PLAN DES COLONNES - NIVEAU 4  ECH: 1/8") == "N4"
    assert N.plan_column_level("PLAN DES COLONNES - SOUS-SOL - A") == "SS"
    assert N.plan_column_level("PLAN DES POUTRES") is None


def test_shop_notation_tolerates_what_ocr_does_to_it():
    # OCR often drops spaces and the quote mark; the mark must not swallow the spacing
    t = N.parse_shop_ties("ETRI:1310MT4X18@9")
    assert t == N.ShopTies(13, "10M", "T4X18", 228.6)
    v = N.parse_shop_vert("VERT:425MB7-01")
    assert v == N.ShopVert(4, "25M", "B7-01")
    assert N.parse_shop_ties('ETRI:510M T4X21@6"').spacing_mm == 152.4


def test_level_names_tolerate_dropped_spaces_from_ocr():
    assert N.canon_level("NIVEAU4") == "N4" and N.canon_level("LEVEL12") == "N12"
    assert N.plan_column_level("PLAN DES COLONNES - NIVEAU2") == "N2"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest backend/tests/extract/test_notation.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.extract.notation'`.

- [ ] **Step 3: Write the parsers**

Create `backend/l2c/extract/notation.py`:

```python
"""Deterministic parsers for rebar notation. Patterns and units come from the Config."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from l2c.contract.constants import FOOT_MM, INCH_MM
from l2c.extract.config import DEFAULT_CONFIG, Config

_QUOTES = "\"”″'"


@dataclass(frozen=True)
class CountSize:
    count: int
    size: str


@dataclass(frozen=True)
class SizeSpacing:
    size: str
    spacing_mm: float


@dataclass(frozen=True)
class ShopTies:
    count: int
    size: str
    mark: str
    spacing_mm: float | None


@dataclass(frozen=True)
class ShopVert:
    count: int
    size: str
    mark: str


def inches_to_mm(inches: float) -> float:
    return round(inches * INCH_MM, 3)


def _spacing_mm(value: float, unit: str | None, config: Config) -> float:
    unit = (unit or "").lower()
    if unit == "mm":
        return value
    if unit in {"cm"}:
        return round(value * 10.0, 3)
    if unit:  # a quote mark
        return inches_to_mm(value)
    return value if config.default_spacing_unit == "mm" else inches_to_mm(value)


@lru_cache(maxsize=64)
def _count_size_re(size: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\d)(\d{{1,2}})\s*-\s*({size})\b")


@lru_cache(maxsize=64)
def _size_spacing_re(size: str) -> re.Pattern[str]:
    return re.compile(
        rf"({size})\s*@\s*(\d+(?:\.\d+)?)\s*(mm|cm|[{_QUOTES}]{{1,2}})?", re.IGNORECASE
    )


@lru_cache(maxsize=64)
def _shop_re(words: tuple[str, ...], size: str, ties: bool) -> re.Pattern[str]:
    alt = "|".join(re.escape(w) for w in words)
    base = rf"(?:{alt})\.?:?\s*(\d{{1,3}})\s*({size})\s*([^\s@]+)"
    if ties:
        base += rf"(?:\s*@\s*(\d+(?:\.\d+)?)\s*(mm|cm|[{_QUOTES}]{{1,2}})?)?"
    return re.compile(base, re.IGNORECASE)


def parse_count_size(text: str, config: Config = DEFAULT_CONFIG) -> CountSize | None:
    m = _count_size_re(config.bar_size_pattern).search(text)
    return CountSize(int(m.group(1)), m.group(2).upper()) if m else None


def parse_size_spacing(text: str, config: Config = DEFAULT_CONFIG) -> SizeSpacing | None:
    """`10M@6" c/c` -> 152.4 mm; `10M@200mm` -> 200 mm; bare numbers use the config unit."""
    m = _size_spacing_re(config.bar_size_pattern).search(text)
    if not m:
        return None
    return SizeSpacing(m.group(1).upper(), _spacing_mm(float(m.group(2)), m.group(3), config))


def parse_section(text: str) -> tuple[float, float] | None:
    """`COL. 18"x20"` -> (406.4, 609.6) mm (inches) ; `COL. 400x600mm` -> (400, 600)."""
    m = re.search(
        rf"COL\.?\s*(\d+(?:\.\d+)?)\s*[{_QUOTES}]?\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(mm)?", text
    )
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    return (a, b) if m.group(3) else (inches_to_mm(a), inches_to_mm(b))


def parse_elevation(text: str) -> float | None:
    """Elevation in mm from `143' - 3"`, `12.50 m` or `3500 mm`."""
    metric = re.search(r"(-?\d+(?:\.\d+)?)\s*(mm|m)\b", text)
    if metric and "'" not in text:
        v = float(metric.group(1))
        return round(v if metric.group(2) == "mm" else v * 1000.0, 3)
    m = re.search(rf"(\d+)\s*'\s*-?\s*(\d+(?:\.\d+)?)?\s*[{_QUOTES[:-1]}]?", text)
    if not m:
        return None
    feet = int(m.group(1))
    inches = float(m.group(2)) if m.group(2) else 0.0
    return round(feet * FOOT_MM + inches * INCH_MM, 3)


def parse_feet_inches(text: str) -> float | None:  # kept for readability at call sites
    return parse_elevation(text)


def parse_shop_vert(text: str, config: Config = DEFAULT_CONFIG) -> ShopVert | None:
    """`VERT: 4 25M B7-01`."""
    m = _shop_re(config.shop_vert, config.bar_size_pattern, False).search(text)
    return ShopVert(int(m.group(1)), m.group(2).upper(), m.group(3)) if m else None


def parse_shop_ties(text: str, config: Config = DEFAULT_CONFIG) -> ShopTies | None:
    """`ÉTRI: 6 10M T4X21 @6"` (spacing optional)."""
    m = _shop_re(config.shop_ties, config.bar_size_pattern, True).search(text)
    if not m:
        return None
    spacing = _spacing_mm(float(m.group(4)), m.group(5), config) if m.group(4) else None
    return ShopTies(int(m.group(1)), m.group(2).upper(), m.group(3), spacing)


def parse_grid_label(text: str, config: Config = DEFAULT_CONFIG) -> tuple[str, float] | None:
    """`J-12` -> ("J", 12.0); `A-7.5` -> ("A", 7.5)."""
    m = re.match(config.grid_label_pattern, text.strip())
    return (m.group(1), float(m.group(2))) if m else None


def _plain(text: str) -> str:
    """Upper case with accents removed, so `Étage` and `ETAGE` compare equal."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper().strip()


def canon_level(text: str, config: Config = DEFAULT_CONFIG) -> str | None:
    """Canonical level: SS, RDC, N2.., TOIT. None when the text is not a level name."""
    t = _plain(text)
    numbered = "|".join(re.escape(n) for n in config.level_numbered)
    m = re.match(rf"(?:{numbered})\s*(\d{{1,2}})\b", t)  # OCR often drops the space
    if m:
        return f"N{int(m.group(1))}"
    for name, canon in sorted(config.level_names, key=lambda kv: len(kv[0]), reverse=True):
        if t.startswith(_plain(name)):
            return canon
    return None


def plan_column_level(page_text: str, config: Config = DEFAULT_CONFIG) -> str | None:
    """Level from a column-plan title such as `PLAN DES COLONNES - NIVEAU 4`."""
    m = config.plan_title_regex().search(page_text)
    return canon_level(m.group(1), config) if m else None
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_notation.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/extract/notation.py backend/tests/extract/test_notation.py
git commit -m "Add rebar notation parsers"
```

```bash
git switch dev && git merge --no-ff eric/e3-notation
```


---

### Task E4: Geometry: text runs, grid detection, per-page calibration

**Files:**
- Create: `backend/l2c/extract/runs.py`, `backend/l2c/extract/grid.py`, `backend/l2c/extract/calibrate.py`
- Test: `backend/tests/extract/test_grid.py`, `backend/tests/extract/test_calibrate.py`

**Interfaces:**
- Consumes: `Word`, `load_pdf` (E2), `Config` (E1).
- Produces: `Run(text, x0, y0, x1, y1, words)` and `text_runs(words, gap=12.0, line_tol=3.0, split_before=()) -> list[Run]` (a line split into phrases at gaps, and before any keyword so nearly touching blocks stay apart); `median_word_height(words) -> float`; `cluster_1d(values, tol) -> list[list[int]]` (single-linkage grouping, independent of bucket edges); `Grid(rows, cols, letters_on)` with `.center(row, col) -> (x, y)`, `.snap(cx, cy, tol) -> (row, col, grid_conf) | None`, `.nearest_row`, `.nearest_col`; `fit_grid(words, config) -> Grid | None` (detects whether letters run down an edge `letters_on="y"` or along one `"x"`, scoring candidate axes by mirrored labels on the opposite edge, monotonic order and count; handles rows past Z such as `AA`, `BB`); `PageScale(word_h, run_gap, snap_tol, max_bind_dist, row_spacing, col_spacing)` and `calibrate(words, grid=None, config) -> PageScale` (every tolerance is a multiple of the page's own geometry).

- [ ] **Step 1: Branch and write the failing tests**

```bash
git switch dev && git pull
git switch -c eric/e4-geometry
```

Create `backend/tests/extract/test_grid.py`:

```python
from l2c.extract.grid import Grid, fit_grid
from l2c.extract.runs import text_runs
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import new_doc, put, save

ROWS = {"A": 700, "B": 640, "C": 560, "D": 480, "E": 400, "F": 300}
COLS = {"1": 900, "2": 850, "3": 790, "3.8": 740, "4": 690, "5": 600, "6": 543}


def grid_pdf(tmp_path):
    doc, page = new_doc(1100, 800)
    for letter, y in ROWS.items():
        put(page, 40, y, letter)
        put(page, 1000, y, letter)  # same letters on the opposite edge
    for label, x in COLS.items():
        put(page, x, 40, label)
        put(page, x, 760, label)
    put(page, 500, 400, "ARM.: 4-25M")  # noise
    return save(doc, tmp_path / "grid.pdf")


def test_fit_grid_finds_rows_cols_and_fractional_lines(tmp_path):
    (page,) = load_pdf(grid_pdf(tmp_path))
    grid = fit_grid(page.words)
    assert grid is not None
    assert set(grid.rows) == set(ROWS) and set(grid.cols) == set(COLS)
    assert abs(grid.rows["C"] - (560 + 4)) < 3
    assert abs(grid.cols["3.8"] - (740 + 6)) < 8  # label center, not left edge


def test_fit_grid_requires_enough_labels(tmp_path):
    doc, page = new_doc()
    put(page, 40, 100, "A")
    put(page, 100, 40, "1")
    (p,) = load_pdf(save(doc, tmp_path / "few.pdf"))
    assert fit_grid(p.words) is None


def test_snap_confidence_drops_when_between_close_gridlines():
    g = Grid(rows={"A": 100.0, "B": 200.0}, cols={"3.4": 1400.0, "4": 1352.0})
    exact = g.snap(1352.0, 100.0, 14.0)
    assert exact == ("A", "4", 1.0)
    ambiguous = g.snap(1376.0, 104.0, tol=30.0)  # halfway between two close gridlines
    assert ambiguous is not None and ambiguous[1] in {"3.4", "4"} and ambiguous[2] < 0.1
    assert g.snap(1376.0, 104.0, 14.0) is None  # default tolerance rejects a point on neither line
    assert g.snap(900.0, 100.0, 14.0) is None  # too far from any gridline


def test_text_runs_split_on_gaps(tmp_path):
    doc, page = new_doc()
    put(page, 100, 100, "ARM.: 4-25M")
    put(page, 300, 100, "ARM.: 6-20M")
    (p,) = load_pdf(save(doc, tmp_path / "runs.pdf"))
    runs = text_runs(p.words)
    assert [r.text for r in runs] == ["ARM.: 4-25M", "ARM.: 6-20M"]


def test_rows_may_continue_past_z_and_noise_letters_are_ignored(tmp_path):
    doc, page = new_doc(1100, 800)
    rows = ["X", "Y", "Z", "AA", "BB", "CC"]
    for i, r in enumerate(rows):
        put(page, 40, 100 + 80 * i, r)
        put(page, 1000, 100 + 80 * i, r)
    for i in range(1, 8):
        put(page, 100 * i, 40, str(i))
        put(page, 100 * i, 740, str(i))
    for i in range(30):  # many identical noise letters, like "/ N" in concrete notes
        put(page, 200 + 7 * i, 300 + 11 * (i % 5), "N")
    (p,) = load_pdf(save(doc, tmp_path / "wide.pdf"))
    grid = fit_grid(p.words)
    assert grid is not None and list(grid.rows) == rows
    assert len(grid.cols) == 7


def transposed_grid_pdf(tmp_path, noise=True):
    """Letters along the top edge, numbers down the side: the opposite of the first convention."""
    doc, page = new_doc(1400, 900)
    letters = ["A", "B", "C", "D", "E", "F", "G"]
    for i, ch in enumerate(letters):
        put(page, 150 + 150 * i, 40, ch)
    for i in range(1, 7):
        put(page, 40, 100 + 110 * i, str(i))
        put(page, 1300, 100 + 110 * i, str(i))  # mirrored on the opposite edge
    if noise:
        for i in range(25):
            put(page, 300 + 9 * i, 200 + 13 * (i % 7), str(i % 9 + 1))
    return save(doc, tmp_path / "transposed.pdf")


def test_transposed_grid_is_detected_with_its_orientation(tmp_path):
    (p,) = load_pdf(transposed_grid_pdf(tmp_path))
    grid = fit_grid(p.words)
    assert grid is not None and grid.letters_on == "x"
    assert list(grid.rows) == ["A", "B", "C", "D", "E", "F", "G"]
    assert list(grid.cols) == ["1", "2", "3", "4", "5", "6"]
    x, y = grid.center("C", "3")
    assert abs(x - (150 + 300 + 2)) < 8 and abs(y - (100 + 330 + 4)) < 8
    assert grid.snap(x + 3, y - 2, 14.0)[:2] == ("C", "3")


def test_the_usual_convention_still_reports_letters_on_y(tmp_path):
    (p,) = load_pdf(grid_pdf(tmp_path))
    assert fit_grid(p.words).letters_on == "y"
```

Create `backend/tests/extract/test_calibrate.py`:

```python
import pytest

from l2c.extract.calibrate import calibrate
from l2c.extract.grid import Grid
from l2c.ingest.pages import Word


def words(h: float) -> list[Word]:
    return [Word("ARM.:", 0, i * 3 * h, 4 * h, i * 3 * h + h) for i in range(10)]


@pytest.mark.parametrize("scale", [0.5, 1.0, 3.0])
def test_every_tolerance_scales_with_the_drawing(scale):
    grid = Grid(
        rows={"A": 100 * scale, "B": 236 * scale},
        cols={"1": 100 * scale, "2": 170 * scale, "3": 240 * scale},
    )
    base = calibrate(
        words(8.0), Grid(rows={"A": 100, "B": 236}, cols={"1": 100, "2": 170, "3": 240})
    )
    s = calibrate(words(8.0 * scale), grid)
    assert s.word_h == pytest.approx(base.word_h * scale)
    assert s.run_gap == pytest.approx(base.run_gap * scale)
    assert s.snap_tol == pytest.approx(base.snap_tol * scale)
    assert s.max_bind_dist == pytest.approx(base.max_bind_dist * scale)


def test_without_a_grid_tolerances_still_come_from_the_text_size():
    a, b = calibrate(words(8.0)), calibrate(words(16.0))
    assert b.snap_tol == pytest.approx(2 * a.snap_tol)
    assert b.max_bind_dist == pytest.approx(2 * a.max_bind_dist)


def test_no_words_falls_back_to_a_sane_default():
    s = calibrate([])
    assert s.word_h > 0 and s.run_gap > 0
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python -m pytest backend/tests/extract/test_grid.py backend/tests/extract/test_calibrate.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.extract.grid'`.

- [ ] **Step 3: Write the geometry modules**

Create `backend/l2c/extract/runs.py`:

```python
"""Group words into lines and text runs (words that belong to one printed phrase)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from l2c.ingest.pages import Word

DEFAULT_WORD_H = 8.0


def median_word_height(words: list[Word]) -> float:
    heights = [w.y1 - w.y0 for w in words if len(w.text) >= 2 and w.y1 > w.y0]
    return statistics.median(heights) if heights else DEFAULT_WORD_H


@dataclass(frozen=True)
class Run:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    words: tuple[Word, ...]

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def text_runs(
    words: list[Word],
    gap: float = 12.0,
    line_tol: float = 3.0,
    split_before: tuple[str, ...] = (),
) -> list[Run]:
    """Words on the same baseline, split where the horizontal gap exceeds `gap` points.

    `split_before` lists keywords (upper case); a word starting with one of them begins a new
    run even when it follows closely, so two annotation blocks that nearly touch stay separate.
    """
    ordered = sorted(words, key=lambda w: (w.y0, w.x0))
    lines: list[list[Word]] = []
    for w in ordered:
        if lines and abs(w.y0 - lines[-1][0].y0) <= line_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    runs: list[Run] = []
    for line in lines:
        line.sort(key=lambda w: w.x0)
        group: list[Word] = [line[0]]
        for w in line[1:]:
            starts_keyword = bool(split_before) and w.text.upper().startswith(split_before)
            if w.x0 - group[-1].x1 > gap or starts_keyword:
                runs.append(_make(group))
                group = [w]
            else:
                group.append(w)
        runs.append(_make(group))
    runs.sort(key=lambda r: (round(r.y0, 1), r.x0))
    return runs


def _make(group: list[Word]) -> Run:
    return Run(
        text=" ".join(w.text for w in group),
        x0=min(w.x0 for w in group),
        y0=min(w.y0 for w in group),
        x1=max(w.x1 for w in group),
        y1=max(w.y1 for w in group),
        words=tuple(group),
    )


def cluster_1d(values: list[float], tol: float) -> list[list[int]]:
    """Indices grouped by position: a new group starts where the gap to the previous value
    exceeds `tol` (single linkage, so it does not depend on where bucket edges happen to fall)."""
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    groups: list[list[int]] = []
    for i in order:
        if groups and values[i] - values[groups[-1][-1]] <= tol:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups
```

Create `backend/l2c/extract/grid.py`:

```python
"""Find the structural grid on a sheet: letter rows down one edge, number columns along another.

Grid labels are told apart from other small numbers and letters by structure, not by position:
an axis is the group of labels that (1) sit on one line, (2) form a monotonic sequence, and
(3) are repeated on the opposite edge of the sheet, as grid bubbles usually are.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.runs import cluster_1d, median_word_height
from l2c.ingest.pages import Word

TIGHT_FRACTION = 0.43  # "exactly on the line" is within this share of the snap tolerance
MIRROR_WORD_HEIGHTS = 10.0  # a mirrored label sits at least this far away on the other edge
ALIGN_WORD_HEIGHTS = 1.0  # ... and lines up with the first within this distance


@dataclass
class Grid:
    """Letters name rows, numbers name columns. Where they sit on the page depends on the sheet:
    letters_on="y": letters run down an edge (y positions), numbers along an edge (x positions);
    letters_on="x": the transposed convention (letters along the top, numbers down the side).
    """

    rows: dict[str, float] = field(default_factory=dict)  # letter -> position on its axis (pt)
    cols: dict[str, float] = field(default_factory=dict)  # number label -> position on its axis
    letters_on: str = "y"

    def center(self, row: str, col: str) -> tuple[float, float]:
        """Page (x, y) of the intersection of a letter and a number."""
        if self.letters_on == "y":
            return self.cols[col], self.rows[row]
        return self.rows[row], self.cols[col]

    def nearest_row(self, pos: float) -> tuple[str, float, float]:
        """(letter, distance to it, distance to the runner-up) for a position on the letter axis."""
        return _nearest(self.rows, pos)

    def nearest_col(self, pos: float) -> tuple[str, float, float]:
        return _nearest(self.cols, pos)

    def snap(self, cx: float, cy: float, tol: float) -> tuple[str, str, float] | None:
        """Snap a page point to a grid intersection: (row letter, col label, grid confidence)."""
        if not self.rows or not self.cols:
            return None
        row_pos, col_pos = (cy, cx) if self.letters_on == "y" else (cx, cy)
        row, dr, dr2 = self.nearest_row(row_pos)
        col, dc, dc2 = self.nearest_col(col_pos)
        if dr > tol or dc > tol:
            return None
        if dr < TIGHT_FRACTION * tol and dc < TIGHT_FRACTION * tol:
            conf = 1.0
        else:
            conf = max(0.0, min(_margin(dr, dr2), _margin(dc, dc2)))
        return row, col, round(conf, 3)


def _nearest(axis: dict[str, float], v: float) -> tuple[str, float, float]:
    ranked = sorted(
        ((abs(pos - v), name) for name, pos in axis.items()), key=lambda t: (t[0], t[1])
    )
    best = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else float("inf")
    return best[1], best[0], second


def _margin(d1: float, d2: float) -> float:
    if d2 == float("inf"):
        return 1.0
    return (d2 - d1) / d2 if d2 > 0 else 0.0


def _letter_rank(text: str) -> float:
    """A..Z -> 1..26, then AA, BB, ... -> 27.. : monotonic along an axis in either style."""
    return float(26 * (len(text) - 1) + ord(text[-1]) - 64)


def _lis(values: list[float]) -> int:
    """Length of the longest strictly increasing subsequence."""
    tails: list[float] = []
    for v in values:
        i = bisect.bisect_left(tails, v)
        if i == len(tails):
            tails.append(v)
        else:
            tails[i] = v
    return len(tails)


def _monotonic_length(values: list[float]) -> int:
    return max(_lis(values), _lis([-v for v in values]))


def _pick_axis(
    labels: list[tuple[Word, float]], across: bool, align_tol: float, word_h: float
) -> tuple[list[tuple[Word, float]], tuple[int, int, int]]:
    """Choose the best line of labels. `across` is True for a horizontal axis (numbers).

    A line is a cluster of labels sharing one y (numbers) or one x (letters). Score: how many have
    a mirrored twin on the opposite edge, then the longest monotonic run, then the plain count.
    """
    coords = [w.y0 if across else w.x0 for w, _ in labels]
    groups = [[labels[i] for i in g] for g in cluster_1d(coords, align_tol)]
    best_score: tuple[int, int, int] | None = None
    best: list[tuple[Word, float]] = []
    for members in groups:
        ordered = sorted(members, key=lambda t: t[0].cx if across else t[0].cy)
        mono = _monotonic_length([v for _, v in ordered])
        mirrored = 0
        for w, v in members:
            for w2, v2 in labels:
                if v2 != v or w2 is w:
                    continue
                gap = (w2.y0 - w.y0) if across else (w2.x0 - w.x0)
                off = (w2.cx - w.cx) if across else (w2.cy - w.cy)
                if (
                    abs(gap) >= MIRROR_WORD_HEIGHTS * word_h
                    and abs(off) <= ALIGN_WORD_HEIGHTS * word_h
                ):
                    mirrored += 1
                    break
        score = (mirrored, mono, len(members))
        if best_score is None or score > best_score:
            best_score, best = score, members
    return best, best_score or (0, 0, 0)


def _axis_dict(axis: list[tuple[Word, float]], along_x: bool, as_number: bool) -> dict[str, float]:
    out: dict[str, float] = {}
    for w, _ in sorted(axis, key=lambda t: t[0].cx if along_x else t[0].cy):
        key = f"{float(w.text):g}" if as_number else w.text
        out.setdefault(key, round(w.cx if along_x else w.cy, 2))
    return out


def fit_grid(words: list[Word], config: Config = DEFAULT_CONFIG) -> Grid | None:
    """Rows from letters, columns from small numbers; the orientation is detected per sheet.

    Both conventions are tried (letters down an edge / letters along an edge) and the one whose
    labels are better structured (mirrored on the opposite edge, monotonic, numerous) wins.
    Returns None when fewer than config.grid_min_labels of either kind form an axis.
    """
    letter_re = re.compile(config.grid_letter_pattern)
    number_re = re.compile(config.grid_number_pattern)
    letters = [(w, _letter_rank(w.text)) for w in words if letter_re.match(w.text)]
    numbers = [(w, float(w.text)) for w in words if number_re.match(w.text)]
    if len(letters) < config.grid_min_labels or len(numbers) < config.grid_min_labels:
        return None
    word_h = median_word_height(words)
    tol = max(0.5, config.grid_align_word_heights * word_h)
    best: tuple[tuple[int, int, int], Grid] | None = None
    for letters_on in ("y", "x"):
        # letters_on="y": letters share an x (a vertical line) and vary in y; numbers the reverse
        l_axis, l_score = _pick_axis(
            letters, across=(letters_on == "x"), align_tol=tol, word_h=word_h
        )
        n_axis, n_score = _pick_axis(
            numbers, across=(letters_on == "y"), align_tol=tol, word_h=word_h
        )
        rows = _axis_dict(l_axis, along_x=(letters_on == "x"), as_number=False)
        cols = _axis_dict(n_axis, along_x=(letters_on == "y"), as_number=True)
        if len(rows) < config.grid_min_labels or len(cols) < config.grid_min_labels:
            continue
        score = tuple(a + b for a, b in zip(l_score, n_score, strict=True))
        if best is None or score > best[0]:
            best = (score, Grid(rows=rows, cols=cols, letters_on=letters_on))
    return best[1] if best else None
```

Create `backend/l2c/extract/calibrate.py`:

```python
"""Per-page calibration: every tolerance is a multiple of the page's own geometry.

A different drawing scale, font size or grid spacing changes every distance in points; the
ratios (in Config) stay the same, so nothing here is tied to one project.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import Grid
from l2c.extract.runs import median_word_height
from l2c.ingest.pages import Word


@dataclass(frozen=True)
class PageScale:
    word_h: float
    run_gap: float  # words closer than this belong to the same printed phrase
    snap_tol: float  # distance from an outline centre to a gridline
    max_bind_dist: float  # how far a block may sit from its outline
    row_spacing: float | None
    col_spacing: float | None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _diffs(values: list[float], floor: float) -> list[float]:
    ordered = sorted(values)
    return [b - a for a, b in zip(ordered, ordered[1:], strict=False) if b - a > floor]


def calibrate(
    words: list[Word], grid: Grid | None = None, config: Config = DEFAULT_CONFIG
) -> PageScale:
    h = median_word_height(words)
    run_gap = _clamp(config.run_gap_word_heights * h, 0.5 * h, 5 * h)
    row_d = _diffs(list(grid.rows.values()), 0.1 * h) if grid else []
    col_d = _diffs([float(v) for v in grid.cols.values()], 0.1 * h) if grid else []
    row_sp = statistics.median(row_d) if row_d else None
    col_sp = statistics.median(col_d) if col_d else None
    typical = min([s for s in (row_sp, col_sp) if s is not None], default=None)
    snap = _clamp(config.snap_tol_fraction * typical, 0.75 * h, 4 * h) if typical else 1.75 * h
    bind = _clamp(config.bind_dist_col_spacings * col_sp, 8 * h, 30 * h) if col_sp else 15 * h
    return PageScale(h, run_gap, snap, bind, row_sp, col_sp)
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_grid.py backend/tests/extract/test_calibrate.py -v
```

Expected: 12 passed. `test_transposed_grid_is_detected_with_its_orientation` proves the second sheet convention (letters along the top, numbers down the side, found on two of the four development projects); `test_calibrate` proves tolerances scale with the drawing (0.5x, 1x, 3x).

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/extract backend/tests/extract
git commit -m "Add grid detection and per-page calibration"
```

```bash
git switch dev && git merge --no-ff eric/e4-geometry
```


---

### Task E5: Anchor annotation blocks to column outlines

**Files:**
- Create: `backend/l2c/extract/anchor.py`
- Test: `backend/tests/extract/test_anchor.py`

**Interfaces:**
- Consumes: `Grid` (E4), `Shape` (E2).
- Produces: `Outline(row, col, shape, grid_conf)`; `find_outlines(shapes, grid, tol, size_tolerance=0.4) -> dict[(row, col), Outline]` (small closed shapes whose centre snaps to a grid intersection; outline size learned from the data, not fixed); `Binding(row, col, cost, margin, grid_conf, second_pass)`; `bind_blocks(anchors, outlines, max_dist=120.0) -> list[Binding | None]` (one-to-one Hungarian assignment; learns the sheet's recurring block offsets, usually one left and one right of the column, adds zero offset as a candidate, then a second wider pass for leftovers with a halved margin).

Why this exists (measured on real data): text position alone is ambiguous where gridlines are only tens of points apart, and a single median offset fails because blocks sit on both sides of their column. Plain nearest-outline put the one odd block on the wrong column.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev && git pull
git switch -c eric/e5-anchor
```

Create `backend/tests/extract/test_anchor.py`:

```python
from l2c.extract.anchor import bind_blocks, find_outlines
from l2c.extract.grid import Grid
from l2c.ingest.pages import Shape


def shape(cx, cy, w=12.0, h=18.0):
    return Shape(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


GRID = Grid(rows={"K": 100.0, "L": 200.0}, cols={"3.4": 1400.0, "4": 1352.0, "5": 1220.0})


def test_find_outlines_snaps_to_cells_and_ignores_noise():
    shapes = [
        shape(1352, 100),
        shape(1400, 200),
        shape(500, 500),
        Shape(0, 0, 1, 1),
        shape(1352, 103),
    ]
    out = find_outlines(shapes, GRID, 14.0)
    assert set(out) == {("K", "4"), ("L", "3.4")}
    assert out[("K", "4")].shape.cy == 100  # closest candidate to the intersection wins


def test_binding_uses_consistent_offset_not_nearest_outline():
    outlines = find_outlines([shape(1352, 100), shape(1400, 100), shape(1220, 100)], GRID, 14.0)
    # blocks sit 35 pt right of and 20 pt below their column: the first block is nearer
    # to the neighbouring outline than to its own
    anchors = [(1352 + 35, 120), (1400 + 35, 120), (1220 + 35, 120)]
    bound = bind_blocks(anchors, outlines)
    assert [(b.row, b.col) for b in bound] == [("K", "4"), ("K", "3.4"), ("K", "5")]
    nearest_only = min(outlines, key=lambda k: abs(outlines[k].shape.cx - anchors[0][0]))
    assert nearest_only == ("K", "3.4")  # proves plain nearest-outline would have been wrong


def test_binding_is_one_to_one_and_leaves_extra_blocks_unbound():
    outlines = find_outlines([shape(1352, 100)], GRID, 14.0)
    bound = bind_blocks([(1353, 120), (1354, 121)], outlines)
    assert sum(b is not None for b in bound) == 1


def test_binding_margin_is_low_when_two_outlines_are_equally_close():
    outlines = find_outlines([shape(1352, 100), shape(1400, 100)], GRID, 14.0)
    (b,) = bind_blocks([(1376, 120)], outlines)
    assert b is not None and b.margin < 0.2


def test_empty_inputs():
    assert bind_blocks([], {}) == []
    assert bind_blocks([(1, 2)], {}) == [None]


def test_two_offset_modes_left_and_right_of_columns():
    cols = {"1": 100.0, "2": 400.0, "3": 700.0, "4": 1000.0, "5": 1300.0, "6": 1600.0}
    grid = Grid(rows={"K": 100.0}, cols=cols)
    outlines = find_outlines([shape(x, 100) for x in cols.values()], grid, 14.0)
    side = {"1": +80, "2": -80, "3": +80, "4": -80, "5": +80, "6": -80}
    anchors = [(cols[c] + dx, 120.0) for c, dx in side.items()]
    bound = bind_blocks(anchors, outlines)
    assert [b.col for b in bound] == list(side)
    assert all(not b.second_pass for b in bound)


def test_second_pass_binds_leftovers_with_penalised_margin():
    grid = Grid(rows={"K": 100.0}, cols={"1": 100.0, "2": 400.0})
    outlines = find_outlines([shape(100, 100), shape(400, 100)], grid, 14.0)
    # first block is 150 pt from its outline (beyond the 120 pt first-pass radius)
    bound = bind_blocks([(100 + 150, 100.0), (400, 120.0)], outlines)
    assert [b.col for b in bound] == ["1", "2"]
    assert bound[0].second_pass and not bound[1].second_pass
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest backend/tests/extract/test_anchor.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.extract.anchor'`.

- [ ] **Step 3: Write the anchoring**

Create `backend/l2c/extract/anchor.py`:

```python
"""Anchor annotation blocks to column outlines.

Text position alone is ambiguous near close gridlines (they can be only tens of points
apart), so the anchor is the column *outline* found in the vector geometry. Blocks are bound
to outlines one-to-one (Hungarian assignment) after learning the sheet's recurring block
offsets.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from l2c.extract.grid import Grid
from l2c.ingest.pages import Shape

SIZE_BUCKET_FRACTION = 0.15  # shape sizes are grouped in buckets of 15% of the modal size
MIN_SNAPPED_FOR_MODE = 3
MIN_BLOCKS_FOR_OFFSET = 3
MIN_MODE_COUNT = 3
MODE_BIN_FRACTION = 0.1  # offset bins are a tenth of the binding radius
SECOND_PASS_RADIUS = 1.67  # second pass looks this many times further
SECOND_PASS_MARGIN_FACTOR = 0.5


@dataclass(frozen=True)
class Outline:
    row: str
    col: str
    shape: Shape
    grid_conf: float


@dataclass(frozen=True)
class Binding:
    row: str
    col: str
    cost: float
    margin: float  # 0..1, how much better than the runner-up outline
    grid_conf: float
    second_pass: bool = False


def find_outlines(
    shapes: list[Shape], grid: Grid, tol: float, size_tolerance: float = 0.4
) -> dict[tuple[str, str], Outline]:
    """Small closed shapes whose centre snaps to a grid intersection; one per cell.

    Column outlines share one size on a sheet, so the size is learned from the data: shapes far
    from the most common snapped size (within `size_tolerance`) are dropped. No fixed point sizes.
    """
    snapped: list[tuple[Shape, str, str, float]] = []
    for s in shapes:
        hit = grid.snap(s.cx, s.cy, tol)
        if hit is not None:
            snapped.append((s, hit[0], hit[1], hit[2]))
    if len(snapped) >= MIN_SNAPPED_FOR_MODE:
        step = _size_step(snapped)
        keys = Counter(_size_key(s, step) for s, *_ in snapped)
        lo, hi = sorted(keys.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        snapped = [
            t
            for t in snapped
            if abs(min(t[0].w, t[0].h) - lo) <= size_tolerance * lo
            and abs(max(t[0].w, t[0].h) - hi) <= size_tolerance * hi
        ]
    best: dict[tuple[str, str], tuple[float, Outline]] = {}
    for s, row, col, conf in snapped:
        gx, gy = grid.center(row, col)
        dist = math.hypot(s.cx - gx, s.cy - gy)
        key = (row, col)
        rank = (dist, s.cx, s.cy)
        if key not in best or rank < (best[key][0], best[key][1].shape.cx, best[key][1].shape.cy):
            best[key] = (dist, Outline(row, col, s, conf))
    return {k: v[1] for k, v in sorted(best.items())}


def _size_step(snapped: list[tuple[Shape, str, str, float]]) -> float:
    """Bucket width: a fraction of the median shape size, so it scales with the drawing."""
    sizes = sorted(min(s.w, s.h) for s, *_ in snapped)
    return max(0.5, SIZE_BUCKET_FRACTION * sizes[len(sizes) // 2])


def _size_key(s: Shape, step: float) -> tuple[float, float]:
    lo, hi = sorted((s.w, s.h))
    return (round(lo / step) * step, round(hi / step) * step)


def offset_modes(pts: np.ndarray, centers: np.ndarray, max_dist: float) -> list[np.ndarray]:
    """Recurring (dx, dy) offsets between blocks and their nearest outlines.

    Real sheets place a block either left or right of its column, so there are usually two
    offset modes, not one. A mode needs at least MIN_MODE_COUNT blocks and 10% of all blocks.
    """
    raw = np.linalg.norm(pts[:, None, :] - centers[None, :, :], axis=2)
    nearest = raw.argmin(axis=1)
    near = raw.min(axis=1) <= max_dist
    if near.sum() < MIN_BLOCKS_FOR_OFFSET:
        return []
    offs = pts[near] - centers[nearest[near]]
    bin_pt = max(1.0, MODE_BIN_FRACTION * max_dist)
    bins: dict[tuple[int, int], list[int]] = {}
    for idx, (dx, dy) in enumerate(offs):
        bins.setdefault((round(dx / bin_pt), round(dy / bin_pt)), []).append(idx)
    need = max(MIN_MODE_COUNT, int(0.1 * len(offs)))
    modes = [offs[ids].mean(axis=0) for _, ids in sorted(bins.items()) if len(ids) >= need]
    return modes


def bind_blocks(
    anchors: list[tuple[float, float]],
    outlines: dict[tuple[str, str], Outline],
    max_dist: float = 120.0,
) -> list[Binding | None]:
    """Bind each block anchor point to at most one outline, each outline to at most one block.

    The cost of pairing block i with outline j is the distance from the block to the nearest
    *expected block position* of that outline (outline centre plus one of the sheet's offset modes).
    """
    if not anchors or not outlines:
        return [None] * len(anchors)
    cells = list(outlines)
    centers = np.array([[outlines[c].shape.cx, outlines[c].shape.cy] for c in cells])
    pts = np.array(anchors, dtype=float)
    # Always keep the zero offset as a candidate so this is never worse than nearest-outline.
    modes = [np.zeros(2), *offset_modes(pts, centers, max_dist)]
    cost = np.min(
        [np.linalg.norm(pts[:, None, :] - (centers[None, :, :] + m), axis=2) for m in modes], axis=0
    )
    result: list[Binding | None] = [None] * len(anchors)
    _assign(
        cost,
        list(range(len(anchors))),
        list(range(len(cells))),
        max_dist,
        cells,
        outlines,
        result,
        False,
    )
    left_i = [i for i, r in enumerate(result) if r is None]
    used = {(r.row, r.col) for r in result if r is not None}
    left_j = [j for j, c in enumerate(cells) if c not in used]
    if left_i and left_j:
        plain = np.linalg.norm(pts[:, None, :] - centers[None, :, :], axis=2)
        _assign(plain, left_i, left_j, SECOND_PASS_RADIUS * max_dist, cells, outlines, result, True)
    return result


def _assign(
    cost: np.ndarray,
    rows: list[int],
    cols: list[int],
    limit: float,
    cells: list[tuple[str, str]],
    outlines: dict[tuple[str, str], Outline],
    result: list[Binding | None],
    second_pass: bool,
) -> None:
    sub = cost[np.ix_(rows, cols)]
    ri, cj = linear_sum_assignment(sub)
    for a, b in zip(ri, cj, strict=True):
        i, j = rows[a], cols[b]
        c = float(cost[i, j])
        if c > limit:
            continue
        others = np.delete(cost[i], j)
        runner = float(others.min()) if others.size else math.inf
        margin = (
            1.0 if math.isinf(runner) else (max(0.0, (runner - c) / runner) if runner > 0 else 0.0)
        )
        if second_pass:
            margin *= SECOND_PASS_MARGIN_FACTOR
        o = outlines[cells[j]]
        result[i] = Binding(o.row, o.col, round(c, 3), round(margin, 3), o.grid_conf, second_pass)
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_anchor.py -v
```

Expected: 7 passed (including the two-offset-modes test and the second-pass test).

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/extract/anchor.py backend/tests/extract/test_anchor.py
git commit -m "Bind annotation blocks to column outlines"
```

```bash
git switch dev && git merge --no-ff eric/e5-anchor
```


---

### Task E6: Quality scoring (deterministic confidence)

**Files:**
- Create: `backend/l2c/extract/quality.py`
- Test: `backend/tests/extract/test_quality.py`

**Interfaces:**
- Consumes: `Quality`, `AttrQuality`, `LocationQuality` and the weights in `l2c.contract.constants` (F2); `Config` (E1).
- Produces: `attr(value, *, conf=1.0, status="parsed", text_source="native", ocr_conf=None, snapped=False, original_text=None) -> AttrQuality` (OCR confidence, snapping 0.9 and derivation 0.8 multiply in); `missing_attr() -> AttrQuality` (conf 0.3); `location(anchor, grid_conf, *, page_xy_conf=1.0, anchor_dist_pt=None, grid_cell=None, binding_method="none", assignment_cost=None, margin=None) -> LocationQuality`; `location_score(loc) -> float`; `build_quality(*, type_conf, level_conf, loc, attrs, passed, failed, flags) -> Quality` (`overall` is the weakest link times `0.85 ** failed_checks`, floor 0.3); `column_checks(count, size, spacing_mm, config) -> (passed, failed)`.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev && git pull
git switch -c eric/e6-quality
```

Create `backend/tests/extract/test_quality.py`:

```python
from l2c.extract import quality as Q


def test_attr_penalties_stack():
    assert Q.attr(4).conf == 1.0
    assert Q.attr(4, text_source="ocr", ocr_conf=0.9, snapped=True).conf == round(0.9 * 0.9, 3)
    assert Q.attr(7, status="derived").conf == 0.8


def test_overall_is_the_weakest_link_times_consistency():
    loc = Q.location("outline", 1.0, margin=1.0, grid_cell="D-6", binding_method="hungarian")
    attrs = {"count": Q.attr(4), "size": Q.attr("25M"), "spacing": Q.attr(152.4, conf=0.8)}
    q = Q.build_quality(
        type_conf=1.0, level_conf=1.0, loc=loc, attrs=attrs, passed=["a"], failed=[], flags=["x"]
    )
    assert q.overall == 0.8
    q2 = Q.build_quality(
        type_conf=1.0, level_conf=1.0, loc=loc, attrs=attrs, passed=[], failed=["b", "c"], flags=[]
    )
    assert q2.overall == round(0.8 * 0.85**2, 3)


def test_location_score_reflects_anchor_and_margin():
    strong = Q.location("outline", 1.0, margin=1.0)
    weak = Q.location("text_only", 0.62, margin=0.1)
    assert Q.location_score(strong) == 1.0
    assert Q.location_score(weak) < 0.3


def test_column_checks():
    passed, failed = Q.column_checks(4, "25M", 152.4)
    assert passed == ["size_in_vocabulary", "count_plausible", "spacing_plausible"]
    assert failed == []
    _, failed = Q.column_checks(0, "26M", 5.0)
    assert set(failed) == {"count_plausible", "size_in_vocabulary", "spacing_plausible"}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest backend/tests/extract/test_quality.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.extract.quality'`.

- [ ] **Step 3: Write the scoring**

Create `backend/l2c/extract/quality.py`:

```python
"""Deterministic quality scoring (spec 10.19). All weights live in contract.constants."""

from __future__ import annotations

from l2c.contract import constants as C
from l2c.contract.models import AttrQuality, LocationQuality, Quality
from l2c.extract.config import DEFAULT_CONFIG, Config


def attr(
    value: float | int | str | None,
    *,
    conf: float = 1.0,
    status: str = "parsed",
    text_source: str = "native",
    ocr_conf: float | None = None,
    snapped: bool = False,
    original_text: str | None = None,
) -> AttrQuality:
    score = conf
    if text_source == "ocr" and ocr_conf is not None:
        score *= ocr_conf
    if snapped:
        score *= C.OCR_SNAP_PENALTY
    if status == "derived":
        score *= C.DERIVED_PENALTY
    return AttrQuality(
        value=value,
        conf=round(max(0.0, min(1.0, score)), 3),
        status=status,  # type: ignore[arg-type]
        text_source=text_source,  # type: ignore[arg-type]
        ocr_conf=ocr_conf,
        snapped=snapped,
        original_text=original_text,
    )


def missing_attr() -> AttrQuality:
    return AttrQuality(value=None, conf=0.3, status="missing")


def location(
    anchor: str,
    grid_conf: float,
    *,
    page_xy_conf: float = 1.0,
    anchor_dist_pt: float | None = None,
    grid_cell: str | None = None,
    binding_method: str = "none",
    assignment_cost: float | None = None,
    margin: float | None = None,
) -> LocationQuality:
    return LocationQuality(
        page_xy_conf=page_xy_conf,
        anchor=anchor,  # type: ignore[arg-type]
        anchor_dist_pt=anchor_dist_pt,
        grid_cell=grid_cell,
        grid_conf=grid_conf,
        binding_method=binding_method,
        assignment_cost=assignment_cost,
        margin_to_runner_up=margin,
    )


def location_score(loc: LocationQuality) -> float:
    binding = 1.0 if loc.margin_to_runner_up is None else 0.6 + 0.4 * loc.margin_to_runner_up
    return round(loc.page_xy_conf * loc.grid_conf * C.ANCHOR_FACTOR[loc.anchor] * binding, 3)


def build_quality(
    *,
    type_conf: float,
    level_conf: float,
    loc: LocationQuality,
    attrs: dict[str, AttrQuality],
    passed: list[str],
    failed: list[str],
    flags: list[str],
) -> Quality:
    weakest = min([type_conf, level_conf, location_score(loc), *[a.conf for a in attrs.values()]])
    factor = max(C.CONSISTENCY_FLOOR, C.CONSISTENCY_FAIL_FACTOR ** len(failed))
    return Quality(
        overall=round(weakest * factor, 3),
        type_conf=type_conf,
        level_conf=level_conf,
        location=loc,
        attributes=attrs,
        consistency_passed=sorted(passed),
        consistency_failed=sorted(failed),
        flags=sorted(set(flags)),
    )


def column_checks(
    count: int | None,
    size: str | None,
    spacing_mm: float | None,
    config: Config = DEFAULT_CONFIG,
) -> tuple[list[str], list[str]]:
    """Sanity checks used for quality only; Ian's lane owns the full plausibility check."""
    passed: list[str] = []
    failed: list[str] = []
    if size is not None:
        (passed if size in config.bar_sizes else failed).append("size_in_vocabulary")
    if count is not None:
        (passed if 1 <= count <= 60 else failed).append("count_plausible")
    if spacing_mm is not None:
        (passed if 25.0 <= spacing_mm <= 600.0 else failed).append("spacing_plausible")
    return passed, failed
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_quality.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/extract/quality.py backend/tests/extract/test_quality.py
git commit -m "Add deterministic quality scoring"
```

```bash
git switch dev && git merge --no-ff eric/e6-quality
```


---

### Task E7: Plan column extractor

**Files:**
- Create: `backend/l2c/extract/columns_plan.py`
- Test: `backend/tests/extract/test_columns_plan.py`

**Interfaces:**
- Consumes: E1 to E6.
- Produces: `PlanBlock(runs, arm, col, lig)` with `.bbox`, `.text`; `assemble_blocks(page, config=DEFAULT_CONFIG, scale=None) -> list[PlanBlock]` (the left-aligned runs around each block-start run: section line above, bar line, ties line, end line); `extract_plan_columns(page, level, grid, config=DEFAULT_CONFIG) -> list[ElementExt]` (id `<sheet>_<grid>_plan`; `armature[0]` vertical bars `repere=<grid>-V`, `armature[1]` ties `repere=<grid>-T`; `match_key` `colonne|<level>|<row>|<col>`; blocks that cannot be bound keep `row=col=None` with flag `unbound_block` and `quality.overall <= 0.1`; unparsed fields get status `missing`, flags `<field>_unparsed`).

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev && git pull
git switch -c eric/e7-plan
```

Create `backend/tests/extract/test_columns_plan.py`:

```python
from l2c.extract.columns_plan import assemble_blocks, extract_plan_columns
from l2c.extract.grid import fit_grid
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import new_doc, put, rect, save

ROWY = {"D": 300.0, "E": 400.0, "F": 500.0, "G": 600.0, "H": 700.0}
COLX = {"6": 500.0, "7": 600.0, "8": 700.0, "9": 800.0, "10": 900.0}


def center(row: str, col: str) -> tuple[float, float]:
    return COLX[col] + 2, ROWY[row] + 4


def block(page, row, col, arm="ARM.: 4-25M", lig='LIG.: 10M@6" c/c', dx=35.0, dy=20.0):
    cx, cy = center(row, col)
    x, y = cx + dx, cy + dy
    put(page, x, y - 9, 'COL. 18"x20"')
    put(page, x, y, arm)
    put(page, x, y + 9, lig)
    put(page, x, y + 18, "BÉTON: 25MPa / N")


def plan_pdf(tmp_path, *, with_outline=True, extra=None):
    doc, page = new_doc(1200, 900)
    for letter, y in ROWY.items():
        put(page, 40, y, letter)
        put(page, 1100, y, letter)
    for label, x in COLX.items():
        put(page, x, 60, label)
        put(page, x, 820, label)
    put(page, 1050, 860, "S-517")
    put(page, 300, 40, "PLAN DES COLONNES - NIVEAU 2")
    cells = [("D", "6"), ("D", "7"), ("E", "7"), ("F", "9")]
    for r, c in cells:
        if with_outline:
            rect(page, *center(r, c))
        outlier = (r, c) == ("E", "7")
        block(
            page,
            r,
            c,
            arm="ARM.: 4-35M +GOUJ." if outlier else "ARM.: 4-25M",
            lig='LIG.: 10M@8" c/c' if outlier else 'LIG.: 10M@6" c/c',
        )
    if extra:
        extra(page)
    return save(doc, tmp_path / "plan.pdf")


def test_blocks_are_assembled_per_arm_run(tmp_path):
    (page,) = load_pdf(plan_pdf(tmp_path))
    blocks = assemble_blocks(page)
    assert len(blocks) == 4
    assert all(b.col is not None and b.lig is not None for b in blocks)
    assert "BÉTON" in blocks[0].text


def test_extracts_columns_with_correct_cells_even_when_blocks_sit_beside_neighbours(tmp_path):
    (page,) = load_pdf(plan_pdf(tmp_path))
    grid = fit_grid(page.words)
    els = extract_plan_columns(page, "N2", grid)
    by_grid = {e.grid: e for e in els}
    assert set(by_grid) == {"D-6", "D-7", "E-7", "F-9"}
    odd = by_grid["E-7"]
    assert odd.armature[0].quantite == 4 and odd.armature[0].diametre == "35M"
    assert odd.armature[1].espacement_mm == 203.2
    assert "dowels_noted" in odd.quality.flags
    assert odd.match_key.key_str() == "colonne|N2|E|7"
    assert odd.section_mm == (457.2, 508.0)
    typical = by_grid["D-6"]
    assert typical.armature[0].diametre == "25M" and typical.armature[1].espacement_mm == 152.4
    assert typical.quality.location.anchor == "outline"
    assert 0.9 <= typical.quality.overall <= 1.0
    assert (
        typical.id == "S-517_D-6_plan" and typical.feuillet == "S-517" and typical.source == "plan"
    )


def test_blocks_without_outlines_are_kept_but_flagged_unbound(tmp_path):
    (page,) = load_pdf(plan_pdf(tmp_path, with_outline=False))
    els = extract_plan_columns(page, "N2", fit_grid(page.words))
    assert len(els) == 4
    assert all("unbound_block" in e.quality.flags for e in els)
    assert all(e.match_key.row is None and e.quality.overall <= 0.1 for e in els)


def test_unparseable_block_gets_missing_attributes_and_low_quality(tmp_path):
    def bad(page):
        put(page, 500 + 35, 700 + 4 + 20, "ARM.: ??")

    (page,) = load_pdf(plan_pdf(tmp_path, extra=bad))
    els = extract_plan_columns(page, "N2", fit_grid(page.words))
    broken = [e for e in els if "count_unparsed" in e.quality.flags]
    assert len(broken) == 1 and broken[0].quality.overall <= 0.3
    assert broken[0].armature[0].quantite is None


def test_extraction_is_deterministic(tmp_path):
    (page,) = load_pdf(plan_pdf(tmp_path))
    g = fit_grid(page.words)
    a = [e.model_dump_json() for e in extract_plan_columns(page, "N2", g)]
    b = [e.model_dump_json() for e in extract_plan_columns(page, "N2", g)]
    assert a == b
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest backend/tests/extract/test_columns_plan.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.extract.columns_plan'`.

- [ ] **Step 3: Write the extractor**

Create `backend/l2c/extract/columns_plan.py`:

```python
"""Extract column elements from a plan sheet (`PLAN DES COLONNES - <level>`)."""

from __future__ import annotations

from dataclasses import dataclass

from l2c.contract.models import Armature, ElementExt, MatchKey
from l2c.extract import quality as Q
from l2c.extract.anchor import bind_blocks, find_outlines
from l2c.extract.calibrate import PageScale, calibrate
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import Grid
from l2c.extract.notation import parse_count_size, parse_section, parse_size_spacing
from l2c.extract.runs import Run, text_runs
from l2c.ingest.pages import PageData


@dataclass(frozen=True)
class PlanBlock:
    runs: tuple[Run, ...]
    arm: Run
    col: Run | None
    lig: Run | None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (
            min(r.x0 for r in self.runs),
            min(r.y0 for r in self.runs),
            max(r.x1 for r in self.runs),
            max(r.y1 for r in self.runs),
        )

    @property
    def text(self) -> str:
        return " | ".join(r.text for r in self.runs)


def assemble_blocks(
    page: PageData, config: Config = DEFAULT_CONFIG, scale: PageScale | None = None
) -> list[PlanBlock]:
    """Group the left-aligned text runs around each block-start run into one annotation block."""
    scale = scale or calibrate(page.words, None, config)
    h = scale.word_h
    runs = text_runs(page.words, gap=scale.run_gap, split_before=config.keywords())
    blocks: list[PlanBlock] = []
    for arm in (r for r in runs if config.starts(r.text, config.block_start)):
        column = sorted(
            (r for r in runs if abs(r.x0 - arm.x0) <= config.x_align_word_heights * h),
            key=lambda r: (r.y0, r.x0),
        )
        i = column.index(arm)
        members = [arm]
        col_run = None
        if (
            i > 0
            and 0 < arm.y0 - column[i - 1].y0 <= config.col_above_word_heights * h
            and config.starts(column[i - 1].text, config.section_line)
        ):
            col_run = column[i - 1]
            members.insert(0, col_run)
        lig_run = None
        prev = arm
        for r in column[i + 1 :]:
            if (
                config.starts(r.text, config.block_start)
                or config.starts(r.text, config.section_line)
                or r.y0 - prev.y0 > config.line_gap_word_heights * h
            ):
                break
            members.append(r)
            if config.starts(r.text, config.ties_line) and lig_run is None:
                lig_run = r
            prev = r
            if (
                config.starts(r.text, config.end_line)
                or r.y0 - arm.y0 > config.block_below_word_heights * h
            ):
                break
        blocks.append(PlanBlock(tuple(members), arm, col_run, lig_run))
    return blocks


def extract_plan_columns(
    page: PageData, level: str, grid: Grid | None, config: Config = DEFAULT_CONFIG
) -> list[ElementExt]:
    scale = calibrate(page.words, grid, config)
    blocks = assemble_blocks(page, config, scale)
    outlines = (
        find_outlines(page.shapes, grid, scale.snap_tol, config.outline_size_tolerance)
        if grid
        else {}
    )
    bindings = bind_blocks(
        [(b.arm.x0, b.arm.y0) for b in blocks], outlines, max_dist=scale.max_bind_dist
    )
    sheet = page.feuillet or page.fichier
    out: list[ElementExt] = []
    unbound = 0
    for block, bind in zip(blocks, bindings, strict=True):
        cs = parse_count_size(block.arm.text, config)
        ties = parse_size_spacing(block.lig.text, config) if block.lig else None
        section = parse_section(block.col.text) if block.col else None
        flags: list[str] = []
        if "GOUJ" in block.arm.text.upper():
            flags.append("dowels_noted")
        if bind is not None:
            grid_cell = f"{bind.row}-{bind.col}"
            row, col = bind.row, float(bind.col)
            loc = Q.location(
                "outline",
                bind.grid_conf,
                anchor_dist_pt=bind.cost,
                grid_cell=grid_cell,
                binding_method="hungarian",
                assignment_cost=bind.cost,
                margin=bind.margin,
            )
            if bind.grid_conf < 0.5:
                flags.append("ambiguous_cell")
            if bind.margin < 0.3:
                flags.append("weak_binding")
            if bind.second_pass:
                flags.append("second_pass_binding")
            element_id = f"{sheet}_{grid_cell}_plan"
        else:
            unbound += 1
            grid_cell, row, col = None, None, None
            loc = Q.location("text_only", 0.1, binding_method="none")
            flags.append("unbound_block")
            element_id = f"{sheet}_U{unbound:03d}_plan"
        attrs = {
            "count": Q.attr(cs.count) if cs else Q.missing_attr(),
            "size": Q.attr(cs.size) if cs else Q.missing_attr(),
            "tie_size": Q.attr(ties.size) if ties else Q.missing_attr(),
            "spacing": Q.attr(ties.spacing_mm) if ties else Q.missing_attr(),
        }
        for name, a in attrs.items():
            if a.status == "missing":
                flags.append(f"{name}_unparsed")
        passed, failed = Q.column_checks(
            cs.count if cs else None,
            cs.size if cs else None,
            ties.spacing_mm if ties else None,
            config,
        )
        x0, y0, x1, y1 = block.bbox
        out.append(
            ElementExt(
                id=element_id,
                source="plan",
                fichier=page.fichier,
                feuillet=page.feuillet,
                page=page.page,
                x=round((x0 + x1) / 2, 2),
                y=round((y0 + y1) / 2, 2),
                type_element="colonne",
                element=grid_cell or element_id,
                armature=[
                    Armature(
                        repere=f"{grid_cell or element_id}-V",
                        diametre=cs.size if cs else None,
                        quantite=cs.count if cs else None,
                    ),
                    Armature(
                        repere=f"{grid_cell or element_id}-T",
                        diametre=ties.size if ties else None,
                        espacement_mm=ties.spacing_mm if ties else None,
                    ),
                ],
                match_key=MatchKey(type="colonne", level=level, row=row, col=col),
                grid=grid_cell,
                level=level,
                section_mm=section,
                bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                quality=Q.build_quality(
                    type_conf=1.0,
                    level_conf=1.0,
                    loc=loc,
                    attrs=attrs,
                    passed=passed,
                    failed=failed,
                    flags=flags,
                ),
                extraction_method="rules",
                raw_text=block.text,
                provenance={"file": page.fichier, "page": page.page, "adapter": "plan_outline"},
            )
        )
    return out
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_columns_plan.py -v
```

Expected: 5 passed, including blocks that sit beside the neighbouring column, blocks without outlines, an unparseable block and determinism.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/extract/columns_plan.py backend/tests/extract/test_columns_plan.py
git commit -m "Extract columns from plan sheets"
```

```bash
git switch dev && git merge --no-ff eric/e7-plan
```


---

### Task E8: Shop-drawing column extractor (label convention)

**Files:**
- Create: `backend/l2c/extract/columns_shop.py`
- Test: `backend/tests/extract/test_columns_shop.py`

**Interfaces:**
- Consumes: E1 to E6.
- Produces: `LevelLine(level, name, y, elevation_mm)`; `find_level_lines(page, runs, config, word_h) -> list[LevelLine]` (`EL.: 131' - 9"` plus the level name just below; also accepts `EL:` because OCR drops the dot); `split_views(lines) -> list[list[LevelLine]]` (several elevation views can be stacked on one page); `assign_level(views, y) -> (level, flags)` (between two lines the block takes the lower line's level; below the lowest line it is a foundation dowel segment `FDN`; otherwise `UNKNOWN`); `find_labels(words, config, word_h)` and `strip_tolerance(labels, config, word_h)`; `extract_shop_columns(page, config=DEFAULT_CONFIG) -> (list[ElementExt], list[LevelInfo])` (one element per grid label and level band; id `<file stem>_p<page>_<grid>_<level>_shop`; a tie line without a printed spacing is kept with flag `spacing_not_on_sheet` and no penalty).

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev && git pull
git switch -c eric/e8-shop
```

Create `backend/tests/extract/test_columns_shop.py`:

```python
from l2c.extract.columns_shop import (
    assign_level,
    extract_shop_columns,
    find_level_lines,
    split_views,
)
from l2c.extract.runs import text_runs
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import new_doc, put, save

LEVEL_LINES = [
    ("N4", 100.0, "118' - 4\"", "NIVEAU 4"),
    ("N3", 300.0, "108' - 6\"", "NIVEAU 3"),
    ("N2", 500.0, "98' - 9\"", "NIVEAU 2"),
]
LABELS = {"D-6": 200.0, "D-7": 320.0, "E-7": 440.0}


def shop_pdf(tmp_path, *, drop_label=False):
    doc, page = new_doc(1200, 900)
    for _, y, el, name in LEVEL_LINES:
        put(page, 60, y, f"EL.: {el}")
        put(page, 60, y + 7, name)
    for label, x in LABELS.items():
        if drop_label and label == "E-7":
            continue
        put(page, x, 800, label)
        # upper band (N4..N3 -> level N3) and lower band (N3..N2 -> level N2)
        put(page, x, 130, "VERT: 4 25M B7-01")
        put(page, x, 139, 'ÉTRI: 6 10M T4X21 @6"')
        put(page, x, 330, "VERT: 6 20M B9-02")
        put(page, x, 339, "ÉTRI: 13 10M T2X27")  # no spacing printed, like real sheets
    return save(doc, tmp_path / "COLONNES_P1.pdf")


def test_level_lines_and_bands(tmp_path):
    (page,) = load_pdf(shop_pdf(tmp_path))
    lines = find_level_lines(page, text_runs(page.words))
    assert [line.level for line in lines] == ["N4", "N3", "N2"]
    assert abs(lines[0].elevation_mm - (118 * 304.8 + 4 * 25.4)) < 0.01
    views = split_views(lines)
    assert len(views) == 1
    assert assign_level(views, 130) == ("N3", []) and assign_level(views, 330) == ("N2", [])
    assert assign_level(views, 50) == ("UNKNOWN", ["level_unknown"])
    assert assign_level(views, 900) == ("FDN", ["below_lowest_level"])


def test_two_stacked_elevation_views_do_not_mix_levels(tmp_path):
    doc, page = new_doc(1200, 1400)
    for y, el, name in [
        (100, "108' - 6\"", "NIVEAU 3"),
        (300, "98' - 9\"", "NIVEAU 2"),
        (700, "108' - 6\"", "NIVEAU 3"),
        (900, "98' - 9\"", "NIVEAU 2"),
    ]:
        put(page, 60, y, f"EL.: {el}")
        put(page, 60, y + 7, name)
    (p,) = load_pdf(save(doc, tmp_path / "views.pdf"))
    views = split_views(find_level_lines(p, text_runs(p.words)))
    assert [[line.level for line in v] for v in views] == [["N3", "N2"], ["N3", "N2"]]
    assert assign_level(views, 200) == ("N2", [])  # first view
    assert assign_level(views, 400) == (
        "FDN",
        ["below_lowest_level"],
    )  # below first view's last line
    assert assign_level(views, 800) == ("N2", [])  # second view


def test_extracts_one_element_per_label_and_band(tmp_path):
    (page,) = load_pdf(shop_pdf(tmp_path))
    els, levels = extract_shop_columns(page)
    assert len(els) == 6 and [lv.level for lv in levels] == ["N4", "N3", "N2"]
    k6_n3 = next(e for e in els if e.grid == "D-6" and e.level == "N3")
    assert k6_n3.source == "shop" and k6_n3.feuillet == "COLONNES_P1"
    assert k6_n3.armature[0].quantite == 4 and k6_n3.armature[0].diametre == "25M"
    assert k6_n3.armature[1].quantite == 6 and k6_n3.armature[1].espacement_mm == 152.4
    assert k6_n3.match_key.key_str() == "colonne|N3|D|6"
    assert k6_n3.quality.location.anchor == "label"
    k6_n2 = next(e for e in els if e.grid == "D-6" and e.level == "N2")
    assert k6_n2.armature[1].espacement_mm is None
    assert "spacing_not_on_sheet" in k6_n2.quality.flags
    assert "spacing" not in k6_n2.quality.attributes  # absent, not penalised


def test_no_labels_means_no_elements_but_levels_still_reported(tmp_path):
    doc, page = new_doc()
    put(page, 60, 100, "EL.: 118' - 4\"")
    put(page, 60, 107, "NIVEAU 4")
    put(page, 60, 300, "EL.: 108' - 6\"")
    put(page, 60, 307, "NIVEAU 3")
    (p,) = load_pdf(save(doc, tmp_path / "x.pdf"))
    els, levels = extract_shop_columns(p)
    assert els == [] and len(levels) == 2


def test_blocks_below_the_lowest_level_line_are_foundation_dowels(tmp_path):
    doc, page = new_doc()
    put(page, 60, 100, "EL.: 118' - 4\"")
    put(page, 60, 107, "NIVEAU 4")
    put(page, 60, 300, "EL.: 108' - 6\"")
    put(page, 60, 307, "NIVEAU 3")
    for label, x in {"D-6": 200.0, "D-7": 320.0}.items():
        put(page, x, 800, label)
        put(page, x, 600, "VERT: 4 25M B7-01")  # below the last level line
    (p,) = load_pdf(save(doc, tmp_path / "y.pdf"))
    els, _ = extract_shop_columns(p)
    assert len(els) == 2 and all("below_lowest_level" in e.quality.flags for e in els)
    assert all(e.level == "FDN" and e.quality.overall <= 0.8 for e in els)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest backend/tests/extract/test_columns_shop.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.extract.columns_shop'`.

- [ ] **Step 3: Write the extractor**

Create `backend/l2c/extract/columns_shop.py`:

```python
"""Extract column elements from a shop-drawing elevation sheet (convention A).

Layout (typical of sheets seen so far): grid labels like `J-12` along one edge, one column strip per
label; level bands down the page marked by `EL.: <elevation>` lines with the level name just
below; in each band every column strip holds a `VERT: <n> <size> <mark>` run and an
`ÉTRI: <n> <size> <mark> @<spacing>` run. Distances are multiples of the page's own geometry.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePath

from l2c.contract.models import Armature, ElementExt, LevelInfo, MatchKey
from l2c.extract import quality as Q
from l2c.extract.calibrate import calibrate
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.notation import (
    canon_level,
    parse_elevation,
    parse_grid_label,
    parse_shop_ties,
    parse_shop_vert,
)
from l2c.extract.runs import Run, cluster_1d, text_runs
from l2c.ingest.pages import PageData, Word

MIN_LABELS = 2
FALLBACK_STRIP_TOL_H = 7.5  # used only when there are too few labels to measure their spacing


@dataclass(frozen=True)
class LevelLine:
    level: str
    name: str
    y: float
    elevation_mm: float | None


def find_level_lines(
    page: PageData, runs: list[Run], config: Config = DEFAULT_CONFIG, word_h: float = 8.0
) -> list[LevelLine]:
    lines: list[LevelLine] = []
    for r in runs:
        if not config.starts(r.text, config.elevation_line):
            continue
        if r.x0 > config.level_x_fraction * page.width:
            continue
        below = [
            c
            for c in runs
            if 0 <= c.y0 - r.y0 <= config.level_label_below_word_heights * word_h
            and abs(c.x0 - r.x0) <= 1.5 * word_h
            and c is not r
        ]
        if not below:
            continue
        label = min(below, key=lambda c: c.y0 - r.y0)
        level = canon_level(label.text, config)
        if level is None:
            continue
        lines.append(
            LevelLine(level, label.text, round(r.y0, 2), parse_elevation(r.text.split(":", 1)[-1]))
        )
    return sorted(lines, key=lambda line: line.y)


def split_views(lines: list[LevelLine]) -> list[list[LevelLine]]:
    """Split level lines (top to bottom) into elevation views.

    A new view starts when the elevation rises or a level name repeats.
    """
    views: list[list[LevelLine]] = []
    for line in lines:
        if views:
            cur = views[-1]
            prev = cur[-1]
            rises = (
                line.elevation_mm is not None
                and prev.elevation_mm is not None
                and line.elevation_mm > prev.elevation_mm
            )
            repeats = any(c.level == line.level for c in cur)
            if not (rises or repeats):
                cur.append(line)
                continue
        views.append([line])
    return views


def assign_level(views: list[list[LevelLine]], y: float) -> tuple[str, list[str]]:
    """Level of a block at height y, plus quality flags.

    Between two level lines of one view the block belongs to the lower line's level (the column
    rises from it). Below the lowest line of a view it is a foundation dowel segment: FDN.
    """
    owner = None
    for view in views:
        if view[0].y <= y:
            owner = view
    if owner is None:
        return "UNKNOWN", ["level_unknown"]
    for upper, lower in zip(owner, owner[1:], strict=False):
        if upper.y <= y < lower.y:
            return lower.level, []
    return "FDN", ["below_lowest_level"]


def find_labels(
    words: list[Word], config: Config = DEFAULT_CONFIG, word_h: float = 8.0
) -> list[tuple[str, float, Word]]:
    cand = [(parse_grid_label(w.text, config), w) for w in words]
    cand = [(p, w) for p, w in cand if p is not None]
    if len(cand) < MIN_LABELS:
        return []
    tol = max(0.5, config.grid_align_word_heights * word_h)
    groups = cluster_1d([w.y0 for _, w in cand], tol)
    best = max(groups, key=lambda g: (len(g), -min(cand[i][1].y0 for i in g)))
    labels = [(f"{cand[i][0][0]}-{cand[i][0][1]:g}", cand[i][0][1], cand[i][1]) for i in best]
    return sorted(labels, key=lambda t: t[2].x0)


def strip_tolerance(labels: list[tuple[str, float, Word]], config: Config, word_h: float) -> float:
    xs = sorted({round(w.x0, 1) for _, _, w in labels})
    gaps = [b - a for a, b in zip(xs, xs[1:], strict=False) if b - a > 0.1 * word_h]
    if len(gaps) < 2:
        return FALLBACK_STRIP_TOL_H * word_h
    return config.strip_tol_fraction * statistics.median(gaps)


def _strip_for(run: Run, labels: list[tuple[str, float, Word]], tol: float):
    ranked = sorted(labels, key=lambda t: (abs(t[2].x0 - run.x0), t[2].x0))
    d1 = abs(ranked[0][2].x0 - run.x0)
    if d1 > tol:
        return None
    d2 = abs(ranked[1][2].x0 - run.x0) if len(ranked) > 1 else float("inf")
    margin = 1.0 if d2 == float("inf") else (d2 - d1) / d2
    return ranked[0], round(margin, 3)


def extract_shop_columns(
    page: PageData, config: Config = DEFAULT_CONFIG
) -> tuple[list[ElementExt], list[LevelInfo]]:
    scale = calibrate(page.words, None, config)
    h = scale.word_h
    runs = text_runs(page.words, gap=scale.run_gap, split_before=config.keywords())
    lines = find_level_lines(page, runs, config, h)
    views = split_views(lines)
    levels = [LevelInfo(level=ln.level, name=ln.name, elevation_mm=ln.elevation_mm) for ln in lines]
    labels = find_labels(page.words, config, h)
    if not labels:
        return [], levels
    tol = strip_tolerance(labels, config, h)
    stem = PurePath(page.fichier).stem
    verts = [
        r
        for r in runs
        if config.starts(r.text, config.shop_vert) and parse_shop_vert(r.text, config)
    ]
    ties_runs = [
        r
        for r in runs
        if config.starts(r.text, config.shop_ties) and parse_shop_ties(r.text, config)
    ]
    seen: Counter[str] = Counter()
    out: list[ElementExt] = []
    for v in sorted(verts, key=lambda r: (r.x0, r.y0)):
        strip = _strip_for(v, labels, tol)
        if strip is None:
            continue
        (grid_cell, col_num, label_word), margin = strip
        row = grid_cell.split("-", 1)[0]
        vert = parse_shop_vert(v.text, config)
        near = [
            t
            for t in ties_runs
            if abs(t.x0 - v.x0) <= config.ties_x_tol_word_heights * h
            and 0 < t.y0 - v.y0 <= config.ties_below_word_heights * h
        ]
        tie_run = min(near, key=lambda t: t.y0 - v.y0) if near else None
        tie = parse_shop_ties(tie_run.text, config) if tie_run else None
        level, flags = assign_level(views, v.y0)
        flags = list(flags)
        if tie is None:
            flags.append("ties_missing")
        elif tie.spacing_mm is None:
            flags.append("spacing_not_on_sheet")
        if margin < 0.3:
            flags.append("weak_strip_assignment")
        attrs = {"count": Q.attr(vert.count), "size": Q.attr(vert.size)}
        if tie is not None:
            attrs["tie_size"] = Q.attr(tie.size)
            attrs["tie_count"] = Q.attr(tie.count)
            if tie.spacing_mm is not None:
                attrs["spacing"] = Q.attr(tie.spacing_mm)
        passed, failed = Q.column_checks(
            vert.count, vert.size, tie.spacing_mm if tie else None, config
        )
        loc = Q.location(
            "label",
            1.0,
            grid_cell=grid_cell,
            binding_method="label_strip",
            anchor_dist_pt=round(abs(label_word.x0 - v.x0), 2),
            margin=margin,
        )
        x0 = min(v.x0, tie_run.x0 if tie_run else v.x0)
        y0 = v.y0
        x1 = max(v.x1, tie_run.x1 if tie_run else v.x1)
        y1 = max(v.y1, tie_run.y1 if tie_run else v.y1)
        base = f"{stem}_p{page.page}_{grid_cell}_{level}_shop"
        seen[base] += 1
        element_id = base if seen[base] == 1 else f"{base}_{seen[base]}"
        if seen[base] > 1:
            flags.append("duplicate_cell_level_on_page")
        armature = [Armature(repere=vert.mark, diametre=vert.size, quantite=vert.count)]
        if tie is not None:
            armature.append(
                Armature(
                    repere=tie.mark,
                    diametre=tie.size,
                    quantite=tie.count,
                    espacement_mm=tie.spacing_mm,
                )
            )
        out.append(
            ElementExt(
                id=element_id,
                source="shop",
                fichier=page.fichier,
                feuillet=stem,
                page=page.page,
                x=round((x0 + x1) / 2, 2),
                y=round((y0 + y1) / 2, 2),
                type_element="colonne",
                element=grid_cell,
                armature=armature,
                match_key=MatchKey(type="colonne", level=level, row=row, col=col_num),
                grid=grid_cell,
                level=level,
                bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                quality=Q.build_quality(
                    type_conf=1.0,
                    level_conf={"UNKNOWN": 0.3, "FDN": 0.8}.get(level, 1.0),
                    loc=loc,
                    attrs=attrs,
                    passed=passed,
                    failed=failed,
                    flags=flags,
                ),
                extraction_method="rules",
                raw_text=" | ".join(r.text for r in (v, tie_run) if r is not None),
                provenance={"file": page.fichier, "page": page.page, "adapter": "shop_label_strip"},
            )
        )
    out.sort(key=lambda e: (e.level, e.grid or "", e.id))
    return out, levels
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_columns_shop.py -v
```

Expected: 5 passed (level bands, stacked views, no labels, blocks below the lowest line).

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/extract/columns_shop.py backend/tests/extract/test_columns_shop.py
git commit -m "Extract columns from shop drawings"
```

```bash
git switch dev && git merge --no-ff eric/e8-shop
```


---

### Task E9: Pipeline, per-page vocabulary learning, layout detection, error isolation and the extract CLI

**Files:**
- Create: `backend/l2c/extract/learn.py`, `backend/l2c/extract/ocr_quality.py`, `backend/l2c/extract/pipeline.py`, `backend/l2c/extract/__main__.py`
- Test: `backend/tests/extract/test_learn.py`, `backend/tests/extract/test_pipeline.py`

**Interfaces:**
- Consumes: E1 to E8; `write_bundle`, `MetaBundle`, `SheetInfo`, `GridSheet`, `LevelInfo` (F2).
- Produces: `learn_keywords(words, config) -> dict[field, tuple[str, ...]]` and `learn_config(words, config) -> Config` (the word that precedes each standard notation form, when it repeats at least 3 times and covers a clear share of that form on the page, becomes that page's label; a label is never learned for two roles, most specific form first; unchanged config when nothing new is found). The notation forms are standard (a bar line is a word, a count, a dash and a bar size; a tie line is a word, a bar size, `@`, a spacing; and so on), so a project with other labels needs no config file.
- `discover(project_dir) -> Discovery(plans, shops)` (plan PDFs directly in the project folder; shop PDFs under `DA/`, element type from the folder name in French or English); `extract_project(project_dir, project=None, config=DEFAULT_CONFIG, use_ocr=False, learn=True) -> MetaBundle`; `plan_layout` / `shop_layout` (one of `plan_outline`, `plan_blocks_without_grid`, `not_a_column_plan`, `shop_label_strip`, `shop_unlabelled_unsupported`, `shop_levels_not_found`, `no_column_blocks`, `needs_ocr`, `empty_page`, `rotated_text_unsupported`, `type_not_supported:<type>`, `error:<ExceptionName>`, `error:open_failed:<ExceptionName>`, recorded in `SheetInfo.layout`); `mark_ocr(elements, words, config)`; CLI `python -m l2c.extract <project_dir> --out <dir> [--project NAME] [--ocr] [--no-learn] [--config FILE]` printing counts only.
- A page that fails never stops the run; a file that cannot be opened is recorded and skipped; a page that fits no adapter is reported with the reason, never guessed; shop pages with column blocks but no elevation lines are reported as `shop_levels_not_found` because elements without a level can never be matched.

- [ ] **Step 1: Branch and write the failing tests**

```bash
git switch dev && git pull
git switch -c eric/e9-pipeline
```

Create `backend/tests/extract/test_learn.py`:

```python
"""Labels in an invented language are learned from the notation around them."""

import dataclasses

from l2c.extract.columns_plan import extract_plan_columns
from l2c.extract.config import DEFAULT_CONFIG
from l2c.extract.grid import fit_grid
from l2c.extract.learn import learn_config, learn_keywords
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import DisplayPage

ROWS = {"A": 300.0, "B": 400.0, "C": 500.0, "D": 600.0, "E": 700.0}
COLS = {"1": 500.0, "2": 600.0, "3": 700.0, "4": 800.0, "5": 900.0}
CELLS = [("A", "1"), ("A", "2"), ("B", "2"), ("C", "4"), ("D", "5")]

# an invented vocabulary no default dictionary contains
WORDS = dict(bar="ZORB", tie="KLEM", sect="QUAD", end="FINX", title="PLAN DES COLONNES - NIVEAU 2")


def invented_plan(tmp_path):
    dp = DisplayPage(1200, 900)
    for letter, y in ROWS.items():
        dp.put(40, y, letter)
        dp.put(1100, y, letter)
    for label, x in COLS.items():
        dp.put(x, 60, label)
        dp.put(x, 820, label)
    dp.put(300, 40, WORDS["title"])
    dp.put(1050, 860, "S-517")
    for r, c in CELLS:
        cx, cy = COLS[c] + 2, ROWS[r] + 4
        dp.rect(cx, cy)
        x, y = cx + 35, cy + 20
        dp.put(x, y - 9, f'{WORDS["sect"]} 18"x20"')
        dp.put(x, y, f"{WORDS['bar']}: 4-25M")
        dp.put(x, y + 9, f'{WORDS["tie"]}: 10M@6" c/c')
        dp.put(x, y + 18, f"{WORDS['end']}: 25MPa")
    dp.put(100, 150, "TYP: 4-25M")  # a one-off label must not be learned
    return dp.save(tmp_path / "invented.pdf")


def test_unknown_labels_are_learned_from_the_notation_around_them(tmp_path):
    (page,) = load_pdf(invented_plan(tmp_path))
    learned = learn_keywords(page.words)
    assert learned["block_start"] == ("ZORB",)
    assert learned["ties_line"] == ("KLEM",)
    assert learned["section_line"] == ("QUAD",)
    assert "TYP" not in learned["block_start"]  # appears once: below the occurrence minimum


def test_without_learning_the_default_dictionary_finds_nothing(tmp_path):
    (page,) = load_pdf(invented_plan(tmp_path))
    assert extract_plan_columns(page, "N2", fit_grid(page.words)) == []


def test_with_learning_the_same_page_extracts_every_column(tmp_path):
    (page,) = load_pdf(invented_plan(tmp_path))
    config = learn_config(page.words)
    els = extract_plan_columns(page, "N2", fit_grid(page.words, config), config)
    assert sorted(e.grid for e in els) == ["A-1", "A-2", "B-2", "C-4", "D-5"]
    assert all(e.armature[0].quantite == 4 and e.armature[1].espacement_mm == 152.4 for e in els)


def test_known_labels_are_not_duplicated_and_the_config_is_unchanged_when_nothing_is_new(tmp_path):
    from tests.extract.test_columns_plan import plan_pdf

    (page,) = load_pdf(plan_pdf(tmp_path))
    assert learn_keywords(page.words) == {}
    assert learn_config(page.words) is DEFAULT_CONFIG


def test_learning_is_deterministic_and_does_not_mutate_the_default(tmp_path):
    (page,) = load_pdf(invented_plan(tmp_path))
    a, b = learn_config(page.words), learn_config(page.words)
    assert a == b and dataclasses.is_dataclass(a)
    assert "ZORB" not in DEFAULT_CONFIG.block_start


def test_a_page_without_notation_learns_nothing():
    assert learn_keywords([]) == {}


def test_the_pipeline_learns_by_default_and_can_be_told_not_to(tmp_path):
    from l2c.extract.pipeline import extract_project

    root = tmp_path / "P"
    root.mkdir()
    invented_plan(tmp_path).rename(root / "plan.pdf")
    learned = extract_project(root)
    assert sorted(e.grid for e in learned.elements) == ["A-1", "A-2", "B-2", "C-4", "D-5"]
    assert learned.sheets[0].layout == "plan_outline"
    off = extract_project(root, learn=False)
    assert off.elements == []


def test_a_label_is_never_learned_for_two_roles(tmp_path):
    """A tie line without a printed spacing has the shape of a vertical-bar line; it must not be
    learned as one, or every tie line would be read twice."""
    dp = DisplayPage(1200, 900)
    for x in (100, 300, 500, 700, 900):
        dp.put(x, 100, "QWERT: 4 25M B7-01")
        dp.put(x, 109, 'ZIGZAG: 6 10M T3X21 @6"')
        dp.put(x, 300, "QWERT: 4 25M B7-02")
        dp.put(x, 309, "ZIGZAG: 13 10M T3X18")  # no spacing printed
    (page,) = load_pdf(dp.save(tmp_path / "shop_roles.pdf"))
    learned = learn_keywords(page.words)
    assert learned.get("shop_vert") == ("QWERT",)
    assert "ZIGZAG" not in learned.get("shop_vert", ())
    assert learned.get("shop_ties") == ("ZIGZAG",)
```

Create `backend/tests/extract/test_pipeline.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

import jsonschema

from l2c.contract.io import read_bundle, write_bundle
from l2c.extract.pipeline import discover, extract_project, folder_type
from tests.extract.test_columns_plan import plan_pdf
from tests.extract.test_columns_shop import shop_pdf

SCHEMAS = Path(__file__).resolve().parents[3] / "shared" / "schemas"


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "PROJ"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    (root / "DA" / "Dalles").mkdir(parents=True)
    plan = plan_pdf(tmp_path)
    plan.rename(root / "L2C_PLAN_STR_PROJ.pdf")
    shop = shop_pdf(tmp_path)
    shop.rename(root / "DA" / "Colonnes" / "COLONNES P1.pdf")
    return root


def test_folder_type_mapping():
    assert folder_type(("Colonnes",)) == "colonne"
    assert folder_type(("Semelles et radiers",)) == "fondation"
    assert folder_type(("Murs refends",)) == "mur_refend"
    assert folder_type(("Autre",)) is None


def test_discovery_is_sorted_and_typed(tmp_path):
    found = discover(make_project(tmp_path))
    assert [p.name for p in found.plans] == ["L2C_PLAN_STR_PROJ.pdf"]
    assert [(p.name, t) for p, t in found.shops] == [("COLONNES P1.pdf", "colonne")]


def test_extract_project_end_to_end(tmp_path):
    bundle = extract_project(make_project(tmp_path))
    plan = [e for e in bundle.elements if e.source == "plan"]
    shop = [e for e in bundle.elements if e.source == "shop"]
    assert len(plan) == 4 and len(shop) == 6
    assert {lv.level for lv in bundle.levels} >= {"N2", "N3", "N4"}
    assert bundle.sheets[0].type_element == "colonne" and bundle.sheets[0].level == "N2"
    assert len(bundle.grids) == 1
    assert {e.fichier for e in shop} == {"DA/Colonnes/COLONNES P1.pdf"}


def test_bundle_files_validate_against_exported_schemas(tmp_path):
    out = tmp_path / "meta"
    write_bundle(out, extract_project(make_project(tmp_path)))
    for data_file, schema_file in [
        ("elements.json", "elements.schema.json"),
        ("elements.ext.json", "elements.ext.schema.json"),
        ("grid.json", "grid.schema.json"),
        ("levels.json", "levels.schema.json"),
        ("sheets.json", "sheets.schema.json"),
        ("ids.json", "ids.schema.json"),
        ("manifest.json", "manifest.schema.json"),
    ]:
        data = json.loads((out / data_file).read_text(encoding="utf-8"))
        schema = json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)
    strict = json.loads((out / "elements.json").read_text(encoding="utf-8"))
    assert all(
        set(r)
        == {
            "id",
            "source",
            "fichier",
            "feuillet",
            "page",
            "x",
            "y",
            "type_element",
            "element",
            "armature",
        }
        for r in strict
    )
    assert read_bundle(out).project == "PROJ"


def test_two_runs_are_byte_identical(tmp_path):
    root = make_project(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    write_bundle(a, extract_project(root))
    write_bundle(b, extract_project(root))
    for f in sorted(p.name for p in a.iterdir()):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_cli_prints_counts_only(tmp_path):
    root = make_project(tmp_path)
    out = tmp_path / "cli"
    r = subprocess.run(
        [sys.executable, "-m", "l2c.extract", str(root), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("elements=10 plan=4 shop=6")
    assert "plan_outline" in r.stdout and "shop_label_strip" in r.stdout
    assert "25M" not in r.stdout and "D-6" not in r.stdout  # no drawing values on stdout


def test_empty_project_and_missing_folders_do_not_crash(tmp_path):
    empty = tmp_path / "EMPTY"
    empty.mkdir()
    b = extract_project(empty)
    assert b.elements == [] and b.sheets == [] and b.project == "EMPTY"
    only_plan = tmp_path / "ONLYPLAN"
    only_plan.mkdir()
    plan_pdf(tmp_path).rename(only_plan / "plan.pdf")
    b2 = extract_project(only_plan)  # no DA folder at all
    assert len(b2.elements) == 4 and all(e.source == "plan" for e in b2.elements)


def test_file_names_with_spaces_and_accents_work(tmp_path):
    root = tmp_path / "Projet Été"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    plan_pdf(tmp_path).rename(root / "Plan Structure – Étage 2.pdf")
    shop_pdf(tmp_path).rename(root / "DA" / "Colonnes" / "COLONNES Édition 1 (révisé).pdf")
    out = tmp_path / "meta"
    write_bundle(out, extract_project(root))
    bundle = read_bundle(out)
    assert {e.fichier for e in bundle.elements if e.source == "shop"} == {
        "DA/Colonnes/COLONNES Édition 1 (révisé).pdf"
    }
    assert any("Étage 2" in e.fichier for e in bundle.elements if e.source == "plan")


def test_a_corrupt_pdf_is_reported_and_the_rest_of_the_run_continues(tmp_path):
    root = make_project(tmp_path)
    (root / "DA" / "Colonnes" / "broken.pdf").write_bytes(b"%PDF-1.4 this is not a pdf")
    (root / "DA" / "Colonnes" / "empty.pdf").write_bytes(b"")
    b = extract_project(root)
    bad = {s.fichier: s.layout for s in b.sheets if s.layout and s.layout.startswith("error:")}
    assert set(bad) == {"DA/Colonnes/broken.pdf", "DA/Colonnes/empty.pdf"}
    assert all(v.startswith("error:open_failed:") for v in bad.values())
    assert len([e for e in b.elements if e.source == "shop"]) == 6  # the good file still ran
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python -m pytest backend/tests/extract/test_learn.py backend/tests/extract/test_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.extract.learn'`.

- [ ] **Step 3: Write learning, quality marking, the pipeline and the CLI**

Create `backend/l2c/extract/learn.py`:

```python
"""Learn this document's own labels from the standard notation around them.

The *notation* of rebar annotations is standard even when the *label* is not: a bar line is a word
followed by a count, a dash and a bar size; a tie line is a word followed by a bar size, `@` and a
spacing; a shop vertical-bar line is a word, a count, a bar size and a mark; an elevation line is
a word followed by feet-inches. The word that precedes each form, when it repeats, is that
document's label. Learned labels are added to the config for that page only.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.runs import median_word_height, text_runs
from l2c.ingest.pages import Word

MIN_OCCURRENCES = 3
MIN_SHARE = 0.3  # of all occurrences of that notation form on the page
PRIORITY = ("ties_line", "shop_ties", "block_start", "section_line", "elevation_line", "shop_vert")
_LABEL = r"(?P<k>[^\W\d_][\w.]*)"
_SEP = r"[\s:.\-]*"


def _forms(size: str) -> dict[str, re.Pattern[str]]:
    return {
        "block_start": re.compile(rf"^{_LABEL}{_SEP}\d{{1,2}}\s*-\s*{size}\b"),
        "ties_line": re.compile(rf"^{_LABEL}{_SEP}{size}\s*@"),
        "section_line": re.compile(rf"^{_LABEL}{_SEP}\d+(?:\.\d+)?\s*[\"'”″]?\s*[xX×]\s*\d"),
        "shop_vert": re.compile(rf"^{_LABEL}{_SEP}\d{{1,3}}\s*{size}\s*[^\s@]+$"),
        "shop_ties": re.compile(rf"^{_LABEL}{_SEP}\d{{1,3}}\s*{size}\s*[^\s@]+\s*@"),
        "elevation_line": re.compile(rf"^{_LABEL}{_SEP}\d+\s*'\s*-?\s*\d*"),
    }


def _normalise(label: str) -> str:
    return label.strip(".:- ").upper()


def learn_keywords(
    words: list[Word], config: Config = DEFAULT_CONFIG
) -> dict[str, tuple[str, ...]]:
    """Per config field, the labels found on this page that are not already known."""
    gap = max(1.0, config.run_gap_word_heights * median_word_height(words))
    runs = text_runs(words, gap=gap)
    found: dict[str, Counter[str]] = {}
    totals: Counter[str] = Counter()
    for field, pattern in _forms(config.bar_size_pattern).items():
        counts: Counter[str] = Counter()
        for r in runs:
            m = pattern.match(r.text.strip())
            if m:
                counts[_normalise(m.group("k"))] += 1
                totals[field] += 1
        found[field] = counts
    # A label already used for one role must not be learned for another: a tie line without a
    # printed spacing has the same shape as a vertical-bar line, and would otherwise be read twice.
    all_known = {
        w.strip().rstrip(".:").upper()
        for f in found
        for w in getattr(config, f)
        if w.strip().rstrip(".:")
    }
    learned: dict[str, tuple[str, ...]] = {}
    claimed: set[str] = set()
    # most specific forms first: a label seen before `@` is a tie label before it can be a bar label
    for field in PRIORITY:
        counts = found[field]
        known = all_known
        keep = sorted(
            label
            for label, n in counts.items()
            if n >= MIN_OCCURRENCES
            and n >= MIN_SHARE * totals[field]
            and label
            and label not in claimed
            and not any(label.startswith(k) for k in known if k)
        )
        if keep:
            learned[field] = tuple(keep)
            claimed.update(keep)
    return learned


def learn_config(words: list[Word], config: Config = DEFAULT_CONFIG) -> Config:
    """The config extended with the labels this page uses (unchanged when nothing new is found)."""
    learned = learn_keywords(words, config)
    if not learned:
        return config
    return replace(config, **{f: (*getattr(config, f), *labels) for f, labels in learned.items()})
```

Create `backend/l2c/extract/ocr_quality.py`:

```python
"""Carry OCR confidence and snapping into the quality of the elements built from OCR words."""

from __future__ import annotations

from l2c.contract.models import AttrQuality, ElementExt
from l2c.extract import quality as Q
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.ingest.pages import Word


def mark_ocr(
    elements: list[ElementExt], words: list[Word], config: Config = DEFAULT_CONFIG
) -> list[ElementExt]:
    """Return copies whose attribute confidences reflect how their text was read.

    An element's tokens are looked up among the page's OCR words; the weakest matching word sets
    the confidence, and a token that was snapped to the vocabulary is marked as such.
    """
    by_text: dict[str, tuple[float, bool]] = {}
    for w in words:
        conf, snapped = by_text.get(w.text, (1.0, False))
        by_text[w.text] = (
            min(conf, w.conf if w.conf is not None else 1.0),
            snapped or bool(w.original),
        )
    out: list[ElementExt] = []
    for e in elements:
        tokens = [t for t in (e.raw_text or "").replace("|", " ").split() if t in by_text]
        conf = min((by_text[t][0] for t in tokens), default=0.5)
        snapped = any(by_text[t][1] for t in tokens)
        attrs: dict[str, AttrQuality] = {}
        for name, a in e.quality.attributes.items():
            if a.status == "missing":
                attrs[name] = a
                continue
            attrs[name] = Q.attr(
                a.value,
                conf=1.0,
                status=a.status,
                text_source="ocr",
                ocr_conf=conf,
                snapped=snapped,
                original_text=a.original_text,
            )
        q = e.quality
        quality = Q.build_quality(
            type_conf=q.type_conf,
            level_conf=q.level_conf,
            loc=q.location,
            attrs=attrs,
            passed=q.consistency_passed,
            failed=q.consistency_failed,
            flags=[*q.flags, "ocr_text", *(["ocr_snapped"] if snapped else [])],
        )
        out.append(e.model_copy(update={"quality": quality, "extraction_method": "rules+ocr"}))
    return out
```

Create `backend/l2c/extract/pipeline.py`:

```python
"""Project-level extraction: PDFs in, MetaBundle out. Deterministic; no ML; no network.

For every page the pipeline decides which adapter fits (`layout`) from what the page contains,
and records that decision. A page that fits no adapter is reported as not covered, never guessed;
an exception on one page never stops the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from l2c.contract.io import MetaBundle
from l2c.contract.models import ElementExt, GridSheet, LevelInfo, SheetInfo
from l2c.extract.calibrate import calibrate
from l2c.extract.columns_plan import extract_plan_columns
from l2c.extract.columns_shop import extract_shop_columns, find_labels, find_level_lines
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import Grid, fit_grid
from l2c.extract.learn import learn_config
from l2c.extract.notation import parse_shop_vert, plan_column_level
from l2c.extract.ocr_quality import mark_ocr
from l2c.extract.runs import text_runs
from l2c.ingest.pages import PageData, load_pdf

VERTICAL_TEXT_LIMIT = 0.5  # more than this share of vertical words means rotated text

FOLDER_TYPES = {
    "colonnes": "colonne",
    "columns": "colonne",
    "poutres": "poutre",
    "beams": "poutre",
    "dalles": "dalle",
    "slabs": "dalle",
    "fondations": "fondation",
    "foundations": "fondation",
    "semelles": "fondation",
    "refends": "mur_refend",
    "murs": "mur_refend",
    "walls": "mur_refend",
}


@dataclass(frozen=True)
class Discovery:
    plans: list[Path]
    shops: list[tuple[Path, str | None]]  # (pdf, element type from the folder name)


def folder_type(rel_parts: tuple[str, ...]) -> str | None:
    for part in rel_parts:
        low = part.lower()
        for key, value in FOLDER_TYPES.items():
            if key in low:
                return value
    return None


def discover(project_dir: Path) -> Discovery:
    plans = sorted(p for p in project_dir.glob("*.pdf") if p.is_file())
    shops: list[tuple[Path, str | None]] = []
    da = project_dir / "DA"
    if da.is_dir():
        for pdf in sorted(da.rglob("*.pdf")):
            shops.append((pdf, folder_type(pdf.relative_to(da).parts[:-1])))
    return Discovery(plans, shops)


def has_text(page: PageData, config: Config = DEFAULT_CONFIG) -> bool:
    """Native extraction needs words; the `layer` label only decides whether OCR is needed."""
    return len(page.words) >= config.min_words_native


def _rel(project_dir: Path, path: Path) -> str:
    return path.relative_to(project_dir).as_posix()


def _open_failed(fichier: str, kind: str, etype: str | None, exc: Exception) -> SheetInfo:
    """A file that cannot be opened is recorded and skipped; the rest of the run continues."""
    return SheetInfo(
        fichier=fichier,
        page=0,
        feuillet=None,
        kind=kind,  # type: ignore[arg-type]
        type_element=etype,  # type: ignore[arg-type]
        level=None,
        layer="empty",
        width=0.0,
        height=0.0,
        rotation=0,
        layout=f"error:open_failed:{type(exc).__name__}",
    )


def plan_layout(page: PageData, level: str | None, grid: Grid | None, config: Config) -> str:
    """Which adapter fits a plan page, or why none does."""
    if not has_text(page, config):
        return "needs_ocr" if page.layer in {"vector", "image"} else "empty_page"
    if page.vertical_text > VERTICAL_TEXT_LIMIT:
        return "rotated_text_unsupported"
    if level is None:
        return "not_a_column_plan"
    if grid is None:
        return "plan_blocks_without_grid"
    return "plan_outline"


def shop_layout(page: PageData, etype: str | None, config: Config) -> str:
    if etype != "colonne":
        return f"type_not_supported:{etype or 'unknown'}"
    if not has_text(page, config):
        return "needs_ocr" if page.layer in {"vector", "image"} else "empty_page"
    if page.vertical_text > VERTICAL_TEXT_LIMIT:
        return "rotated_text_unsupported"
    scale = calibrate(page.words, None, config)
    runs = text_runs(page.words, gap=scale.run_gap, split_before=config.keywords())
    verts = [
        r
        for r in runs
        if config.starts(r.text, config.shop_vert) and parse_shop_vert(r.text, config)
    ]
    if not verts:
        return "no_column_blocks"
    if not find_labels(page.words, config, scale.word_h):
        return "shop_unlabelled_unsupported"
    if not find_level_lines(page, runs, config, scale.word_h):
        return "shop_levels_not_found"  # elements without a level can never be matched
    return "shop_label_strip"


def prepare_page(page: PageData, pdf: Path, use_ocr: bool, config: Config) -> PageData:
    """Replace a text-less page's words with OCR words when OCR is enabled."""
    if use_ocr and not has_text(page, config) and page.layer in {"vector", "image"}:
        from l2c.ingest.ocr import ocr_pdf_page, with_ocr_words

        return with_ocr_words(page, ocr_pdf_page(pdf, page.page, config))
    return page


def extract_project(
    project_dir: Path,
    project: str | None = None,
    config: Config = DEFAULT_CONFIG,
    use_ocr: bool = False,
    learn: bool = True,
) -> MetaBundle:
    found = discover(project_dir)
    elements: list[ElementExt] = []
    grids: list[GridSheet] = []
    sheets: list[SheetInfo] = []
    levels: dict[str, LevelInfo] = {}

    def sheet(page: PageData, kind: str, etype, level, layout: str) -> SheetInfo:
        return SheetInfo(
            fichier=page.fichier,
            page=page.page,
            feuillet=page.feuillet if kind == "plan" else None,
            kind=kind,  # type: ignore[arg-type]
            type_element=etype,
            level=level,
            layer=page.layer,  # type: ignore[arg-type]
            width=round(page.width, 2),
            height=round(page.height, 2),
            rotation=page.rotation,
            layout=layout,
        )

    for pdf in found.plans:
        try:
            pages = load_pdf(pdf, _rel(project_dir, pdf), config)
        except Exception as exc:
            sheets.append(_open_failed(_rel(project_dir, pdf), "plan", None, exc))
            continue
        for page in pages:
            page = prepare_page(page, pdf, use_ocr, config)
            cfg = learn_config(page.words, config) if learn else config
            level = None
            layout = "unknown"
            etype = None
            try:
                text = " ".join(w.text for w in page.words)
                level = plan_column_level(text, cfg)
                grid = fit_grid(page.words, cfg) if has_text(page, cfg) else None
                layout = plan_layout(page, level, grid, cfg)
                if grid is not None and layout in {"plan_outline", "not_a_column_plan"}:
                    grids.append(
                        GridSheet(
                            fichier=page.fichier,
                            page=page.page,
                            feuillet=page.feuillet,
                            letters_on=grid.letters_on,  # type: ignore[arg-type]
                            rows=grid.rows,
                            cols=grid.cols,
                        )
                    )
                if layout in {"plan_outline", "plan_blocks_without_grid"}:
                    etype = "colonne"
                    levels.setdefault(level or "", LevelInfo(level=level or "", name=level or ""))
                    els = extract_plan_columns(page, level or "", grid, cfg)
                    elements.extend(mark_ocr(els, page.words, cfg) if page.source == "ocr" else els)
            except Exception as exc:  # one bad page must not stop the run
                layout = f"error:{type(exc).__name__}"
            sheets.append(sheet(page, "plan", etype, level, layout))

    for pdf, folder in found.shops:
        try:
            pages = load_pdf(pdf, _rel(project_dir, pdf), config)
        except Exception as exc:
            sheets.append(_open_failed(_rel(project_dir, pdf), "shop", folder, exc))
            continue
        for page in pages:
            layout = "unknown"
            try:
                page = prepare_page(page, pdf, use_ocr, config) if folder == "colonne" else page
                cfg = learn_config(page.words, config) if learn else config
                layout = shop_layout(page, folder, cfg)
                if layout == "shop_label_strip":
                    els, lvls = extract_shop_columns(page, cfg)
                    elements.extend(mark_ocr(els, page.words, cfg) if page.source == "ocr" else els)
                    for lv in lvls:
                        current = levels.get(lv.level)
                        if current is None or (
                            current.elevation_mm is None and lv.elevation_mm is not None
                        ):
                            levels[lv.level] = lv
            except Exception as exc:
                layout = f"error:{type(exc).__name__}"
            sheets.append(sheet(page, "shop", folder, None, layout))

    return MetaBundle(
        project=project or project_dir.name,
        elements=elements,
        grids=grids,
        levels=[levels[k] for k in sorted(levels)],
        sheets=sheets,
    )
```

Create `backend/l2c/extract/__main__.py`:

```python
"""`python -m l2c.extract <project_dir> --out <dir>`: write the metadata bundle for a project."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from l2c.contract.io import write_bundle
from l2c.extract.config import load_config
from l2c.extract.pipeline import extract_project


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l2c.extract")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--project", default=None)
    ap.add_argument("--ocr", action="store_true", help="read pages without a text layer with OCR")
    ap.add_argument(
        "--no-learn", action="store_true", help="do not learn labels from each page (config only)"
    )
    ap.add_argument(
        "--config",
        type=Path,
        default=None,
        help="JSON overrides for vocabulary, notation and tuning",
    )
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"not a directory: {args.project_dir}", file=sys.stderr)
        return 2
    bundle = extract_project(
        args.project_dir,
        args.project,
        load_config(args.config),
        use_ocr=args.ocr,
        learn=not args.no_learn,
    )
    write_bundle(args.out, bundle)
    flags = Counter(f for e in bundle.elements for f in e.quality.flags)
    layouts = Counter(s.layout for s in bundle.sheets)
    # counts only: never print drawing values
    print(
        f"elements={len(bundle.elements)} "
        f"plan={sum(e.source == 'plan' for e in bundle.elements)} "
        f"shop={sum(e.source == 'shop' for e in bundle.elements)} "
        f"layouts={dict(sorted(layouts.items(), key=lambda kv: str(kv[0])))} "
        f"flags={dict(sorted(flags.items()))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_learn.py backend/tests/extract/test_pipeline.py -v
python scripts/check.py
```

Expected: 17 passed. Learning: labels in an invented language are learned and a page extracts fully without any config (and extracts nothing with `--no-learn`); a one-off label is not learned; known labels are never duplicated; a label is never learned for two roles. Pipeline: end-to-end counts, all seven files validate against `shared/schemas/`, two runs are byte-identical, the CLI prints counts and layouts but no values, empty projects and folders without `DA/` work, names with spaces and accents work, corrupt and zero-byte PDFs are reported while the good file still runs.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/extract backend/tests/extract
git commit -m "Add extraction pipeline, label learning and CLI"
```

```bash
git switch dev && git merge --no-ff eric/e9-pipeline
```


---

### Task E10: Robustness suite: unseen scale, rotation, language, bar sizes, noise

**Files:**
- Test: `backend/tests/extract/test_robustness.py` (no new production code; if a test fails, fix the owning module and keep the test)

The suite builds the same synthetic column plan in different disguises and requires identical extraction: drawing scale 0.5x / 1x / 2.5x; stored page rotation 0 / 90 / 180 / 270 (drawn through `DisplayPage` so it looks upright once rotated); French and English with the default config; Spanish through a JSON config only; a US bar-size system (`#8`) through a JSON config; heavy noise text and thin shapes; no grid at all; unreadable pages (vector-only, empty); a page that raises; a folder type not supported yet.

- [ ] **Step 1: Branch and add the suite**

```bash
git switch dev && git pull
git switch -c eric/e10-robustness
```

Create `backend/tests/extract/test_robustness.py`:

```python
"""The extractor must not depend on one project's scale, rotation, language or bar-size system."""

import json

import pytest

from l2c.extract.columns_plan import extract_plan_columns
from l2c.extract.config import DEFAULT_CONFIG, load_config
from l2c.extract.grid import fit_grid
from l2c.extract.notation import canon_level, parse_count_size, plan_column_level
from l2c.extract.pipeline import extract_project
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import DisplayPage, new_doc, put, save

ROWS = {"D": 300.0, "E": 400.0, "F": 500.0, "G": 600.0, "H": 700.0}
COLS = {"6": 500.0, "7": 600.0, "8": 700.0, "9": 800.0, "10": 900.0}
CELLS = [("D", "6"), ("D", "7"), ("E", "7"), ("F", "9")]

FR = dict(
    title="PLAN DES COLONNES - NIVEAU 2",
    arm="ARM.: {n}-{s}",
    lig='LIG.: {t}@6" c/c',
    end="BÉTON: 25MPa / N",
    col='COL. 18"x20"',
)
EN = dict(
    title="COLUMN PLAN - LEVEL 2",
    arm="REINF.: {n}-{s}",
    lig='TIES: {t}@6" c/c',
    end="CONCRETE: 25MPa",
    col='COLUMN 18"x20"',
)
ES = dict(
    title="PLANO DE COLUMNAS - NIVEL 2",
    arm="REFUERZO: {n}-{s}",
    lig='ESTRIBOS: {t}@6" c/c',
    end="HORMIGON: 25MPa",
    col='COLUMNA 18"x20"',
)


def build_plan(tmp_path, *, scale=1.0, rotation=0, words=FR, size="25M", noise=False, grid=True):
    """A synthetic column plan; every distance and font size is multiplied by `scale`."""
    s = scale
    dp = DisplayPage(1200 * s, 900 * s, rotation)
    fs = 8.0 * s
    if grid:
        for letter, y in ROWS.items():
            dp.put(40 * s, y * s, letter, fs)
            dp.put(1100 * s, y * s, letter, fs)
        for label, x in COLS.items():
            dp.put(x * s, 60 * s, label, fs)
            dp.put(x * s, 820 * s, label, fs)
    dp.put(1050 * s, 860 * s, "S-517", fs)
    dp.put(300 * s, 40 * s, words["title"], fs)
    for r, c in CELLS:
        cx, cy = COLS[c] * s + 2 * s, ROWS[r] * s + 4 * s
        if grid:
            dp.rect(cx, cy, 12 * s, 18 * s)
        x, y = cx + 35 * s, cy + 20 * s
        dp.put(x, y - 9 * s, words["col"], fs)
        dp.put(x, y, words["arm"].format(n=4, s=size), fs)
        dp.put(x, y + 9 * s, words["lig"].format(t="10M" if size.endswith("M") else "#3"), fs)
        dp.put(x, y + 18 * s, words["end"], fs)
    if noise:
        for i in range(30):
            dp.put((50 + 33 * i) * s, (120 + 7 * (i % 9)) * s, f"NOTE {i} SEE DETAIL", fs)
            dp.rect(
                (70 + 31 * i) * s, (150 + 11 * (i % 5)) * s, 40 * s, 3 * s
            )  # thin lines, not columns
    return dp.save(tmp_path / f"plan_{scale}_{rotation}.pdf")


def extract(pdf, config=DEFAULT_CONFIG):
    (page,) = load_pdf(pdf, config=config)
    level = plan_column_level(" ".join(w.text for w in page.words), config)
    grid = fit_grid(page.words, config)
    return page, level, extract_plan_columns(page, level, grid, config)


def signature(els):
    return sorted(
        (e.grid, e.armature[0].quantite, e.armature[0].diametre, e.armature[1].espacement_mm)
        for e in els
        if e.grid
    )


EXPECTED = sorted((f"{r}-{c}", 4, "25M", 152.4) for r, c in CELLS)


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.5])
def test_drawing_scale_does_not_matter(tmp_path, scale):
    _, level, els = extract(build_plan(tmp_path, scale=scale))
    assert level == "N2" and signature(els) == EXPECTED


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_stored_page_rotation_does_not_matter(tmp_path, rotation):
    page, level, els = extract(build_plan(tmp_path, rotation=rotation))
    assert (page.width, page.height) == (1200, 900)  # always the displayed size
    assert level == "N2" and signature(els) == EXPECTED


@pytest.mark.parametrize("words", [FR, EN])
def test_french_and_english_work_with_the_default_config(tmp_path, words):
    _, level, els = extract(build_plan(tmp_path, words=words))
    assert level == "N2" and signature(els) == EXPECTED


def test_another_language_needs_only_a_json_config(tmp_path):
    cfg = tmp_path / "es.json"
    cfg.write_text(
        json.dumps(
            {
                "plan_column_titles": ["PLANO DE COLUMNAS"],
                "block_start": ["REFUERZO"],
                "section_line": ["COLUMNA "],
                "ties_line": ["ESTRIBOS"],
                "end_line": ["HORMIGON"],
                "level_numbered": ["NIVEL"],
            }
        ),
        encoding="utf-8",
    )
    pdf = build_plan(tmp_path, words=ES)
    _, level_default, els_default = extract(pdf)
    assert level_default is None and els_default == [] or signature(els_default) != EXPECTED
    _, level, els = extract(pdf, load_config(cfg))
    assert level == "N2" and signature(els) == EXPECTED


def test_unknown_config_keys_are_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"not_a_setting": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown config keys"):
        load_config(bad)


def test_a_different_bar_size_system_is_a_config_change(tmp_path):
    cfg = tmp_path / "us.json"
    cfg.write_text(
        json.dumps({"bar_size_pattern": r"#\d{1,2}", "bar_sizes": ["#4", "#5", "#8"]}),
        encoding="utf-8",
    )
    config = load_config(cfg)
    assert parse_count_size("ARM.: 4-#8", config).size == "#8"
    assert parse_count_size("ARM.: 4-25M", config) is None
    _, _, els = extract(build_plan(tmp_path, size="#8"), config)
    assert [e.armature[0].diametre for e in els if e.grid] == ["#8"] * 4


def test_noise_text_and_thin_shapes_do_not_change_the_result(tmp_path):
    _, _, els = extract(build_plan(tmp_path, noise=True))
    assert signature(els) == EXPECTED and len(els) == 4


def test_spacing_unit_default_is_configurable():
    from l2c.extract.notation import parse_size_spacing

    mm = load_config(None)
    assert parse_size_spacing("10M@150", mm).spacing_mm == pytest.approx(
        3810.0
    )  # inches by default
    metric = type(mm)(default_spacing_unit="mm")
    assert parse_size_spacing("10M@150", metric).spacing_mm == 150.0
    assert parse_size_spacing('10M@6"', metric).spacing_mm == pytest.approx(152.4)


def test_level_names_in_other_conventions():
    assert canon_level("Basement") == "SS" and canon_level("LEVEL 12") == "N12"
    assert canon_level("Étage 3") is None  # unknown word: reported, not guessed


def make_project(tmp_path, plan_pdf_path):
    root = tmp_path / "P"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    plan_pdf_path.rename(root / "plan.pdf")
    return root


def test_grid_missing_is_reported_not_guessed(tmp_path):
    root = make_project(tmp_path, build_plan(tmp_path, grid=False))
    b = extract_project(root)
    assert b.sheets[0].layout == "plan_blocks_without_grid"
    assert len(b.elements) == 4 and all("unbound_block" in e.quality.flags for e in b.elements)


def test_unreadable_pages_are_labelled_with_the_reason(tmp_path):
    doc, page = new_doc()
    for i in range(300):
        page.draw_line((10, 10 + i), (500, 12 + i))  # many paths, no text: a vector-only sheet
    root = tmp_path / "P"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    save(doc, root / "DA" / "Colonnes" / "vec.pdf")
    doc2, page2 = new_doc()
    save(doc2, root / "DA" / "Colonnes" / "empty.pdf")
    layouts = {s.fichier: s.layout for s in extract_project(root).sheets}
    assert layouts["DA/Colonnes/vec.pdf"] == "needs_ocr"
    assert layouts["DA/Colonnes/empty.pdf"] == "empty_page"


def test_a_failing_page_does_not_stop_the_run(tmp_path, monkeypatch):
    import l2c.extract.pipeline as P

    root = make_project(tmp_path, build_plan(tmp_path))

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(P, "extract_plan_columns", boom)
    b = extract_project(root)
    assert b.sheets[0].layout == "error:RuntimeError" and b.elements == []


def test_unsupported_folder_types_are_covered_in_sheets_not_elements(tmp_path):
    root = tmp_path / "P"
    (root / "DA" / "Dalles").mkdir(parents=True)
    doc, page = new_doc()
    put(page, 100, 100, "SOMETHING " * 5)
    save(doc, root / "DA" / "Dalles" / "slab.pdf")
    b = extract_project(root)
    assert b.elements == [] and b.sheets[0].layout == "type_not_supported:dalle"


def test_a_shop_sheet_without_any_level_marks_is_reported_not_emitted_as_unusable_elements(
    tmp_path,
):
    root = tmp_path / "P"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    dp = DisplayPage(1200, 900)
    for label, x in {"D-6": 200.0, "D-7": 360.0, "E-7": 520.0}.items():
        dp.put(x, 800, label)
        for y in (130, 330):
            dp.put(x, y, "VERT: 4 25M V7-A")
            dp.put(x, y + 9, 'ETRI: 6 10M T4X21 @6"')
    dp.save(root / "DA" / "Colonnes" / "nolevels.pdf")
    b = extract_project(root)
    assert b.elements == [] and b.sheets[0].layout == "shop_levels_not_found"
```

- [ ] **Step 2: Run it**

```bash
python -m pytest backend/tests/extract/test_robustness.py -v
```

Expected: 20 passed. If any case fails, that is a real adaptation bug: reproduce it with the smallest synthetic page, fix the module (never the test), re-run the whole suite.

- [ ] **Step 3: Commit and merge**

```bash
git add backend/tests/extract/test_robustness.py
git commit -m "Add robustness tests for unseen layouts"
```

```bash
git switch dev && git merge --no-ff eric/e10-robustness
```


---

### Task E11: Real-data tools and the first full run (local only)

**Files:**
- Create: `scripts/validate_extract.py`, `scripts/probe_project.py`, `scripts/sample_for_handcheck.py`, `scripts/grid_debug.py`

These print **counts and percentages only** (never drawing text) and write nothing that can be committed. Measured baselines from the development projects are in the local, git-ignored `docs/private/baselines.md`; this plan states the acceptance criteria without them.

- [ ] **Step 1: Add the scripts**

```bash
git switch dev && git pull
git switch -c eric/e11-tools
```

Create `scripts/validate_extract.py`:

```python
"""Local-only checks of the extractor on a real project. Prints counts and percentages only.

Usage: python scripts/validate_extract.py <project_dir>
Exit code 1 when a MVP threshold is missed (spec 10.16 criteria 3 and 4).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from l2c.extract.calibrate import calibrate
from l2c.extract.columns_plan import assemble_blocks, extract_plan_columns
from l2c.extract.columns_shop import extract_shop_columns
from l2c.extract.grid import fit_grid
from l2c.extract.notation import plan_column_level
from l2c.extract.pipeline import discover
from l2c.ingest.pages import load_pdf

PLAN_BOUND_MIN = 0.90
PLAN_PARSED_MIN = 0.95
SHOP_PARSED_MIN = 0.90


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", type=Path)
    args = ap.parse_args()
    found = discover(args.project_dir)
    ok = True
    print("PLAN column sheets: sheet level blocks parsed% bound%")
    for pdf in found.plans:
        for page in load_pdf(pdf, pdf.name):
            level = plan_column_level(" ".join(w.text for w in page.words))
            if not level:
                continue
            census = len(assemble_blocks(page, scale=calibrate(page.words)))
            els = extract_plan_columns(page, level, fit_grid(page.words))
            parsed = sum(e.armature[0].quantite is not None for e in els)
            bound = sum(e.grid is not None for e in els)
            pp, bb = parsed / max(census, 1), bound / max(census, 1)
            flag = "" if pp >= PLAN_PARSED_MIN and bb >= PLAN_BOUND_MIN else "  <-- below threshold"
            ok &= not flag
            print(f"  {page.feuillet} {level} {census} {pp:.0%} {bb:.0%}{flag}")
    print("SHOP column files: file page vert-runs elements parsed%")
    for pdf, etype in found.shops:
        if etype != "colonne":
            continue
        for page in load_pdf(pdf, pdf.name):
            if len(page.words) < 10:
                continue
            census = sum(1 for w in page.words if w.text.upper().startswith("VERT:"))
            els, _ = extract_shop_columns(page)
            if census == 0:
                continue
            pp = len(els) / census
            flag = "" if pp >= SHOP_PARSED_MIN else "  <-- below threshold"
            ok &= not flag
            print(f"  {pdf.name[-18:]} p{page.page} {census} {len(els)} {pp:.0%}{flag}")
    print("RESULT:", "pass" if ok else "below threshold")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

Create `scripts/probe_project.py`:

```python
"""First command to run on an unseen project: what will the extractor cover, and why not the rest?

Prints counts only (never drawing text). Local use.
Usage: python scripts/probe_project.py <project_dir> [--config overrides.json]
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from l2c.extract.config import load_config
from l2c.extract.pipeline import discover, extract_project

ADVICE = {
    "needs_ocr": "no text layer: needs the OCR path (SECOND tier)",
    "shop_unlabelled_unsupported": "column blocks without grid labels: needs the mark+axis adapter",
    "plan_blocks_without_grid": "blocks found but no grid: elements will be unbound (needs_review)",
    "rotated_text_unsupported": "text drawn sideways: not supported yet",
    "no_column_blocks": "shop page without column blocks (details, notes?)",
    "shop_levels_not_found": "blocks and labels but no elevation lines: no level can be assigned",
    "not_a_column_plan": "plan page that is not a column plan (other element type or notes)",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args()
    found = discover(args.project_dir)
    print(f"plan pdfs: {len(found.plans)}   shop pdfs: {len(found.shops)}")
    bundle = extract_project(args.project_dir, config=load_config(args.config))
    for kind in ("plan", "shop"):
        layouts = Counter(s.layout for s in bundle.sheets if s.kind == kind)
        print(f"\n{kind} pages by layout ({sum(layouts.values())} pages):")
        for name, n in sorted(layouts.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}  {name}" + (f"   <- {ADVICE[name]}" if name in ADVICE else ""))
    layers = Counter((s.kind, s.layer) for s in bundle.sheets)
    print("\nlayer kinds:", {f"{k}/{v}": n for (k, v), n in sorted(layers.items())})
    plan = sum(e.source == "plan" for e in bundle.elements)
    shop = sum(e.source == "shop" for e in bundle.elements)
    flags = Counter(f for e in bundle.elements for f in e.quality.flags)
    print(f"\nelements: plan={plan} shop={shop}   levels={[lv.level for lv in bundle.levels]}")
    print("quality flags:", dict(flags.most_common(6)))
    covered = sum(1 for s in bundle.sheets if s.layout in {"plan_outline", "shop_label_strip"})
    print(f"pages fully handled: {covered} of {len(bundle.sheets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `scripts/sample_for_handcheck.py`:

```python
"""Write a local CSV of N random extracted elements so a person can verify them in the PDF.

The CSV holds real values: it is written under data/ (git-ignored) and never shared.
Usage: python scripts/sample_for_handcheck.py <metadata_dir> --n 20 --out data/handcheck.csv
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from l2c.contract.io import read_bundle


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("metadata_dir", type=Path)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    els = read_bundle(args.metadata_dir).elements
    rng = random.Random(args.seed)
    sample = rng.sample(els, min(args.n, len(els)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "id",
                "source",
                "file",
                "page",
                "x",
                "y",
                "grid",
                "level",
                "count",
                "size",
                "tie_spacing_mm",
                "overall",
                "flags",
                "correct? (y/n)",
                "note",
            ]
        )
        for e in sample:
            a = e.armature
            w.writerow(
                [
                    e.id,
                    e.source,
                    e.fichier,
                    e.page,
                    e.x,
                    e.y,
                    e.grid,
                    e.level,
                    a[0].quantite if a else "",
                    a[0].diametre if a else "",
                    next((x.espacement_mm for x in a if x.espacement_mm is not None), ""),
                    e.quality.overall,
                    ";".join(e.quality.flags),
                    "",
                    "",
                ]
            )
    print(f"wrote {len(sample)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `scripts/grid_debug.py`:

```python
"""Why is (or is not) the grid found on one page? Counts only, never drawing text.

Usage: python scripts/grid_debug.py <pdf> <page number> [--config overrides.json]
Prints how many letter-like and number-like labels the page has, where they line up, and what
fit_grid decides. Use it when scripts/probe_project.py reports `plan_blocks_without_grid`.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from l2c.extract.config import load_config
from l2c.extract.grid import fit_grid
from l2c.extract.runs import cluster_1d, median_word_height
from l2c.ingest.pages import load_pdf


def lines_of(words, key, tol):
    groups = cluster_1d([key(w) for w in words], tol)
    return sorted((len(g) for g in groups), reverse=True)[:5]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("page", type=int)
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args()
    config = load_config(args.config)
    page = load_pdf(args.pdf, config=config)[args.page - 1]
    h = median_word_height(page.words)
    tol = config.grid_align_word_heights * h
    letters = [w for w in page.words if re.match(config.grid_letter_pattern, w.text)]
    numbers = [w for w in page.words if re.match(config.grid_number_pattern, w.text)]
    print(f"page {page.page}: {round(page.width)}x{round(page.height)} pt, word height {h:.1f}")
    distinct = len({w.text for w in letters})
    print(f"letters: {len(letters)} (distinct {distinct}), numbers: {len(numbers)}")
    print("letters sharing a column x:", lines_of(letters, lambda w: w.x0, tol))
    print("letters sharing a row y   :", lines_of(letters, lambda w: w.y0, tol))
    print("numbers sharing a column x:", lines_of(numbers, lambda w: w.x0, tol))
    print("numbers sharing a row y   :", lines_of(numbers, lambda w: w.y0, tol))
    repeated = Counter(w.text for w in letters + numbers)
    print(
        "labels that appear 2+ times (mirrored candidates):",
        sum(1 for n in repeated.values() if n >= 2),
    )
    grid = fit_grid(page.words, config)
    if grid is None:
        print("fit_grid: NONE (fewer than", config.grid_min_labels, "labels form an axis)")
    else:
        print(f"fit_grid: letters_on={grid.letters_on} rows={len(grid.rows)} cols={len(grid.cols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Put the projects where the tools expect them**

```bash
mkdir -p data/in
# unzip the participant archive into a temporary folder, then copy each project folder
# so that data/in/<project>/<plan>.pdf and data/in/<project>/DA/** exist
python scripts/purge.py        # dry run: shows what would be removed at the end of the event
```

`data/` is git-ignored; the hook refuses anything under it.

- [ ] **Step 3: Probe every project first (what is covered and why not)**

```bash
python scripts/probe_project.py data/in/<project>
```

For each project this lists, per plan page and shop page, which adapter ran or why none did (`plan_outline`, `plan_blocks_without_grid`, `shop_label_strip`, `shop_unlabelled_unsupported`, `shop_levels_not_found`, `needs_ocr`, `type_not_supported:<type>`, ...), the layer kinds, element counts and the share of pages fully handled. Compare with `docs/private/baselines.md`; the numbers should match or beat it. Expect very different shapes per project: that is the point of the tool.

- [ ] **Step 4: Validate the fully-text project against the census**

```bash
python scripts/validate_extract.py data/in/<project>
```

Acceptance for the plan column sheets of the fully-text project: every block's text is parsed, and at least 90% of blocks are bound to a grid cell on most sheets (rows below the threshold are marked; investigate them with Task E13, do not lower the threshold). Shop column pages: report which pages assign fewer strips than the census; those are E13 material.

- [ ] **Step 5: Write the metadata, estimate binding accuracy and sample for a hand check**

```bash
python -m l2c.extract data/in/<project> --out data/out/<project>/metadata
python scripts/sample_for_handcheck.py data/out/<project>/metadata --n 20 --out data/handcheck_<project>.csv
```

The first command prints counts only. Open the CSV, and for each of the 20 rows open the PDF page at the given x, y and fill `correct? (y/n)`. The file holds real values and stays in `data/`. Then record, with Ian at the sync, the element counts, the share of pages fully handled and the hand-check result; these are the numbers the integration gate (Ian's Task I10) compares against.

- [ ] **Step 6: Commit the tools and merge**

```bash
git add scripts
git commit -m "Add real-data validation and probe tools"
```

```bash
git switch dev && git merge --no-ff eric/e11-tools
```


---

### Task E12 (second tier): OCR for pages without a text layer

Start this task only after E1 to E11 pass and Ian's comparison has run on real output (the core gate). Most shop pages across the development projects have no text layer, and the hidden evaluation project is likely to look the same.

**Files:**
- Create: `backend/l2c/ingest/snap.py`, `backend/l2c/ingest/ocr.py`
- Test: `backend/tests/extract/test_ocr.py`

**Interfaces:**
- Consumes: `Word`, `PageData`, `load_pdf` (E2); `Config` OCR knobs (E1); `mark_ocr` and `prepare_page` (E9, already wired behind `--ocr`).
- Produces: `snap_token(text, config) -> (text, changed)` (repairs confusable characters only when the result is a valid bar size); `render(page, dpi)`, `tiles(img, tile_px, overlap)`, `to_tile_frame`, `read_tile`, `line_to_words`, `dedupe` (longer, more confident readings win; fragments of a better box are dropped), `choose_orientations` (optional probe), `ocr_page(page, config, orientations=None) -> OcrResult(words, orientations, snapped, mean_conf)`, `ocr_pdf_page(path, page_number, config)`, `with_ocr_words(page, result) -> PageData(source="ocr")`, `load_with_ocr(path, fichier, config)`. RapidOCR (ONNX, CPU, models bundled in the wheel) is created lazily once. The engine reads vertical text itself, so the default policy reads the upright orientation only (the orientation probe is slower and was less accurate in measurement).

- [ ] **Step 1: Branch and write the failing tests**

```bash
git switch dev && git pull
git switch -c eric/e12-ocr
```

Create `backend/tests/extract/test_ocr.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python -m pytest backend/tests/extract/test_ocr.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.ingest.ocr'` (or `snap`).

- [ ] **Step 3: Write snapping and OCR**

Create `backend/l2c/ingest/snap.py`:

```python
"""Vocabulary snapping: repair OCR digit and letter confusions using what a token can be.

Bar sizes come from a closed list and spacings from a small set of notations, so a token that is
one confusable character away from a valid one is corrected (and marked as snapped, which lowers
its confidence). Tokens that do not look like rebar notation are left untouched.
"""

from __future__ import annotations

import re

from l2c.extract.config import DEFAULT_CONFIG, Config

DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5", "B": "8", "Z": "2"})
UNIT_FIX = str.maketrans({"N": "M", "H": "M", "m": "M", "n": "M"})
TOKEN_RE = re.compile(r"^([0-9OolISBZ]{1,3})([MNHmn])$")
COUNT_SIZE_RE = re.compile(r"^([0-9OolISBZ]{1,2})-([0-9OolISBZ]{1,3}[MNHmn])$")


def _snap_size(token: str, config: Config) -> str | None:
    m = TOKEN_RE.match(token)
    if not m:
        return None
    fixed = m.group(1).translate(DIGIT_FIX) + m.group(2).translate(UNIT_FIX)
    return fixed if fixed in config.bar_sizes else None


def snap_token(text: str, config: Config = DEFAULT_CONFIG) -> tuple[str, bool]:
    """Return (possibly corrected text, whether it was changed)."""
    if text in config.bar_sizes:
        return text, False
    size = _snap_size(text, config)
    if size is not None:
        return size, size != text
    m = COUNT_SIZE_RE.match(text)
    if m:
        size = _snap_size(m.group(2), config)
        if size is not None:
            count = m.group(1).translate(DIGIT_FIX)
            fixed = f"{count}-{size}"
            return fixed, fixed != text
    return text, False
```

Create `backend/l2c/ingest/ocr.py`:

```python
"""OCR for pages without a text layer (vector-outlined or image-only sheets).

Local, CPU-only, deterministic with fixed weights: RapidOCR (ONNX) on tiles of the rendered page.
Pipeline: pick the orientations worth reading -> render tiles -> read lines -> split lines into
words -> map back to PDF points (displayed frame) -> drop overlap duplicates -> snap to the
vocabulary. Every size and threshold comes from the Config.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pymupdf

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.ingest.pages import PageData, Word, load_pdf
from l2c.ingest.snap import snap_token

ROTATIONS = (0, 90, 270)  # degrees the text is turned clockwise in the image
# strict on purpose: only real notation counts as evidence for an orientation
RELEVANT = re.compile(r"\b(?:VERT|ETRI|ÉTRI|ARM|LIG)\b|\d{1,2}\s?-\s?\d{2}\s?M\b", re.IGNORECASE)
MIN_INK = 0.00002  # only tiles with essentially no ink are skipped (labels are tiny)
DEDUP_IOU = 0.5
CONTAINED_SHARE = 0.6  # a box mostly inside a better one is a fragment of it


@lru_cache(maxsize=1)
def engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


@dataclass(frozen=True)
class OcrResult:
    words: list[Word]
    orientations: tuple[int, ...]
    snapped: int
    mean_conf: float


def render(page: pymupdf.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)


def ink(tile: np.ndarray) -> float:
    return float((tile.mean(axis=2) < 128).mean())


def tiles(img: np.ndarray, tile_px: int, overlap: float):
    """Yield (tile, x offset, y offset) covering the image with the given overlap."""
    h, w = img.shape[:2]
    step = max(1, int(tile_px * (1 - overlap)))
    for y in range(0, max(h - int(tile_px * overlap), 1), step):
        for x in range(0, max(w - int(tile_px * overlap), 1), step):
            yield img[y : y + tile_px, x : x + tile_px], x, y


def to_tile_frame(xp: float, yp: float, rotation: int, w: int, h: int) -> tuple[float, float]:
    """Map a point of the image turned counter-clockwise by `rotation` back to the tile.

    np.rot90(T, 1): new[i, j] = T[j, w-1-i]   ->  tile point (x, y) = (w - y', x')
    np.rot90(T, 3): new[i, j] = T[h-1-j, i]   ->  tile point (x, y) = (y', h - x')
    """
    if rotation == 0:
        return xp, yp
    if rotation == 90:
        return w - yp, xp
    return yp, h - xp  # 270


def read_tile(
    tile: np.ndarray, rotation: int
) -> list[tuple[float, float, float, float, str, float]]:
    """OCR one tile; boxes (x0, y0, x1, y1) are in the tile's own pixels."""
    h, w = tile.shape[:2]
    turned = np.ascontiguousarray(np.rot90(tile, rotation // 90))
    result, _ = engine()(turned)
    out = []
    for box, text, conf in result or []:
        pts = [to_tile_frame(px, py, rotation, w, h) for px, py in box]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out.append((min(xs), min(ys), max(xs), max(ys), text, float(conf)))
    return out


def line_to_words(
    box: tuple[float, float, float, float], text: str, conf: float, rotation: int
) -> list[tuple[float, float, float, float, str, float]]:
    """Split an OCR line into words, sharing the box in proportion to word length."""
    tokens = text.split()
    if not tokens:
        return []
    x0, y0, x1, y1 = box
    weights = [len(t) for t in tokens]
    total = sum(weights) + max(len(tokens) - 1, 0)
    out, cursor = [], 0.0
    for tok, wt in zip(tokens, weights, strict=True):
        a, b = cursor / total, (cursor + wt) / total
        cursor += wt + 1
        if rotation == 0:
            out.append((x0 + a * (x1 - x0), y0, x0 + b * (x1 - x0), y1, tok, conf))
        elif rotation == 90:  # text reads downward
            out.append((x0, y0 + a * (y1 - y0), x1, y0 + b * (y1 - y0), tok, conf))
        else:  # 270: text reads upward
            out.append((x0, y1 - b * (y1 - y0), x1, y1 - a * (y1 - y0), tok, conf))
    return out


def _iou(a: Word, b: Word) -> float:
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    union = (a.x1 - a.x0) * (a.y1 - a.y0) + (b.x1 - b.x0) * (b.y1 - b.y0) - inter
    return inter / union if union > 0 else 0.0


def _inside(a: Word, b: Word) -> float:
    """Share of a's area that lies inside b."""
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    area = (a.x1 - a.x0) * (a.y1 - a.y0)
    return ix * iy / area if area > 0 else 0.0


def dedupe(words: list[Word]) -> list[Word]:
    """Remove duplicates from overlapping tiles and orientations.

    Longer, more confident readings win; a word mostly covered by one already kept is dropped.
    """
    kept: list[Word] = []
    for w in sorted(words, key=lambda w: (-len(w.text) * (w.conf or 0.0), w.y0, w.x0, w.text)):
        same = any(k.text == w.text and _iou(k, w) > DEDUP_IOU for k in kept)
        covered = any(_inside(w, k) >= CONTAINED_SHARE for k in kept)
        if not (same or covered):
            kept.append(w)
    return sorted(kept, key=lambda w: (round(w.y0, 1), w.x0, w.text))


def choose_orientations(img: np.ndarray, config: Config) -> tuple[int, ...]:
    """Read the orientation(s) that actually contain rebar notation, probed on the inkiest tiles."""
    cands = sorted(
        tiles(img, config.ocr_tile_px, config.ocr_overlap_fraction),
        key=lambda t: (-ink(t[0]), t[2], t[1]),
    )[: config.ocr_probe_tiles]
    hits = {r: 0 for r in ROTATIONS}
    for tile, _, _ in cands:
        for r in ROTATIONS:
            hits[r] += sum(
                1
                for *_, text, c in read_tile(tile, r)
                if c >= config.ocr_min_conf and RELEVANT.search(text)
            )
    best = max(hits.values())
    if best == 0:
        return (0,)
    return tuple(r for r in ROTATIONS if hits[r] >= max(1, config.ocr_min_orientation_share * best))


def ocr_page(
    page: pymupdf.Page,
    config: Config = DEFAULT_CONFIG,
    orientations: tuple[int, ...] | None = None,
) -> OcrResult:
    img = render(page, config.ocr_dpi)
    scale = 72.0 / config.ocr_dpi
    if orientations is None:
        orientations = choose_orientations(img, config) if config.ocr_orientation_probe else (0,)
    words: list[Word] = []
    for tile, ox, oy in tiles(img, config.ocr_tile_px, config.ocr_overlap_fraction):
        if ink(tile) < MIN_INK:
            continue
        for r in orientations:
            for x0, y0, x1, y1, text, conf in read_tile(tile, r):
                if conf < config.ocr_min_conf:
                    continue
                for wx0, wy0, wx1, wy1, tok, c in line_to_words((x0, y0, x1, y1), text, conf, r):
                    snapped, changed = snap_token(tok, config)
                    words.append(
                        Word(
                            snapped,
                            (ox + wx0) * scale,
                            (oy + wy0) * scale,
                            (ox + wx1) * scale,
                            (oy + wy1) * scale,
                            round(c, 3),
                            tok if changed else None,
                        )
                    )
    words = dedupe(words)
    mean = sum(w.conf or 0.0 for w in words) / len(words) if words else 0.0
    return OcrResult(words, orientations, sum(1 for w in words if w.original), round(mean, 3))


def ocr_pdf_page(path: Path, page_number: int, config: Config = DEFAULT_CONFIG) -> OcrResult:
    with pymupdf.open(path) as doc:
        return ocr_page(doc[page_number - 1], config)


def with_ocr_words(page: PageData, result: OcrResult) -> PageData:
    """A copy of the page whose words come from OCR, so the normal extractors can run on it."""
    return replace(page, words=result.words, source="ocr")


def load_with_ocr(path: Path, fichier: str, config: Config = DEFAULT_CONFIG) -> list[PageData]:
    pages = load_pdf(path, fichier, config)
    out = []
    for p in pages:
        if len(p.words) < config.min_words_native and p.layer in {"vector", "image"}:
            out.append(with_ocr_words(p, ocr_pdf_page(path, p.page, config)))
        else:
            out.append(p)
    return out
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_ocr.py -v
```

Expected: 10 passed (the first run is slower while the ONNX models load). The end-to-end test makes an image-only shop sheet; without `--ocr` its layout is `needs_ocr`, with OCR it becomes `shop_label_strip` with elements flagged `ocr_text`.

- [ ] **Step 5: Measure on a rasterized real sheet (local only)**

Rasterize a text-layer shop PDF at 200 dpi (so it looks like an image-only drawing), OCR it, and compare the extracted elements with the ones from the native text. Save this as `data/ocr_check.py` (git-ignored) and run `python data/ocr_check.py <pdf> <first page> <last page>` from the repository root with the environment active:

```python
import sys, tempfile
from pathlib import Path
import pymupdf
from l2c.extract.columns_shop import extract_shop_columns
from l2c.extract.config import DEFAULT_CONFIG as C
from l2c.ingest import ocr
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import rasterize

src, first, last = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
for pg in range(first - 1, last):
    tmp = Path(tempfile.mkdtemp())
    one = pymupdf.open()
    one.insert_pdf(pymupdf.open(src), from_page=pg, to_page=pg)
    one.save(tmp / 'one.pdf')
    raster = rasterize(tmp / 'one.pdf', tmp / 'raster.pdf', dpi=200)
    native = load_pdf(tmp / 'one.pdf')[0]
    def keyed(page):
        return {{(e.grid, e.level): (e.armature[0].quantite, e.armature[0].diametre)
                for e in extract_shop_columns(page)[0]}}
    want = keyed(native)
    with pymupdf.open(raster) as d:
        words = ocr.ocr_page(d[0], C)
    got = keyed(ocr.with_ocr_words(native, words))
    both = set(want) & set(got)
    exact = sum(want[k] == got[k] for k in both)
    print(f'page {{pg + 1}}: found {{len(both)}}/{{len(want)}}, vertical exact {{exact}}/{{len(both)}}')
```

Use `PYTHONPATH=backend` if `tests` is not importable. Acceptance: at least 90% of the native elements are found and at least 95% of the found ones have the correct vertical bars; the number measured while building this plan is in `docs/private/baselines.md`. About 7 seconds per page.

- [ ] **Step 6: Commit and merge**

```bash
git add backend/l2c/ingest backend/tests/extract
git commit -m "Add OCR path for pages without a text layer"
```

```bash
git switch dev && git merge --no-ff eric/e12-ocr
```


---

### Task E13 (second tier): Measure binding accuracy, harden against unseen layouts, calibrate quality

**Files:**
- Create: `backend/l2c/extract/witness.py`, `scripts/binding_witness.py`
- Test: `backend/tests/extract/test_witness.py` (uses `make_element` from Plan 00 Task F4, so F4 must be merged)

**Interfaces:**
- Produces: `witness(bundle, seed=1) -> Witness(matched_cells, typical_total, typical_agree, atypical_total, atypical_agree, chance_total, chance_agree)` with `.binding_accuracy` and `.chance` properties.

Why: the text parse is exact (every field has confidence 1.0), but *which outline a block belongs to* is a geometric judgement, and the quality score reflects that doubt only through an uncalibrated formula. The witness estimates binding accuracy without any labels: a plan column that differs from its sheet's usual profile must match the shop element **at the same grid cell**. If binding were wrong, those unusual columns would agree only at chance level. Typical columns agree almost always and are reported separately because they prove nothing.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev && git pull
git switch -c eric/e13-witness
```

Create `backend/tests/extract/test_witness.py`:

```python
from l2c.contract.io import MetaBundle
from l2c.extract.witness import witness
from l2c.mock.elements import make_element


def project(shuffle_atypical: bool):
    cols = range(1, 21)
    odd = {3: 6, 9: 8, 15: 10}  # three atypical plan columns (different bar count)
    plan = [make_element("plan", "N2", "K", c, count=odd.get(c, 4), x=10.0 * c) for c in cols]
    shop_counts = dict(odd)
    if shuffle_atypical:  # the shop has the unusual values, but in other cells
        shop_counts = {4: 6, 10: 8, 16: 10}
    shop = [
        make_element("shop", "N2", "K", c, count=shop_counts.get(c, 4), x=10.0 * c) for c in cols
    ]
    return MetaBundle(project="w", elements=plan + shop)


def test_correct_binding_makes_atypical_columns_agree_with_the_shop():
    w = witness(project(shuffle_atypical=False))
    assert w.atypical_total == 3 and w.atypical_agree == 3 and w.binding_accuracy == 1.0
    assert w.typical_total == 17 and w.typical_agree == 17
    assert w.matched_cells == 20


def test_wrong_binding_drops_atypical_agreement_to_chance():
    w = witness(project(shuffle_atypical=True))
    assert w.atypical_agree == 0 and w.binding_accuracy == 0.0
    assert w.chance is not None and w.chance < 0.5


def test_no_atypical_columns_means_no_estimate():
    plan = [make_element("plan", "N2", "K", c) for c in range(1, 6)]
    shop = [make_element("shop", "N2", "K", c) for c in range(1, 6)]
    w = witness(MetaBundle(project="x", elements=plan + shop))
    assert w.binding_accuracy is None and w.atypical_total == 0
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest backend/tests/extract/test_witness.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.extract.witness'`.

- [ ] **Step 3: Write the witness and the script**

Create `backend/l2c/extract/witness.py`:

```python
"""Estimate binding accuracy without labels, using the other document as an independent witness.

A column on the plan that differs from its sheet's usual profile (an *atypical* column) must match
the shop element at the **same grid cell**. If blocks were bound to the wrong cells, atypical
columns would agree with the shop at chance level; typical columns agree almost always and prove
nothing, so they are reported separately and excluded from the estimate. Percentages only.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass

from l2c.contract.io import MetaBundle
from l2c.contract.models import ElementExt


@dataclass(frozen=True)
class Witness:
    matched_cells: int
    typical_total: int
    typical_agree: int
    atypical_total: int
    atypical_agree: int
    chance_total: int
    chance_agree: int

    @property
    def binding_accuracy(self) -> float | None:
        """Lower bound: genuine plan/shop differences also count as disagreement."""
        return self.atypical_agree / self.atypical_total if self.atypical_total else None

    @property
    def chance(self) -> float | None:
        return self.chance_agree / self.chance_total if self.chance_total else None


def _key(e: ElementExt) -> tuple[int | None, str | None]:
    v = e.armature[0] if e.armature else None
    return (v.quantite if v else None, v.diametre if v else None)


def witness(bundle: MetaBundle, seed: int = 1) -> Witness:
    plan = {(e.level, e.grid): e for e in bundle.elements if e.source == "plan" and e.grid}
    shop: dict[tuple[str, str | None], list[ElementExt]] = defaultdict(list)
    for e in bundle.elements:
        if e.source == "shop" and e.grid:
            shop[(e.level, e.grid)].append(e)
    mode: dict[str, Counter] = defaultdict(Counter)
    for (level, _), e in plan.items():
        mode[level][_key(e)] += 1
    usual = {lv: c.most_common(1)[0][0] for lv, c in mode.items()}
    rng = random.Random(seed)
    cells_by_level: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for k in plan:
        if k in shop:
            cells_by_level[k[0]].append(k)
    t_tot = t_ok = a_tot = a_ok = c_tot = c_ok = 0
    for k in sorted(k for ks in cells_by_level.values() for k in ks):
        e = plan[k]
        agree = any(_key(s) == _key(e) for s in shop[k])
        if _key(e) == usual[k[0]]:
            t_tot += 1
            t_ok += agree
        else:
            a_tot += 1
            a_ok += agree
            other = rng.choice(cells_by_level[k[0]])
            c_tot += 1
            c_ok += any(_key(s) == _key(e) for s in shop[other])
    matched = sum(len(v) for v in cells_by_level.values())
    return Witness(matched, t_tot, t_ok, a_tot, a_ok, c_tot, c_ok)
```

Create `scripts/binding_witness.py`:

```python
"""Binding accuracy estimate for a metadata folder, using the shop drawings as a witness.

Usage: python scripts/binding_witness.py data/out/<project>/metadata
Prints percentages only. A binding change must not lower the atypical agreement.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from l2c.contract.io import read_bundle
from l2c.extract.witness import witness


def pct(a: int, b: int) -> str:
    return f"{a}/{b} = {a / b:.0%}" if b else "n/a (no cases)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("metadata_dir", type=Path)
    args = ap.parse_args()
    w = witness(read_bundle(args.metadata_dir))
    typical = pct(w.typical_agree, w.typical_total)
    atypical = pct(w.atypical_agree, w.atypical_total)
    chance = pct(w.chance_agree, w.chance_total)
    print(f"cells present on both plan and shop: {w.matched_cells}")
    print(f"typical plan columns agree with shop at the same cell : {typical}")
    print(f"ATYPICAL plan columns agree with shop (binding estimate): {atypical}")
    print(f"chance level for atypical columns (random cell)        : {chance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest backend/tests/extract/test_witness.py -v
```

Expected: 3 passed (correct binding gives 100% agreement; shuffled cells drop it to chance; no unusual columns means no estimate).

- [ ] **Step 5: Measure the real project**

```bash
python scripts/binding_witness.py data/out/<project>/metadata
```

It prints three percentages: typical columns, unusual columns (the binding estimate, a lower bound because genuine plan/shop differences also count as disagreement) and the chance level. Record the unusual-column figure: it is the standing quality gate for every binding change from now on, and it must never go down. The figure measured while building this plan is in `docs/private/baselines.md`: well above chance, clearly below 100%.

- [ ] **Step 6: Commit and merge**

```bash
git add backend/l2c/extract/witness.py scripts/binding_witness.py backend/tests/extract/test_witness.py
git commit -m "Add binding accuracy witness"
```

```bash
git switch dev && git merge --no-ff eric/e13-witness
```


**Hardening loop (repeat per gap; no new files up front).** Every fix adds a synthetic test that reproduces the failure *shape* with invented labels, then changes config or code, then re-runs the baselines so nothing regresses.

- [ ] **Step 1: Pick the largest gap from the probe**

Run `python scripts/probe_project.py data/in/<project>` and choose the biggest `plan_blocks_without_grid`, `shop_unlabelled_unsupported`, `shop_levels_not_found` or `no_column_blocks` count.

- [ ] **Step 2: Find out why**

```bash
python scripts/grid_debug.py data/in/<project>/<plan>.pdf <page number>
```

It prints how many letter-like and number-like labels the page has, how many share a line in each direction, how many repeat on the opposite edge, and what `fit_grid` decided. This is how the second grid orientation (letters along the top, numbers down the side) and rows past Z were found.

- [ ] **Step 3: Reproduce the shape synthetically**

Add a test in `backend/tests/extract/test_grid.py`, `test_columns_plan.py`, `test_columns_shop.py` or `test_robustness.py` that builds the same shape from invented labels (never real values) and fails today.

- [ ] **Step 4: Fix at the right level**

Prefer, in this order: learn it from the page (extend `learn.py`), a `Config` value (new key or default ratio), a vocabulary entry, then a code change. Never add a fixed distance in points and never copy a label or layout from the development data into code.

- [ ] **Step 5: Re-run all baselines**

```bash
python scripts/check.py
python scripts/validate_extract.py data/in/<project>
python scripts/binding_witness.py data/out/<project>/metadata
for p in <each project>; do python scripts/probe_project.py data/in/$p; done
```

Nothing may drop against `docs/private/baselines.md` or the witness figure; the probe tables should improve.

- [ ] **Step 6: Commit and merge**

```bash
git add backend scripts
git commit -m "Handle <the shape> in <module>"
git switch dev && git merge --no-ff eric/<branch>
```


**Known gap categories (details and numbers in `docs/private/baselines.md`):** sheets whose plan grid is not found (remaining sheets of the projects that use the transposed grid, likely too few labels or labels drawn as shapes); shop pages with blocks but no grid labels (a mark plus axis convention: add an adapter that resolves marks by their order along the plan axis); shop pages without elevation lines (levels cannot be assigned: find another level cue such as the file name or a title); shop pages where only part of the column strips are assigned; element types other than columns (a later plan adds one adapter per type).

**Quality calibration (once real data has flowed through Ian's comparison):** the binding confidence (`0.6 + 0.4 * margin` in `quality.location_score`) is an uncalibrated heuristic: the margin to the runner-up outline is zero for about half of the blocks even when the binding is right, because two outlines are about equally plausible once block offsets are learned, so most pairs fall below the verdict bar and most findings land in `needs_review`.

- [ ] **Step 1: Label a sample**

Use `scripts/sample_for_handcheck.py` (Task E11) on plan and shop elements, about 30 each, and fill `correct?`.

- [ ] **Step 2: Build the reliability table**

Bin `overall` (0 to 1 in tenths) and report, per bin, the share marked correct, next to the witness estimate. A trustworthy score has the share rising with the bin.

- [ ] **Step 3: Adjust only what the evidence justifies**

Change the binding factor in `quality.location_score` or the weights in `l2c.contract.constants` (`ANCHOR_FACTOR`, `CONSISTENCY_*`); never the verdict threshold. Acceptance: the elements in the 0.7+ bins are at least 90% correct in the hand check, a clear majority of matched pairs reach 0.7, and the witness figure has not dropped. Weights are a contract change: announce it and regenerate fixtures if their numbers move.

