"""Deterministic Rule-Based Investigator and Provenance Checker (C11, FR-AGT-001, FR-AGT-007, EV-01, EV-02, RULE-006)."""

from __future__ import annotations

import datetime
from dataclasses import asdict
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set

from gateway.policy import PolicyGateway
from gateway.sanitizer import DeterministicSanitizer
from observability.ai_tracer import SanitizedAITracer
from observability.cost_tracker import CostAndResourceTracker
from orchestrator.claim_validator_contract import ClaimValidator, HypothesisStatus
from orchestrator.checkpoint import CheckpointManager
from orchestrator.confidence import (
    assess_sop_diagnostic_relevance,
    compute_evidence_confidence,
    confidence_label_for_score,
    rank_hypotheses,
)
from orchestrator.dossier import DossierMarkdownRenderer, DossierSerializer
from orchestrator.fallback import ManualFallbackGenerator
from orchestrator.llm_investigator import LLMInvestigator, sanitized_citations
from orchestrator.resilience import (
    BudgetExhaustedError,
    CircuitOpenError,
    DeadlineExceededError,
    IncidentCancelledError,
    ResilienceController,
)
from orchestrator.state_machine import (
    InvestigationStateMachine,
    utc_now_z,
)
from services.alert_intake.correlation import DependencyCorrelator

_LOG = logging.getLogger(__name__)

DEFAULT_COORDINATOR_TOKEN = "sre-sim-coord-token-secret-2026"


