"""What each PDF says, kept in a folder so a file read once is not read again.

data/cache/files/<sha256>.<source>.json  one entry per file content and role (plan or shop): the
                                         free-form elements, the page counts, when it was read
data/cache/files/index.json              the last content seen under each file name, to tell a new
                                         file from a changed one

Keyed by the file's content (SHA-256), so a file uploaded again under another folder is still
known, and a changed file (same name, new content) is read again. No PDF is stored. Entries written
by an older reader (another VERSION) are ignored and replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path, PurePath

VERSION = "1"  # raise when reading or grouping changes, so older entries are read again


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_retry(tmp: Path, path: Path, tries: int = 100) -> None:
    """Swap a finished temporary file into place (a reader never sees half a file). Windows refuses
    while another process has the target open for reading, so the swap is retried briefly."""
    for i in range(tries):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.02)


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    replace_retry(tmp, path)


class FileCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        try:
            self.index: dict[str, str] = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.index = {}

    def _entry(self, digest: str, source: str) -> Path:
        return self.root / f"{digest}.{source}.json"

    def get(self, digest: str, source: str) -> dict | None:
        try:
            entry = json.loads(self._entry(digest, source).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return entry if entry.get("version") == VERSION else None

    def status(self, name: str, digest: str, source: str) -> str:
        """`cached` (this content was read before), `changed` (a file of this name was read with
        other content) or `new`."""
        if self.get(digest, source) is not None:
            return "cached"
        return "changed" if PurePath(name).name in self.index else "new"

    def put(self, digest: str, source: str, name: str, meta: dict, elements: dict) -> None:
        entry = {
            "version": VERSION,
            "sha256": digest,
            "source": source,
            "name": PurePath(name).name,
            "read_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **meta,
            "elements": elements,
        }
        _write(self._entry(digest, source), entry)
        self.index[PurePath(name).name] = digest
        _write(self.index_path, self.index)


def relocate(elements: dict, rel: str) -> dict:
    """Cached elements as they apply to the file's place in this project (the same PDF can sit in
    another folder than when it was read)."""
    for e in elements.get("elements", []):
        e["file"] = rel
    if isinstance(elements.get("file"), dict):
        elements["file"]["file"] = rel
    return elements
