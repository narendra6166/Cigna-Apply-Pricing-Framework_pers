"""Command-line entry point for the Apply Pricing framework."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .engine import CatalogError, load_catalog, load_results, run_catalog
from .report import write_csv, write_excel, write_markdown, write_word

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = Path(__file__).resolve().parent / "rules" / "expected-results.json"


def _report_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--results",
        type=Path,
        action="append",
        help="Bruno JSON result file; repeat to merge distinct result files",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "bruno")
    parser.add_argument("--validate-only", action="store_true", help="validate catalog without scoring")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m apply_pricing_framework",
        description="Evaluate Bruno results using the centralized Apply Pricing scenario catalog.",
    )
    subparsers = parser.add_subparsers(dest="command")
    report_parser = subparsers.add_parser("report", help="evaluate Bruno JSON and write reports")
    _report_arguments(report_parser)
    _report_arguments(parser)
    add_parser = subparsers.add_parser("add-scenario", help="add a non-runnable scenario scaffold")
    add_parser.add_argument("--id", required=True, help="unique scenario identifier")
    add_parser.add_argument("--name", required=True, help="business-readable scenario name")
    add_parser.add_argument("--payload", required=True, help="existing Bruno .bru path relative to bruno\\")
    add_parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    return parser


def _write_reports(catalog_path: Path, result_paths: list[Path], output_dir: Path) -> int:
    try:
        catalog = load_catalog(catalog_path)
        if not result_paths:
            result_paths = [PROJECT_ROOT / "bruno" / "results.json"]
        results = load_results(result_paths)
        report_time = datetime.now().astimezone().isoformat(timespec="seconds")
        outcomes, unmapped = run_catalog(catalog, results, report_time)
        output_dir.mkdir(parents=True, exist_ok=True)
        xlsx_path = output_dir / "TEST-RESULTS.xlsx"
        csv_path = output_dir / "TEST-RESULTS.csv"
        word_path = output_dir / "TEST-RESULTS.docx"
        markdown_path = output_dir / "EXECUTION-REPORT.md"
        markdown_legacy_path = output_dir / "TEST-RESULTS.md"
        write_excel(xlsx_path, outcomes, unmapped, catalog, report_time)
        write_word(word_path, outcomes, unmapped, catalog, report_time)
        write_csv(csv_path, outcomes)
        write_markdown(markdown_path, outcomes, unmapped, report_time)
        write_markdown(markdown_legacy_path, outcomes, unmapped, report_time)
    except (CatalogError, FileNotFoundError, json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
        print(f"Framework error: {exc}", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    design_scenarios = len({outcome.scenario_id for outcome in outcomes})
    print(
        f"Evaluated {len(outcomes)} payload executions across {design_scenarios} design scenarios; "
        f"unmapped requests: {len(unmapped)}."
    )
    print("Statuses: " + ", ".join(f"{status}={count}" for status, count in sorted(counts.items())))
    print(f"Excel: {xlsx_path}")
    print(f"Word: {word_path}")
    print(f"CSV: {csv_path}")
    print(f"Markdown: {markdown_path}")
    print(f"Markdown compatibility copy: {markdown_legacy_path}")
    return 0


def _add_scenario(args: argparse.Namespace) -> int:
    try:
        catalog = load_catalog(args.catalog)
        scenario_id = args.id.strip()
        name = args.name.strip()
        payload = args.payload.strip().replace("\\", "/")
        if not scenario_id or not name:
            raise CatalogError("Scenario ID and name must not be blank")
        if any(item["id"].casefold() == scenario_id.casefold() for item in catalog["scenarios"]):
            raise CatalogError(f"Scenario ID already exists: {scenario_id}")
        if not payload.endswith(".bru") or payload.startswith("/") or ".." in payload.split("/"):
            raise CatalogError("Use a .bru payload path relative to bruno\\.")
        if not (PROJECT_ROOT / "bruno" / Path(payload)).is_file():
            raise CatalogError(f"Bruno payload does not exist: bruno\\{payload}")
        catalog["scenarios"].append(
            {
                "id": scenario_id,
                "name": name,
                "category": "Uncategorized - update before use",
                "payloads": [payload],
                "expected": "Expected result pending; add the source-backed business rule before enabling.",
                "readiness": "design_pending",
                "conditions": [],
                "checks": [],
                "design_refs": ["Add references to the applicable design/scenario source."],
            }
        )
        args.catalog.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        load_catalog(args.catalog)
    except (CatalogError, OSError, json.JSONDecodeError) as exc:
        print(f"Framework error: {exc}", file=sys.stderr)
        return 1
    print(f"Added {scenario_id} as design-pending in {args.catalog}.")
    print("Update expected, conditions, checks, design_refs, and readiness before scoring it.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "add-scenario":
        return _add_scenario(args)
    try:
        catalog = load_catalog(args.catalog)
    except (CatalogError, OSError, json.JSONDecodeError) as exc:
        print(f"Framework error: {exc}", file=sys.stderr)
        return 1
    if args.validate_only:
        print(f"Valid catalog: {catalog['catalog_name']} ({len(catalog['scenarios'])} scenarios)")
        return 0
    return _write_reports(args.catalog, args.results or [], args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
