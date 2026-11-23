"""Dummy ITSM Ticket Manager enforcing post-approval ticketing and zero auto-remediation (C16, AT-017, FR-OUT-007, ADR-S07)."""

from __future__ import annotations

import datetime
import json
import logging
import pathlib
import uuid
from typing import Any, Dict, List, Optional

from orchestrator.dossier import compute_canonical_dossier_hash

_LOG = logging.getLogger(__name__)


class TicketError(Exception):
    """Base exception for ITSM ticketing operations."""

    def __init__(self, message: str, code: str = "TICKET_ERROR") -> None:
        super().__init__(message)
        self.code = code


class InvalidDossierStateError(TicketError):
    """Raised when ticket creation is attempted against a non-approved dossier revision."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="INVALID_DOSSIER_STATE")


class DummyTicketManager:
    """Manages local dummy ITSM tickets for approved incident dossiers (AT-017, FR-OUT-007, ADR-S07).

    Guarantees:
    1. Tickets are created ONLY after human sign-off (dossier review status == 'APPROVED').
    2. Drafted, pending, or rejected dossiers are rejected with INVALID_DOSSIER_STATE.
    3. auto_action_triggered is strictly False (no automated remediation).
    """

    def __init__(self, storage_path: Optional[pathlib.Path | str] = None) -> None:
        self.storage_path = pathlib.Path(storage_path) if storage_path else None
        self._tickets: Dict[str, Dict[str, Any]] = {}

        if self.storage_path and self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "ticket_id" in item:
                            self._tickets[item["ticket_id"]] = item
                elif isinstance(data, dict):
                    self._tickets.update(data)
            except Exception as e:
                _LOG.warning("Failed to load existing tickets from %s: %s", self.storage_path, e)

    def _persist(self) -> None:
        """Persist in-memory tickets to local sandbox storage file if path is configured."""
        if self.storage_path:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                self.storage_path.write_text(
                    json.dumps(list(self._tickets.values()), indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                _LOG.warning("Failed to persist tickets to %s: %s", self.storage_path, e)

    def create_ticket_from_dossier(
        self,
        dossier: Dict[str, Any],
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a local dummy ITSM ticket bound to an approved dossier revision."""
        # 1. Check Review Status
        review_summary = dossier.get("review_summary", {})
        status = review_summary.get("status") or dossier.get("status") or dossier.get("review_status") or "DRAFTED"

        if status != "APPROVED":
            raise InvalidDossierStateError(
                f"INVALID_DOSSIER_STATE: Cannot create ticket for dossier in state {status!r}. "
                "Must be 'APPROVED' by an authorized human reviewer."
            )

        given_hash = dossier.get("dossier_hash")
        if given_hash and compute_canonical_dossier_hash(dossier) != given_hash:
            raise InvalidDossierStateError(
                "INVALID_DOSSIER_STATE: Dossier hash integrity mismatch; refusing ticket creation."
            )

        # 2. Extract Required Metadata
        incident_id = dossier.get("incident_id", "inc-unknown")
        if not incident_id.startswith("inc-"):
            incident_id = f"inc-{incident_id}"

        revision_number = int(dossier.get("dossier_version", 1))
        approved_by = review_summary.get("reviewed_by") or "authorized_reviewer"

        # Primary hypothesis extraction
        rca = dossier.get("root_cause_analysis", {})
        primary_hypothesis = (
            rca.get("primary_hypothesis")
            or dossier.get("primary_hypothesis")
        )
        if not primary_hypothesis and rca.get("ranked_hypotheses"):
            primary_hypothesis = rca["ranked_hypotheses"][0].get("hypothesis_statement")
        if not primary_hypothesis and dossier.get("hypotheses"):
            first_h = dossier["hypotheses"][0]
            primary_hypothesis = first_h.get("statement") or first_h.get("hypothesis_statement")
        if not primary_hypothesis:
            primary_hypothesis = f"Telemetry anomaly investigation for {incident_id}"

        # SOP references extraction
        rec_actions = dossier.get("recommended_actions", {})
        sop_refs = (
            rec_actions.get("sop_citations")
            or dossier.get("sop_citations")
            or dossier.get("runbook_references")
            or dossier.get("sop_references")
            or []
        )
        # Normalize to list of identifiers or strings
        normalized_sop_refs: List[str] = []
        for ref in sop_refs:
            if isinstance(ref, dict):
                normalized_sop_refs.append(
                    ref.get("doc_id") or ref.get("document_id") or ref.get("title") or str(ref)
                )
            elif isinstance(ref, str):
                normalized_sop_refs.append(ref)

        ticket_id = f"TICK-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        severity = dossier.get("severity") or dossier.get("incident_summary", {}).get("severity", "medium")
        ticket_priority = priority or ("P1" if severity == "critical" else ("P2" if severity == "high" else "P3"))

        primary_support_status = "INCONCLUSIVE"
        if dossier.get("hypotheses") and isinstance(dossier["hypotheses"], list):
            first_h = dossier["hypotheses"][0]
            if isinstance(first_h, dict):
                primary_support_status = str(first_h.get("support_status") or "INCONCLUSIVE")
        elif rca.get("ranked_hypotheses"):
            primary_support_status = str(rca["ranked_hypotheses"][0].get("evaluation_status") or "INCONCLUSIVE")

        ticket: Dict[str, Any] = {
            "ticket_id": ticket_id,
            "incident_id": incident_id,
            "revision_number": revision_number,
            "approved_by": approved_by,
            "primary_hypothesis": primary_hypothesis,
            "diagnosis_support_status": primary_support_status,
            "diagnosis_verified": False,
            "remediation_authorized": False,
            "has_applicable_sop": bool(normalized_sop_refs),
            "sop_references": normalized_sop_refs,
            "status": "OPEN",
            "priority": ticket_priority,
            "assignee": assignee or "L2_SRE_TEAM",
            "created_at": now_z,
            "target_dossier_hash": dossier.get("dossier_hash", ""),
            "auto_action_triggered": False,  # Strict RULE-008 & HUM-01 compliance
        }

        self._tickets[ticket_id] = ticket
        self._persist()
        _LOG.info("Created dummy ticket %s for approved incident %s v%d", ticket_id, incident_id, revision_number)
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a ticket by ID."""
        return self._tickets.get(ticket_id)

    def list_tickets(self, incident_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all tickets, optionally filtered by incident_id."""
        if incident_id:
            formatted_inc = incident_id if incident_id.startswith("inc-") else f"inc-{incident_id}"
            return [t for t in self._tickets.values() if t.get("incident_id") == formatted_inc]
        return list(self._tickets.values())

    def clear(self) -> None:
        """Clear all stored tickets."""
        self._tickets.clear()
        if self.storage_path and self.storage_path.exists():
            self.storage_path.unlink()
