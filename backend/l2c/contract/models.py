"""Pydantic models that define the metadata contract between the extract and compare lanes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from l2c.contract.constants import ELEMENT_TYPES  # noqa: F401  (documented source of the literals)

ElementType = Literal["fondation", "poutre", "mur_refend", "colonne", "dalle"]
Source = Literal["plan", "shop"]
Status = Literal["compliant", "non_compliant", "missing", "added", "needs_review"]
CheckType = Literal[
    "cross.plan_vs_shop",
    "cross.shop_vs_shop",
    "cross.plan_vs_plan",
    "cross.revision",
    "cross.project",
    "self.peer_outlier",
    "self.level_consistency",
    "self.internal_consistency",
    "self.plausibility",
    "self.duplicate",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- Appendix A
class Armature(_Strict):
    repere: str | None = None
    diametre: str | None = None
    quantite: int | None = None
    espacement_mm: float | None = None
    longueur_mm: float | None = None


class ElementStrict(_Strict):
    """Exactly the Appendix A record. Nothing else may be added."""

    id: str
    source: Source
    fichier: str
    feuillet: str | None
    page: int
    x: float
    y: float
    type_element: ElementType
    element: str
    armature: list[Armature]


# --------------------------------------------------------------------------- extensions
class MatchKey(_Strict):
    type: ElementType
    level: str
    row: str | None = None  # grid letter
    col: float | None = None  # grid number, fractional allowed (10.8)
    span_from: float | None = None
    span_to: float | None = None

    def key_str(self) -> str:
        col = "" if self.col is None else f"{self.col:g}"
        if self.span_from is not None or self.span_to is not None:
            sf = "" if self.span_from is None else f"{self.span_from:g}"
            st = "" if self.span_to is None else f"{self.span_to:g}"
            return f"{self.type}|{self.level}|{self.row or ''}|{col}|{sf}-{st}"
        return f"{self.type}|{self.level}|{self.row or ''}|{col}"


class AttrQuality(_Strict):
    value: float | int | str | None = None
    conf: float = Field(ge=0.0, le=1.0)
    status: Literal["parsed", "derived", "inferred", "missing"] = "parsed"
    text_source: Literal["native", "ocr", "vlm"] = "native"
    ocr_conf: float | None = None
    snapped: bool = False
    original_text: str | None = None


class LocationQuality(_Strict):
    page_xy_conf: float = Field(ge=0.0, le=1.0)
    anchor: Literal["outline", "label", "mark_axis", "text_only"]
    anchor_dist_pt: float | None = None
    grid_cell: str | None = None
    grid_conf: float = Field(ge=0.0, le=1.0)
    binding_method: str = "none"
    assignment_cost: float | None = None
    margin_to_runner_up: float | None = None


class Quality(_Strict):
    overall: float = Field(ge=0.0, le=1.0)
    type_conf: float = Field(ge=0.0, le=1.0)
    level_conf: float = Field(ge=0.0, le=1.0)
    location: LocationQuality
    attributes: dict[str, AttrQuality] = Field(default_factory=dict)
    consistency_passed: list[str] = Field(default_factory=list)
    consistency_failed: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class ElementExt(ElementStrict):
    match_key: MatchKey
    grid: str | None = None
    level: str
    section_mm: tuple[float, float] | None = None
    bbox: tuple[float, float, float, float]
    quality: Quality
    extraction_method: str
    raw_text: str | None = None
    provenance: dict[str, str | int | float] = Field(default_factory=dict)

    def to_strict(self) -> ElementStrict:
        data = self.model_dump(include=set(ElementStrict.model_fields))
        return ElementStrict.model_validate(data)


# --------------------------------------------------------------------------- side files
class GridSheet(_Strict):
    fichier: str
    page: int
    feuillet: str | None
    # Letters name the rows and numbers the columns of the match key. Their page positions are
    # y (letters_on="y", letters run down an edge) or x (letters_on="x", letters run along an edge).
    letters_on: Literal["x", "y"] = "y"
    rows: dict[str, float]  # letter -> position along its axis, PDF points (top-left origin)
    cols: dict[str, float]  # number label -> position along its axis, PDF points


class LevelInfo(_Strict):
    level: str  # canonical: SS, RDC, N2, N3, ..., TOIT
    name: str
    elevation_mm: float | None = None


class SheetInfo(_Strict):
    fichier: str
    page: int
    feuillet: str | None
    kind: Source
    type_element: ElementType | None
    level: str | None
    layer: Literal["text", "vector", "image", "empty"]
    width: float
    height: float
    rotation: int
    revision: str | None = None
    layout: str | None = None  # which adapter ran, or why none did (coverage reporting)


class IdRow(_Strict):
    element_id: str
    match_key: str
    global_id: str


class Manifest(_Strict):
    contract_version: str
    project: str
    counts: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- findings
class Ref(_Strict):
    element_id: str | None
    fichier: str
    page: int
    x: float
    y: float


class Diff(_Strict):
    field: str
    plan: float | int | str | None
    shop: float | int | str | None
    delta: float | None = None


class RuleEvidence(_Strict):
    fired: bool
    kind: str
    diffs: list[Diff] = Field(default_factory=list)


class ExtractionEvidence(_Strict):
    plan_overall: float | None = None
    shop_overall: float | None = None
    flags: list[str] = Field(default_factory=list)


class MatchEvidence(_Strict):
    method: str
    assignment_cost: float | None = None
    margin_to_runner_up: float | None = None


class MlEvidence(_Strict):
    peer_anomaly: float | None = None
    pair_probability: float | None = None
    model_version: str | None = None


class Evidence(_Strict):
    rule: RuleEvidence
    extraction: ExtractionEvidence
    match: MatchEvidence | None = None
    ml: MlEvidence | None = None
    llm_rationale: str | None = None


class Finding(_Strict):
    id: str
    check_type: CheckType
    status: Status
    type_element: ElementType
    level: str
    grid: str | None
    plan_ref: Ref | None = None
    shop_ref: Ref | None = None
    diffs: list[Diff] = Field(default_factory=list)
    evidence: Evidence
    trust: float = Field(ge=0.0, le=1.0)
    discrepancy_probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str = ""


class ComparisonFile(_Strict):
    contract_version: str
    shop_file: str
    revision: str | None = None
    plan_sheets: list[str] = Field(default_factory=list)
    counts: dict[str, int]
    findings: list[Finding]
