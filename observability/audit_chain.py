"""Cryptographic Hash-Chained Audit Ledger (audit-event.v1, BRD §12.2, ADR-S06, C15)."""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import uuid
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

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


class AuditWriteError(IOError):
    """Raised when appending to the independent security audit log fails, enforcing FAIL_CLOSED policy."""
    def __init__(self, message: str = "Failed to write independent security audit event") -> None:
        super().__init__(message)
        self.code = "AUDIT_WRITE_FAILED"


def compute_chain_hash(
    prev_hash: str | None,
    event_id: str,
    occurred_at: str,
    actor_ref: str,
    action: str,
    target_ref: str,
    result_code: str,
    reason_code: str,
    request_fingerprint: str,
) -> str:
    """Compute deterministic SHA-256 hash chaining seed compatible with gateway.audit."""
    seed = (
        f"{prev_hash or 'GENESIS'}::{event_id}::{occurred_at}::{actor_ref}::{action}::"
        f"{target_ref}::{result_code}::{reason_code}::{request_fingerprint}"
    ).encode("utf-8")
    return hashlib.sha256(seed).hexdigest()


def compute_request_fingerprint(request_payload: Any) -> str:
    """Compute SHA-256 fingerprint of request payload."""
    payload_bytes = json.dumps(request_payload or {}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest()


class HashChainedAuditStore:
    """Independent append-only security audit store with strict SHA-256 hash chaining and fail-closed persistence."""

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
        """Record and validate a security audit event, appending it to the cryptographic chain.

        Enforces FAIL_CLOSED semantics: any schema error or disk write failure raises an
        exception immediately and prevents state advancement.
        """
        now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        event_id = f"aud-{uuid.uuid4().hex[:16]}"
        corr_id = correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        req_fp = compute_request_fingerprint(request_payload)

        prev_hash = self.last_event_hash
        event_hash = compute_chain_hash(
            prev_hash=prev_hash,
            event_id=event_id,
            occurred_at=now_z,
            actor_ref=actor_ref,
            action=action,
            target_ref=target_ref,
            result_code=result_code,
            reason_code=reason_code,
            request_fingerprint=req_fp,
        )

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

        # Validate against audit-event.v1 contract
        if _VALIDATOR is not None:
            errors = list(_VALIDATOR.iter_errors(event))
            if errors:
                err_msg = "; ".join(f"{e.message} at {list(e.path)}" for e in errors)
                raise ValueError(f"Generated audit event violates audit-event.v1 schema: {err_msg}")

        # Persist to disk fail-closed
        if self.log_path:
            try:
                line = json.dumps(event) + "\n"
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
            except Exception as exc:
                raise AuditWriteError(
                    f"FAIL_CLOSED: Failed to write audit event {event_id} to {self.log_path}: {exc}"
                ) from exc

        # Update in-memory state only upon successful persistence
        self.last_event_hash = event_hash
        self.events.append(event)
        return event


# Semantic alias matching C15 / C16 audit chain nomenclature (ADR-S06)
AuditHashChain = HashChainedAuditStore


def verify_chain_integrity(events: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Verify cryptographic integrity of an ordered sequence of audit events.

    Returns:
        (is_valid, violation_reasons)
    """
    violations: list[str] = []
    if not events:
        return True, []

    expected_prev_hash: str | None = None

    for idx, ev in enumerate(events):
        event_id = ev.get("audit_event_id", f"index-{idx}")

        # 1. Verify prev_event_hash linkage
        actual_prev = ev.get("prev_event_hash")
        if idx == 0:
            if actual_prev is not None:
                violations.append(
                    f"Genesis event {event_id} at index 0 must have prev_event_hash=None, found {actual_prev}"
                )
        else:
            if actual_prev != expected_prev_hash:
                violations.append(
                    f"Chain break at event {event_id} (index {idx}): expected prev_event_hash {expected_prev_hash}, found {actual_prev}"
                )

        # 2. Verify re-computed event_hash
        recomputed_hash = compute_chain_hash(
            prev_hash=actual_prev,
            event_id=ev.get("audit_event_id", ""),
            occurred_at=ev.get("occurred_at", ""),
            actor_ref=ev.get("actor_ref", ""),
            action=ev.get("action", ""),
            target_ref=ev.get("target_ref", ""),
            result_code=ev.get("result_code", ""),
            reason_code=ev.get("reason_code", ""),
            request_fingerprint=ev.get("request_fingerprint", ""),
        )
        actual_hash = ev.get("event_hash")
        if actual_hash != recomputed_hash:
            violations.append(
                f"Hash mismatch at event {event_id} (index {idx}): expected {recomputed_hash}, found {actual_hash} (tamper detected)"
            )

        # 3. Verify sanitization flag
        if ev.get("sanitized") is not True:
            violations.append(f"Event {event_id} has sanitized={ev.get('sanitized')} (must be True)")

        expected_prev_hash = actual_hash

    return len(violations) == 0, violations
