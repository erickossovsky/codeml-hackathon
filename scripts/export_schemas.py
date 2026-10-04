"""Regenerate shared/schemas/*.json from the pydantic models (run after any contract change)."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from l2c.contract.models import (
    ComparisonFile,
    ElementExt,
    ElementStrict,
    Finding,
    GridSheet,
    IdRow,
    LevelInfo,
    Manifest,
    SheetInfo,
)

OUT = Path(__file__).resolve().parents[1] / "shared" / "schemas"

SCHEMAS = {
    "elements.schema.json": list[ElementStrict],
    "elements.ext.schema.json": list[ElementExt],
    "grid.schema.json": list[GridSheet],
    "levels.schema.json": list[LevelInfo],
    "sheets.schema.json": list[SheetInfo],
    "ids.schema.json": list[IdRow],
    "findings.schema.json": list[Finding],
    "comparison.schema.json": ComparisonFile,
    "manifest.schema.json": Manifest,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, tp in SCHEMAS.items():
        schema = TypeAdapter(tp).json_schema()
        (OUT / name).write_text(
            json.dumps(schema, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    print(f"wrote {len(SCHEMAS)} schemas to {OUT}")


if __name__ == "__main__":
    main()