class DeterministicInvestigator:
    """Orchestrates deterministic 9-state investigation with bounded scope, honest uncertainty, and durable checkpoints (C11)."""

    def __init__(
        self,
        state_machine: InvestigationStateMachine,
        gateway: PolicyGateway,
        correlator: DependencyCorrelator | None = None,
        resilience: ResilienceController | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        bearer_token: str = DEFAULT_COORDINATOR_TOKEN,
        llm_investigator: LLMInvestigator | None = None,
        claim_validator: ClaimValidator | None = None,
        ai_tracer: SanitizedAITracer | None = None,
        cost_tracker: CostAndResourceTracker | None = None,
        pending_review_notifier: Callable[[Dict[str, Any]], Any] | None = None,
    ) -> None:
        self.sm = state_machine
        self.gateway = gateway
        self.correlator = correlator or DependencyCorrelator()
        self.resilience = resilience or ResilienceController()
        self.checkpoint = checkpoint_manager or CheckpointManager(self.sm.store)
        self.bearer_token = bearer_token
        self.llm = llm_investigator
        self.claim_validator = claim_validator if claim_validator is not None else ClaimValidator()
        self.ai_tracer = ai_tracer if ai_tracer is not None else SanitizedAITracer()
        self.cost_tracker = cost_tracker if cost_tracker is not None else CostAndResourceTracker()
        self.pending_review_notifier = pending_review_notifier

    def _format_incident_id(self, raw_id: str) -> str:
        return raw_id if raw_id.startswith("inc-") else f"inc-{raw_id}"

    @staticmethod
    def _retrieval_query_text(context: Dict[str, Any]) -> str:
        service_id = context.get("service_id")
        error_code = context.get("error_code")
        observed = [error_code] if error_code and error_code != "ERR_UNKNOWN" else []
        downstream_details: list[str] = []
        primary_err_rate: str | None = None
        for evidence in context.get("evidence_items", []):
            tname = evidence.get("tool_name")
            ev_svc = evidence.get("service_id", service_id)
            if tname == "search_error_logs":
                for record in evidence.get("records", [])[:3]:
                    if not isinstance(record, dict):
                        continue
                    rec_svc = record.get("service_id", ev_svc)
                    detail = record.get("message") or record.get("error_code")
                    if not detail:
                        continue
                    if rec_svc == service_id:
                        observed.append(str(detail))
                    elif len(downstream_details) < 2:
                        downstream_details.append(f"{rec_svc}: {record.get('error_code') or detail}")
            elif tname == "get_service_metrics" and ev_svc == service_id:
                for record in evidence.get("records", []):
                    if not isinstance(record, dict):
                        continue
                    m_name = str(record.get("metric_enum") or record.get("metric_name") or "").lower()
                    val = record.get("value")
                    if m_name in ("error_rate", "sim_red_error_rate_ratio") and isinstance(val, (int, float)) and val > 0:
                        primary_err_rate = f"error_rate={float(val):.2f}"
        if context.get("message"):
            observed.append(str(context["message"]))
        if observed or primary_err_rate:
            if primary_err_rate and len(observed) < 6:
                observed.append(primary_err_rate)
            for ds in downstream_details:
                if ds not in observed:
                    observed.append(ds)
        sanitized, _ = DeterministicSanitizer().sanitize_text(" | ".join(dict.fromkeys(observed)))
        return sanitized.strip()[:512]

    def investigate_incident(self, alert_or_incident: Dict[str, Any]) -> Dict[str, Any]:
        """Execute full 9-state investigation lifecycle: RECEIVED -> ... -> HUMAN_REVIEW."""
        raw_id = alert_or_incident.get("incident_id") or f"inc-{uuid.uuid4().hex[:12]}"
        incident_id = self._format_incident_id(raw_id)
        raw_service = alert_or_incident.get("service_id")
        has_service = isinstance(raw_service, str) and bool(raw_service.strip())
        service_id = raw_service.strip() if has_service else "api-gateway"
        raw_env = alert_or_incident.get("environment")
        has_env = isinstance(raw_env, str) and bool(raw_env.strip())
        environment = raw_env.strip() if has_env else "lab"
        has_valid_time = True
        if "event_time" in alert_or_incident:
            raw_event_time = alert_or_incident.get("event_time")
            has_valid_time = False
            if isinstance(raw_event_time, str) and raw_event_time.endswith("Z"):
                try:
                    datetime.datetime.fromisoformat(raw_event_time[:-1] + "+00:00")
                    has_valid_time = True
                except ValueError:
                    has_valid_time = False
            event_time = raw_event_time if has_valid_time else utc_now_z()
        else:
            event_time = utc_now_z()
        error_code = alert_or_incident.get("error_code", "ERR_UNKNOWN")
        trace_id = alert_or_incident.get("trace_id")

        # Initialize resilience tracking for global deadline
        admitted = self.resilience.start_incident(incident_id)

        # Initialize C15 AI observability trace and cost accounting session
        corr_id = alert_or_incident.get("correlation_id") or f"corr-{uuid.uuid4().hex[:12]}"
        self.cost_tracker.start_incident(incident_id)
        ai_trace_id = self.ai_tracer.start_trace(
            incident_id=incident_id,
            correlation_id=corr_id,
            trace_id=trace_id,
            version_manifest=self.sm.get_version_manifest(),
        )

        context: Dict[str, Any] = {
            "incident_id": incident_id,
            "correlation_id": corr_id,
            "ai_trace_id": ai_trace_id,
            "service_id": service_id,
            "environment": environment,
            "event_time": event_time,
            "error_code": error_code,
            "trace_id": trace_id,
            "message": alert_or_incident.get("message", ""),
            "investigation_scope": [service_id],
            "impact_graph": {},
            "priority": "MEDIUM",
            "query_window": {},
            "evidence_items": [],
            "runbook_citations": [],
            "no_applicable_runbook": False,
            "sop_availability": "NOT_ASSESSED",
            "sop_filter_reasons": [],
            "has_match_context": has_service and has_env and has_valid_time,
            "hypotheses": [],
            "contradictions": [],
            "unknowns": [],
            "version_manifest": self.sm.get_version_manifest(),
            "dossier": {},
            "timeline": [],
        }

        try:
            if not admitted:
                raise IncidentCancelledError(
                    f"Incident {incident_id} rejected: emergency kill switch engaged"
                )
            # 1. RECEIVED
            t0 = time.perf_counter()
            context = self._step_received(incident_id, context)
            dur = max(0.0, (time.perf_counter() - t0) * 1000.0)
            self.cost_tracker.record_state_duration(incident_id, "RECEIVED", dur)
            self.ai_tracer.record_span(incident_id, "state.received", duration_ms=dur, attributes={"state": "RECEIVED"})

            # 2. CORRELATED
            t0 = time.perf_counter()
            context = self._step_correlated(incident_id, context)
            dur = max(0.0, (time.perf_counter() - t0) * 1000.0)
            self.cost_tracker.record_state_duration(incident_id, "CORRELATED", dur)
            self.ai_tracer.record_span(incident_id, "state.correlated", duration_ms=dur, attributes={"state": "CORRELATED"})

            # 3. TRIAGED
            t0 = time.perf_counter()
            context = self._step_triaged(incident_id, context)
            dur = max(0.0, (time.perf_counter() - t0) * 1000.0)
            self.cost_tracker.record_state_duration(incident_id, "TRIAGED", dur)
            self.ai_tracer.record_span(incident_id, "state.triaged", duration_ms=dur, attributes={"state": "TRIAGED"})

            # 4. EVIDENCE_COLLECTED
            t0 = time.perf_counter()
            context = self._step_evidence_collected(incident_id, context)
            dur = max(0.0, (time.perf_counter() - t0) * 1000.0)
            self.cost_tracker.record_state_duration(incident_id, "EVIDENCE_COLLECTED", dur)
            self.cost_tracker.record_tool_call(incident_id, count=len(context.get("evidence_items", [])))
            self.ai_tracer.record_span(
                incident_id,
                "state.evidence_collected",
                duration_ms=dur,
                attributes={"state": "EVIDENCE_COLLECTED", "evidence_count": len(context.get("evidence_items", []))},
            )

            # 5. RETRIEVED
            t0 = time.perf_counter()
            context = self._step_retrieved(incident_id, context)
            dur = max(0.0, (time.perf_counter() - t0) * 1000.0)
            self.cost_tracker.record_state_duration(incident_id, "RETRIEVED", dur)
            self.cost_tracker.record_retrieval(incident_id, dur)
            self.ai_tracer.record_span(
                incident_id,
                "state.retrieved",
                duration_ms=dur,
                attributes={
                    "state": "RETRIEVED",
                    "citations_count": len(context.get("runbook_citations", [])),
                    "no_applicable": context.get("no_applicable_runbook", False),
                },
            )

            # 6. HYPOTHESES
            t0 = time.perf_counter()
            context = self._step_hypotheses(incident_id, context)
            dur = max(0.0, (time.perf_counter() - t0) * 1000.0)
            self.cost_tracker.record_state_duration(incident_id, "HYPOTHESES", dur)
            if self.llm:
                usage = self.llm.ledger.usage(incident_id)
                in_tok = usage.get("input_reported") or usage.get("input_reserved") or 0
                out_tok = usage.get("output_reported") or usage.get("output_reserved") or 0
                self.cost_tracker.record_tokens(incident_id, in_tok, out_tok)
                self.ai_tracer.record_span(
                    incident_id,
                    "state.hypotheses",
                    duration_ms=dur,
                    attributes={
                        "state": "HYPOTHESES",
                        "mode": context.get("investigation_mode"),
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "hypotheses_count": len(context.get("hypotheses", [])),
                    },
                )
            else:
                self.ai_tracer.record_span(
                    incident_id,
                    "state.hypotheses",
                    duration_ms=dur,
                    attributes={"state": "HYPOTHESES", "mode": "deterministic", "hypotheses_count": len(context.get("hypotheses", []))},
                )

            # 7. VALIDATED
            t0 = time.perf_counter()
            context = self._step_validated(incident_id, context)
            dur = max(0.0, (time.perf_counter() - t0) * 1000.0)
            self.cost_tracker.record_state_duration(incident_id, "VALIDATED", dur)
            self.ai_tracer.record_span(
                incident_id,
                "state.validated",
                duration_ms=dur,
                attributes={
                    "state": "VALIDATED",
                    "contradictions_count": len(context.get("contradictions", [])),
                    "unknowns_count": len(context.get("unknowns", [])),
                },
            )

            # 8. DRAFTED
            t0 = time.perf_counter()
            context = self._step_drafted(incident_id, context)
            dur = max(0.0, (time.perf_counter() - t0) * 1000.0)
            self.cost_tracker.record_state_duration(incident_id, "DRAFTED", dur)
            self.ai_tracer.record_span(
                incident_id,
                "state.drafted",
                duration_ms=dur,
                attributes={"state": "DRAFTED", "dossier_hash": context.get("dossier_hash")},
            )

            # 9. HUMAN_REVIEW
            t0 = time.perf_counter()
            context = self._step_human_review(incident_id, context)
            dur = max(0.0, (time.perf_counter() - t0) * 1000.0)
            self.cost_tracker.record_state_duration(incident_id, "HUMAN_REVIEW", dur)
            self.ai_tracer.record_span(incident_id, "state.human_review", duration_ms=dur, attributes={"state": "HUMAN_REVIEW"})

            # Conclude metrics and AI trace session
            metrics = self.cost_tracker.finish_incident(incident_id, outcome="COMPLETED")
            context["metrics"] = metrics
            self.ai_tracer.end_trace(
                incident_id=incident_id,
                outcome="COMPLETED",
                final_summary={
                    "priority": context.get("priority"),
                    "dossier_hash": context.get("dossier_hash"),
                    "total_duration_ms": metrics["latency"]["intake_to_dossier_duration_ms"],
                    "shadow_cost_usd": metrics["shadow_cost"]["estimated_unit_cost_usd"],
                },
            )

            return context

        except IncidentCancelledError as exc:
            _LOG.warning("Investigation cancelled for %s: %s", incident_id, exc)
            self._handle_abort(
                incident_id,
                to_state="CANCELLED",
                reason_code="CANCELLED",
                terminal_outcome="TERMINATED_CANCELLED",
                reason=str(exc),
                context=context,
            )
            context["status"] = "CANCELLED"
            context["abort_reason"] = str(exc)
            return context

        except (DeadlineExceededError, BudgetExhaustedError) as exc:
            _LOG.warning("Resource bound reached for %s: %s", incident_id, exc)
            code = getattr(exc, "code", "DEADLINE_EXCEEDED")
            self._handle_abort(
                incident_id,
                to_state="FAILED_SAFE",
                reason_code=code,
                terminal_outcome="TERMINATED_FAILED_SAFE",
                reason=str(exc),
                context=context,
            )
            context["status"] = "FAILED_SAFE"
            context["abort_reason"] = str(exc)
            return context

        except Exception as exc:
            _LOG.exception("Unexpected error in investigation of %s: %s", incident_id, exc)
            self._handle_abort(
                incident_id,
                to_state="FAILED_SAFE",
                reason_code="MANUAL_FALLBACK_ACTIVE",
                terminal_outcome="TERMINATED_FAILED_SAFE",
                reason=f"Unexpected error: {exc}",
                context=context,
            )
            context["status"] = "FAILED_SAFE"
            context["abort_reason"] = str(exc)
            return context

    def resume_investigation(self, incident_id: str) -> Dict[str, Any]:
        """Resume in-flight or interrupted investigation from latest durable checkpoint (FR-AGT-009, AT-012)."""
        formatted_id = self._format_incident_id(incident_id)
        chk = self.checkpoint.get_checkpoint(formatted_id)
        if not chk:
            raise ValueError(f"No checkpoint found for incident {formatted_id}")

        current_state = chk["state"]
        context = chk["context"]
        _LOG.info("Resuming investigation for %s from checkpoint state %s", formatted_id, current_state)

        # Check cancellation before resuming
        self.resilience.check_cancellation(formatted_id)

        # Resume sequentially from current checkpoint state forward
        try:
            if current_state == "RECEIVED":
                context = self._step_correlated(formatted_id, context)
                context = self._step_triaged(formatted_id, context)
                context = self._step_evidence_collected(formatted_id, context)
                context = self._step_retrieved(formatted_id, context)
                context = self._step_hypotheses(formatted_id, context)
                context = self._step_validated(formatted_id, context)
                context = self._step_drafted(formatted_id, context)
                context = self._step_human_review(formatted_id, context)
            elif current_state == "CORRELATED":
                context = self._step_triaged(formatted_id, context)
                context = self._step_evidence_collected(formatted_id, context)
                context = self._step_retrieved(formatted_id, context)
                context = self._step_hypotheses(formatted_id, context)
                context = self._step_validated(formatted_id, context)
                context = self._step_drafted(formatted_id, context)
                context = self._step_human_review(formatted_id, context)
            elif current_state == "TRIAGED":
                context = self._step_evidence_collected(formatted_id, context)
                context = self._step_retrieved(formatted_id, context)
                context = self._step_hypotheses(formatted_id, context)
                context = self._step_validated(formatted_id, context)
                context = self._step_drafted(formatted_id, context)
                context = self._step_human_review(formatted_id, context)
            elif current_state == "EVIDENCE_COLLECTED":
                context = self._step_retrieved(formatted_id, context)
                context = self._step_hypotheses(formatted_id, context)
                context = self._step_validated(formatted_id, context)
                context = self._step_drafted(formatted_id, context)
                context = self._step_human_review(formatted_id, context)
            elif current_state == "RETRIEVED":
                context = self._step_hypotheses(formatted_id, context)
                context = self._step_validated(formatted_id, context)
                context = self._step_drafted(formatted_id, context)
                context = self._step_human_review(formatted_id, context)
            elif current_state == "HYPOTHESES":
                context = self._step_validated(formatted_id, context)
                context = self._step_drafted(formatted_id, context)
                context = self._step_human_review(formatted_id, context)
            elif current_state == "VALIDATED":
                context = self._step_drafted(formatted_id, context)
                context = self._step_human_review(formatted_id, context)
            elif current_state == "DRAFTED":
                context = self._step_human_review(formatted_id, context)
            elif current_state == "HUMAN_REVIEW":
                _LOG.info("Incident %s is already at HUMAN_REVIEW", formatted_id)

            return context

        except (IncidentCancelledError, DeadlineExceededError, BudgetExhaustedError, Exception) as exc:
            _LOG.warning("Resume failed for %s: %s", formatted_id, exc)
            to_state = "CANCELLED" if isinstance(exc, IncidentCancelledError) else "FAILED_SAFE"
            reason_code = getattr(exc, "code", "MANUAL_FALLBACK_ACTIVE")
            outcome = "TERMINATED_CANCELLED" if to_state == "CANCELLED" else "TERMINATED_FAILED_SAFE"
            self._handle_abort(
                formatted_id,
                to_state=to_state,
                reason_code=reason_code,
                terminal_outcome=outcome,
                reason=str(exc),
                context=context,
            )
            context["status"] = to_state
            context["abort_reason"] = str(exc)
            return context

    def _handle_abort(
        self,
        incident_id: str,
        to_state: str,
        reason_code: str,
        terminal_outcome: str,
        reason: str,
        context: Dict[str, Any],
    ) -> None:
        """Handle abnormal workflow termination safely into persistence and DLQ."""
        # Generate and save fallback dossier if aborted
        try:
            fb = ManualFallbackGenerator.generate_fallback_dossier(
                context=context,
                reason_code=reason_code,
                error_message=reason,
            )
            context["dossier"] = fb["dossier_json"]
            context["dossier_markdown"] = fb["dossier_markdown"]
            self.sm.store.save_dossier(
                incident_id=incident_id,
                dossier_version=1,
                dossier_hash=fb["dossier_json"]["dossier_hash"],
                dossier_json=fb["dossier_json"],
                dossier_markdown=fb["dossier_markdown"],
            )
        except Exception as fb_err:
            _LOG.warning("Fallback dossier generation failed for %s: %s", incident_id, fb_err)

        try:
            self.sm.transition(
                incident_id=incident_id,
                to_state=to_state,
                idempotency_key=f"idem-{incident_id}-{to_state.lower()}",
                reason_code=reason_code,
                terminal_outcome=terminal_outcome,
                reason=reason,
                input_data=context,
            )
        except Exception as e:
            _LOG.error("Failed to record abort state transition for %s: %s", incident_id, e)

        # Enqueue to DLQ and save checkpoint
        self.resilience.record_dlq_event(incident_id, reason_code, reason, context)
        self.checkpoint.save_checkpoint(incident_id, to_state, context)

        # Conclude cost and AI trace metrics for aborted run fail-open
        try:
            metrics = self.cost_tracker.finish_incident(incident_id, outcome=terminal_outcome)
            context["metrics"] = metrics
            self.ai_tracer.end_trace(
                incident_id=incident_id,
                outcome=terminal_outcome,
                final_summary={
                    "reason_code": reason_code,
                    "abort_reason": reason,
                    "shadow_cost_usd": metrics["shadow_cost"]["estimated_unit_cost_usd"],
                },
            )
        except Exception as obs_err:
            _LOG.warning("Failed to record abort metrics for %s: %s", incident_id, obs_err)

    # --- Step Implementations ---

    def _step_received(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        # Transition to RECEIVED
        self.sm.transition(
            incident_id=incident_id,
            to_state="RECEIVED",
            idempotency_key=f"idem-{incident_id}-received",
            reason_code="OK",
            reason="Incident intake admitted",
            input_data={"incident_id": incident_id},
            output_data=context,
        )
        context["timeline"].append({"state": "RECEIVED", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "RECEIVED", context)
        return context

    def _step_correlated(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        primary_service = context["service_id"]
        ref_time = context["event_time"]

        # Call dependency correlation (C10) with max_depth=2
        try:
            impact = self.correlator.build_impact_graph(
                primary_service=primary_service,
                reference_time=ref_time,
                max_depth=2,
            )
        except Exception as e:
            _LOG.warning("Correlation fallback for %s: %s", primary_service, e)
            impact = {
                "primary_service": primary_service,
                "reference_time": ref_time,
                "max_depth": 2,
                "upstream_callers": [],
                "downstream_dependencies": [],
                "edges": [],
                "uncertainty": "Correlation fallback triggered",
            }

        # Bounded service scope: primary + upstream + downstream, max 5 services total (ADR-S05)
        raw_scope = [primary_service] + impact.get("upstream_callers", []) + impact.get("downstream_dependencies", [])
        dedup_scope: List[str] = []
        for s in raw_scope:
            if s not in dedup_scope:
                dedup_scope.append(s)
        bounded_scope = dedup_scope[:5]

        context["impact_graph"] = impact
        context["investigation_scope"] = bounded_scope

        self.sm.transition(
            incident_id=incident_id,
            to_state="CORRELATED",
            idempotency_key=f"idem-{incident_id}-correlated",
            reason_code="OK",
            reason="Dependency impact graph and investigation scope established",
            input_data={"primary_service": primary_service},
            output_data={"scope": bounded_scope},
        )
        context["timeline"].append({"state": "CORRELATED", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "CORRELATED", context)
        return context

    def _step_triaged(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        # Compute triage priority and investigation time window
        scope = context.get("investigation_scope", [context["service_id"]])
        priority = "HIGH" if len(scope) > 1 or context.get("error_code", "").startswith("ERR_5") else "MEDIUM"
        context["priority"] = priority

        # Window: reference_time - 300s to reference_time + 60s
        ref_time_str = context["event_time"]
        ref_dt = datetime.datetime.fromisoformat(ref_time_str.replace("Z", "+00:00"))
        start_dt = ref_dt - datetime.timedelta(seconds=300)
        end_dt = ref_dt + datetime.timedelta(seconds=60)
        start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        context["query_window"] = {
            "start": start_str,
            "end": end_str,
            "duration_seconds": 360.0,
        }

        self.sm.transition(
            incident_id=incident_id,
            to_state="TRIAGED",
            idempotency_key=f"idem-{incident_id}-triaged",
            reason_code="OK",
            reason=f"Triage priority set to {priority}; query window bounded to 360s",
            input_data={"scope_size": len(scope)},
            output_data={"priority": priority, "window": context["query_window"]},
        )
        context["timeline"].append({"state": "TRIAGED", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "TRIAGED", context)
        return context

    def _step_evidence_collected(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        scope = context.get("investigation_scope", [context["service_id"]])
        window = context["query_window"]
        evidence_items: List[Dict[str, Any]] = []
        seq = 1

        for svc in scope:
            # 1. Metrics query
            try:
                self.resilience.check_preflight(incident_id, "get_service_metrics")
                metrics_res = self.gateway.execute_tool(
                    tool_name="get_service_metrics",
                    arguments={
                        "service_id": svc,
                        "environment": context["environment"],
                        "metric_enum": "request_rate",
                        "start": window["start"],
                        "end": window["end"],
                        "max_points": 100,
                    },
                    token=f"Bearer {self.bearer_token}",
                    incident_id=incident_id,
                )
                self.resilience.record_tool_result("get_service_metrics", metrics_res.get("status", "ok"))
                evidence_items.append({
                    "evidence_id": f"ev-{incident_id}-{seq:03d}",
                    "tool_name": "get_service_metrics",
                    "service_id": svc,
                    "source_ref": metrics_res.get("source_ref", "prometheus"),
                    "observed_at": metrics_res.get("observed_at", utc_now_z()),
                    "data_quality": metrics_res.get("data_quality", "complete"),
                    "error_code": metrics_res.get("error_code"),
                    "data": metrics_res,
                    "records": metrics_res.get("records", []),
                    "sanitized": metrics_res.get("sanitized") is True,
                })
                seq += 1
            except CircuitOpenError:
                evidence_items.append({
                    "evidence_id": f"ev-{incident_id}-{seq:03d}",
                    "tool_name": "get_service_metrics",
                    "service_id": svc,
                    "source_ref": "circuit-breaker",
                    "observed_at": utc_now_z(),
                    "data_quality": "unavailable",
                    "error_code": "SOURCE_UNAVAILABLE",
                    "data": {},
                    "records": [],
                    "sanitized": True,
                })
                seq += 1

            # 2. Error logs query
            try:
                self.resilience.check_preflight(incident_id, "search_error_logs")
                err_code_arg = context.get("error_code")
                if not err_code_arg or err_code_arg == "ERR_UNKNOWN":
                    err_code_arg = None
                logs_res = self.gateway.execute_tool(
                    tool_name="search_error_logs",
                    arguments={
                        "service_id": svc,
                        "environment": context["environment"],
                        "start": window["start"],
                        "end": window["end"],
                        "error_code": err_code_arg,
                        "max_hits": 50,
                    },
                    token=f"Bearer {self.bearer_token}",
                    incident_id=incident_id,
                )
                self.resilience.record_tool_result("search_error_logs", logs_res.get("status", "ok"))
                evidence_items.append({
                    "evidence_id": f"ev-{incident_id}-{seq:03d}",
                    "tool_name": "search_error_logs",
                    "service_id": svc,
                    "source_ref": logs_res.get("source_ref", "loki"),
                    "observed_at": logs_res.get("observed_at", utc_now_z()),
                    "data_quality": logs_res.get("data_quality", "complete"),
                    "error_code": logs_res.get("error_code"),
                    "data": logs_res,
                    "records": logs_res.get("records", []),
                    "sanitized": logs_res.get("sanitized") is True,
                })
                seq += 1
            except CircuitOpenError:
                evidence_items.append({
                    "evidence_id": f"ev-{incident_id}-{seq:03d}",
                    "tool_name": "search_error_logs",
                    "service_id": svc,
                    "source_ref": "circuit-breaker",
                    "observed_at": utc_now_z(),
                    "data_quality": "unavailable",
                    "error_code": "SOURCE_UNAVAILABLE",
                    "data": {},
                    "records": [],
                    "sanitized": True,
                })
                seq += 1

        # 3. Traces query (for trace_id if present or default baseline trace)
        try:
            self.resilience.check_preflight(incident_id, "get_trace_summary")
            trace_id_val = context.get("trace_id")
            if not trace_id_val or len(trace_id_val) != 32:
                trace_id_val = "4bf92f3577b34da6a3ce929d0e0e4736"

            traces_res = self.gateway.execute_tool(
                tool_name="get_trace_summary",
                arguments={
                    "trace_id": trace_id_val,
                    "service_id": context["service_id"],
                    "environment": context["environment"],
                    "start": window["start"],
                    "end": window["end"],
                },
                token=f"Bearer {self.bearer_token}",
                incident_id=incident_id,
            )
            self.resilience.record_tool_result("get_trace_summary", traces_res.get("status", "ok"))
            evidence_items.append({
                "evidence_id": f"ev-{incident_id}-{seq:03d}",
                "tool_name": "get_trace_summary",
                "service_id": context["service_id"],
                "source_ref": traces_res.get("source_ref", "tempo"),
                "observed_at": traces_res.get("observed_at", utc_now_z()),
                "data_quality": traces_res.get("data_quality", "complete"),
                "error_code": traces_res.get("error_code"),
                "data": traces_res,
                "records": traces_res.get("records", []),
                "sanitized": traces_res.get("sanitized") is True,
            })
            seq += 1
        except CircuitOpenError:
            evidence_items.append({
                "evidence_id": f"ev-{incident_id}-{seq:03d}",
                "tool_name": "get_trace_summary",
                "service_id": context["service_id"],
                "source_ref": "circuit-breaker",
                "observed_at": utc_now_z(),
                "data_quality": "unavailable",
                "error_code": "SOURCE_UNAVAILABLE",
                "data": {},
                "records": [],
                "sanitized": True,
            })
            seq += 1

        # 4. Primary service error_rate (collected before retrieval & reasoning; non-fatal on open circuit)
        primary_svc = context["service_id"]
        has_primary_error_rate = any(
            ev.get("tool_name") == "get_service_metrics"
            and ev.get("service_id") == primary_svc
            and any(
                str(r.get("metric_enum") or r.get("metric_name") or "").lower()
                in ("error_rate", "sim_red_error_rate_ratio")
                for r in ev.get("records", [])
                if isinstance(r, dict)
            )
            for ev in evidence_items
        )
        if not has_primary_error_rate:
            try:
                self.resilience.check_preflight(incident_id, "get_service_metrics")
                err_metrics_res = self.gateway.execute_tool(
                    tool_name="get_service_metrics",
                    arguments={
                        "service_id": primary_svc,
                        "environment": context["environment"],
                        "metric_enum": "error_rate",
                        "start": window["start"],
                        "end": window["end"],
                        "max_points": 100,
                    },
                    token=f"Bearer {self.bearer_token}",
                    incident_id=incident_id,
                )
                self.resilience.record_tool_result("get_service_metrics", err_metrics_res.get("status", "ok"))
                evidence_items.append({
                    "evidence_id": f"ev-{incident_id}-{seq:03d}",
                    "tool_name": "get_service_metrics",
                    "service_id": primary_svc,
                    "source_ref": err_metrics_res.get("source_ref", "prometheus"),
                    "observed_at": err_metrics_res.get("observed_at", utc_now_z()),
                    "data_quality": err_metrics_res.get("data_quality", "complete"),
                    "error_code": err_metrics_res.get("error_code"),
                    "data": err_metrics_res,
                    "records": err_metrics_res.get("records", []),
                    "sanitized": err_metrics_res.get("sanitized") is True,
                })
                seq += 1
            except CircuitOpenError:
                context.setdefault("unknowns", []).append("Error-rate metrics source unavailable.")

        context["evidence_items"] = evidence_items

        self.sm.transition(
            incident_id=incident_id,
            to_state="EVIDENCE_COLLECTED",
            idempotency_key=f"idem-{incident_id}-evidence",
            reason_code="OK",
            reason=f"Collected {len(evidence_items)} evidence artifacts across bounded scope",
            input_data={"scope": scope},
            output_data={"evidence_count": len(evidence_items)},
        )
        context["timeline"].append({"state": "EVIDENCE_COLLECTED", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "EVIDENCE_COLLECTED", context)
        return context

    def _assess_runbooks(self, incident_id: str, context: dict) -> tuple[str, list[dict]]:
        query = self._retrieval_query_text(context)
        if (not context.get("has_match_context", True) or len(query) < 3
                or not all(context.get(k) for k in ("service_id", "environment", "event_time"))):
            return "INSUFFICIENT_MATCH_CONTEXT", []
        primary_service = context["service_id"]
        try:
            self.resilience.check_preflight(incident_id, "retrieve_runbooks")
            retrieval_res = self.gateway.execute_tool(
                tool_name="retrieve_runbooks",
                arguments={
                    "service_id": primary_service,
                    "environment": context["environment"],
                    "query_text": query,
                    "reference_time": context["event_time"],
                    "retrieval_mode": "hybrid_rrf",
                    "top_k": 3,
                    "max_context_tokens": 1024,
                    "index_version_policy": "kb_active_alias",
                },
                token=f"Bearer {self.bearer_token}",
                incident_id=incident_id,
            )
            status = retrieval_res.get("status")
            self.resilience.record_tool_result("retrieve_runbooks", "ok" if status == "no_match" else status or "unavailable")
            if status in ("ok", "no_match"):
                candidates = sanitized_citations(retrieval_res)
                filters = retrieval_res["applied_filters"]
                principal = self.gateway.authenticator.authenticate(self.bearer_token, incident_id).principal_id
                if (not retrieval_res["index_version"] or filters["caller_scope_ref"] != principal
                        or filters["service_id"] != primary_service or filters["environment"] != context["environment"]
                        or filters["reference_time"] != context["event_time"]
                        or retrieval_res["retrieval_mode_executed"] != "hybrid_rrf"):
                    return "RETRIEVAL_UNAVAILABLE", []
                context["version_manifest"]["kb_version"] = retrieval_res["index_version"]
                if status == "no_match" and not candidates and retrieval_res["gap_reason"] == "NO_APPLICABLE_RUNBOOK":
                    return "NO_APPLICABLE_RUNBOOK", []
                if status == "ok" and candidates and retrieval_res.get("gap_reason") is None:
                    unique = {}
                    for candidate in candidates:
                        previous = unique.setdefault(candidate["chunk_id"], candidate)
                        if previous != candidate:
                            return "RETRIEVAL_UNAVAILABLE", []
                    citations, _, sop_reasons = self.claim_validator.validate_sop_citations(
                        list(unique.values()), primary_service, context["environment"], context["event_time"]
                    )
                    if citations:
                        docs = {(c["document_id"], c["document_version"]) for c in citations}
                        return ("CONFLICTING_OR_COMPETING_SOPS" if len(docs) > 1 else "APPLICABLE_SOP_FOUND"), citations
                    allowed_filter_reasons = {
                        "OBSOLETE_SOP",
                        "SCOPE_MISMATCH",
                        "OUT_OF_WINDOW",
                        "MISSING_EVIDENCE_REF",
                        "VALUE_MISMATCH",
                    }
                    context["sop_filter_reasons"] = [
                        r for r in dict.fromkeys(sop_reasons) if r in allowed_filter_reasons
                    ]
                    return "SOP_FILTERED_OUT", []
            if status == "rejected":
                return "RETRIEVAL_REJECTED", []
        except (DeadlineExceededError, BudgetExhaustedError, IncidentCancelledError):
            raise
        except Exception:
            _LOG.warning("Runbook retrieval unavailable for incident %s", incident_id)
        return "RETRIEVAL_UNAVAILABLE", []

    def _step_retrieved(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)
        availability, citations = self._assess_runbooks(incident_id, context)

        sop_relevance = assess_sop_diagnostic_relevance(citations, context)

        context["runbook_citations"] = citations
        context["sop_availability"] = availability
        context["sop_relevance"] = sop_relevance
        context["no_applicable_runbook"] = availability in ("NO_APPLICABLE_RUNBOOK", "SOP_FILTERED_OUT")
        context["retrieval_diagnostics"] = {
            "query_text": self._retrieval_query_text(context),
            "retrieved_count": len(citations),
            "retrieved_doc_ids": [
                f"{c.get('document_id')}@{c.get('document_version')}"
                for c in citations
                if c.get("document_id")
            ],
            "sop_availability": availability,
            "relevance_status": sop_relevance.get("status"),
            "multi_sop_relation": sop_relevance.get("multi_sop_relation"),
            "specific_coverage_gap": bool(sop_relevance.get("specific_coverage_gap")),
        }
        if sop_relevance.get("specific_coverage_gap"):
            codes_str = ", ".join(sop_relevance.get("incident_error_codes") or []) or "observed error"
            doc_str = ", ".join(
                f"{c.get('document_id')} v{c.get('document_version')}"
                for c in citations
                if c.get("document_id")
            )
            gap_msg = (
                f"Retrieved {context['service_id']} runbook(s) ({doc_str}) provide general/adjacent guidance only "
                f"and do not specifically cover {codes_str} (no exact SOP match for {context['service_id']})."
            )
            unknowns = list(context.get("unknowns", []))
            if gap_msg not in unknowns:
                unknowns.append(gap_msg)
            context["unknowns"] = unknowns

        self.sm.transition(
            incident_id=incident_id,
            to_state="RETRIEVED",
            idempotency_key=f"idem-{incident_id}-retrieved",
            reason_code="OK",
            reason=f"Runbook assessment: {availability} ({len(citations)} citations)",
            input_data={"service_id": context["service_id"], "error_code": context.get("error_code")},
            output_data={"citations_count": len(context["runbook_citations"])},
        )
        context["timeline"].append({"state": "RETRIEVED", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "RETRIEVED", context)
        return context

    def _step_hypotheses(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Baseline Deterministic Rule Engine synthesizing candidate hypotheses from actual evidence (FR-AGT-007)."""
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        evidence_items = context.get("evidence_items", [])
        primary_service = context["service_id"]
        error_code = context.get("error_code", "ERR_UNKNOWN")

        # Inspect collected evidence items
        observed_errors: List[Dict[str, Any]] = []
        metrics_points: List[Dict[str, Any]] = []
        trace_spans: List[Dict[str, Any]] = []

        for ev in evidence_items:
            tname = ev.get("tool_name")
            data = ev.get("data", {})
            records = ev.get("records", data.get("records", []) if isinstance(data, dict) else [])

            if tname == "search_error_logs" and records:
                observed_errors.extend(records)
            elif tname == "get_service_metrics" and records:
                metrics_points.extend(records)
            elif tname == "get_trace_summary" and records:
                trace_spans.extend(records)

        hypotheses: List[Dict[str, Any]] = []

        # Rule 1: Correlate error logs with primary or downstream services
        if observed_errors:
            err_services = {err.get("service_id", primary_service) for err in observed_errors}
            first_err = observed_errors[0]
            err_msg = first_err.get("message", "Service operational error")

            supporting_ids = [
                ev["evidence_id"] for ev in evidence_items if ev.get("tool_name") == "search_error_logs" and ev.get("records")
            ]

            if len(err_services) > 1 and primary_service in err_services:
                downstream = sorted(s for s in err_services if s != primary_service)[0]
                hypotheses.append({
                    "hypothesis_id": f"hyp-{incident_id}-001",
                    "title": f"Cascading failure from {downstream} propagating error to {primary_service}",
                    "description": f"Downstream dependency {downstream} logged errors ('{err_msg}'), leading to upstream failure in {primary_service}.",
                    "candidate_cause": f"{downstream}_dependency_error",
                    "supporting_evidence_ids": supporting_ids,
                    "refuting_evidence_ids": [],
                    "confidence_score": 0.85,
                    "status": "PROPOSED",
                })
            else:
                hypotheses.append({
                    "hypothesis_id": f"hyp-{incident_id}-001",
                    "title": f"Service operational error in {primary_service} ({error_code})",
                    "description": f"Error logs indicate failure: '{err_msg}'.",
                    "candidate_cause": f"{primary_service}_runtime_error",
                    "supporting_evidence_ids": supporting_ids,
                    "refuting_evidence_ids": [],
                    "confidence_score": 0.80,
                    "status": "PROPOSED",
                })

        # Rule 2: Correlate trace spans if span errors exist
        span_errors = [s for s in trace_spans if str(s.get("status_code", "")).upper() in ("ERROR", "500", "504")]
        if span_errors:
            supporting_trace_ids = [
                ev["evidence_id"] for ev in evidence_items if ev.get("tool_name") == "get_trace_summary"
            ]
            hypotheses.append({
                "hypothesis_id": f"hyp-{incident_id}-002",
                "title": f"High latency / error span observed on {primary_service}",
                "description": f"Distributed trace captured span '{span_errors[0].get('operation', 'operation')}' with error status.",
                "candidate_cause": "span_execution_error",
                "supporting_evidence_ids": supporting_trace_ids,
                "refuting_evidence_ids": [],
                "confidence_score": 0.75,
                "status": "PROPOSED",
            })

        # Fallback hypothesis if no specific evidence found
        if not hypotheses:
            hypotheses.append({
                "hypothesis_id": f"hyp-{incident_id}-001",
                "title": f"Transient or unobserved anomaly on {primary_service}",
                "description": "No definitive error patterns or metric anomalies captured in observation window.",
                "candidate_cause": "unobserved_transient_failure",
                "supporting_evidence_ids": [],
                "refuting_evidence_ids": [],
                "confidence_score": 0.30,
                "status": "PROPOSED",
            })

        context["hypotheses"] = hypotheses
        if self.llm:
            llm_context = self._compact_llm_context(context)
            result = self.llm.generate(llm_context, self.resilience)
            context["llm_result"] = result
            usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
            manifest_info = result.get("manifest") if isinstance(result.get("manifest"), dict) else {}
            in_tok = usage.get("input_tokens") if usage.get("input_tokens") is not None else usage.get("input_reported")
            out_tok = usage.get("output_tokens") if usage.get("output_tokens") is not None else usage.get("output_reported")
            tot_tok = usage.get("total_tokens")
            if tot_tok is None and in_tok is not None and out_tok is not None:
                tot_tok = in_tok + out_tok
            context["version_manifest"] = {
                **context["version_manifest"],
                "provider": manifest_info.get("provider"),
                "model_name": manifest_info.get("model_name"),
                "model_version": manifest_info.get("version", "unknown"),
                "prompt_version": manifest_info.get("prompt_sha256", "unknown"),
                "llm_status": result.get("status"),
                "llm_reason": result.get("reason_code"),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": tot_tok,
            }
            ctx_diag = dict(context.get("llm_context_diagnostics") or {})
            if isinstance(result.get("context_diagnostics"), dict):
                ctx_diag.update(result["context_diagnostics"])
            ctx_diag["provider_status"] = result.get("status")
            ctx_diag["provider_reason_code"] = result.get("reason_code")
            if result["status"] == "accepted":
                candidates = result["candidates"]
                primary = {**candidates["primary_hypothesis"],
                           "supporting_evidence_ids": candidates["supporting_evidence_ids"],
                           "contradicting_evidence_ids": candidates["contradicting_evidence_ids"]}
                context["hypotheses"] = [
                    {
                        "hypothesis_id": f"hyp-{incident_id}-{index:03d}",
                        "title": hypothesis["summary"],
                        "description": (
                            f"Mechanism / Why: {hypothesis['diagnosis']} | "
                            f"Candidate Root Cause (unconfirmed): {hypothesis['estimated_root_cause']}"
                        ),
                        "candidate_cause": hypothesis["estimated_root_cause"],
                        "diagnosis": hypothesis["diagnosis"],
                        "confidence": hypothesis["confidence"],
                        "llm_proposed_confidence": hypothesis["confidence"],
                        "confidence_score": {"HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.2}[hypothesis["confidence"]],
                        "status": "PARTIAL",
                        "supporting_evidence_ids": hypothesis["supporting_evidence_ids"],
                        "refuting_evidence_ids": hypothesis["contradicting_evidence_ids"],
                        "unknowns": candidates["unknowns"],
                    }
                    for index, hypothesis in enumerate(
                        [primary, *candidates["alternative_hypotheses"]], start=1
                    )
                ]
                context["unknowns"] = list(dict.fromkeys([*context.get("unknowns", []), *candidates["unknowns"]]))
                context["investigation_mode"] = "agentic_llm"
                ctx_diag["hypothesis_generation_path"] = "llm_accepted"
            else:
                context["investigation_mode"] = "manual_fallback"
                context["unknowns"] = list(dict.fromkeys([
                    *context.get("unknowns", []),
                    f"LLM synthesis unavailable ({result['reason_code']}); C11 evidence baseline requires human triage.",
                ]))
                context["review_summary"] = {
                    "status": "MANUAL_TRIAGE", "latest_review_event_id": None,
                    "reviewed_by": None, "reviewed_at": None,
                }
                ctx_diag["hypothesis_generation_path"] = "manual_fallback"
            context["llm_context_diagnostics"] = ctx_diag

        self.sm.transition(
            incident_id=incident_id,
            to_state="HYPOTHESES",
            idempotency_key=f"idem-{incident_id}-hypotheses",
            reason_code="OK",
            reason=f"Formulated {len(context['hypotheses'])} candidates ({context.get('investigation_mode', 'deterministic_baseline')})",
            input_data={"evidence_count": len(evidence_items)},
            output_data={"hypotheses_count": len(context["hypotheses"])},
        )
        context["timeline"].append({"state": "HYPOTHESES", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "HYPOTHESES", context)
        return context

    def _compact_llm_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Compact evidence and citations so SanitizedContextBuilder stays within max_input_tokens."""
        primary_svc = context["service_id"]
        all_ev = context.get("evidence_items", [])

        def _ev_priority(ev: Dict[str, Any]) -> tuple[int, int, str]:
            has_recs = bool(ev.get("records"))
            tname = str(ev.get("tool_name") or "")
            is_primary = ev.get("service_id") == primary_svc
            if is_primary and tname == "search_error_logs" and has_recs:
                tier = 0
            elif is_primary and tname == "get_service_metrics" and has_recs:
                m_names = {
                    str(r.get("metric_enum") or r.get("metric_name") or "").lower()
                    for r in ev.get("records", [])
                    if isinstance(r, dict)
                }
                tier = 1 if ("error_rate" in m_names or "sim_red_error_rate_ratio" in m_names) else 2
            elif not is_primary and tname == "search_error_logs" and has_recs:
                tier = 3
            elif is_primary and tname == "get_trace_summary" and has_recs:
                tier = 4
            elif has_recs:
                tier = 5
            elif ev.get("data_quality") == "unavailable" or ev.get("error_code"):
                tier = 6
            else:
                tier = 7
            return (tier, 0 if is_primary else 1, str(ev.get("evidence_id") or ""))

        ordered_ev = sorted(all_ev, key=_ev_priority)
        pool_ev = ordered_ev[:4]

        raw_citations = [c for c in context.get("runbook_citations", []) if isinstance(c, dict)]
        rel_map: dict[str, str] = {}
        sop_rel = context.get("sop_relevance")
        if isinstance(sop_rel, dict):
            for entry in sop_rel.get("citations", []):
                if isinstance(entry, dict) and entry.get("chunk_id") and entry.get("relevance_class"):
                    rel_map[str(entry["chunk_id"])] = str(entry["relevance_class"])
        rel_order = {
            "EXACT_ERROR_CODE_MATCH": 0,
            "MECHANISM_MATCH": 1,
            "GENERAL_SERVICE_GUIDANCE": 2,
            "ADJACENT_MECHANISM_MISMATCH": 3,
        }
        ordered_citations = sorted(
            raw_citations,
            key=lambda c: (
                rel_order.get(rel_map.get(str(c.get("chunk_id") or ""), ""), 2),
                str(c.get("chunk_id") or ""),
            ),
        )

        keep_rec_keys = {
            "metric_name", "metric_enum", "value", "unit",
            "severity", "error_code", "message",
            "span_id", "duration_ms", "operation", "status_code", "error",
            "service_name",
        }

        def _shrink_record(rec: Any, ev_svc: Any) -> Any:
            if not isinstance(rec, dict):
                return rec
            out = {k: v for k, v in rec.items() if k in keep_rec_keys}
            if "service_id" in rec and rec["service_id"] != ev_svc:
                out["service_id"] = rec["service_id"]
            if "environment" in rec and rec["environment"] != context.get("environment"):
                out["environment"] = rec["environment"]
            if isinstance(out.get("message"), str) and len(out["message"]) > 140:
                out["message"] = out["message"][:137] + "..."
            return out

        def _build_candidate(max_ev: int, max_recs: int, max_cites: int, excerpt_len: int) -> Dict[str, Any]:
            compact_ev = []
            for ev in pool_ev[:max_ev]:
                ev_svc = ev.get("service_id")
                recs = [_shrink_record(r, ev_svc) for r in ev.get("records", [])[:max_recs]]
                data_obj = ev.get("data")
                compact_item = {**ev, "records": recs}
                if isinstance(data_obj, dict):
                    shrunk_data = {
                        k: data_obj[k]
                        for k in ("status", "data_quality", "error_code", "sanitized")
                        if k in data_obj
                    }
                    if "records" in data_obj:
                        shrunk_data["records"] = recs
                    compact_item["data"] = shrunk_data
                compact_ev.append(compact_item)
            compact_cites = []
            for cite in ordered_citations[:max_cites]:
                c = dict(cite)
                if isinstance(c.get("sanitized_excerpt"), str) and len(c["sanitized_excerpt"]) > excerpt_len:
                    c["sanitized_excerpt"] = c["sanitized_excerpt"][: max(3, excerpt_len) - 3] + "..."
                compact_cites.append(c)
            llm_scope = list(dict.fromkeys([primary_svc, *(e.get("service_id", primary_svc) for e in compact_ev)]))
            return {
                **context,
                "investigation_scope": llm_scope,
                "evidence_items": compact_ev,
                "runbook_citations": compact_cites,
            }

        max_tokens = getattr(getattr(self.llm, "limits", None), "max_input_tokens", 4096)
        chosen: Dict[str, Any] | None = None
        chosen_rung = "fallback_1_1_0_0"
        builder = None
        try:
            from orchestrator.context_builder import SanitizedContextBuilder
            from orchestrator.llm_investigator import HYPOTHESIS_SCHEMA
            builder = SanitizedContextBuilder()
        except Exception:
            builder = None

        ladder = (
            (4, 1, 2, 240),
            (4, 1, 2, 160),
            (3, 1, 2, 160),
            (3, 1, 2, 120),
            (3, 1, 1, 140),
            (2, 1, 2, 120),
            (2, 1, 1, 100),
            (2, 1, 1, 80),
            (3, 1, 0, 0),
            (2, 1, 0, 0),
            (1, 1, 0, 0),
        )
        if builder is None:
            chosen = _build_candidate(3, 1, 1, 160)
            chosen_rung = "no_builder_3_1_1_160"
        else:
            for max_ev, max_recs, max_cites, excerpt_len in ladder:
                candidate = _build_candidate(max_ev, max_recs, max_cites, excerpt_len)
                rung_name = f"{max_ev}_{max_recs}_{max_cites}_{excerpt_len}"
                try:
                    prepared = builder.build(candidate, HYPOTHESIS_SCHEMA)
                    if prepared.input_tokens_upper_bound <= max_tokens:
                        chosen = candidate
                        chosen_rung = rung_name
                        break
                except Exception:
                    chosen = candidate
                    chosen_rung = f"error_{rung_name}"
                    break
            if chosen is None:
                chosen = _build_candidate(1, 1, 0, 0)
                chosen_rung = "exhausted_1_1_0_0"

        context["llm_context_diagnostics"] = {
            "retrieved_citations_count": len(raw_citations),
            "selected_citations_count": len(chosen.get("runbook_citations", [])),
            "selected_citation_chunk_ids": [
                c.get("chunk_id") for c in chosen.get("runbook_citations", []) if c.get("chunk_id")
            ],
            "selected_evidence_ids": [
                e.get("evidence_id") for e in chosen.get("evidence_items", []) if e.get("evidence_id")
            ],
            "compaction_rung": chosen_rung,
            "budget_truncated_citations": len(chosen.get("runbook_citations", [])) < len(raw_citations),
            "budget_dropped_all_citations": bool(raw_citations) and not chosen.get("runbook_citations"),
            "max_input_tokens_budget": max_tokens,
        }
        return chosen

    def _step_validated(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate hypotheses with honest uncertainty checking (EV-01, EV-02, RULE-006)."""
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        evidence_items = context.get("evidence_items", [])
        if context.get("investigation_mode") == "agentic_llm":
            window = context["query_window"]
            svc = context["service_id"]
            already_has_error_rate = any(
                ev.get("tool_name") == "get_service_metrics"
                and ev.get("service_id") == svc
                and any(
                    str(r.get("metric_enum") or r.get("metric_name") or "").lower()
                    in ("error_rate", "sim_red_error_rate_ratio")
                    for r in ev.get("records", [])
                    if isinstance(r, dict)
                )
                for ev in evidence_items
            )
            if not already_has_error_rate:
                try:
                    self.resilience.check_preflight(incident_id, "get_service_metrics")
                    result = self.gateway.execute_tool(
                        tool_name="get_service_metrics",
                        arguments={"service_id": svc, "environment": context["environment"],
                                   "metric_enum": "error_rate", "start": window["start"],
                                   "end": window["end"], "max_points": 100},
                        token=f"Bearer {self.bearer_token}", incident_id=incident_id,
                    )
                    self.resilience.record_tool_result("get_service_metrics", result.get("status", "ok"))
                    evidence_items.append({
                        "evidence_id": f"ev-{incident_id}-{len(evidence_items) + 1:03d}",
                        "tool_name": "get_service_metrics", "service_id": svc,
                        "source_ref": result.get("source_ref", "prometheus"),
                        "observed_at": result.get("observed_at", utc_now_z()),
                        "data_quality": result.get("data_quality", "complete"),
                        "error_code": result.get("error_code"), "data": result,
                        "records": result.get("records", []), "sanitized": result.get("sanitized") is True,
                    })
                except CircuitOpenError:
                    context.setdefault("unknowns", []).append("Error-rate metrics source unavailable.")
        if context.get("investigation_mode") == "agentic_llm":
            return self._validate_agentic(incident_id, context)

        hypotheses = context.get("hypotheses", [])
        contradictions: List[str] = []
        unknowns: List[str] = list(context.get("unknowns", []))

        # 1. Honest Uncertainty Check: Trace Outage / Missing Trace (EV-02, SC-09)
        trace_ev = [ev for ev in evidence_items if ev.get("tool_name") == "get_trace_summary"]
        trace_outage = any(
            ev.get("data_quality") == "unavailable" or ev.get("error_code") in ("SOURCE_UNAVAILABLE", "TIMEOUT")
            for ev in trace_ev
        )
        if trace_outage or not trace_ev:
            unknowns.append(
                "Distributed trace backend is unavailable or traces are missing; causality across microservice hops cannot be proven (EV-02)."
            )

        # 2. Honest Uncertainty Check: Metrics vs Logs Contradiction (EV-01)
        log_errors = [
            ev for ev in evidence_items
            if ev.get("tool_name") == "search_error_logs" and ev.get("records")
        ]
        metrics_ev = [
            ev for ev in evidence_items
            if ev.get("tool_name") == "get_service_metrics" and ev.get("records")
        ]

        # Contradiction pattern: Log errors exist but metrics report 0 errors or normal throughput
        # Or metrics indicate heavy degradation but log search yields 0 hits
        if log_errors and not metrics_ev:
            contradictions.append(
                "Discrepancy detected: Error logs capture active exceptions, but metrics query returned no telemetry points (EV-01)."
            )

        # 3. Assign validated status and evidence-aware confidence to hypotheses
        is_manual_fb = context.get("investigation_mode") == "manual_fallback"
        for hyp in hypotheses:
            sup_ids = list(hyp.get("supporting_evidence_ids", []))
            ref_ids = list(hyp.get("refuting_evidence_ids", []))
            if is_manual_fb:
                hyp["status"] = "INCONCLUSIVE"
            elif trace_outage:
                hyp["status"] = "INCONCLUSIVE"
            elif contradictions:
                hyp["status"] = "PARTIAL"
            elif not sup_ids:
                hyp["status"] = "INCONCLUSIVE"
            else:
                hyp["status"] = "SUPPORTED"

            assessment = compute_evidence_confidence(
                status=hyp["status"],
                supporting_evidence_ids=sup_ids,
                contradicting_evidence_ids=ref_ids,
                evidence_items=evidence_items,
                contradictions=contradictions,
                unknowns=unknowns,
                trace_outage=trace_outage,
                manual_fallback=is_manual_fb,
            )
            hyp["confidence_score"] = assessment.score
            hyp["confidence"] = assessment.label
            hyp["confidence_breakdown"] = assessment.breakdown
            hyp["confidence_rationale"] = assessment.rationale

        hypotheses = rank_hypotheses(hypotheses)
        context["contradictions"] = contradictions
        context["unknowns"] = list(dict.fromkeys(unknowns))
        context["hypotheses"] = hypotheses

        self.sm.transition(
            incident_id=incident_id,
            to_state="VALIDATED",
            idempotency_key=f"idem-{incident_id}-validated",
            reason_code="OK",
            reason=f"Validated hypotheses (status: {[h['status'] for h in hypotheses]}, contradictions: {len(contradictions)}, unknowns: {len(unknowns)})",
            input_data={"hypotheses_count": len(hypotheses)},
            output_data={
                "contradictions_count": len(contradictions),
                "unknowns_count": len(unknowns),
            },
        )
        context["timeline"].append({"state": "VALIDATED", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "VALIDATED", context)
        return context

    def _validate_agentic(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        hypotheses = context.get("hypotheses", [])
        citations = context.get("runbook_citations", [])
        reports = []
        try:
            for hypothesis in hypotheses:
                candidate = {
                    **hypothesis,
                    "contradicting_evidence_ids": hypothesis.get("refuting_evidence_ids", []),
                }
                report = self.claim_validator.validate_hypothesis(candidate, context)
                if report.hypothesis_id != hypothesis["hypothesis_id"]:
                    raise ValueError("Validation report hypothesis ID mismatch")
                reports.append(asdict(report))

            # A citation must survive every report; validation failures must not leak it.
            valid_citations = [
                citation for citation in citations
                if reports and all(citation in report["valid_sop_citations"] for report in reports)
            ]
            usable_ids = {
                ev["evidence_id"] for ev in context.get("evidence_items", [])
                if ev.get("evidence_id") and ev.get("records")
                and ev.get("data_quality") != "unavailable"
                and not ev.get("error_code")
            }
            for hypothesis, report in zip(hypotheses, reports):
                status = HypothesisStatus(report["status"])
                # The validator cannot promote an unconfirmed LLM diagnosis to a verified/proven finding.
                checked_ids = {
                    claim["evidence_id"] for claim in report["claims"]
                    if claim["status"] == HypothesisStatus.SUPPORTED
                }
                supporting_ids = [
                    evidence_id for evidence_id in report["supporting_evidence_ids"]
                    if evidence_id in usable_ids and evidence_id in checked_ids
                ]
                if not supporting_ids and status not in (
                    HypothesisStatus.UNSUPPORTED,
                    HypothesisStatus.CONTRADICTED,
                ):
                    status = HypothesisStatus.INCONCLUSIVE
                elif status == HypothesisStatus.SUPPORTED:
                    status = HypothesisStatus.PARTIAL
                hypothesis["status"] = status.value
                raw_report_status = report["status"]
                validation_status = (
                    raw_report_status.value
                    if hasattr(raw_report_status, "value")
                    else str(raw_report_status)
                )
                hypothesis["validation_status"] = validation_status
                hypothesis["validation_reason_codes"] = list(report.get("reason_codes", []))
                hypothesis["llm_proposed_confidence"] = (
                    hypothesis.get("llm_proposed_confidence") or hypothesis.get("confidence")
                )
                if supporting_ids == report["supporting_evidence_ids"] and report.get("confidence_breakdown"):
                    validated_score = float(report["confidence_score"])
                    breakdown = dict(report["confidence_breakdown"])
                    validated_label = str(
                        report.get("confidence_label") or confidence_label_for_score(validated_score)
                    )
                else:
                    recomputed = compute_evidence_confidence(
                        status=validation_status,
                        supporting_evidence_ids=supporting_ids,
                        contradicting_evidence_ids=report["contradicting_evidence_ids"],
                        evidence_items=context.get("evidence_items", []),
                        claims=report.get("claims", []),
                        contradictions=report.get("contradictions", []),
                        unknowns=report.get("unknowns", []),
                        reason_codes=report.get("reason_codes", []),
                        llm_proposed_confidence=str(hypothesis.get("llm_proposed_confidence") or ""),
                        trace_outage=("SOURCE_UNAVAILABLE" in report.get("reason_codes", [])),
                        has_forbidden_verified=("VERIFIED_STATUS_FORBIDDEN" in report.get("reason_codes", [])),
                    )
                    validated_score = recomputed.score
                    validated_label = recomputed.label
                    breakdown = {
                        **recomputed.breakdown,
                        "rationale": recomputed.rationale,
                        "score_semantics": recomputed.score_semantics,
                        "is_calibrated_probability": recomputed.is_calibrated_probability,
                    }
                hypothesis["confidence_score"] = validated_score
                hypothesis["confidence"] = validated_label
                hypothesis["confidence_breakdown"] = breakdown
                if breakdown.get("rationale"):
                    hypothesis["confidence_rationale"] = str(breakdown["rationale"])
                hypothesis["supporting_evidence_ids"] = supporting_ids
                hypothesis["refuting_evidence_ids"] = report["contradicting_evidence_ids"]
                hypothesis["unknowns"] = list(dict.fromkeys(
                    [*hypothesis.get("unknowns", []), *report["unknowns"]]
                ))
            hypotheses = rank_hypotheses(hypotheses)
            context["hypotheses"] = hypotheses
            report_by_id = {r["hypothesis_id"]: r for r in reports}
            context["validation_reports"] = [
                report_by_id[h["hypothesis_id"]] for h in hypotheses if h["hypothesis_id"] in report_by_id
            ]
            context["runbook_citations"] = valid_citations
            if citations and not valid_citations:
                allowed_filter_reasons = {
                    "OBSOLETE_SOP",
                    "SCOPE_MISMATCH",
                    "OUT_OF_WINDOW",
                    "MISSING_EVIDENCE_REF",
                    "VALUE_MISMATCH",
                }
                context["sop_filter_reasons"] = list(dict.fromkeys(
                    r for report in reports for r in report.get("reason_codes", []) if r in allowed_filter_reasons
                ))
                context["sop_availability"] = "SOP_FILTERED_OUT"
                context["no_applicable_runbook"] = True
            elif valid_citations:
                docs = {(c["document_id"], c["document_version"]) for c in valid_citations}
                context["sop_availability"] = (
                    "CONFLICTING_OR_COMPETING_SOPS" if len(docs) > 1 else "APPLICABLE_SOP_FOUND"
                )
            context["contradictions"] = list(dict.fromkeys([
                *context.get("contradictions", []),
                *(item for report in reports for item in report["contradictions"]),
            ]))
            context["unknowns"] = list(dict.fromkeys([
                *context.get("unknowns", []),
                *(item for report in reports for item in report["unknowns"]),
            ]))
        except Exception:
            context["runbook_citations"] = []
            context["sop_availability"] = "RETRIEVAL_UNAVAILABLE"
            context["no_applicable_runbook"] = False
            for hypothesis in hypotheses:
                hypothesis["status"] = "INCONCLUSIVE"
                hypothesis["confidence_score"] = min(hypothesis.get("confidence_score", 0.5), 0.30)
                hypothesis["confidence"] = confidence_label_for_score(hypothesis["confidence_score"])
            raise

        self.sm.transition(
            incident_id=incident_id,
            to_state="VALIDATED",
            idempotency_key=f"idem-{incident_id}-validated",
            reason_code="OK",
            reason=f"Validated {len(reports)} candidate hypotheses",
            input_data={"hypotheses_count": len(hypotheses)},
            output_data={
                "contradictions_count": len(context["contradictions"]),
                "unknowns_count": len(context["unknowns"]),
            },
        )
        context["timeline"].append({"state": "VALIDATED", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "VALIDATED", context)
        return context

    def _step_drafted(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Compile baseline Draft Handover Dossier structure (C11, C12 handover)."""
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        # Compile standard contract-compliant dossier via DossierSerializer & MarkdownRenderer
        dossier_json = DossierSerializer.serialize(
            context, revision=1, investigation_mode=context.get("investigation_mode", "deterministic_baseline")
        )
        validation_summary = DossierSerializer.serialize_validation_summary(context)
        context["validation_summary"] = validation_summary
        dossier_markdown = DossierMarkdownRenderer.render(dossier_json, validation_summary)

        # Persist dossier to SQLite store
        self.sm.store.save_dossier(
            incident_id=incident_id,
            dossier_version=1,
            dossier_hash=dossier_json["dossier_hash"],
            dossier_json=dossier_json,
            dossier_markdown=dossier_markdown,
        )

        context["dossier"] = dossier_json
        context["dossier_markdown"] = dossier_markdown
        context["dossier_hash"] = dossier_json["dossier_hash"]

        self.sm.transition(
            incident_id=incident_id,
            to_state="DRAFTED",
            idempotency_key=f"idem-{incident_id}-drafted",
            reason_code="OK",
            reason=f"Drafted baseline investigation dossier v1 (hash: {dossier_json['dossier_hash'][:16]}...)",
            input_data={"incident_id": incident_id},
            output_data={"dossier_hash": dossier_json["dossier_hash"]},
        )
        context["timeline"].append({"state": "DRAFTED", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "DRAFTED", context)
        return context

    def _step_human_review(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Transition to HUMAN_REVIEW, checkpointing final state awaiting human review (HUM-01)."""
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        self.sm.transition(
            incident_id=incident_id,
            to_state="HUMAN_REVIEW",
            idempotency_key=f"idem-{incident_id}-human-review",
            reason_code="OK",
            reason="Investigation completed; dossier handed over for human engineering review",
            input_data={"dossier_id": context.get("dossier", {}).get("dossier_id")},
            output_data={"status": "AWAITING_HUMAN_REVIEW"},
        )
        context["timeline"].append({"state": "HUMAN_REVIEW", "timestamp": utc_now_z()})
        context["status"] = "HUMAN_REVIEW"
        self.checkpoint.save_checkpoint(incident_id, "HUMAN_REVIEW", context)
        if self.pending_review_notifier is not None:
            try:
                self.pending_review_notifier(context["dossier"])
            except Exception as exc:
                _LOG.warning(
                    "Passive pending-review notification failed for %s: %s",
                    incident_id,
                    exc,
                )
        _LOG.info("Investigation for %s successfully reached HUMAN_REVIEW", incident_id)
        return context
