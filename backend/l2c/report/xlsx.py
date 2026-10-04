"""Jury-style list: sheet, location, plan value, shop value, status."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from l2c.compare.outputs import NO_SHEET, describe, plan_sheet_of
from l2c.contract.io import MetaBundle
from l2c.contract.models import Finding

HEADER = [
    "Feuillet",
    "Localisation",
    "Plan L2C",
    "Dessin d'atelier",
    "Statut",
    "Confiance",
    "Verification",
]


def write_xlsx(path: Path, findings: list[Finding], bundle: MetaBundle) -> None:
    by_id = {e.id: e for e in bundle.elements}
    wb = Workbook()
    ws = wb.active
    ws.title = "findings"
    ws.append(HEADER)
    for f in findings:
        plan = by_id.get(f.plan_ref.element_id) if f.plan_ref and f.plan_ref.element_id else None
        shop = by_id.get(f.shop_ref.element_id) if f.shop_ref and f.shop_ref.element_id else None
        sheet = plan_sheet_of(f, by_id)
        ws.append(
            [
                sheet if sheet != NO_SHEET else (shop.fichier if shop else ""),
                f"{f.level} {f.grid or ''}".strip(),
                describe(plan),
                describe(shop),
                f.status,
                f.confidence,
                f.check_type,
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
