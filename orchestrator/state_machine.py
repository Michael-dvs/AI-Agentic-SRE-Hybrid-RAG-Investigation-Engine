"""Durable Deterministic Investigation State Machine and SQLite Store (C11, FR-AGT-001, FR-AGT-008, ADR-TBD05)."""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import sqlite3
import uuid
from typing import Any, Optional

from jsonschema import Draft202012Validator, FormatChecker

# Path to canonical contract schema
_CONTRACT_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
)
_WORKFLOW_EVENT_SCHEMA_PATH = _CONTRACT_DIR / "workflow-event.v1.schema.json"
_VALIDATOR: Draft202012Validator | None = None
if _WORKFLOW_EVENT_SCHEMA_PATH.exists():
    try:
        _schema = json.loads(_WORKFLOW_EVENT_SCHEMA_PATH.read_text(encoding="utf-8"))
        _VALIDATOR = Draft202012Validator(_schema, format_checker=FormatChecker())
    except Exception:
        _VALIDATOR = None


class InvalidStateTransitionError(Exception):
    """Raised when an illegal workflow state transition is attempted (FR-AGT-001)."""

    def __init__(self, message: str = "Invalid state transition attempted") -> None:
        super().__init__(message)
        self.code = "INVALID_STATE_TRANSITION"


# 9 Mandatory Sequential States (FR-AGT-001)
MANDATORY_STATES = (
    "RECEIVED",
    "CORRELATED",
    "TRIAGED",
    "EVIDENCE_COLLECTED",
    "RETRIEVED",
    "HYPOTHESES",
    "VALIDATED",
    "DRAFTED",
    "HUMAN_REVIEW",
)

# Valid sequential forward transitions
VALID_FORWARD_TRANSITIONS: dict[str | None, str] = {
    None: "RECEIVED",
    "RECEIVED": "CORRELATED",
    "CORRELATED": "TRIAGED",
    "TRIAGED": "EVIDENCE_COLLECTED",
    "EVIDENCE_COLLECTED": "RETRIEVED",
    "RETRIEVED": "HYPOTHESES",
    "HYPOTHESES": "VALIDATED",
    "VALIDATED": "DRAFTED",
    "DRAFTED": "HUMAN_REVIEW",
    "HUMAN_REVIEW": "CLOSED",
    "CLOSED": "LEARNED",
}

# Permitted terminal/abort targets from any non-terminal state
PERMITTED_ABORT_TARGETS = {
    "CANCELLED",
    "FAILED_SAFE",
    "MANUAL_TRIAGE_REQUIRED",
    "REJECTED",
}


