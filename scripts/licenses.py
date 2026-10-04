"""List every installed dependency with its version and declared license (for THIRD_PARTY.md).

Usage: python scripts/licenses.py
Review every line; resolve anything marked UNKNOWN before submission.
"""

from __future__ import annotations

from importlib import metadata

WATCH = {"pymupdf": "AGPL-3.0 (source must ship with the submission)"}


def license_of(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    text = meta.get("License-Expression") or meta.get("License") or ""
    if not text or len(text) > 80:
        classifiers = [
            c.split("::")[-1].strip()
            for c in meta.get_all("Classifier") or []
            if c.startswith("License ::")
        ]
        text = ", ".join(classifiers) or "UNKNOWN"
    return text.splitlines()[0]


def main() -> int:
    rows = sorted((d.metadata["Name"], d.version, license_of(d)) for d in metadata.distributions())
    width = max(len(n) for n, _, _ in rows)
    for name, version, lic in rows:
        note = f"   <-- {WATCH[name.lower()]}" if name.lower() in WATCH else ""
        print(f"{name:<{width}}  {version:<12} {lic}{note}")
    unknown = [n for n, _, lic in rows if lic == "UNKNOWN"]
    print(f"\n{len(rows)} packages; {len(unknown)} with unknown license: {unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
