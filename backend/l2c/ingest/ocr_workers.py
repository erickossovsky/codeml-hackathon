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
GPU_WORKER_THREADS = 2  # pre- and post-processing around the GPU calls
CPU_WORKER_THREADS = (
    2  # CPU workers use spare cores at low priority, without crowding the GPU worker
)
WORKER_TIMEOUT_S = 3600


def default_workers() -> int:
    return max(1, (os.cpu_count() or 2) // THREADS_PER_WORKER)


def default_mix() -> tuple[int, int]:
    """(GPU workers, CPU workers). With the GPU build: one GPU worker and no CPU worker. On a laptop
    the CPU workers share the power and heat budget with the GPU and slowed it about fivefold
    (measured), and a 4 GB card holds one OCR session. Without it: CPU workers on half the cores."""
    from l2c.ingest.ocr import VENDOR

    if os.environ.get("L2C_OCR_GPU", "1") != "0" and (VENDOR / "ortgpu").is_dir():
        return 1, 0
    return 0, default_workers()


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


def start_workers(
    jobs: list[tuple[Path, int]],
    config: Config,
    cache_dir: Path,
    gpu_workers: int = 1,
    cpu_workers: int = 4,
) -> list[subprocess.Popen]:
    """Start OCR workers without waiting for them. They share one queue: each takes the next page
    no other worker has claimed (a claim file next to the cache entry), so fast GPU workers and
    slower CPU workers finish together. GPU workers take the pages in order and CPU workers from the
    end, so the first files are complete first. Results appear in `cache_dir` page by page."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        _entry(cache_dir, j, config).with_suffix(".claim").unlink(
            missing_ok=True
        )  # left by an interrupted run
    job_file = cache_dir / f"jobs_{os.getpid()}.pkl"
    job_file.write_bytes(pickle.dumps((jobs, config)))
    procs = []
    for i in range(gpu_workers + cpu_workers):
        gpu = i < gpu_workers
        # every library a worker loads (ONNX, OpenCV, numpy) gets the same small thread budget; CPU
        # workers run at low priority, so the GPU workers' pre- and post-processing is never starved
        n = str(GPU_WORKER_THREADS if gpu else CPU_WORKER_THREADS)
        env = dict(
            os.environ,
            L2C_OCR_GPU="1" if gpu else "0",
            L2C_OCR_THREADS=n,
            OMP_NUM_THREADS=n,
            OPENBLAS_NUM_THREADS=n,
            MKL_NUM_THREADS=n,
        )
        flags = 0
        if os.name == "nt":
            flags = (
                subprocess.ABOVE_NORMAL_PRIORITY_CLASS
                if gpu
                else subprocess.BELOW_NORMAL_PRIORITY_CLASS
            )
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "l2c.ingest.ocr_workers",
                    str(job_file),
                    str(cache_dir),
                    "forward" if gpu else "backward",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        )
    return procs


def _claim(entry: Path) -> bool:
    try:
        os.close(os.open(entry.with_suffix(".claim"), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except FileExistsError:
        return False


def _worker(job_file: str, cache_dir: str, order: str = "forward") -> int:
    threads = int(os.environ.get("L2C_OCR_THREADS", THREADS_PER_WORKER))
    try:
        import cv2

        cv2.setNumThreads(threads)
    except Exception:
        pass
    gpu = os.environ.get("L2C_OCR_GPU") != "0"
    if os.name == "nt":
        # set here: the venv's python.exe is a launcher, and Windows does not pass an above-normal
        # priority on to the interpreter it starts
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p  # a 64-bit handle, not a C int
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.SetPriorityClass(
            k32.GetCurrentProcess(), 0x8000 if gpu else 0x4000
        )  # above / below normal
    elif not gpu:
        os.nice(10)
    set_engine_options(threads=threads)
    share, config = pickle.loads(Path(job_file).read_bytes())
    cache = Path(cache_dir)
    for path, page in share if order == "forward" else share[::-1]:
        entry = _entry(cache, (path, page), config)
        if entry.is_file() or not _claim(entry):
            continue  # done, or another worker has it
        try:
            cached_ocr_page(path, page, config, cache)
        except Exception:
            pass  # the caller reads this page itself and records the real error
        finally:
            entry.with_suffix(".claim").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(_worker(sys.argv[1], sys.argv[2], *sys.argv[3:4]))
