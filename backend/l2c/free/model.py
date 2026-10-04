"""Free-form element: a few fixed identity and location fields, everything else open.

`bars`, `descriptions` and `characteristics` hold any number of entries of any shape. A key a page
does not support is left out, never set to null. Names are English; the Appendix A (French) names
exist only in an export step.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FreeElement(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source: str  # plan | shop
    file: str
    sheet: str | None = None
    page: int
    x: float
    y: float
    bbox: list[float]
    kind: str | None = None  # open vocabulary; None when the reader cannot tell
    name: str | None = None
    locations: list[dict[str, Any]] = Field(default_factory=list)
    bars: list[dict[str, Any]] = Field(default_factory=list)
    descriptions: list[dict[str, Any]] = Field(default_factory=list)
    characteristics: list[dict[str, Any]] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class PageSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    file: str
    page: int
    sheet: str | None = None
    layer: str
    text_source: str
    n_words: int
    drawings: list[dict[str, Any]] = Field(default_factory=list)  # titles found on the sheet
    grid: dict[str, Any] | None = None
    scale_text: list[str] = Field(default_factory=list)
    n_elements: int = 0
    notes: list[str] = Field(default_factory=list)
