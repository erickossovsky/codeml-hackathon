"""`python -m l2c run <project_dir>`: PDFs in, metadata, findings and reports out.

`run` is extract then compare; `extract` and `compare` are the same as their own modules.
Prints counts and timings only, never drawing values.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

USAGE = "usage: python -m l2c run <project_dir> [--out DIR] [--ocr] [--workers N]"


def run(argv: list[str]) -> int:
    from l2c.compare.__main__ import main as compare_main
    from l2c.extract.__main__ import main as extract_main

    args = list(argv)
    if not args or args[0].startswith("-"):
        print(USAGE, file=sys.stderr)
        return 2
    project = Path(args.pop(0))
    out = Path("data/out") / project.name
    if "--out" in args:
        i = args.index("--out")
        out = Path(args[i + 1])
        del args[i : i + 2]
    t0 = time.time()
    code = extract_main([str(project), "--out", str(out / "metadata"), *args])
    if code:
        return code
    t1 = time.time()
    code = compare_main([str(out / "metadata"), "--out", str(out / "compare")])
    print(f"extract {t1 - t0:.1f}s, compare {time.time() - t1:.1f}s, output in {out}")
    return code


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    commands = {"run": run}
    if not argv or argv[0] not in commands:
        print(USAGE, file=sys.stderr)
        return 2
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    code = main()
    # Everything is written and closed. Leave at once: the ONNX runtime can abort in its native
    # shutdown code after OCR, which would turn a finished run into a failing exit code.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