def utc_now_z() -> str:
    """Return ISO 8601 UTC timestamp ending in 'Z'."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def compute_sha256_hash(data: Any) -> str:
    """Compute SHA-256 hash of JSON-serialized object."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class WorkflowStateStore:
    """Durable SQLite storage for incident states, transitions, and checkpoints (ADR-TBD05 Opsi C)."""

    def __init__(self, db_path: str = "orchestrator_state.db") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit mode
        )
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    current_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    service_id TEXT,
                    environment TEXT,
                    fingerprint TEXT
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    incident_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    input_hash TEXT,
                    output_hash TEXT,
                    reason TEXT,
                    producer_ref TEXT NOT NULL,
                    workflow_version TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    terminal_outcome TEXT,
                    reason_code TEXT,
                    artifact_ref TEXT
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    incident_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    context_blob TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_incident(
        self,
        incident_id: str,
        service_id: str | None = None,
        environment: str | None = None,
        fingerprint: str | None = None,
        initial_state: str = "RECEIVED",
        status: str = "ACTIVE",
    ) -> None:
        now = utc_now_z()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO incidents (incident_id, current_state, created_at, updated_at, status, service_id, environment, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (incident_id, initial_state, now, now, status, service_id, environment, fingerprint),
        )

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        cursor = self._conn.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_incident_state(
        self, incident_id: str, new_state: str, status: str = "ACTIVE"
    ) -> None:
        now = utc_now_z()
        self._conn.execute(
            """
            UPDATE incidents
            SET current_state = ?, updated_at = ?, status = ?
            WHERE incident_id = ?
            """,
            (new_state, now, status, incident_id),
        )

    def record_transition(
        self,
        event: dict[str, Any],
        input_hash: str | None = None,
        output_hash: str | None = None,
        reason: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO state_transitions (
                event_id, incident_id, idempotency_key, from_state, to_state,
                occurred_at, input_hash, output_hash, reason, producer_ref,
                workflow_version, policy_version, terminal_outcome, reason_code, artifact_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                event["incident_id"],
                event["idempotency_key"],
                event["from_state"],
                event["to_state"],
                event["occurred_at"],
                input_hash,
                output_hash,
                reason,
                event["producer_ref"],
                event["workflow_version"],
                event["policy_version"],
                event["terminal_outcome"],
                event["reason_code"],
                event["artifact_ref"],
            ),
        )

    def get_transitions(self, incident_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM state_transitions WHERE incident_id = ? ORDER BY id ASC",
            (incident_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def save_checkpoint(
        self, incident_id: str, state: str, context: dict[str, Any]
    ) -> None:
        now = utc_now_z()
        blob = json.dumps(context, sort_keys=True, default=str)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO checkpoints (incident_id, state, context_blob, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (incident_id, state, blob, now),
        )

    def get_checkpoint(self, incident_id: str) -> dict[str, Any] | None:
        cursor = self._conn.execute(
            "SELECT * FROM checkpoints WHERE incident_id = ?", (incident_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "incident_id": row["incident_id"],
            "state": row["state"],
            "updated_at": row["updated_at"],
            "context": json.loads(row["context_blob"]),
        }

    def get_active_incidents(self) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM incidents WHERE status = 'ACTIVE' ORDER BY created_at ASC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        self._conn.close()


class InvestigationStateMachine:
    """Deterministic, auditable state machine governing the 9 investigation states (FR-AGT-001, FR-AGT-008)."""

    def __init__(
        self,
        store: WorkflowStateStore | None = None,
        workflow_version: str = "1.0.0",
        policy_version: str = "1.0.0",
        kb_version: str = "kb-idx-20261111-v1",
        tool_schema_version: str = "1.0",
        producer_ref: str = "CMP-INV-01",
    ) -> None:
        self.store = store or WorkflowStateStore(":memory:")
        self.workflow_version = workflow_version
        self.policy_version = policy_version
        self.kb_version = kb_version
        self.tool_schema_version = tool_schema_version
        self.producer_ref = producer_ref

    def get_version_manifest(self) -> dict[str, str]:
        """Return frozen version identifier manifest (FR-AGT-008)."""
        return {
            "workflow_version": self.workflow_version,
            "policy_version": self.policy_version,
            "kb_version": self.kb_version,
            "tool_schema_version": self.tool_schema_version,
            "coordinator_ref": self.producer_ref,
        }

    def can_transition(self, from_state: str | None, to_state: str) -> bool:
        """Validate if transition from_state -> to_state is strictly permitted."""
        if to_state in PERMITTED_ABORT_TARGETS:
            return True
        expected = VALID_FORWARD_TRANSITIONS.get(from_state)
        return expected == to_state

    def transition(
        self,
        incident_id: str,
        to_state: str,
        idempotency_key: str,
        reason_code: str = "OK",
        terminal_outcome: str | None = None,
        reason: str | None = None,
        artifact_ref: str | None = None,
        input_data: Any = None,
        output_data: Any = None,
    ) -> dict[str, Any]:
        """Execute and durably record a state transition."""
        now = utc_now_z()
        event_id = f"wfe-{uuid.uuid4().hex[:16]}"

        incident = self.store.get_incident(incident_id)
        from_state = incident["current_state"] if incident else None

        # Validate transition legitimacy
        if not self.can_transition(from_state, to_state):
            raise InvalidStateTransitionError(
                f"Illegal state transition from {from_state!r} to {to_state!r} for incident {incident_id}"
            )

        # Derive terminal outcome and status
        status = "ACTIVE"
        if to_state == "CLOSED":
            status = "CLOSED"
            terminal_outcome = terminal_outcome or "CLOSED_APPROVED"
        elif to_state == "CANCELLED":
            status = "CANCELLED"
            terminal_outcome = terminal_outcome or "TERMINATED_CANCELLED"
        elif to_state == "FAILED_SAFE":
            status = "FAILED_SAFE"
            terminal_outcome = terminal_outcome or "TERMINATED_FAILED_SAFE"

        # Compute cryptographic fingerprints for audit reproducibility
        in_hash = compute_sha256_hash(input_data) if input_data is not None else None
        out_hash = compute_sha256_hash(output_data) if output_data is not None else None

        # Format canonical incident ID
        formatted_inc_id = incident_id
        if not formatted_inc_id.startswith("inc-"):
            formatted_inc_id = f"inc-{formatted_inc_id}"

        # Construct canonical workflow-event.v1 payload
        event_payload: dict[str, Any] = {
            "schema_version": "1.0",
            "event_id": event_id,
            "incident_id": formatted_inc_id,
            "idempotency_key": idempotency_key,
            "occurred_at": now,
            "from_state": from_state,
            "to_state": to_state,
            "producer_ref": self.producer_ref,
            "workflow_version": self.workflow_version,
            "policy_version": self.policy_version,
            "terminal_outcome": terminal_outcome,
            "reason_code": reason_code,
            "artifact_ref": artifact_ref,
        }

        # Validate against strict contract
        if _VALIDATOR is not None:
            errors = list(_VALIDATOR.iter_errors(event_payload))
            if errors:
                err_msg = "; ".join(e.message for e in errors)
                raise ValueError(f"State machine emitted invalid workflow event: {err_msg}")

        # Update persistence store
        if not incident:
            self.store.create_incident(
                incident_id=formatted_inc_id,
                initial_state=to_state,
                status=status,
            )
        else:
            self.store.update_incident_state(
                incident_id=formatted_inc_id, new_state=to_state, status=status
            )

        self.store.record_transition(
            event=event_payload,
            input_hash=in_hash,
            output_hash=out_hash,
            reason=reason or f"Transition to {to_state}",
        )

        return event_payload
