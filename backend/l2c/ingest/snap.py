"""Vocabulary snapping: repair OCR digit and letter confusions using what a token can be.

Bar sizes come from a closed list and spacings from a small set of notations, so a token that is
one confusable character away from a valid one is corrected (and marked as snapped, which lowers
its confidence). Tokens that do not look like rebar notation are left untouched.
"""

from __future__ import annotations

import re

from l2c.extract.config import DEFAULT_CONFIG, Config

DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5", "B": "8", "Z": "2"})
UNIT_FIX = str.maketrans({"N": "M", "H": "M", "m": "M", "n": "M"})
TOKEN_RE = re.compile(r"^([0-9OolISBZ]{1,3})([MNHmn])$")
COUNT_SIZE_RE = re.compile(r"^([0-9OolISBZ]{1,2})-([0-9OolISBZ]{1,3}[MNHmn])$")


def _snap_size(token: str, config: Config) -> str | None:
    m = TOKEN_RE.match(token)
    if not m:
        return None
    fixed = m.group(1).translate(DIGIT_FIX) + m.group(2).translate(UNIT_FIX)
    return fixed if fixed in config.bar_sizes else None


def snap_token(text: str, config: Config = DEFAULT_CONFIG) -> tuple[str, bool]:
    """Return (possibly corrected text, whether it was changed)."""
    if text in config.bar_sizes:
        return text, False
    size = _snap_size(text, config)
    if size is not None:
        return size, size != text
    m = COUNT_SIZE_RE.match(text)
    if m:
        size = _snap_size(m.group(2), config)
        if size is not None:
            count = m.group(1).translate(DIGIT_FIX)
            fixed = f"{count}-{size}"
            return fixed, fixed != text
    return text, False
