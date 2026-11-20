#!/usr/bin/env python3
"""Blinded Manual Baseline & Anti-Carryover Protocol Collector (C19, RULE-011, KPI-08)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evaluator.manual_baseline import (
    ManualBaselineError,
    build_default_dev_manual_records,
    compute_manual_vs_assisted_summary,
    render_manual_baseline_markdown,
    validate_anti_carryover_record,
)


def collect_manual_baseline(
    *,
    records: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Validate manual timing records and assemble the protocol payload."""
    effective_run_id = run_id or f"c19-manual-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}"
    effective_records = records if records is not None else build_default_dev_manual_records()
    for rec in effective_records:
        validate_anti_carryover_record(rec)
    summary = compute_manual_vs_assisted_summary(effective_records)
    return {
        "run_id": effective_run_id,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "protocol_version": "1.0",
        "split_id": "dev",
        "summary": summary,
        "records": effective_records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=pathlib.Path, help="Optional JSON file of manual baseline records to validate.")
    parser.add_argument("--output-json", type=pathlib.Path, help="Destination JSON file path.")
    parser.add_argument("--output-md", type=pathlib.Path, help="Destination Markdown file path.")
    parser.add_argument("--run-id", help="Optional run_id label.")
    parser.add_argument("--validate-only", action="store_true", help="Validate without writing files.")
    args = parser.parse_args(argv)

    loaded_records = None
    if args.input is not None:
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("records"), list):
            loaded_records = raw["records"]
        elif isinstance(raw, list):
            loaded_records = raw
        else:
            raise ManualBaselineError("Input JSON must be a list of records or an object with a 'records' list")

    payload = collect_manual_baseline(records=loaded_records, run_id=args.run_id)
    if not args.validate_only:
        if args.output_json is not None:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.output_md is not None:
            args.output_md.parent.mkdir(parents=True, exist_ok=True)
            args.output_md.write_text(render_manual_baseline_markdown(payload), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "VALIDATED",
                "matched_pair_count": payload["summary"]["matched_pair_count"],
                "kpi_08_time_reduction_ratio": payload["summary"]["kpi_08_time_reduction_ratio"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
