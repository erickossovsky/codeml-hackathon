"""Send a project folder to the local API, the way the UI does, and print its progress events.

python scripts/api_run.py <project_dir> [--url http://localhost:8000]

Plans are the PDFs at the top of the folder, shop drawings the PDFs under DA/. Prints counts and
step details only, never drawing values. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path


def _multipart(fields: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, path in fields:
        disposition = f'form-data; name="{name}"; filename="{path.name}"'
        head = f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
        head += "Content-Type: application/pdf\r\n\r\n"
        parts += [head.encode(), path.read_bytes(), b"\r\n"]
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _get(url: str):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--url", default="http://localhost:8000")
    args = ap.parse_args()
    plans = sorted(p for p in args.project.glob("*.pdf"))
    shops = sorted((args.project / "DA").rglob("*.pdf")) if (args.project / "DA").is_dir() else []
    body, ctype = _multipart([("plans", p) for p in plans] + [("shops", s) for s in shops])
    req = urllib.request.Request(f"{args.url}/api/run", data=body, headers={"Content-Type": ctype})
    t0 = time.time()
    with urllib.request.urlopen(req) as r:
        run_id = json.loads(r.read())["runId"]
    print(f"run {run_id}: {len(plans)} plans, {len(shops)} shop drawings", flush=True)
    while True:
        for e in _get(f"{args.url}/api/status/{run_id}"):
            t = time.time() - t0
            if e["kind"] in ("partial", "result"):
                c, n = e["result"]["counts"], len(e["result"]["findings"])
                print(f"[{t:6.1f}s] {e['kind']}: {c} ({n} listed)", flush=True)
            elif e["kind"] == "error":
                print(f"[{t:6.1f}s] error: {e['message']}", flush=True)
            elif e["kind"] == "step":
                print(f"[{t:6.1f}s] {e['step']} {e['status']} {e.get('detail', '')}", flush=True)
            if e["kind"] in ("result", "error"):
                return 0 if e["kind"] == "result" else 1
        time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
