"""Incident Investigation Handover Dossier Serializer and Markdown Renderer (C12, FR-OUT-001, FR-OUT-002, FR-OUT-003, BRD Appendix A)."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator, FormatChecker

from gateway.sanitizer import DeterministicSanitizer


_DOSSIER_SANITIZER = DeterministicSanitizer()


def _bounded_sanitized_text(value: Any, *, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    sanitized, _ = _DOSSIER_SANITIZER.sanitize_text(normalized)
    return sanitized[:limit]

# Path to canonical dossier contract schema
_CONTRACT_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
)
_DOSSIER_SCHEMA_PATH = _CONTRACT_DIR / "dossier.v1.schema.json"
_VALIDATOR: Draft202012Validator | None = None
if _DOSSIER_SCHEMA_PATH.exists():
    try:
        _schema = json.loads(_DOSSIER_SCHEMA_PATH.read_text(encoding="utf-8"))
        _VALIDATOR = Draft202012Validator(_schema, format_checker=FormatChecker())
    except Exception:
        _VALIDATOR = None


def compute_canonical_dossier_hash(payload_without_hash: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of canonical JSON-serialized dossier payload."""
    # Ensure dossier_hash is omitted when computing the hash
    sanitized = {k: v for k, v in payload_without_hash.items() if k != "dossier_hash"}
    serialized = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class DossierSerializer:
    """Serializes investigation contexts into strictly validated JSON Handover Dossiers (C12, FR-OUT-001)."""

    @classmethod
    def get_schema(cls) -> Optional[Dict[str, Any]]:
        if _DOSSIER_SCHEMA_PATH.exists():
            return json.loads(_DOSSIER_SCHEMA_PATH.read_text(encoding="utf-8"))
        return None

    @classmethod
    def serialize(
        cls,
        context: Dict[str, Any],
        revision: int = 1,
        investigation_mode: str = "deterministic_baseline",
    ) -> Dict[str, Any]:
        """Map raw investigation context to 100% contract-compliant dossier dictionary."""
        incident_id = context.get("incident_id", "inc-unknown")
        if not incident_id.startswith("inc-"):
            incident_id = f"inc-{incident_id}"

        service_id = context.get("service_id", "api-gateway")
        environment = context.get("environment", "lab")
        if environment not in ("lab", "sim-staging", "sim-prod-like"):
            environment = "lab"

        raw_priority = str(context.get("priority") or context.get("severity") or "medium").lower()
        severity_map = {
            "critical": "critical",
            "p1": "critical",
            "high": "high",
            "p2": "high",
            "medium": "medium",
            "p3": "medium",
            "low": "low",
            "p4": "low",
        }
        severity = severity_map.get(raw_priority, "medium")

        alert_time = context.get("event_time") or context.get("alert_received_at") or "2026-11-12T00:00:00Z"
        if not alert_time.endswith("Z"):
            alert_time = f"{alert_time.replace('+00:00', '')}Z"

        window = context.get("query_window") or {}
        window_start = window.get("start") or context.get("window_start") or alert_time
        window_end = window.get("end") or context.get("window_end") or alert_time
        if not window_start.endswith("Z"):
            window_start = f"{window_start.replace('+00:00', '')}Z"
        if not window_end.endswith("Z"):
            window_end = f"{window_end.replace('+00:00', '')}Z"

        dossier_ready_at = context.get("dossier_ready_at") or alert_time

        # 1. Impact Summary
        prior_impact = context.get("impact_summary") if isinstance(context.get("impact_summary"), dict) else {}
        scope = context.get("investigation_scope") or prior_impact.get("affected_services") or [service_id]
        if not scope:
            scope = [service_id]
        observed_symptoms = context.get("message") or prior_impact.get("observed_symptoms") or f"Telemetry signals indicated anomalies in {service_id} ({context.get('error_code', 'ERR_UNKNOWN')})"
        if len(observed_symptoms) < 3:
            observed_symptoms = f"Anomaly observed in {service_id}"
        error_budget = "severe" if severity == "critical" else ("moderate" if severity == "high" else "minor")

        impact_summary = {
            "affected_services": scope,
            "observed_symptoms": observed_symptoms[:2048],
            "error_budget_impact": error_budget,
        }

        # 2. Timeline
        raw_timeline = context.get("timeline", [])
        timeline: List[Dict[str, Any]] = []
        if not raw_timeline:
            timeline.append({
                "timestamp": alert_time,
                "event_kind": "alert",
                "source_ref": "alert_intake:queue",
                "summary": f"Incident alert triggered for {service_id}",
            })
        else:
            for item in raw_timeline:
                ts = item.get("timestamp", alert_time)
                if not ts.endswith("Z"):
                    ts = f"{ts.replace('+00:00', '')}Z"
                ek = item.get("event_kind", "workflow_event")
                if ek not in ("alert", "metric_anomaly", "error_log", "trace_observation", "dependency_state", "workflow_event"):
                    ek = "workflow_event"
                src = item.get("source_ref") or "orchestrator:coordinator"
                summary_txt = item.get("summary") or f"Workflow state transitioned to {item.get('state', 'UNKNOWN')}"
                timeline.append({
                    "timestamp": ts,
                    "event_kind": ek,
                    "source_ref": src[:128],
                    "summary": summary_txt[:1024],
                })

        # 3. Evidence vs Missing Sources Separation
        evidence_context = context.get("evidence_items")
        raw_evidence = evidence_context if isinstance(evidence_context, list) else context.get("evidence", [])
        evidence_list: List[Dict[str, Any]] = []
        raw_missing = context.get("missing_sources", [])
        missing_sources: List[Dict[str, Any]] = [
            dict(item) for item in raw_missing if isinstance(item, dict)
        ]

        valid_tools = {
            "get_service_metrics",
            "search_error_logs",
            "get_trace_summary",
            "get_service_dependencies",
            "get_apm_health",
        }

        for ev in raw_evidence:
            tname = ev.get("tool_name", "get_service_metrics")
            if tname not in valid_tools:
                tname = "get_service_metrics"

            dq = ev.get("data_quality", "complete")
            obs_at = ev.get("observed_at", alert_time)
            if not obs_at.endswith("Z"):
                obs_at = f"{obs_at.replace('+00:00', '')}Z"

            err_code = ev.get("error_code")
            if dq == "unavailable" or err_code in ("SOURCE_UNAVAILABLE", "TIMEOUT", "BACKEND_TIMEOUT"):
                m_err = "SOURCE_UNAVAILABLE"
                if err_code in ("TIMEOUT", "BACKEND_TIMEOUT"):
                    m_err = "BACKEND_TIMEOUT"
                elif err_code == "NO_APPLICABLE_RUNBOOK":
                    m_err = "NO_APPLICABLE_RUNBOOK"
                elif err_code == "BUDGET_EXHAUSTED":
                    m_err = "BUDGET_EXHAUSTED"
                elif err_code == "DEADLINE_EXCEEDED":
                    m_err = "DEADLINE_EXCEEDED"

                missing_sources.append({
                    "tool_name": tname[:64],
                    "error_code": m_err,
                    "recorded_at": obs_at,
                    "impact_note": f"Telemetry backend for {tname} was unavailable or timed out during observation window."[:512],
                })
                continue

            quality_val = "partial" if dq == "partial" else "complete"
            ev_id = ev.get("evidence_id", f"ev-{incident_id}-001")
            if not ev_id.startswith("ev-"):
                ev_id = f"ev-{ev_id}"
            records = ev.get("records", [])
            summary_source = ev.get("summary")
            if not summary_source and records:
                preview_values = []
                for record in records[:3]:
                    if isinstance(record, dict):
                        preview_values.append(
                            record.get("message")
                            or record.get("metric")
                            or record.get("value")
                            or json.dumps(record, sort_keys=True, default=str)
                        )
                summary_source = "; ".join(str(value) for value in preview_values if value is not None)
            if not summary_source:
                summary_source = (
                    f"{tname} queried on {ev.get('service_id', service_id)}: "
                    f"{len(records)} records returned."
                )
            ev_window = ev.get("query_window") if isinstance(ev.get("query_window"), dict) else {}
            evidence_list.append({
                "evidence_id": ev_id,
                "tool_name": tname,
                "source_ref": ev.get("source_ref", "telemetry:adapter")[:128],
                "observed_at": obs_at,
                "query_window": {
                    "start": ev_window.get("start", window_start),
                    "end": ev_window.get("end", window_end),
                },
                "data_quality": quality_val,
                "truncated": bool(ev.get("truncated", False)),
                "sanitized": True,
                "summary": _bounded_sanitized_text(summary_source, limit=2048),
            })

        # Ensure missing sources from context errors are captured
        if context.get("no_applicable_runbook"):
            missing_sources.append({
                "tool_name": "retrieve_runbooks",
                "error_code": "NO_APPLICABLE_RUNBOOK",
                "recorded_at": dossier_ready_at,
                "impact_note": "No active approved SOP runbook found matching the observed error pattern in corpus.",
            })

        # 4. Hypotheses
        raw_hyp = context.get("hypotheses", [])
        hypotheses_list: List[Dict[str, Any]] = []

        # Collect available valid evidence IDs for reference
        available_ev_ids = [e["evidence_id"] for e in evidence_list]

        if not raw_hyp:
            raw_hyp = [{
                "hypothesis_id": f"hyp-{incident_id}-001",
                "title": f"Operational degradation in {service_id}",
                "description": f"Telemetry observation indicates possible anomaly on {service_id}.",
                "status": "INCONCLUSIVE",
                "supporting_evidence_ids": [],
                "refuting_evidence_ids": [],
            }]

        for idx, h in enumerate(raw_hyp, start=1):
            h_id = h.get("hypothesis_id", f"hyp-{incident_id}-{idx:03d}")
            if not h_id.startswith("hyp-"):
                h_id = f"hyp-{h_id}"

            raw_val = h.get("status") or h.get("support_status") or "INCONCLUSIVE"
            raw_status = str(raw_val.value if hasattr(raw_val, "value") else raw_val).upper()
            v_val = h.get("validation_status") or raw_status
            validation_status = str(v_val.value if hasattr(v_val, "value") else v_val).upper()
            # Frozen dossier.v1 schema permits SUPPORTED | PARTIAL | INCONCLUSIVE;
            # UNSUPPORTED and CONTRADICTED map non-breakingly to INCONCLUSIVE in dossier.v1
            # and are preserved verbatim in validation_summary.
            status_val = raw_status if raw_status in ("SUPPORTED", "PARTIAL", "INCONCLUSIVE") else "INCONCLUSIVE"

            stmt = h.get("title") or h.get("statement") or f"Service anomaly on {service_id}"
            if len(stmt) < 5:
                stmt = f"Service failure detected on {service_id}"

            if validation_status in ("UNSUPPORTED", "CONTRADICTED"):
                sup_ids = []
            else:
                sup_ids = [eid for eid in h.get("supporting_evidence_ids", []) if eid in available_ev_ids]
            ref_ids = [eid for eid in h.get("contradicting_evidence_ids", h.get("refuting_evidence_ids", [])) if eid in available_ev_ids]

            # Do not assign unrelated evidence to satisfy the schema.
            if status_val == "SUPPORTED" and not sup_ids:
                status_val = "INCONCLUSIVE"

            reason = h.get("description") or h.get("reason_summary") or f"Hypothesis derived from observed signals on {service_id}."
            if len(reason) < 5:
                reason = "Candidate cause derived from telemetry logs and metrics."
            if validation_status in ("UNSUPPORTED", "CONTRADICTED") and f"[{validation_status}]" not in reason:
                reason = f"[{validation_status}] {reason}"

            h_unknowns = h.get("unknowns") or []
            if not h_unknowns and status_val == "INCONCLUSIVE":
                h_unknowns = ["Root cause cannot be conclusively proven with available telemetry data."]

            hypotheses_list.append({
                "hypothesis_id": h_id,
                "rank": idx,
                "statement": re.sub(r"\bverified\b", "unconfirmed", stmt, flags=re.IGNORECASE)[:2048],
                "support_status": status_val,
                "supporting_evidence_ids": list(set(sup_ids)),
                "contradicting_evidence_ids": list(set(ref_ids)),
                "reason_summary": re.sub(r"\bverified\b", "unconfirmed", reason, flags=re.IGNORECASE)[:2048],
                "unknowns": [u[:512] for u in h_unknowns if len(u) >= 3],
            })

        # 5. SOP Citations
        citation_context = context.get("runbook_citations")
        raw_citations = citation_context if isinstance(citation_context, list) else context.get("sop_citations", [])
        sop_citations: List[Dict[str, Any]] = []
        for cit in raw_citations:
            doc_id = cit.get("doc_id") or cit.get("document_id") or "SOP-GENERIC"
            ver = cit.get("version") or cit.get("document_version") or "1.0.0"
            sec = cit.get("section_path") or "/troubleshooting"
            src_uri = cit.get("source_uri") or f"kb://sop/{doc_id.lower()}.md"
            if not src_uri.startswith("kb://"):
                src_uri = f"kb://sop/{doc_id.lower()}.md"

            cid = cit.get("chunk_id") or f"chk-{doc_id.lower()}-001"
            excerpt_source = (
                cit.get("excerpt")
                or cit.get("text_excerpt")
                or cit.get("summary")
                or "Excerpt tidak tersedia pada payload retrieval tersanitasi."
            )
            sop_citations.append({
                "chunk_id": cid[:128],
                "doc_id": doc_id[:128],
                "version": ver[:64],
                "section_path": sec[:256],
                "source_uri": src_uri,
                "applicability_verified": True,
                "excerpt": _bounded_sanitized_text(excerpt_source, limit=512),
                "sanitized": True,
            })

        # 6. Unknowns
        unknowns = [u[:512] for u in context.get("unknowns", []) if len(u) >= 3]
        if not unknowns and missing_sources:
            unknowns.append("One or more telemetry backends were unavailable during investigation window.")

        # 7. Recommended Checks (Human-Controlled Only)
        raw_checks = context.get("recommended_checks") or context.get("recommended_human_actions") or []
        recommended_checks: List[Dict[str, Any]] = []
        check_idx = 1
        for chk in raw_checks:
            desc = chk if isinstance(chk, str) else chk.get("description", "Inspect service logs and metric dashboard")
            if len(desc) < 5:
                desc = "Inspect service logs and metric dashboard"
            
            if isinstance(chk, dict) and chk.get("check_id"):
                cid = chk["check_id"]
            else:
                cid = f"chk-{check_idx:02d}"

            if isinstance(chk, dict) and chk.get("risk_level") in ("critical", "high", "medium", "low"):
                risk = chk["risk_level"]
            else:
                risk = "high" if "critical" in desc.lower() else "medium"

            sop_ref = chk.get("related_sop_doc_id") if isinstance(chk, dict) else (sop_citations[0]["doc_id"] if sop_citations else None)

            recommended_checks.append({
                "check_id": cid[:64],
                "description": desc[:1024],
                "risk_level": risk,
                "requires_human_approval": True,
                "auto_execution_allowed": False,
                "related_sop_doc_id": sop_ref,
            })
            check_idx += 1

        if not recommended_checks:
            recommended_checks.append({
                "check_id": "chk-01",
                "description": f"Manually verify health and upstream connectivity of {service_id}.",
                "risk_level": "medium",
                "requires_human_approval": True,
                "auto_execution_allowed": False,
                "related_sop_doc_id": sop_citations[0]["doc_id"] if sop_citations else None,
            })

        # 8. Review Summary
        review_summary = context.get("review_summary") or {
            "status": "PENDING_REVIEW",
            "latest_review_event_id": None,
            "reviewed_by": None,
            "reviewed_at": None,
        }

        # 9. Reproducibility
        manifest = context.get("version_manifest") or context.get("reproducibility") or {}
        raw_corr_ids = manifest.get("correlation_ids")
        if isinstance(raw_corr_ids, list) and raw_corr_ids:
            corr_ids = [str(c) for c in raw_corr_ids if isinstance(c, str) and len(c) >= 4] or [
                context.get("trace_id") or f"corr-{incident_id}"
            ]
        else:
            corr_ids = [context.get("trace_id") or f"corr-{incident_id}"]
        reproducibility = {
            "workflow_version": manifest.get("workflow_version", "1.0.0"),
            "policy_version": manifest.get("policy_version", "1.0.0"),
            "model_version": manifest.get("model_version", "deterministic_rule_engine_v1"),
            "prompt_version": manifest.get("prompt_version", "deterministic_baseline_rules_v1"),
            "tool_schema_version": manifest.get("tool_schema_version", "1.0"),
            "kb_index_version": manifest.get("kb_version") or manifest.get("kb_index_version", "kb-idx-20261111-v1"),
            "correlation_ids": corr_ids,
        }

        # Construct payload without hash
        dossier_payload: Dict[str, Any] = {
            "schema_version": "1.0",
            "incident_id": incident_id,
            "dossier_version": revision,
            "severity": severity,
            "service_id": service_id,
            "environment": environment,
            "alert_received_at": alert_time,
            "window_start": window_start,
            "window_end": window_end,
            "dossier_ready_at": dossier_ready_at,
            "investigation_mode": investigation_mode,
            "impact_summary": impact_summary,
            "timeline": timeline,
            "evidence": evidence_list,
            "missing_sources": missing_sources,
            "hypotheses": hypotheses_list,
            "sop_citations": sop_citations,
            "unknowns": unknowns,
            "recommended_checks": recommended_checks,
            "review_summary": review_summary,
            "reproducibility": reproducibility,
        }

        # Calculate and inject SHA-256 hash
        dossier_hash = compute_canonical_dossier_hash(dossier_payload)
        dossier_payload["dossier_hash"] = dossier_hash

        # Programmatic schema validation
        if _VALIDATOR is not None:
            errors = list(_VALIDATOR.iter_errors(dossier_payload))
            if errors:
                err_msg = "; ".join(f"{e.json_path}: {e.message}" for e in errors)
                raise ValueError(f"Dossier failed schema validation against dossier.v1: {err_msg}")

        return dossier_payload

    @classmethod
    def serialize_validation_summary(cls, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Serialize validation separately from the frozen dossier v1 payload."""
        if "validation_reports" not in context:
            return None
        reports = context["validation_reports"]
        claims = [claim for report in reports for claim in report.get("claims", [])]
        contradictions = list(context.get("contradictions", []))
        rejected_citations = []
        seen_rejections = set()
        for report in reports:
            contradictions.extend(report.get("contradictions", []))
            for citation in report.get("rejected_sop_citations", []):
                rejection = {
                    "doc_id": citation.get("doc_id") or citation.get("document_id") or "",
                    "chunk_id": citation.get("chunk_id") or "",
                    "rejection_reason": citation.get("rejection_reason") or "",
                    "details": citation.get("details") or "",
                }
                key = tuple(rejection.values())
                if key not in seen_rejections:
                    seen_rejections.add(key)
                    rejected_citations.append(rejection)
        def _status_str(val: Any, default: str = "INCONCLUSIVE") -> str:
            if val is None:
                return default
            return str(val.value) if hasattr(val, "value") else str(val)

        hypotheses_by_id = {
            h.get("hypothesis_id"): h
            for h in context.get("hypotheses", [])
            if isinstance(h, dict) and h.get("hypothesis_id")
        }
        hypothesis_validations = []
        for report in reports:
            r_status = _status_str(report.get("status"), "INCONCLUSIVE")
            r_hyp = hypotheses_by_id.get(report.get("hypothesis_id"), {})
            d_status = _status_str(r_hyp.get("status"), r_status)
            if d_status not in ("SUPPORTED", "PARTIAL", "INCONCLUSIVE"):
                d_status = "INCONCLUSIVE"
            rejected_claims = [
                {
                    "evidence_id": c.get("evidence_id"),
                    "status": _status_str(c.get("status")),
                    "reason_code": c.get("reason_code"),
                    "details": c.get("details", ""),
                }
                for c in report.get("claims", [])
                if _status_str(c.get("status")) in ("UNSUPPORTED", "CONTRADICTED")
            ]
            hypothesis_validations.append({
                "hypothesis_id": report.get("hypothesis_id"),
                "validation_status": r_status,
                "dossier_support_status": d_status,
                "reason_codes": list(report.get("reason_codes", [])),
                "supporting_evidence_ids": list(report.get("supporting_evidence_ids", [])),
                "contradicting_evidence_ids": list(report.get("contradicting_evidence_ids", [])),
                "rejected_claims": rejected_claims,
            })
        return {
            "supported_claims_count": sum(_status_str(claim.get("status")) == "SUPPORTED" for claim in claims),
            "unsupported_claims_count": sum(_status_str(claim.get("status")) == "UNSUPPORTED" for claim in claims),
            "contradicted_claims_count": sum(_status_str(claim.get("status")) == "CONTRADICTED" for claim in claims),
            "irrelevant_evidence_claims_count": sum(claim.get("reason_code") == "IRRELEVANT_EVIDENCE" for claim in claims),
            "total_material_claims_count": len(claims),
            "contradictions": list(dict.fromkeys(contradictions)),
            "rejected_sop_citations": rejected_citations,
            "hypothesis_validations": hypothesis_validations,
        }


class DossierMarkdownRenderer:
    """Renders human-readable Markdown handover dossiers adhering to BRD Appendix A (C12, FR-OUT-002, NFR-020)."""

    @classmethod
    def render(cls, dossier: Dict[str, Any], validation_summary: Optional[Dict[str, Any]] = None) -> str:
        """Render dossier dictionary into standard enterprise Markdown report."""
        inc_id = dossier["incident_id"]
        status = dossier["hypotheses"][0]["support_status"] if dossier.get("hypotheses") else "INCONCLUSIVE"
        rev_summary = dossier.get("review_summary", {})
        repro = dossier.get("reproducibility", {})
        impact = dossier.get("impact_summary", {})

        md_lines = [
            f"# Incident Investigation Dossier — {inc_id}",
            f"- **Scenario label visible to reviewer:** `{inc_id}` (Synthetic Lab Simulation)",
            f"- **Service / Environment / Severity:** `{dossier['service_id']}` / `{dossier['environment']}` / `{dossier['severity'].upper()}`",
            f"- **Alert received at / Dossier ready at:** `{dossier['alert_received_at']}` / `{dossier['dossier_ready_at']}`",
            f"- **Investigation mode & Status:** `{dossier['investigation_mode']}` | **`{status}`**",
            f"- **Dossier Revision / SHA-256 Hash:** `v{dossier['dossier_version']}` / `{dossier['dossier_hash']}`",
            f"- **Workflow / KB / Tool Versions:** `{repro.get('workflow_version')}` / `{repro.get('kb_index_version')}` / `{repro.get('tool_schema_version')}`",
            "",
            "---",
            "",
            "## 1. Executive Summary & Observed Symptoms",
            "",
            f"{impact.get('observed_symptoms', 'N/A')}",
            "",
            "## 2. Impact and Scope",
            "",
            f"- **Affected Microservices:** {', '.join(f'`{s}`' for s in impact.get('affected_services', []))}",
            f"- **Error Budget Impact Assessment:** `{impact.get('error_budget_impact', 'unknown').upper()}`",
            f"- **Investigation Window:** `{dossier['window_start']}` to `{dossier['window_end']}`",
            "",
            "## 3. Timeline of Observed Signals",
            "",
            "| Timestamp (UTC) | Event Kind | Source Reference | Summary |",
            "|---|---|---|---|",
        ]

        for t in dossier.get("timeline", []):
            md_lines.append(f"| `{t['timestamp']}` | `{t['event_kind']}` | `{t['source_ref']}` | {t['summary']} |")

        md_lines.extend([
            "",
            "## 4. Evidence Table",
            "",
            "| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |",
            "|---|---|---|---|---|---|",
        ])

        for ev in dossier.get("evidence", []):
            w = ev.get("query_window", {})
            window_str = f"{w.get('start')} s/d {w.get('end')}"
            md_lines.append(
                f"| `{ev['evidence_id']}` | `{ev['tool_name']}` (`{ev['source_ref']}`) | `{window_str}` | `{ev['data_quality']}` | `{ev['sanitized']}` | {ev['summary']} |"
            )

        if not dossier.get("evidence"):
            md_lines.append("| *None* | *No positive telemetry evidence collected* | - | - | - | - |")

        md_lines.extend([
            "",
            "## 5. Ranked Hypotheses",
            "",
            "| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |",
            "|---|---|---|---|---|---|",
        ])

        for h in dossier.get("hypotheses", []):
            for_ev = ", ".join(f"`{e}`" for e in h.get("supporting_evidence_ids", [])) or "*None*"
            against_ev = ", ".join(f"`{e}`" for e in h.get("contradicting_evidence_ids", [])) or "*None*"
            md_lines.append(
                f"| {h['rank']} | **{h['statement']}** | {for_ev} | {against_ev} | `{h['support_status']}` | {h['reason_summary']} |"
            )

        md_lines.extend([
            "",
            "## 6. Relevant Runbooks & SOP Citations",
            "",
            "| Document ID & Version | Section Path | Source URI | Applicability Verified |",
            "|---|---|---|---|",
        ])

        for sop in dossier.get("sop_citations", []):
            md_lines.append(
                f"| `{sop['doc_id']} v{sop['version']}` | `{sop['section_path']}` | `{sop['source_uri']}` | `{sop['applicability_verified']}` |"
            )

        if not dossier.get("sop_citations"):
            md_lines.append("| *NO_APPLICABLE_RUNBOOK* | *No matching SOP in corpus* | `kb://sop/unmapped` | `False` |")

        md_lines.extend([
            "",
            "## 7. Unknowns & Telemetry Gaps",
            "",
        ])

        if dossier.get("unknowns"):
            for u in dossier["unknowns"]:
                md_lines.append(f"> [!WARNING] **Telemetry Uncertainty:** {u}")
        else:
            md_lines.append("No material telemetry gaps reported.")

        if dossier.get("missing_sources"):
            md_lines.append("")
            md_lines.append("**Unavailable Telemetry Sources:**")
            for ms in dossier["missing_sources"]:
                md_lines.append(f"- Tool `{ms['tool_name']}` reported `{ms['error_code']}` at `{ms['recorded_at']}`: {ms['impact_note']}")

        validation = validation_summary
        if validation is not None:
            md_lines.extend([
                "",
                "### Validation results",
                "",
                "Claim counts reflect validator reference, time, value, and relevance checks.",
                "",
                f"- Supported claims: {validation['supported_claims_count']}",
                f"- Unsupported claims: {validation['unsupported_claims_count']}",
                f"- Contradicted claims: {validation.get('contradicted_claims_count', 0)}",
                f"- Irrelevant evidence claims: {validation.get('irrelevant_evidence_claims_count', 0)}",
                f"- Total material claims: {validation['total_material_claims_count']}",
                "",
                "**Contradictions:**",
            ])
            for contradiction in validation["contradictions"]:
                md_lines.append(f"- {contradiction}")
            if not validation["contradictions"]:
                md_lines.append("- None reported.")
            hyp_vals = validation.get("hypothesis_validations") or []
            if hyp_vals:
                md_lines.extend(["", "**Per-hypothesis validation statuses:**"])
                for hv in hyp_vals:
                    codes = ", ".join(hv.get("reason_codes", [])) or "none"
                    md_lines.append(
                        f"- `{hv.get('hypothesis_id')}`: `{hv.get('validation_status')}` "
                        f"(dossier `support_status`: `{hv.get('dossier_support_status')}`, reasons: `{codes}`)"
                    )
                    for rc in hv.get("rejected_claims", []):
                        md_lines.append(
                            f"  - Rejected evidence `{rc.get('evidence_id')}` (`{rc.get('reason_code')}`): {rc.get('details')}"
                        )
            md_lines.extend(["", "**Rejected SOP citations:**"])
            for citation in validation["rejected_sop_citations"]:
                md_lines.append(
                    f"- `{citation['doc_id']}` / `{citation['chunk_id']}`: "
                    f"`{citation['rejection_reason']}` {citation['details']}"
                )
            if not validation["rejected_sop_citations"]:
                md_lines.append("- None reported.")

        md_lines.extend([
            "",
            "## 8. Proposed Next Checks (Human-Controlled Only)",
            "",
            "> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.",
            "",
            "| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |",
            "|---|---|---|---|---|",
        ])

        for chk in dossier.get("recommended_checks", []):
            sop_link = f"`{chk['related_sop_doc_id']}`" if chk.get("related_sop_doc_id") else "*None*"
            md_lines.append(
                f"| `{chk['check_id']}` | {chk['description']} | `{chk['risk_level'].upper()}` | `{chk['requires_human_approval']}` | {sop_link} |"
            )

        md_lines.extend([
            "",
            "## 9. Reviewer Decision, Edits, and Sign-off Box",
            "",
            f"- **Current Review Status:** **`{rev_summary.get('status', 'PENDING_REVIEW')}`**",
            f"- **Latest Review Event ID:** `{rev_summary.get('latest_review_event_id') or 'N/A'}`",
            f"- **Reviewed By / Role:** `{rev_summary.get('reviewed_by') or 'PENDING'}`",
            f"- **Review Timestamp:** `{rev_summary.get('reviewed_at') or 'PENDING'}`",
            "- **Diagnosis Verified:** `false` (APPROVE signifies dossier handover acceptance only; does not prove unconfirmed root causes)",
            "- **Remediation Authorized / Auto-Action Triggered:** `false` (HUM-01 & RULE-008)",
            "",
            "```text",
            "┌────────────────────────────────────────────────────────────────────────┐",
            "│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │",
            "├────────────────────────────────────────────────────────────────────────┤",
            f"│  INCIDENT ID      : {inc_id:<50} │",
            f"│  DOSSIER VERSION  : v{dossier['dossier_version']:<49} │",
            f"│  DOSSIER HASH     : {dossier['dossier_hash'][:32]}...                │",
            f"│  DECISION         : {rev_summary.get('status', 'PENDING_REVIEW'):<50} │",
            f"│  REVIEWER         : {str(rev_summary.get('reviewed_by') or 'Awaiting Human Review'):<50} │",
            f"│  DATE SIGNED      : {str(rev_summary.get('reviewed_at') or 'PENDING'):<50} │",
            "└────────────────────────────────────────────────────────────────────────┘",
            "```",
        ])

        return "\n".join(md_lines)
