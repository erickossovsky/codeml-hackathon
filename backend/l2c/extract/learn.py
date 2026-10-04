"""Learn this document's own labels from the standard notation around them.

The *notation* of rebar annotations is standard even when the *label* is not: a bar line is a word
followed by a count, a dash and a bar size; a tie line is a word followed by a bar size, `@` and a
spacing; a shop vertical-bar line is a word, a count, a bar size and a mark; an elevation line is
a word followed by feet-inches. The word that precedes each form, when it repeats, is that
document's label. Learned labels are added to the config for that page only.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.runs import median_word_height, text_runs
from l2c.ingest.pages import Word

MIN_OCCURRENCES = 3
MIN_SHARE = 0.3  # of all occurrences of that notation form on the page
PRIORITY = ("ties_line", "shop_ties", "block_start", "section_line", "elevation_line", "shop_vert")
_LABEL = r"(?P<k>[^\W\d_][\w.]*)"
_SEP = r"[\s:.\-]*"


def _forms(size: str) -> dict[str, re.Pattern[str]]:
    return {
        "block_start": re.compile(rf"^{_LABEL}{_SEP}\d{{1,2}}\s*-\s*{size}\b"),
        "ties_line": re.compile(rf"^{_LABEL}{_SEP}{size}\s*@"),
        "section_line": re.compile(rf"^{_LABEL}{_SEP}\d+(?:\.\d+)?\s*[\"'”″]?\s*[xX×]\s*\d"),
        "shop_vert": re.compile(rf"^{_LABEL}{_SEP}\d{{1,3}}\s*{size}\s*[^\s@]+$"),
        "shop_ties": re.compile(rf"^{_LABEL}{_SEP}\d{{1,3}}\s*{size}\s*[^\s@]+\s*@"),
        "elevation_line": re.compile(rf"^{_LABEL}{_SEP}\d+\s*'\s*-?\s*\d*"),
    }


def _normalise(label: str) -> str:
    return label.strip(".:- ").upper()


def learn_keywords(
    words: list[Word], config: Config = DEFAULT_CONFIG
) -> dict[str, tuple[str, ...]]:
    """Per config field, the labels found on this page that are not already known."""
    gap = max(1.0, config.run_gap_word_heights * median_word_height(words))
    runs = text_runs(words, gap=gap)
    found: dict[str, Counter[str]] = {}
    totals: Counter[str] = Counter()
    for field, pattern in _forms(config.bar_size_pattern).items():
        counts: Counter[str] = Counter()
        for r in runs:
            m = pattern.match(r.text.strip())
            if m:
                counts[_normalise(m.group("k"))] += 1
                totals[field] += 1
        found[field] = counts
    # A label already used for one role must not be learned for another: a tie line without a
    # printed spacing has the same shape as a vertical-bar line, and would otherwise be read twice.
    all_known = {
        w.strip().rstrip(".:").upper()
        for f in found
        for w in getattr(config, f)
        if w.strip().rstrip(".:")
    }
    learned: dict[str, tuple[str, ...]] = {}
    claimed: set[str] = set()
    # most specific forms first: a label seen before `@` is a tie label before it can be a bar label
    for field in PRIORITY:
        counts = found[field]
        known = all_known
        keep = sorted(
            label
            for label, n in counts.items()
            if n >= MIN_OCCURRENCES
            and n >= MIN_SHARE * totals[field]
            and label
            and label not in claimed
            and not any(label.startswith(k) for k in known if k)
        )
        if keep:
            learned[field] = tuple(keep)
            claimed.update(keep)
    return learned


def learn_config(words: list[Word], config: Config = DEFAULT_CONFIG) -> Config:
    """The config extended with the labels this page uses (unchanged when nothing new is found)."""
    learned = learn_keywords(words, config)
    if not learned:
        return config
    return replace(config, **{f: (*getattr(config, f), *labels) for f, labels in learned.items()})
