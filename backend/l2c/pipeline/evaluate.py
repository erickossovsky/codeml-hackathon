"""Measure the pipeline without an answer key: plant known differences, see which ones come back.

The challenge's discrepancies are single numbers changed on one element of a shop drawing (a bar count,
a bar size, a spacing). This evaluator does the same on any project:

1. read the project once;
2. run the matching and comparison on the original (the baseline);
3. pick shop notes at random, change one number in each (count, size or spacing), and run again;
4. a planted change is *found* when the finding that holds that shop note flags the new value.

It reports recall (planted changes found), why each miss was missed (never matched, matched but not
flagged, flagged something else), and the false flags the changes created on untouched elements. The
baseline's own flags are reported as background: on a project with a known answer key, they are the
real discrepancies plus false alarms.

python -m l2c.pipeline.evaluate <project_dir> --out <dir> [--mutations 40] [--seed 1] [--llm server]
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from l2c.contract.io import dumps
from l2c.free.reader import entries
from l2c.pipeline import assign as A
from l2c.pipeline import compare as C
from l2c.pipeline import lean

SIZES = ["10M", "15M", "20M", "25M", "30M", "35M"]


def core(
    read: dict[str, dict], sources: dict[str, str], client
) -> tuple[list[dict], list[dict], dict]:
    """Elements, matching and comparison, in memory (no files, no report)."""
    plan, shop = [], []
    for rel, r in read.items():
        data = lean.build_elements(r, sources[rel], client)
        (plan if sources[rel] == "plan" else shop).extend(data["elements"])
    res = A.assign(plan, shop, client)
    return plan, shop, C.build_findings(plan, shop, res, client)


def _mutate_line(line: str, bar: dict, kind: str, rng: random.Random) -> tuple[str, Any] | None:
    """The line with one number changed, and the new value; None when this bar cannot take that change."""
    if kind == "count" and bar.get("count") is not None:
        old = bar["count"]
        new = max(1, old + rng.choice([-3, -2, -1, 1, 2, 3, 4]))
        if new == old:
            return None
        m = re.search(rf"(?<![\d.]){old}(?![\d])", line)
        return (line[: m.start()] + str(new) + line[m.end() :], new) if m else None
    if kind == "size" and bar.get("size") in SIZES:
        old = bar["size"]
        i = SIZES.index(old)
        options = [s for s in SIZES[max(0, i - 1) : i + 2] if s != old]
        new = rng.choice(options)
        return (line.replace(old, new, 1), new) if old in line else None
    if kind == "spacing" and bar.get("spacing") is not None:
        old = bar["spacing"]
        old_txt = f"{old:g}"
        new = old + rng.choice([-2, 2, 3, 4]) if old < 30 else old + rng.choice([-50, 50, 100])
        if new <= 0:
            return None
        m = re.search(rf"@\s*{re.escape(old_txt)}(?![\d])", line)
        return (line[: m.start()] + "@" + f"{new:g}" + line[m.end() :], new) if m else None
    return None


def plant(
    read: dict[str, dict], sources: dict[str, str], n: int, seed: int, allowed: set | None = None
) -> tuple[dict[str, dict], list[dict]]:
    """A copy of the read project with `n` shop notes changed, and the list of changes. With `allowed`,
    only shop notes at those places are changed: the ones whose pair agreed before the change, as the
    jury's planted differences were made on elements that appear in both documents."""
    rng = random.Random(seed)
    mutated = copy.deepcopy(read)
    pool = []
    for rel, r in mutated.items():
        if sources[rel] != "shop":
            continue
        for b in r["blocks"]:
            if b.get("has_facts") and not b.get("schedule_part") and b["facts"]["bars"]:
                if allowed is None or (rel, b["page"], tuple(b["bbox"])) in allowed:
                    pool.append((rel, b))
    checked = allowed if isinstance(allowed, dict) else {}
    rng.shuffle(pool)
    changes: list[dict] = []
    for rel, b in pool:
        if len(changes) >= n:
            break
        # only values the pair compared as equal before the change: a number both documents state
        stated = checked.get((rel, b["page"], tuple(b["bbox"])), set()) if checked else None
        options = []
        for x in b["facts"]["bars"]:
            for k in ("count", "size", "spacing"):
                if stated is not None and (x.get("source_text"), k) not in stated:
                    continue
                if (
                    (k == "count" and x.get("count") is not None and x.get("spacing") is None)
                    or (k == "size" and x.get("size"))
                    or (k == "spacing" and x.get("spacing") is not None)
                ):
                    options.append((x, k))
        if not options:
            continue
        bar, kind = rng.choice(options)
        for li, line in enumerate(b["lines"]):
            if (
                (bar.get("source_text") or "")
                and bar["source_text"] in line
                or line in (bar.get("source_text") or "")
            ):
                got = _mutate_line(line, bar, kind, rng)
                if not got:
                    continue
                new_line, new_value = got
                lines = list(b["lines"])
                lines[li] = new_line
                bars2, chars2, descs2 = entries(lines)
                b["lines"], b["text"] = lines, " | ".join(lines)
                b["facts"] = {"bars": bars2, "characteristics": chars2, "descriptions": descs2}
                changes.append(
                    {
                        "file": rel,
                        "page": b["page"],
                        "bbox": b["bbox"],
                        "field": kind,
                        "old_line": line,
                        "new_line": new_line,
                        "new_value": new_value,
                    }
                )
                break
    return mutated, changes


