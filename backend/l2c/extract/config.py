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
    ("FDN", "FDN"),
    ("SS", "SS"),
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
    level_numbered: tuple[str, ...] = ("NIVEAU", "LEVEL", "FLOOR", "NIV")
    # ---- notation
    bar_size_pattern: str = r"(?:10|15|20|25|30|35)M"
    bar_sizes: tuple[str, ...] = ("10M", "15M", "20M", "25M", "30M", "35M")
    grid_letter_pattern: str = r"^[A-Z]{1,2}(?:\.\d|')?$"  # AA past Z; A.5 or A' between rows
    grid_number_pattern: str = r"^\d{1,2}(?:\.\d)?$"
    # a cell like J-12, J.5-12 or J'-12; C-01 is a mark, not a cell
    grid_label_pattern: str = r"^([A-Z]{1,2}(?:\.\d|')?)-([1-9]\d?(?:\.\d)?)$"
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
    outline_relaxed_snap: float = 3.0  # off-grid columns: second snap pass at this x snap_tol
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
