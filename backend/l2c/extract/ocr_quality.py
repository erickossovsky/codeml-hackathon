"""Carry OCR confidence and snapping into the quality of the elements built from OCR words."""

from __future__ import annotations

from l2c.contract.models import AttrQuality, ElementExt
from l2c.extract import quality as Q
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.ingest.pages import Word


def mark_ocr(
    elements: list[ElementExt], words: list[Word], config: Config = DEFAULT_CONFIG
) -> list[ElementExt]:
    """Return copies whose attribute confidences reflect how their text was read.

    An element's tokens are looked up among the page's OCR words; the weakest matching word sets
    the confidence, and a token that was snapped to the vocabulary is marked as such.
    """
    by_text: dict[str, tuple[float, bool]] = {}
    for w in words:
        conf, snapped = by_text.get(w.text, (1.0, False))
        by_text[w.text] = (
            min(conf, w.conf if w.conf is not None else 1.0),
            snapped or bool(w.original),
        )
    out: list[ElementExt] = []
    for e in elements:
        tokens = [t for t in (e.raw_text or "").replace("|", " ").split() if t in by_text]
        conf = min((by_text[t][0] for t in tokens), default=0.5)
        snapped = any(by_text[t][1] for t in tokens)
        attrs: dict[str, AttrQuality] = {}
        for name, a in e.quality.attributes.items():
            if a.status == "missing":
                attrs[name] = a
                continue
            attrs[name] = Q.attr(
                a.value,
                conf=1.0,
                status=a.status,
                text_source="ocr",
                ocr_conf=conf,
                snapped=snapped,
                original_text=a.original_text,
            )
        q = e.quality
        quality = Q.build_quality(
            type_conf=q.type_conf,
            level_conf=q.level_conf,
            loc=q.location,
            attrs=attrs,
            passed=q.consistency_passed,
            failed=q.consistency_failed,
            flags=[*q.flags, "ocr_text", *(["ocr_snapped"] if snapped else [])],
        )
        out.append(e.model_copy(update={"quality": quality, "extraction_method": "rules+ocr"}))
    return out
