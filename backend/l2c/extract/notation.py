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
