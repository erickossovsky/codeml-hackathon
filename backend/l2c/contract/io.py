"""Deterministic JSON read/write and the metadata bundle (one folder per project)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from l2c.contract import constants as C
from l2c.contract.models import (
    ElementExt,
    ElementStrict,
    GridSheet,
    IdRow,
    LevelInfo,
    Manifest,
    SheetInfo,
)


class ContractVersionError(RuntimeError):
    """Raised when a file was written with a different contract version."""


def dumps(obj: object) -> str:
    """Stable text: sorted keys, 2-space indent, trailing newline, UTF-8 friendly."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_models(path: Path, models: list[BaseModel] | BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        [m.model_dump(mode="json") for m in models]
        if isinstance(models, list)
        else models.model_dump(mode="json")
    )
    path.write_text(dumps(data), encoding="utf-8", newline="\n")


def read_models[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return TypeAdapter(list[model]).validate_python(raw)


@dataclass
class MetaBundle:
    """Everything Eric's lane writes and Ian's lane reads."""

    project: str
    elements: list[ElementExt] = field(default_factory=list)
    grids: list[GridSheet] = field(default_factory=list)
    levels: list[LevelInfo] = field(default_factory=list)
    sheets: list[SheetInfo] = field(default_factory=list)
    ids: list[IdRow] = field(default_factory=list)


def write_bundle(directory: Path, bundle: MetaBundle) -> None:
    from l2c.contract.ids import global_id

    ordered = sorted(bundle.elements, key=lambda e: (e.source, e.fichier, e.page, e.id))
    ids = [
        IdRow(
            element_id=e.id,
            match_key=e.match_key.key_str(),
            global_id=global_id(e.match_key.key_str()),
        )
        for e in ordered
    ]
    write_models(directory / C.FILE_ELEMENTS_EXT, ordered)
    write_models(directory / C.FILE_ELEMENTS_STRICT, [e.to_strict() for e in ordered])
    write_models(directory / C.FILE_GRID, sorted(bundle.grids, key=lambda g: (g.fichier, g.page)))
    write_models(directory / C.FILE_LEVELS, bundle.levels)
    write_models(
        directory / C.FILE_SHEETS, sorted(bundle.sheets, key=lambda s: (s.fichier, s.page))
    )
    write_models(directory / C.FILE_IDS, ids)
    manifest = Manifest(
        contract_version=C.CONTRACT_VERSION,
        project=bundle.project,
        counts={
            "elements": len(ordered),
            "plan": sum(1 for e in ordered if e.source == C.SOURCE_PLAN),
            "shop": sum(1 for e in ordered if e.source == C.SOURCE_SHOP),
        },
    )
    write_models(directory / C.FILE_MANIFEST, manifest)


def read_bundle(directory: Path | str) -> MetaBundle:
    directory = Path(directory)
    manifest_path = directory / C.FILE_MANIFEST
    manifest = Manifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.contract_version != C.CONTRACT_VERSION:
        raise ContractVersionError(
            f"{manifest_path} has contract_version {manifest.contract_version}, "
            f"this code expects {C.CONTRACT_VERSION}"
        )
    return MetaBundle(
        project=manifest.project,
        elements=read_models(directory / C.FILE_ELEMENTS_EXT, ElementExt),
        grids=read_models(directory / C.FILE_GRID, GridSheet),
        levels=read_models(directory / C.FILE_LEVELS, LevelInfo),
        sheets=read_models(directory / C.FILE_SHEETS, SheetInfo),
        ids=read_models(directory / C.FILE_IDS, IdRow),
    )


def strict_records(directory: Path) -> list[ElementStrict]:
    return read_models(directory / C.FILE_ELEMENTS_STRICT, ElementStrict)
