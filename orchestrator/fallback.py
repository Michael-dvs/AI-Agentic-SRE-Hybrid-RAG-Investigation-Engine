"""Documented Manual Fallback Generator for Degraded and Outage Scenarios (C12, FR-AGT-007, AT-012, NFR-006)."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

from orchestrator.dossier import DossierMarkdownRenderer, DossierSerializer
from orchestrator.state_machine import utc_now_z


class ManualFallbackGenerator:
    """Generates standardized Manual Fallback Dossiers when automated investigation fails or aborts (FR-AGT-007, AT-012)."""

    @classmethod
    def generate_fallback_dossier(
        cls,
        context: Dict[str, Any],
        reason_code: str,
        error_message: str,
    ) -> Dict[str, Any]:
        """Construct, serialize, and render a complete manual fallback dossier."""
        incident_id = context.get("incident_id", "inc-fallback")
        service_id = context.get("service_id", "api-gateway")
        now = utc_now_z()

        # Map reason_code to standard enum
        valid_err_codes = {
            "DEADLINE_EXCEEDED": "DEADLINE_EXCEEDED",
            "BUDGET_EXHAUSTED": "BUDGET_EXHAUSTED",
            "SOURCE_UNAVAILABLE": "SOURCE_UNAVAILABLE",
            "BACKEND_TIMEOUT": "BACKEND_TIMEOUT",
            "TIMEOUT": "BACKEND_TIMEOUT",
        }
        std_err_code = valid_err_codes.get(reason_code, "BACKEND_TIMEOUT")

        # Prepare fallback context
        fallback_ctx = dict(context)
        fallback_ctx["investigation_mode"] = "manual_fallback"
        fallback_ctx["dossier_ready_at"] = now

        # Add abort event to timeline
        timeline = list(fallback_ctx.get("timeline", []))
        timeline.append({
            "timestamp": now,
            "event_kind": "workflow_event",
            "source_ref": "orchestrator:resilience",
            "summary": f"Automated workflow aborted with {reason_code}: {error_message[:200]}",
        })
        fallback_ctx["timeline"] = timeline

        # Record in missing sources
        missing_sources = list(fallback_ctx.get("missing_sources", []))
        missing_sources.append({
            "tool_name": "investigator_workflow",
            "error_code": std_err_code,
            "recorded_at": now,
            "impact_note": f"Automated investigation terminated prematurely: {error_message[:400]}",
        })
        fallback_ctx["missing_sources"] = missing_sources

        # Set conservative fallback hypothesis
        fallback_ctx["hypotheses"] = [
            {
                "hypothesis_id": f"hyp-{incident_id}-fallback",
                "title": f"Automated investigation aborted ({reason_code}); manual triage required",
                "statement": f"Automated analysis on {service_id} could not complete due to {reason_code}. Human engineering review is required.",
                "description": f"Workflow abort triggered: '{error_message}'. Telemetry signals remain inconclusive.",
                "status": "INCONCLUSIVE",
                "supporting_evidence_ids": [],
                "refuting_evidence_ids": [],
                "unknowns": [
                    f"Root cause cannot be automatically determined due to {reason_code}.",
                    "System telemetry state must be validated manually by on-call engineer.",
                ],
            }
        ]

        # Add explicit unknowns
        unknowns = list(fallback_ctx.get("unknowns", []))
        unknowns.append(f"Automated pipeline halted due to {reason_code}: {error_message[:200]}")
        unknowns.append("Full dependency graph and span waterfall could not be verified automatically.")
        fallback_ctx["unknowns"] = unknowns

        # Set review summary to MANUAL_TRIAGE
        fallback_ctx["review_summary"] = {
            "status": "MANUAL_TRIAGE",
            "latest_review_event_id": None,
            "reviewed_by": None,
            "reviewed_at": None,
        }

        # Serialize & Render
        dossier_json = DossierSerializer.serialize(
            fallback_ctx,
            revision=1,
            investigation_mode="manual_fallback",
        )
        dossier_md = DossierMarkdownRenderer.render(dossier_json)

        return {
            "dossier_json": dossier_json,
            "dossier_markdown": dossier_md,
            "context": fallback_ctx,
        }

