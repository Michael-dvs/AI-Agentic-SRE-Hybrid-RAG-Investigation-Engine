"""Cryptographic Hash-Chained Audit Ledger (audit-event.v1, BRD §12.2, ADR-S06, C15)."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import threading
import uuid
from typing import Any, Iterator

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



class _LazyAuditEvents(list[dict[str, Any]]):
    """Load historical events only when a consumer explicitly inspects them."""

    def __init__(self, path: pathlib.Path, expected_count: int) -> None:
        super().__init__()
        self._path = path
        self._expected_count = expected_count
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            loaded = [
                json.loads(line)
                for line in self._path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise AuditWriteError(
                f"FAIL_CLOSED: Existing audit log cannot be loaded from {self._path}: {exc}"
            ) from exc
        if len(loaded) != self._expected_count:
            raise AuditWriteError(
                "FAIL_CLOSED: Audit event count changed after incremental initialization"
            )
        super().extend(loaded)
        self._loaded = True

    def __iter__(self) -> Iterator[dict[str, Any]]:
        self._ensure_loaded()
        return super().__iter__()

    def __len__(self) -> int:
        if not self._loaded:
            return self._expected_count
        return super().__len__()

    def __getitem__(self, index: Any) -> Any:
        self._ensure_loaded()
        return super().__getitem__(index)

    def append_persisted(self, event: dict[str, Any]) -> None:
        self._expected_count += 1
        if self._loaded:
            super().append(event)


def _read_tail_event(path: pathlib.Path, max_bytes: int = 1_048_576) -> dict[str, Any] | None:
    size = path.stat().st_size
    if size == 0:
        return None
    with path.open("rb") as handle:
        handle.seek(max(0, size - max_bytes))
        payload = handle.read()
    lines = [line for line in payload.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise AuditWriteError(
            f"FAIL_CLOSED: Audit tail is not valid JSON at {path}: {exc}"
        ) from exc


class HashChainedAuditStore:
    """Append-only security audit store with cached tail verification and serialized writes."""

    def __init__(self, log_path: pathlib.Path | str | None = None) -> None:
        self.log_path = pathlib.Path(log_path) if log_path else None
        self.checkpoint_path = (
            self.log_path.with_name(f"{self.log_path.name}.checkpoint.json")
            if self.log_path
            else None
        )
        self.last_event_hash: str | None = None
        self.events: list[dict[str, Any]] = []
        self.initialization_mode = "memory"
        self._lock = threading.RLock()
        self._log_size = 0
        self._log_mtime_ns = 0
        if not self.log_path:
            return

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            if self.log_path.exists():
                stat = self.log_path.stat()
                self._log_size = stat.st_size
                self._log_mtime_ns = stat.st_mtime_ns
            self.initialization_mode = "empty"
            return
        if self._restore_from_checkpoint():
            self.initialization_mode = "tail"
            return

        try:
            existing_events = [
                json.loads(line)
                for line in self.log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise AuditWriteError(
                f"FAIL_CLOSED: Existing audit log cannot be loaded from {self.log_path}: {exc}"
            ) from exc
        is_valid, violations = verify_chain_integrity(existing_events)
        if not is_valid:
            raise AuditWriteError(
                f"FAIL_CLOSED: Existing audit chain is invalid at {self.log_path}: {violations}"
            )
        self.events = existing_events
        self.last_event_hash = existing_events[-1]["event_hash"] if existing_events else None
        stat = self.log_path.stat()
        self._log_size = stat.st_size
        self._log_mtime_ns = stat.st_mtime_ns
        self.initialization_mode = "full"
        self._write_checkpoint()

    def _restore_from_checkpoint(self) -> bool:
        if not self.checkpoint_path or not self.checkpoint_path.exists() or not self.log_path:
            return False
        try:
            checkpoint = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            stat = self.log_path.stat()
            if (
                checkpoint.get("version") != 1
                or checkpoint.get("file_size") != stat.st_size
                or checkpoint.get("file_mtime_ns") != stat.st_mtime_ns
                or not isinstance(checkpoint.get("event_count"), int)
                or checkpoint["event_count"] < 1
            ):
                return False
            tail = _read_tail_event(self.log_path)
            if not tail or tail.get("event_hash") != checkpoint.get("last_event_hash"):
                return False
            recomputed = compute_chain_hash(
                prev_hash=tail.get("prev_event_hash"),
                event_id=tail.get("audit_event_id", ""),
                occurred_at=tail.get("occurred_at", ""),
                actor_ref=tail.get("actor_ref", ""),
                action=tail.get("action", ""),
                target_ref=tail.get("target_ref", ""),
                result_code=tail.get("result_code", ""),
                reason_code=tail.get("reason_code", ""),
                request_fingerprint=tail.get("request_fingerprint", ""),
            )
            if recomputed != tail.get("event_hash") or tail.get("sanitized") is not True:
                return False
        except (OSError, ValueError, TypeError, AuditWriteError):
            return False

        self.last_event_hash = str(checkpoint["last_event_hash"])
        self.events = _LazyAuditEvents(self.log_path, checkpoint["event_count"])
        self._log_size = stat.st_size
        self._log_mtime_ns = stat.st_mtime_ns
        return True

    def _write_checkpoint(self) -> None:
        if not self.checkpoint_path or not self.log_path or not self.last_event_hash:
            return
        stat = self.log_path.stat()
        checkpoint = {
            "version": 1,
            "file_size": stat.st_size,
            "file_mtime_ns": stat.st_mtime_ns,
            "event_count": len(self.events),
            "last_event_hash": self.last_event_hash,
        }
        temporary = self.checkpoint_path.with_suffix(f"{self.checkpoint_path.suffix}.tmp")
        try:
            temporary.write_text(
                json.dumps(checkpoint, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, self.checkpoint_path)
        except OSError:
            temporary.unlink(missing_ok=True)

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
        """Validate and durably append one event without allowing concurrent chain forks."""
        with self._lock:
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

            if _VALIDATOR is not None:
                errors = list(_VALIDATOR.iter_errors(event))
                if errors:
                    err_msg = "; ".join(f"{e.message} at {list(e.path)}" for e in errors)
                    raise ValueError(f"Generated audit event violates audit-event.v1 schema: {err_msg}")

            if self.log_path:
                try:
                    if self.log_path.exists():
                        stat = self.log_path.stat()
                        if (
                            stat.st_size != self._log_size
                            or (
                                self._log_mtime_ns
                                and stat.st_mtime_ns != self._log_mtime_ns
                            )
                        ):
                            raise AuditWriteError(
                                "FAIL_CLOSED: Audit log changed outside the active writer"
                            )
                    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                    with open(self.log_path, "a", encoding="utf-8") as handle:
                        handle.write(line)
                        handle.flush()
                        os.fsync(handle.fileno())
                    stat = self.log_path.stat()
                    self._log_size = stat.st_size
                    self._log_mtime_ns = stat.st_mtime_ns
                except AuditWriteError:
                    raise
                except Exception as exc:
                    raise AuditWriteError(
                        f"FAIL_CLOSED: Failed to write audit event {event_id} to {self.log_path}: {exc}"
                    ) from exc

            self.last_event_hash = event_hash
            if isinstance(self.events, _LazyAuditEvents):
                self.events.append_persisted(event)
            else:
                self.events.append(event)
            self._write_checkpoint()
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
