"""OCR of many pages in worker processes.

Each worker is its own Python process (not a pool: a process pool deadlocked with the ONNX
engine), reads its share of the pages and writes every result into the shared on-disk cache. The
caller then reads the results back from the cache; a page a worker could not read is simply
absent and is read by the caller itself.

A single OCR page is limited by one core, so several workers with a couple of threads each use the
machine far better than one worker with all the threads.
"""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.ingest.ocr import OcrResult, cache_key, cached_ocr_page, set_engine_options

THREADS_PER_WORKER = 2
WORKER_TIMEOUT_S = 3600


def default_workers() -> int:
    return max(1, (os.cpu_count() or 2) // THREADS_PER_WORKER)


def _entry(cache_dir: Path, job: tuple[Path, int], config: Config) -> Path:
    return cache_dir / f"{cache_key(job[0], job[1], config)}.pkl"


def ocr_pages(
    jobs: list[tuple[Path, int]],
    config: Config = DEFAULT_CONFIG,
    workers: int = 0,
    cache_dir: Path | None = None,
) -> dict[tuple[Path, int], OcrResult]:
    """Read (file, page) jobs in parallel; returns the results that were produced."""
    workers = workers or default_workers()
    with tempfile.TemporaryDirectory() as scratch:
        cache = Path(cache_dir) if cache_dir else Path(scratch) / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        todo = [j for j in jobs if not _entry(cache, j, config).is_file()]
        n = min(workers, len(todo))
        procs = []
        for i in range(n):
            share = todo[i::n]
            job_file = Path(scratch) / f"jobs_{i}.pkl"
            job_file.write_bytes(pickle.dumps((share, config)))
            procs.append(
                subprocess.Popen(
                    [sys.executable, "-m", "l2c.ingest.ocr_workers", str(job_file), str(cache)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        for p in procs:
            try:
                p.wait(timeout=WORKER_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                p.kill()
        results = {}
        for j in jobs:
            entry = _entry(cache, j, config)
            if entry.is_file():
                try:
                    results[j] = pickle.loads(entry.read_bytes())
                except Exception:
                    continue
        return results


def _worker(job_file: str, cache_dir: str) -> int:
    set_engine_options(threads=THREADS_PER_WORKER)
    share, config = pickle.loads(Path(job_file).read_bytes())
    for path, page in share:
        try:
            cached_ocr_page(path, page, config, Path(cache_dir))
        except Exception:
            pass  # the caller reads this page itself and records the real error
    return 0


if __name__ == "__main__":
    sys.exit(_worker(sys.argv[1], sys.argv[2]))
