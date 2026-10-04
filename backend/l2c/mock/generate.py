"""A small synthetic project with known defects and the findings they must produce.

This is the shared definition of "what the metadata looks like" for both lanes. The same
builder feeds contract tests, golden-file tests and the committed fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass

from l2c.contract.io import MetaBundle
from l2c.contract.models import ElementExt, GridSheet, LevelInfo, SheetInfo
from l2c.mock.elements import TIE_COUNT_FOR_3500, make_element

ROWS = ("K", "L")
COLS = (3, 4, 5, 6, 7, 8)
LEVELS = {"N2": 0.0, "N3": 3500.0, "N4": 7000.0}
FILE_A = "DA/Colonnes/PART1.pdf"
FILE_B = "DA/Colonnes/PART2.pdf"


@dataclass(frozen=True)
class Expected:
    check_type: str
    status: str
    level: str
    grid: str | None
    note: str = ""


@dataclass
class MockProject:
    bundle: MetaBundle
    expected: list[Expected]


def _typical(source: str, level: str, row: str, col: int, **kw) -> ElementExt:
    fichier = "plan.pdf" if source == "plan" else (FILE_A if row == "K" else FILE_B)
    feuillet = {"N2": "S-517", "N3": "S-518"}[level] if source == "plan" else None
    return make_element(
        source,
        level,
        row,
        col,
        fichier=fichier,
        feuillet=feuillet,
        tie_count=TIE_COUNT_FOR_3500 if source == "shop" else None,
        x=100.0 + 40 * col,
        y=100.0 + (60 if row == "K" else 120),
        **kw,
    )


def mock_project() -> MockProject:
    plan: list[ElementExt] = []
    shop: list[ElementExt] = []
    for level in ("N2", "N3"):
        for row in ROWS:
            for col in COLS:
                plan.append(_typical("plan", level, row, col))
                shop.append(_typical("shop", level, row, col))

    def replace(lst: list[ElementExt], level: str, row: str, col: int, new: ElementExt) -> None:
        for i, e in enumerate(lst):
            if (e.level, e.match_key.row, e.match_key.col) == (level, row, col):
                lst[i] = new
                return
        raise KeyError((level, row, col))

    def drop(lst: list[ElementExt], level: str, row: str, col: int) -> None:
        lst[:] = [
            e for e in lst if (e.level, e.match_key.row, e.match_key.col) != (level, row, col)
        ]

    expected: list[Expected] = []
    # 1. count mismatch (plan 4 vs shop 6)
    replace(shop, "N2", "K", 4, _typical("shop", "N2", "K", 4, count=6))
    expected.append(Expected("cross.plan_vs_shop", "non_compliant", "N2", "K-4", "count"))
    # 2. spacing mismatch (plan 6" vs shop 12")
    replace(
        shop,
        "N3",
        "L",
        5,
        make_element(
            "shop", "N3", "L", 5, fichier=FILE_B, spacing_mm=304.8, tie_count=11, x=300.0, y=220.0
        ),
    )
    expected.append(Expected("cross.plan_vs_shop", "non_compliant", "N3", "L-5", "spacing"))
    # 3. missing from shop drawings
    drop(shop, "N2", "L", 8)
    expected.append(Expected("cross.plan_vs_shop", "missing", "N2", "L-8"))
    # 4. added in shop drawings (column 9 does not exist on the plan)
    shop.append(_typical("shop", "N3", "K", 9))
    expected.append(Expected("cross.plan_vs_shop", "added", "N3", "K-9"))
    # 5. the realistic known case: plan has one odd size among peers, shop has the typical value
    replace(plan, "N2", "K", 5, _typical("plan", "N2", "K", 5, size="35M"))
    expected.append(Expected("cross.plan_vs_shop", "non_compliant", "N2", "K-5", "size"))
    expected.append(Expected("self.peer_outlier", "needs_review", "N2", "K-5", "size"))
    # 6. a difference seen through an unreliable extraction: must NOT be a firm verdict
    replace(
        shop,
        "N3",
        "K",
        4,
        make_element(
            "shop",
            "N3",
            "K",
            4,
            fichier=FILE_A,
            count=5,
            tie_count=TIE_COUNT_FOR_3500,
            overall=0.4,
            flags=("weak_strip_assignment",),
            x=260.0,
            y=160.0,
        ),
    )
    expected.append(Expected("cross.plan_vs_shop", "needs_review", "N3", "K-4", "low trust"))
    # 7. internal inconsistency: 34 ties at 6" cannot fit a 3500 mm storey
    replace(
        shop,
        "N2",
        "L",
        3,
        make_element("shop", "N2", "L", 3, fichier=FILE_B, tie_count=34, x=220.0, y=220.0),
    )
    expected.append(Expected("self.internal_consistency", "needs_review", "N2", "L-3"))
    # 8. conflicting duplicate across two shop files
    shop.append(
        make_element(
            "shop",
            "N3",
            "K",
            7,
            fichier=FILE_B,
            count=8,
            tie_count=TIE_COUNT_FOR_3500,
            page=2,
            x=380.0,
            y=160.0,
        )
    )
    expected.append(Expected("cross.shop_vs_shop", "needs_review", "N3", "K-7"))
    # 9. benign duplicate (same values in both files): no finding expected
    shop.append(
        make_element(
            "shop",
            "N3",
            "K",
            8,
            fichier=FILE_B,
            tie_count=TIE_COUNT_FOR_3500,
            page=2,
            x=420.0,
            y=160.0,
        )
    )
    # 10. plan block that could not be bound to a grid cell
    plan.append(
        make_element(
            "plan",
            "N3",
            None,
            None,
            feuillet="S-518",
            flags=("unbound_block",),
            overall=0.1,
            x=900.0,
            y=900.0,
        )
    )
    expected.append(Expected("cross.plan_vs_shop", "needs_review", "N3", None, "unbound"))
    # 11. shop block below the lowest level line (foundation dowels): level has no plan sheet
    shop.append(
        make_element(
            "shop", "FDN", "K", 3, fichier=FILE_A, tie_count=None, spacing_mm=None, x=140.0, y=700.0
        )
    )
    expected.append(Expected("cross.plan_vs_shop", "needs_review", "FDN", "K-3", "level"))

    bundle = MetaBundle(
        project="MOCK",
        elements=plan + shop,
        grids=[
            GridSheet(
                fichier="plan.pdf",
                page=1,
                feuillet="S-517",
                rows={"K": 300.0, "L": 400.0},
                cols={str(c): 100.0 + 40 * c for c in COLS},
            )
        ],
        levels=[LevelInfo(level=k, name=k, elevation_mm=v) for k, v in LEVELS.items()],
        sheets=[
            SheetInfo(
                fichier="plan.pdf",
                page=1,
                feuillet="S-517",
                kind="plan",
                type_element="colonne",
                level="N2",
                layer="text",
                width=3000,
                height=2000,
                rotation=0,
            ),
            SheetInfo(
                fichier="plan.pdf",
                page=2,
                feuillet="S-518",
                kind="plan",
                type_element="colonne",
                level="N3",
                layer="text",
                width=3000,
                height=2000,
                rotation=0,
            ),
            SheetInfo(
                fichier=FILE_A,
                page=1,
                feuillet=None,
                kind="shop",
                type_element="colonne",
                level=None,
                layer="text",
                width=2500,
                height=1700,
                rotation=0,
            ),
            SheetInfo(
                fichier=FILE_B,
                page=1,
                feuillet=None,
                kind="shop",
                type_element="colonne",
                level=None,
                layer="text",
                width=2500,
                height=1700,
                rotation=0,
            ),
        ],
    )
    return MockProject(bundle=bundle, expected=expected)
