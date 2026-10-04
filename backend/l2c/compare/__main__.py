"""`python -m l2c.compare <metadata_dir> --out <dir>`: findings, per-shop files, reports, XLSX."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from l2c.compare.outputs import by_plan_sheet, comparison_files, counts, coverage_lines, safe_name
from l2c.compare.run import run_comparison
from l2c.contract.io import ContractVersionError, read_bundle, write_models
from l2c.report.pdf import write_plan_sheet_report, write_shop_report, write_summary
from l2c.report.xlsx import write_xlsx


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l2c.compare")
    ap.add_argument("metadata_dir", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--ml", action="store_true", help="learn pair probabilities from the project's own pairs"
    )
    args = ap.parse_args(argv)
    if not (args.metadata_dir / "manifest.json").is_file():
        print(f"no manifest.json in {args.metadata_dir}", file=sys.stderr)
        return 2
    if args.ml and importlib.util.find_spec("l2c.compare.ml") is None:
        print("ML tier not available in this build; running rules only", file=sys.stderr)
    try:
        bundle = read_bundle(args.metadata_dir)
    except (ContractVersionError, OSError, ValueError) as exc:
        print(f"cannot read metadata: {exc}", file=sys.stderr)
        return 2
    findings = run_comparison(bundle, use_ml=args.ml)
    out = args.out
    coverage = coverage_lines(bundle)
    write_models(out / "findings.json", findings)
    comps, unassigned = comparison_files(findings, bundle)
    for comp in comps:
        name = safe_name(comp.shop_file)
        write_models(out / "comparison" / f"{name}.json", comp)
        write_shop_report(out / "comparison" / f"{name}.pdf", comp, coverage)
    write_plan_sheet_report(
        out / "report" / "by_plan_sheet.pdf", by_plan_sheet(findings, bundle), coverage, unassigned
    )
    write_summary(out / "report" / "summary.pdf", bundle.project, findings, coverage)
    write_xlsx(out / "findings.xlsx", findings, bundle)
    print(f"findings={len(findings)} shop_files={len(comps)} statuses={counts(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
