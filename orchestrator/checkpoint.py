"""Checkpointing and Crash Recovery Manager (C11, FR-AGT-009, AT-012, ADR-TBD05)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from orchestrator.state_machine import WorkflowStateStore

_LOG = logging.getLogger(__name__)


class CheckpointManager:
    """Manages durable state checkpoints for crash recovery, pause/resume, and idempotent replay (FR-AGT-009, AT-012)."""

    def __init__(self, store: WorkflowStateStore) -> None:
        self.store = store

    def save_checkpoint(
        self,
        incident_id: str,
        state: str,
        context: Dict[str, Any],
    ) -> None:
        """Save a durable checkpoint snapshot of the incident context."""
        formatted_id = incident_id if incident_id.startswith("inc-") else f"inc-{incident_id}"
        self.store.save_checkpoint(formatted_id, state, context)
        _LOG.info("Durable checkpoint saved for %s at state %s", formatted_id, state)

    def get_checkpoint(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the latest durable checkpoint for an incident."""
        formatted_id = incident_id if incident_id.startswith("inc-") else f"inc-{incident_id}"
        return self.store.get_checkpoint(formatted_id)

    def has_checkpoint(self, incident_id: str) -> bool:
        """Check if an incident has an existing checkpoint."""
        return self.get_checkpoint(incident_id) is not None

    def recover_in_flight_incidents(self) -> List[Dict[str, Any]]:
        """Scan persistence store for active in-flight incidents requiring recovery after worker crash/restart (AT-012).

        Returns a list of dicts with:
        - incident_id
        - current_state
        - status
        - checkpoint_context (if present)
        """
        active_incidents = self.store.get_active_incidents()
        recovered: List[Dict[str, Any]] = []

        for inc in active_incidents:
            inc_id = inc["incident_id"]
            chk = self.store.get_checkpoint(inc_id)
            recovered.append({
                "incident_id": inc_id,
                "current_state": inc["current_state"],
                "status": inc["status"],
                "created_at": inc["created_at"],
                "updated_at": inc["updated_at"],
                "service_id": inc.get("service_id"),
                "environment": inc.get("environment"),
                "fingerprint": inc.get("fingerprint"),
                "checkpoint": chk,
            })

        _LOG.info("Recovered %d active in-flight incidents for resume/replay", len(recovered))
        return recovered

