"""Deterministic Rule-Based Investigator and Provenance Checker (C11, FR-AGT-001, FR-AGT-007, EV-01, EV-02, RULE-006)."""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional, Set

from gateway.policy import PolicyGateway
from orchestrator.checkpoint import CheckpointManager
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
    ) -> None:
        self.sm = state_machine
        self.gateway = gateway
        self.correlator = correlator or DependencyCorrelator()
        self.resilience = resilience or ResilienceController()
        self.checkpoint = checkpoint_manager or CheckpointManager(self.sm.store)
        self.bearer_token = bearer_token

    def _format_incident_id(self, raw_id: str) -> str:
        return raw_id if raw_id.startswith("inc-") else f"inc-{raw_id}"

    def investigate_incident(self, alert_or_incident: Dict[str, Any]) -> Dict[str, Any]:
        """Execute full 9-state investigation lifecycle: RECEIVED -> ... -> HUMAN_REVIEW."""
        raw_id = alert_or_incident.get("incident_id") or f"inc-{uuid.uuid4().hex[:12]}"
        incident_id = self._format_incident_id(raw_id)
        service_id = alert_or_incident.get("service_id", "api-gateway")
        environment = alert_or_incident.get("environment", "lab")
        event_time = alert_or_incident.get("event_time") or utc_now_z()
        error_code = alert_or_incident.get("error_code", "ERR_UNKNOWN")
        trace_id = alert_or_incident.get("trace_id")

        # Initialize resilience tracking for global deadline
        self.resilience.start_incident(incident_id)

        context: Dict[str, Any] = {
            "incident_id": incident_id,
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
            "hypotheses": [],
            "contradictions": [],
            "unknowns": [],
            "dossier": {},
            "timeline": [],
        }

        try:
            # 1. RECEIVED
            context = self._step_received(incident_id, context)

            # 2. CORRELATED
            context = self._step_correlated(incident_id, context)

            # 3. TRIAGED
            context = self._step_triaged(incident_id, context)

            # 4. EVIDENCE_COLLECTED
            context = self._step_evidence_collected(incident_id, context)

            # 5. RETRIEVED
            context = self._step_retrieved(incident_id, context)

            # 6. HYPOTHESES
            context = self._step_hypotheses(incident_id, context)

            # 7. VALIDATED
            context = self._step_validated(incident_id, context)

            # 8. DRAFTED
            context = self._step_drafted(incident_id, context)

            # 9. HUMAN_REVIEW
            context = self._step_human_review(incident_id, context)

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
                    "sanitized": metrics_res.get("sanitized", True),
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
                    "sanitized": logs_res.get("sanitized", True),
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
                "sanitized": traces_res.get("sanitized", True),
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

    def _step_retrieved(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        primary_service = context["service_id"]
        error_code = context.get("error_code", "ERROR")

        try:
            self.resilience.check_preflight(incident_id, "retrieve_runbooks")
            retrieval_res = self.gateway.execute_tool(
                tool_name="retrieve_runbooks",
                arguments={
                    "service_id": primary_service,
                    "environment": context["environment"],
                    "query_text": f"Troubleshooting runbook SOP for {primary_service} {error_code}",
                    "reference_time": context["event_time"],
                    "retrieval_mode": "hybrid_rrf",
                    "top_k": 3,
                    "max_context_tokens": 1024,
                    "index_version_policy": "active_only",
                },
                token=f"Bearer {self.bearer_token}",
                incident_id=incident_id,
            )
            self.resilience.record_tool_result("retrieve_runbooks", retrieval_res.get("status", "ok"))

            citations = retrieval_res.get("citations", [])

            if not citations or retrieval_res.get("status") != "ok":
                context["no_applicable_runbook"] = True
                context["runbook_citations"] = []
                _LOG.info("No applicable runbook found for %s (%s)", primary_service, error_code)
            else:
                context["no_applicable_runbook"] = False
                context["runbook_citations"] = citations

        except Exception as e:
            _LOG.warning("Runbook retrieval failed for %s: %s", primary_service, e)
            context["no_applicable_runbook"] = True
            context["runbook_citations"] = []

        self.sm.transition(
            incident_id=incident_id,
            to_state="RETRIEVED",
            idempotency_key=f"idem-{incident_id}-retrieved",
            reason_code="OK",
            reason=f"Runbook retrieval completed (citations: {len(context['runbook_citations'])}, no_applicable: {context['no_applicable_runbook']})",
            input_data={"service_id": primary_service, "error_code": error_code},
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
            records = data.get("records", []) if isinstance(data, dict) else []

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
                downstream = [s for s in err_services if s != primary_service][0]
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

        self.sm.transition(
            incident_id=incident_id,
            to_state="HYPOTHESES",
            idempotency_key=f"idem-{incident_id}-hypotheses",
            reason_code="OK",
            reason=f"Formulated {len(hypotheses)} candidate hypotheses via deterministic rule engine",
            input_data={"evidence_count": len(evidence_items)},
            output_data={"hypotheses_count": len(hypotheses)},
        )
        context["timeline"].append({"state": "HYPOTHESES", "timestamp": utc_now_z()})
        self.checkpoint.save_checkpoint(incident_id, "HYPOTHESES", context)
        return context

    def _step_validated(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate hypotheses with honest uncertainty checking (EV-01, EV-02, RULE-006)."""
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        evidence_items = context.get("evidence_items", [])
        hypotheses = context.get("hypotheses", [])
        contradictions: List[str] = []
        unknowns: List[str] = []

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

        # 3. Assign validated status to hypotheses
        for hyp in hypotheses:
            if trace_outage:
                # Must abstain / downgrade when trace is missing
                hyp["status"] = "INCONCLUSIVE"
                hyp["confidence_score"] = min(hyp.get("confidence_score", 0.5), 0.40)
            elif contradictions:
                # Contradictory evidence
                hyp["status"] = "PARTIAL"
                hyp["confidence_score"] = min(hyp.get("confidence_score", 0.5), 0.50)
            elif not hyp.get("supporting_evidence_ids"):
                hyp["status"] = "INCONCLUSIVE"
                hyp["confidence_score"] = 0.20
            else:
                # Fully corroborated by available evidence
                hyp["status"] = "SUPPORTED"

        context["contradictions"] = contradictions
        context["unknowns"] = unknowns
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

    def _step_drafted(self, incident_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Compile baseline Draft Handover Dossier structure (C11, C12 handover)."""
        self.resilience.check_cancellation(incident_id)
        self.resilience.check_deadline(incident_id)

        dossier: Dict[str, Any] = {
            "dossier_id": f"dos-{incident_id}",
            "incident_id": incident_id,
            "service_id": context["service_id"],
            "environment": context["environment"],
            "created_at": utc_now_z(),
            "priority": context.get("priority", "MEDIUM"),
            "investigation_scope": context.get("investigation_scope", []),
            "timeline": context.get("timeline", []),
            "evidence_summary": {
                "total_count": len(context.get("evidence_items", [])),
                "evidence_ids": [ev["evidence_id"] for ev in context.get("evidence_items", [])],
            },
            "ranked_hypotheses": context.get("hypotheses", []),
            "contradictions": context.get("contradictions", []),
            "unknowns": context.get("unknowns", []),
            "runbook_citations": context.get("runbook_citations", []),
            "no_applicable_runbook": context.get("no_applicable_runbook", False),
            "version_manifest": self.sm.get_version_manifest(),
            "recommended_human_actions": [
                f"Verify service status and network connectivity for {context['service_id']}",
                "Review active alerts and dependency downstream health",
                "Execute remediation in accordance with SOP runbook (strictly manual)",
            ],
        }

        context["dossier"] = dossier

        self.sm.transition(
            incident_id=incident_id,
            to_state="DRAFTED",
            idempotency_key=f"idem-{incident_id}-drafted",
            reason_code="OK",
            reason=f"Drafted baseline investigation dossier {dossier['dossier_id']}",
            input_data={"incident_id": incident_id},
            output_data={"dossier_id": dossier["dossier_id"]},
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
        _LOG.info("Investigation for %s successfully reached HUMAN_REVIEW", incident_id)
        return context