def _value_matches(flag: dict, change: dict) -> bool:
    v, new = flag.get("shop"), change["new_value"]
    if change["field"] == "spacing":
        try:
            return abs(float(v) - float(new) * (25.4 if float(new) < 30 else 1.0)) <= 5.0
        except (TypeError, ValueError):
            return False
    return str(v).strip().upper() == str(new).strip().upper()


def judge(
    changes: list[dict], shop: list[dict], findings: dict, base_status: dict[tuple, str]
) -> list[dict]:
    """Was each planted change found? Each change is located by the shop note it was planted in."""
    by_place = {(e["file"], e["page"], tuple(e["bbox"])): e for e in shop}
    finding_of = {}
    for r in findings["entities"]:
        for m in r["members"]["shop"]:
            finding_of.setdefault(m["element_id"], r)
    out = []
    for ch in changes:
        e = by_place.get((ch["file"], ch["page"], tuple(ch["bbox"])))
        r = finding_of.get(e["id"]) if e else None
        if e is None:
            verdict = "not an element"
        elif r is None or r["status"] == "not_in_plan":
            verdict = "never matched"
        elif any(
            _value_matches(f, ch)
            for f in r["flags"] + [i for i in r["info"] if i.get("result") == "possible_difference"]
        ):
            verdict = "found" if r["status"] in ("differs", "uncertain") else "found (as info)"
        elif r["flags"]:
            verdict = "flagged something else"
        else:
            verdict = "matched, not flagged"
        out.append(
            {
                **ch,
                "verdict": verdict,
                "status": r["status"] if r else None,
                "baseline_status": base_status.get((ch["file"], ch["page"], tuple(ch["bbox"]))),
            }
        )
    return out


def _flagged(findings: dict) -> set[str]:
    return {
        r["entity_id"] + "|" + ",".join(sorted(m["element_id"] for m in r["members"]["shop"]))
        for r in findings["entities"]
        if r["status"] == "differs" or (r["status"] == "uncertain" and r["flags"])
    }


