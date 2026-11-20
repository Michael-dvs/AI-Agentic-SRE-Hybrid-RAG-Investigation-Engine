#!/usr/bin/env python3
"""Entrypoint for the Chapter 19 Unified SRE Command Center prototype."""

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
    parser = argparse.ArgumentParser(description="Unified SRE Command Center (C19 Tahap 1A)")
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
    args = parser.parse_args()

    dashboard = SREDashboard(
        WorkflowStateStore(args.state_db),
        reviewer_ref=args.reviewer_ref,
        reviewer_role=args.reviewer_role,
        audit_path=args.audit_log,
        handover_root=args.handover_root,
    )
    dashboard.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
