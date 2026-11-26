#!/usr/bin/env python3
"""Entrypoint for the SRE Investigation & Human Review Console (C19, P2-06)."""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.state_machine import WorkflowStateStore
from orchestrator.usability_console import SREDashboard


def main() -> int:
    parser = argparse.ArgumentParser(description="SRE Investigation & Human Review Console (P2-06)")
    parser.add_argument("--state-db", default=os.getenv("SRE_STATE_DB", "orchestrator_state.db"))
    parser.add_argument("--reviewer-ref", default=os.getenv("SRE_REVIEWER_REF", "sre_reviewer"))
    parser.add_argument("--reviewer-role", default=os.getenv("SRE_REVIEWER_ROLE", "L2_SRE"))
    parser.add_argument(
        "--audit-log",
        default=os.getenv("SRE_REVIEW_AUDIT_LOG", "artifacts/audit/c19-review-audit.jsonl"),
    )
    parser.add_argument(
        "--handover-root",
        default=os.getenv("SRE_HANDOVER_ROOT", "artifacts/handover"),
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=float(os.getenv("SRE_REFRESH_INTERVAL_SEC", "2.0")),
        help="Bounded UI poll interval in seconds (minimum 0.5s)",
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="Force ASCII-only borders and markers for limited terminal fonts",
    )
    args = parser.parse_args()

    dashboard = SREDashboard(
        WorkflowStateStore(args.state_db),
        reviewer_ref=args.reviewer_ref,
        reviewer_role=args.reviewer_role,
        audit_path=args.audit_log,
        handover_root=args.handover_root,
        ascii_mode=True if args.ascii else None,
    )
    dashboard.run(refresh_interval=args.refresh_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
