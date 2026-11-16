"""Append-only, cryptographically chained Security Audit Logger (audit-event.v1, NFR-005, C08)."""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import uuid
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from observability.audit_chain import AuditWriteError, compute_chain_hash, compute_request_fingerprint, verify_chain_integrity

_CONTRACT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
    / "audit-event.v1.schema.json"
)

_VALIDATOR: Draft202012Validator | None = None
if _CONTRACT_PATH.exists():
    _schema = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    _VALIDATOR = Draft202012Validator(_schema, format_checker=FormatChecker())


class SecurityAuditLogger:
    """Independent append-only security audit log writer with SHA-256 cryptographic hash chaining."""

    def __init__(self, log_path: pathlib.Path | str | None = None) -> None:
        self.log_path = pathlib.Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_event_hash: str | None = None
        self.events: list[dict[str, Any]] = []

    def record_event(
        self,
        actor_ref: str,
        action: str,
        target_ref: str,
        result_code: str,
        reason_code: str,
        request_payload: Any = None,
        incident_id: str | None = None,
        correlation_id: str | None = None,
        target_version: str | None = "1.0",
        policy_version: str = "1.0.0",
        workflow_version: str = "1.0.0",
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record a single validated audit event into the append-only ledger."""
        now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        event_id = f"aud-{uuid.uuid4().hex[:16]}"
        corr_id = correlation_id or f"corr-{uuid.uuid4().hex[:12]}"

        # Compute request fingerprint
        payload_bytes = json.dumps(request_payload or {}, sort_keys=True).encode("utf-8")
        req_fp = hashlib.sha256(payload_bytes).hexdigest()

        # Chain hash computation
        prev_hash = self.last_event_hash
        hash_seed = (
            f"{prev_hash or 'GENESIS'}::{event_id}::{now_z}::{actor_ref}::{action}::"
            f"{target_ref}::{result_code}::{reason_code}::{req_fp}"
        ).encode("utf-8")
        event_hash = hashlib.sha256(hash_seed).hexdigest()

        # Format incident_id to match pattern ^inc-[a-z0-9-]+$ or null
        formatted_inc_id = incident_id
        if formatted_inc_id and not formatted_inc_id.startswith("inc-"):
            formatted_inc_id = f"inc-{formatted_inc_id}"

        event: dict[str, Any] = {
            "schema_version": "1.0",
            "audit_event_id": event_id,
            "occurred_at": now_z,
            "incident_id": formatted_inc_id,
            "correlation_id": corr_id,
            "actor_ref": actor_ref,
            "action": action,
            "target_ref": target_ref,
            "target_version": target_version,
            "policy_version": policy_version,
            "workflow_version": workflow_version,
            "request_fingerprint": req_fp,
            "result_code": result_code,
            "reason_code": reason_code,
            "sanitized": True,
            "evidence_refs": evidence_refs or [],
            "prev_event_hash": prev_hash,
            "event_hash": event_hash,
        }

        # Validate against schema contract
        if _VALIDATOR is not None:
            errors = list(_VALIDATOR.iter_errors(event))
            if errors:
                err_msg = "; ".join(f"{e.message} at {list(e.path)}" for e in errors)
                raise ValueError(f"Generated audit event violates audit-event.v1 schema: {err_msg}")

        # Update chain state
        self.last_event_hash = event_hash
        self.events.append(event)

        # Append to file if configured (FAIL_CLOSED)
        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")
                    f.flush()
            except Exception as exc:
                raise AuditWriteError(
                    f"FAIL_CLOSED: Failed to write audit event {event_id} to {self.log_path}: {exc}"
                ) from exc

        return event