def main() -> int:
    from l2c.ingest import ocr as _ocr
    from l2c.llm.client import make_client
    from l2c.pipeline.__main__ import OCR_CACHE, discover

    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mutations", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--llm", default="server")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    t0 = time.time()
    found = list(discover(args.project))
    sources = {rel: src for _, rel, src in found}
    read = lean.read_many(
        [(pdf, rel) for pdf, rel, _ in found], workers=args.workers, ocr_cache=OCR_CACHE
    )
    _ocr.release_engine()
    client = make_client(args.llm)
    t = time.time()
    plan0, shop0, base = core(read, sources, client)
    t_base = time.time() - t
    base_status = {}
    finding_of = {
        m["element_id"]: r["status"] for r in base["entities"] for m in r["members"]["shop"]
    }
    for e in shop0:
        base_status[(e["file"], e["page"], tuple(e["bbox"]))] = finding_of.get(e["id"])
    field_of = {"count": "count", "size": "size", "spacing mm": "spacing"}
    place_of = {e["id"]: (e["file"], e["page"], tuple(e["bbox"])) for e in shop0}
    agreeing: dict[tuple, set] = {}
    for r in base["entities"]:
        if r["status"] != "conforms":
            continue
        for c in r["checks"]:
            f = next((v for k, v in field_of.items() if c["property"].endswith(k)), None)
            if not f or not c.get("shop_text"):
                continue
            for m in r["members"]["shop"]:
                agreeing.setdefault(place_of[m["element_id"]], set()).add((c["shop_text"], f))
    mutated, changes = plant(read, sources, args.mutations, args.seed, agreeing)
    # the baseline outputs, for the known-case check
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "findings.json").write_text(dumps(base), encoding="utf-8")
    (args.out / "elements").mkdir(exist_ok=True)
    (args.out / "elements" / "elements.all.json").write_text(
        dumps({"elements": plan0 + shop0}), encoding="utf-8"
    )
    plan1, shop1, after = core(mutated, sources, client)
    # the changed run too, so each miss can be traced to its pairing
    (args.out / "findings.changed.json").write_text(dumps(after), encoding="utf-8")
    (args.out / "elements" / "elements.changed.json").write_text(
        dumps({"elements": plan1 + shop1}), encoding="utf-8"
    )
    results = judge(changes, shop1, after, base_status)
    verdicts = Counter(r["verdict"] for r in results)
    found_n = verdicts["found"] + verdicts["found (as info)"]
    planted_ids = {(r["file"], r["page"], tuple(r["bbox"])) for r in results}
    new_flags = _flagged(after) - _flagged(base)
    by_id = {e["id"]: e for e in shop1}
    stray = [
        f
        for f in new_flags
        if not any(
            (by_id[i]["file"], by_id[i]["page"], tuple(by_id[i]["bbox"])) in planted_ids
            for i in f.split("|")[1].split(",")
            if i in by_id
        )
    ]
    summary = {
        "project": args.project.name,
        "planted": len(results),
        "found": found_n,
        "recall": round(found_n / len(results), 3) if results else None,
        "verdicts": dict(verdicts),
        "by_field": {
            k: f"{sum(1 for r in results if r['field'] == k and r['verdict'].startswith('found'))}/{sum(1 for r in results if r['field'] == k)}"
            for k in ("count", "size", "spacing")
        },
        "false_flags_created": len(stray),
        "plan_coverage": f"{sum(1 for r in base['entities'] if r['members']['plan'] and r['members']['shop'])} of {sum(1 for r in base['entities'] if r['members']['plan'])} plan elements matched",
        "baseline_counts": base["counts"],
        "background_flags": len(_flagged(base)),
        "baseline_seconds": round(t_base, 1),
        "total_seconds": round(time.time() - t0, 1),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "eval.json").write_text(
        dumps({"summary": summary, "changes": results}), encoding="utf-8"
    )
    print(json.dumps(summary, indent=1))
    for r in results:
        if not r["verdict"].startswith("found"):
            print(
                f"  MISS [{r['verdict']}] {r['field']}: {r['old_line']!r} -> {r['new_line']!r}  ({Path(r['file']).name} p{r['page']}, baseline {r['baseline_status']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
