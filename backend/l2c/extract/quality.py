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
