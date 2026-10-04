"""Random synthetic projects with injected defects: proves the comparison does not depend on one
project's shape (levels, grid size, bar sizes, spacings, file layout all vary with the seed)."""

from __future__ import annotations

import random
from dataclasses import dataclass

from l2c.contract.constants import BAR_SIZES
from l2c.contract.io import MetaBundle
from l2c.contract.models import ElementExt, LevelInfo
from l2c.mock.elements import make_element

LEVEL_POOL = ("SS", "RDC", "N2", "N3", "N4", "N5", "N6")
ROW_POOL = "ABCDEFGHJKLMN"
SPACINGS_MM = (101.6, 152.4, 203.2, 304.8)
DEFECT_KINDS = ("count", "size", "spacing", "tie_size", "missing", "added")
EXPECTED_STATUS = {
    "count": "non_compliant",
    "size": "non_compliant",
    "spacing": "non_compliant",
    "tie_size": "non_compliant",
    "missing": "missing",
    "added": "added",
}


@dataclass(frozen=True)
class Injected:
    kind: str
    level: str
    grid: str

    @property
    def expected_status(self) -> str:
        return EXPECTED_STATUS[self.kind]


@dataclass
class FuzzProject:
    bundle: MetaBundle
    injected: list[Injected]


def _grid(row: str, col: float) -> str:
    return f"{row}-{col:g}"


def fuzz_project(seed: int) -> FuzzProject:
    rng = random.Random(seed)
    n_levels = rng.randint(2, 4)
    names = sorted(rng.sample(LEVEL_POOL, n_levels + 1), key=LEVEL_POOL.index)
    elevations, z = {}, 0.0
    for name in names:
        elevations[name] = z
        z += rng.choice((2800.0, 3200.0, 3500.0, 4200.0))
    covered = names[:-1]  # the top level only closes the last storey
    rows = rng.sample(ROW_POOL, rng.randint(2, 5))
    cols = sorted(rng.sample(range(1, 21), rng.randint(3, 9)))
    cols_f = [c + (0.5 if rng.random() < 0.15 else 0.0) for c in cols]
    n_files = rng.randint(1, 3)
    files = [f"DA/Colonnes/PART{i + 1}.pdf" for i in range(n_files)]
    typical = {
        "count": rng.choice((4, 6, 8, 10)),
        "size": rng.choice(BAR_SIZES),
        "tie_size": rng.choice(("10M", "15M")),
        "spacing": rng.choice(SPACINGS_MM),
    }

    def build(source: str, level: str, row: str, col: float, **over) -> ElementExt:
        height = elevations[names[names.index(level) + 1]] - elevations[level]
        p = {**typical, **over}
        file = files[rows.index(row) % n_files] if source == "shop" else "plan.pdf"
        return make_element(
            source,
            level,
            row,
            col,
            count=p["count"],
            size=p["size"],
            tie_size=p["tie_size"],
            spacing_mm=p["spacing"],
            tie_count=round(height / p["spacing"]) if source == "shop" else None,
            fichier=file,
            feuillet=f"S-5{names.index(level):02d}" if source == "plan" else None,
            x=100.0 + 50 * col,
            y=100.0 + 40 * rows.index(row),
        )

    cells = [(lv, r, c) for lv in covered for r in rows for c in cols_f]
    plan = [build("plan", *cell) for cell in cells]
    shop = {cell: build("shop", *cell) for cell in cells}
    injected: list[Injected] = []
    for lv, r, c in rng.sample(cells, min(len(cells), rng.randint(3, 6))):
        kind = rng.choice(DEFECT_KINDS)
        if kind == "missing":
            del shop[(lv, r, c)]
        elif kind == "added":
            extra_col = max(cols_f) + 1
            shop[(lv, r, extra_col)] = build("shop", lv, r, extra_col)
            injected.append(Injected(kind, lv, _grid(r, extra_col)))
            continue
        else:
            if kind == "count":
                over = {"count": typical["count"] + rng.choice((-2, -1, 1, 2, 4))}
            elif kind == "size":
                over = {"size": rng.choice([s for s in BAR_SIZES if s != typical["size"]])}
            elif kind == "tie_size":
                over = {"tie_size": "15M" if typical["tie_size"] == "10M" else "10M"}
            else:
                over = {"spacing": rng.choice([s for s in SPACINGS_MM if s != typical["spacing"]])}
            shop[(lv, r, c)] = build("shop", lv, r, c, **over)
        injected.append(Injected(kind, lv, _grid(r, c)))
    bundle = MetaBundle(
        project=f"FUZZ{seed}",
        elements=plan + list(shop.values()),
        levels=[LevelInfo(level=n, name=n, elevation_mm=elevations[n]) for n in names],
    )
    return FuzzProject(bundle, injected)
