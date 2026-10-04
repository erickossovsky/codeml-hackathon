"""Synthetic ElementExt builders. Mock data is clearly synthetic: no real drawing values."""

from __future__ import annotations

from l2c.contract.models import (
    Armature,
    AttrQuality,
    ElementExt,
    LocationQuality,
    MatchKey,
    Quality,
)

TIE_COUNT_FOR_3500 = 23  # round(3500 / 152.4)


def make_element(
    source: str,
    level: str,
    row: str | None,
    col: float | None,
    *,
    count: int | None = 4,
    size: str | None = "25M",
    tie_size: str | None = "10M",
    spacing_mm: float | None = 152.4,
    tie_count: int | None = None,
    fichier: str | None = None,
    page: int = 1,
    overall: float = 0.95,
    flags: tuple[str, ...] = (),
    feuillet: str | None = None,
    x: float = 100.0,
    y: float = 100.0,
    type_element: str = "colonne",
    armature: list[Armature] | None = None,
) -> ElementExt:
    grid = f"{row}-{col:g}" if row is not None and col is not None else None
    sheet = feuillet or ("S-500" if source == "plan" else "PART1")
    file = fichier or ("plan.pdf" if source == "plan" else "DA/Colonnes/PART1.pdf")
    if source == "plan":
        element_id = f"{sheet}_{grid or 'U'}_plan" if grid else f"{sheet}_U{int(x)}_plan"
    else:
        stem = file.rsplit("/", 1)[-1].removesuffix(".pdf")
        element_id = f"{stem}_p{page}_{grid or 'U'}_{level}_shop"
    attrs = {
        "count": AttrQuality(value=count, conf=overall),
        "size": AttrQuality(value=size, conf=overall),
    }
    quality = Quality(
        overall=overall,
        type_conf=1.0,
        level_conf=1.0,
        location=LocationQuality(
            page_xy_conf=1.0,
            anchor="outline" if source == "plan" else "label",
            grid_cell=grid,
            grid_conf=1.0 if grid else 0.1,
        ),
        attributes=attrs,
        flags=list(flags),
    )
    return ElementExt(
        id=element_id,
        source=source,  # type: ignore[arg-type]
        fichier=file,
        feuillet=sheet,
        page=page,
        x=x,
        y=y,
        type_element=type_element,  # type: ignore[arg-type]
        element=grid or element_id,
        armature=armature
        if armature is not None
        else [
            Armature(repere="V", diametre=size, quantite=count),
            Armature(repere="T", diametre=tie_size, quantite=tie_count, espacement_mm=spacing_mm),
        ],
        match_key=MatchKey(type=type_element, level=level, row=row, col=col),  # type: ignore[arg-type]
        grid=grid,
        level=level,
        bbox=(x - 10, y - 5, x + 10, y + 5),
        quality=quality,
        extraction_method="mock",
        provenance={"synthetic": 1},
    )
