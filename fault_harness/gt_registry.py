"""Restricted append-only Ground Truth Registry for C04 (RULE-002 / AT-008 / NFR-011).

Physically and logically isolated from runtime investigator components.
Enforces principal authentication, append-only immutability, and post-CLOSED evaluation join.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import re
from typing import Any

from fault_harness.scenarios import (
    AUTHORIZED_EVALUATOR_PRINCIPAL,
    SCENARIO_CATALOG,
    SPLIT_FREEZE_HASH,
    get_restricted_oracle,
)
from services.common.fault_control import (
    AUTHORIZED_HARNESS_PRINCIPAL,
    FORBIDDEN_RUNTIME_PRINCIPALS,
)
from services.common.telemetry import utc_now_iso

_RUN_ID_RE = re.compile(r"^run-[a-z0-9-]+$")
_INC_ID_RE = re.compile(r"^inc-[a-z0-9-]+$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class GroundTruthAccessDeniedError(PermissionError):
    """Raised when an unauthorized principal or unclosed workflow attempts to read/write GT."""

    def __init__(self, error_code: str, message: str, audit_record: dict[str, Any]) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.audit_record = audit_record


class GroundTruthImmutabilityError(RuntimeError):
    """Raised when attempting to overwrite or mutate an already-frozen ground-truth label."""


class RestrictedGroundTruthRegistry:
    """Isolated append-only Ground Truth Registry stored outside container mounts."""

    def __init__(
        self,
        storage_dir: str | pathlib.Path | None = None,
        harness_token: str | None = None,
        evaluator_token: str | None = None,
    ) -> None:
        default_dir = (
            pathlib.Path(__file__).resolve().parent.parent
            / "restricted"
            / "gt_registry"
        )
        self.storage_dir = pathlib.Path(
            storage_dir or os.getenv("RESTRICTED_EVAL_ROOT", str(default_dir))
        )
        self.harness_token = harness_token or os.getenv(
            "HARNESS_CONTROL_TOKEN", "SYNTH-HARNESS-CTRL-KEY-C04"
        )
        self.evaluator_token = evaluator_token or os.getenv(
            "EVALUATOR_CONTROL_TOKEN", "SYNTH-EVALUATOR-KEY-C04"
        )
        self.records_file = self.storage_dir / "ground_truth_records.jsonl"
        self.outcomes_file = self.storage_dir / "recovery_outcomes.jsonl"
        self.audit_file = self.storage_dir / "gt_access_audit.jsonl"
        self._ensure_isolated_storage()

    def _ensure_isolated_storage(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.storage_dir, 0o700)
        except OSError:
            pass
        for fpath in (self.records_file, self.outcomes_file, self.audit_file):
            if not fpath.exists():
                fpath.write_text("", encoding="utf-8")
            try:
                os.chmod(fpath, 0o600)
            except OSError:
                pass

    def _append_jsonl(self, path: pathlib.Path, obj: dict[str, Any]) -> None:
        line = json.dumps(obj, separators=(",", ":"), sort_keys=True) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()

    def _record_audit(
        self,
        action: str,
        caller_principal: str,
        decision: str,
        reason_code: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "timestamp": utc_now_iso(),
            "action": action,
            "caller_principal": caller_principal,
            "run_id": run_id,
            "decision": decision,
            "reason_code": reason_code,
        }
        self._append_jsonl(self.audit_file, event)
        return event

    def _verify_harness_caller(
        self, action: str, caller_principal: str, caller_token: str, run_id: str | None = None
    ) -> None:
        if (
            caller_principal in FORBIDDEN_RUNTIME_PRINCIPALS
            or caller_principal != AUTHORIZED_HARNESS_PRINCIPAL
        ):
            audit = self._record_audit(
                action, caller_principal, "DENY", "ERR_FORBIDDEN_PRINCIPAL", run_id
            )
            raise GroundTruthAccessDeniedError(
                "ERR_FORBIDDEN_PRINCIPAL",
                f"Principal '{caller_principal}' is forbidden from accessing Ground Truth Registry",
                audit,
            )
        if not caller_token or not hmac.compare_digest(caller_token, self.harness_token):
            audit = self._record_audit(
                action, caller_principal, "DENY", "ERR_INVALID_HARNESS_TOKEN", run_id
            )
            raise GroundTruthAccessDeniedError(
                "ERR_INVALID_HARNESS_TOKEN",
                "Invalid or missing HARNESS_CONTROL_TOKEN for Ground Truth Registry",
                audit,
            )

    def _find_frozen_record(self, run_id: str) -> dict[str, Any] | None:
        if not self.records_file.exists():
            return None
        for line in self.records_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("run_id") == run_id:
                return obj
        return None

    def freeze_ground_truth(
        self,
        *,
        run_id: str,
        incident_id: str,
        scenario_id: str,
        fault_seed: int,
        injected_parameters: list[dict[str, Any]],
        caller_principal: str,
        caller_token: str,
    ) -> dict[str, Any]:
        """Freeze ground-truth record append-only BEFORE fault onset / alert intake."""
        self._verify_harness_caller("freeze_ground_truth", caller_principal, caller_token, run_id)

        if not _RUN_ID_RE.match(run_id):
            raise ValueError(f"run_id '{run_id}' must match ^run-[a-z0-9-]+$")
        if not _INC_ID_RE.match(incident_id):
            raise ValueError(f"incident_id '{incident_id}' must match ^inc-[a-z0-9-]+$")
        if scenario_id not in SCENARIO_CATALOG:
            raise ValueError(f"Unknown scenario_id '{scenario_id}'")

        existing = self._find_frozen_record(run_id)
        if existing is not None:
            self._record_audit(
                "freeze_ground_truth",
                caller_principal,
                "DENY",
                "ERR_GT_RECORD_ALREADY_FROZEN",
                run_id,
            )
            raise GroundTruthImmutabilityError(
                f"Ground-truth record for run_id '{run_id}' is already frozen and immutable"
            )

        oracle = get_restricted_oracle(scenario_id, caller_principal)
        pub_spec = SCENARIO_CATALOG[scenario_id]
        frozen_at = utc_now_iso()

        core_payload = {
            "gt_record_id": f"gt-{run_id}",
            "run_id": run_id,
            "incident_id": incident_id,
            "scenario_id": scenario_id,
            "split_id": oracle.split_id,
            "split_freeze_hash": SPLIT_FREEZE_HASH,
            "fault_category": oracle.fault_category,
            "target_services": pub_spec.target_services,
            "actual_root_cause": {
                "expected_root_cause_services": oracle.expected_root_cause_services,
                "expected_fault_types": oracle.expected_fault_types,
                "expected_relevant_chunk_ids": oracle.expected_relevant_chunk_ids,
                "is_healthy_control": oracle.is_healthy_control,
                "is_multi_fault": oracle.is_multi_fault,
            },
            "injected_parameters": injected_parameters,
            "fault_seed": fault_seed,
            "expected_impact": pub_spec.expected_symptoms,
            "label_frozen_at": frozen_at,
        }
        record_sha256 = hashlib.sha256(
            json.dumps(core_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        record = {**core_payload, "record_sha256": record_sha256}

        self._append_jsonl(self.records_file, record)
        self._record_audit(
            "freeze_ground_truth", caller_principal, "ALLOW", "GT_FROZEN_PRE_ONSET", run_id
        )
        return record

    def record_execution_outcome(
        self,
        *,
        run_id: str,
        fault_onset_at: str,
        fault_end_at: str,
        injection_outcome: str,
        recovery_outcome: str,
        leakage_detected: bool,
        evidence_refs: list[str],
        caller_principal: str,
        caller_token: str,
    ) -> dict[str, Any]:
        """Append post-run onset/end timestamps and recovery outcome without mutating frozen label."""
        self._verify_harness_caller(
            "record_execution_outcome", caller_principal, caller_token, run_id
        )
        frozen = self._find_frozen_record(run_id)
        if frozen is None:
            raise KeyError(f"Cannot record outcome: no frozen GT record found for '{run_id}'")

        outcome_entry = {
            "run_id": run_id,
            "frozen_record_sha256": frozen["record_sha256"],
            "fault_onset_at": fault_onset_at,
            "fault_end_at": fault_end_at,
            "injection_outcome": injection_outcome,
            "recovery_outcome": recovery_outcome,
            "leakage_detected": leakage_detected,
            "evidence_refs": evidence_refs,
            "recorded_at": utc_now_iso(),
        }
        self._append_jsonl(self.outcomes_file, outcome_entry)
        self._record_audit(
            "record_execution_outcome",
            caller_principal,
            "ALLOW",
            "OUTCOME_APPENDED",
            run_id,
        )
        return outcome_entry

    def read_for_offline_evaluation(
        self,
        *,
        run_id: str,
        caller_principal: str,
        caller_token: str,
        investigation_status: str,
        closed_dossier_version: int,
        closed_dossier_hash: str,
    ) -> dict[str, Any]:
        """Join frozen GT record ONLY for principal:offline-evaluator after status == CLOSED."""
        if (
            caller_principal in FORBIDDEN_RUNTIME_PRINCIPALS
            or caller_principal != AUTHORIZED_EVALUATOR_PRINCIPAL
        ):
            audit = self._record_audit(
                "read_for_offline_evaluation",
                caller_principal,
                "DENY",
                "ERR_FORBIDDEN_PRINCIPAL",
                run_id,
            )
            raise GroundTruthAccessDeniedError(
                "ERR_FORBIDDEN_PRINCIPAL",
                f"Principal '{caller_principal}' is forbidden from reading Ground Truth Registry",
                audit,
            )

        if not caller_token or not hmac.compare_digest(caller_token, self.evaluator_token):
            audit = self._record_audit(
                "read_for_offline_evaluation",
                caller_principal,
                "DENY",
                "ERR_INVALID_EVALUATOR_TOKEN",
                run_id,
            )
            raise GroundTruthAccessDeniedError(
                "ERR_INVALID_EVALUATOR_TOKEN",
                "Invalid or missing EVALUATOR_CONTROL_TOKEN",
                audit,
            )

        if investigation_status != "CLOSED":
            audit = self._record_audit(
                "read_for_offline_evaluation",
                caller_principal,
                "DENY",
                "ERR_INVESTIGATION_NOT_CLOSED",
                run_id,
            )
            raise GroundTruthAccessDeniedError(
                "ERR_INVESTIGATION_NOT_CLOSED",
                f"Cannot join ground truth while investigation status is '{investigation_status}' (must be CLOSED)",
                audit,
            )

        if not _SHA256_RE.match(closed_dossier_hash):
            audit = self._record_audit(
                "read_for_offline_evaluation",
                caller_principal,
                "DENY",
                "ERR_INVALID_DOSSIER_HASH",
                run_id,
            )
            raise GroundTruthAccessDeniedError(
                "ERR_INVALID_DOSSIER_HASH",
                "closed_dossier_hash must be a valid 64-character lowercase hex SHA-256",
                audit,
            )

        frozen = self._find_frozen_record(run_id)
        if frozen is None:
            raise KeyError(f"No frozen ground-truth record found for run_id '{run_id}'")

        latest_outcome: dict[str, Any] | None = None
        if self.outcomes_file.exists():
            for line in self.outcomes_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                if obj.get("run_id") == run_id:
                    latest_outcome = obj

        onset_at = (
            latest_outcome["fault_onset_at"]
            if latest_outcome
            else frozen["label_frozen_at"]
        )
        end_at = (
            latest_outcome["fault_end_at"]
            if latest_outcome
            else frozen["label_frozen_at"]
        )
        rc = frozen["actual_root_cause"]

        # Build evaluation-manifest.v1.schema.json compliant object
        eval_manifest = {
            "schema_version": "1.0",
            "evaluation_manifest_id": f"eval-man-{run_id}",
            "run_id": frozen["run_id"],
            "incident_id": frozen["incident_id"],
            "scenario_id": frozen["scenario_id"],
            "split_id": frozen["split_id"],
            "split_freeze_hash": frozen["split_freeze_hash"],
            "fault_seed": frozen["fault_seed"],
            "fault_onset_at": onset_at,
            "fault_end_at": end_at,
            "expected_root_cause_services": rc["expected_root_cause_services"],
            "expected_fault_types": rc["expected_fault_types"],
            "expected_relevant_chunk_ids": rc["expected_relevant_chunk_ids"],
            "is_healthy_control": rc["is_healthy_control"],
            "is_multi_fault": rc["is_multi_fault"],
            "required_terminal_state": "CLOSED",
            "closed_dossier_version": closed_dossier_version,
            "closed_dossier_hash": closed_dossier_hash,
            "label_frozen_at": frozen["label_frozen_at"],
        }
        self._record_audit(
            "read_for_offline_evaluation",
            caller_principal,
            "ALLOW",
            "EVALUATION_JOIN_AUTHORIZED",
            run_id,
        )
        return {
            "evaluation_manifest": eval_manifest,
            "frozen_record": frozen,
            "execution_outcome": latest_outcome,
        }

    def list_audit_events(self) -> list[dict[str, Any]]:
        if not self.audit_file.exists():
            return []
        return [
            json.loads(line)
            for line in self.audit_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

