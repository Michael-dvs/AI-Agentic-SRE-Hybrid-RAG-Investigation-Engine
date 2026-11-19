"""Offline delayed join for DEV and separately provisioned H-G3 records.

C15 hashes are not signatures: a separately protected trusted chain head is required.
C16 emits a final-dossier-bound closure event when its audit sink succeeds.
Source directories are trusted configuration and must contain only the selected split;
this runner cannot prove provenance or safely separate a mixed-split registry.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from observability.audit_chain import compute_request_fingerprint, verify_chain_integrity
from orchestrator.dossier import compute_canonical_dossier_hash


class EvaluationBlocked(PermissionError):
    """The closure or isolation prerequisites cannot be established."""


def _private_directory(path: Path) -> Path:
    path = Path(path).absolute()
    if path.resolve(strict=True) != path:
        raise EvaluationBlocked("Directory must not traverse symbolic links")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise EvaluationBlocked("Evaluator directories must be owner-only")
    return path


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def _closure_payload(incident_id: str, version: int, dossier_hash: str) -> dict[str, Any]:
    return {"incident_id": incident_id, "dossier_version": version,
            "dossier_hash": dossier_hash, "terminal_state": "CLOSED"}


def join_evaluator(*, store: Any, audit_events: list[dict[str, Any]], trusted_audit_head: str,
                   incident_id: str, run_id: str, split_id: str, source_dir: Path,
                   output_dir: Path, runtime_dir: Path) -> Path:
    """Join one post-CLOSED record from a dedicated DEV or H-G3 directory.

    Each source is an owner-only JSON object named <run_id>.json. The caller must
    independently provision and verify a single-split directory; never supply a
    mixed registry. H-G4 and all other split identifiers are rejected before source
    access. Paths and the complete audit chain's independently trusted head are
    trusted configuration; hashing alone cannot establish their trustworthiness.
    """
    if split_id == "H-G4":
        raise EvaluationBlocked("H-G4 split remains strictly sealed until C21")
    if split_id not in ("dev", "H-G3"):
        raise EvaluationBlocked("Unsupported evaluation split")
    if not re.fullmatch(r"inc-[a-z0-9-]+", incident_id) or not re.fullmatch(r"run-[a-z0-9-]+", run_id):
        raise EvaluationBlocked("Invalid opaque identifier")
    incident = store.get_incident(incident_id)
    if not incident or incident.get("current_state") != "CLOSED" or incident.get("status") != "CLOSED":
        raise EvaluationBlocked("PREMATURE_EVALUATION_BLOCKED")
    record = store.get_dossier(incident_id)
    if not record or not isinstance(record.get("dossier_json"), dict):
        raise EvaluationBlocked("Missing closed dossier")
    dossier = record["dossier_json"]
    version = record.get("dossier_version")
    digest = record.get("dossier_hash")
    if (not isinstance(version, int) or isinstance(version, bool) or version < 1
            or dossier.get("incident_id") != incident_id or dossier.get("dossier_version") != version
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or dossier.get("dossier_hash") != digest or compute_canonical_dossier_hash(dossier) != digest):
        raise EvaluationBlocked("Closed dossier integrity mismatch")
    if (not audit_events or not isinstance(trusted_audit_head, str)
            or not re.fullmatch(r"[0-9a-f]{64}", trusted_audit_head)):
        raise EvaluationBlocked("Missing trusted audit anchor")
    try:
        valid, _ = verify_chain_integrity(audit_events)
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid or audit_events[-1].get("event_hash") != trusted_audit_head:
        raise EvaluationBlocked("Invalid or unanchored audit chain")
    fingerprint = compute_request_fingerprint(_closure_payload(incident_id, version, digest))
    if not any(event.get("actor_ref") == "principal_reviewer"
               and event.get("action") == "WORKFLOW_TRANSITION"
               and event.get("target_ref") == f"{incident_id}:v{version}"
               and event.get("result_code") == "ALLOW" and event.get("reason_code") == "OK"
               and event.get("request_fingerprint") == fingerprint for event in audit_events):
        raise EvaluationBlocked("No final-dossier-bound closure audit event")

    source = _private_directory(Path(source_dir))
    output = _private_directory(Path(output_dir))
    runtime = Path(runtime_dir).resolve(strict=True)
    if _overlap(source, output) or _overlap(source, runtime) or _overlap(output, runtime):
        raise EvaluationBlocked("Evaluator and runtime paths must be disjoint")
    # O_NOFOLLOW plus fstat prevents symlink and hard-link inputs from redirecting reads.
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(f"{run_id}.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_fd)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise EvaluationBlocked("Evaluation source must be an owner-only regular file")
            with os.fdopen(fd, encoding="utf-8") as stream:
                fd = -1
                ground_truth = json.load(stream)
        finally:
            if fd != -1:
                os.close(fd)
    finally:
        os.close(source_fd)
    if (not isinstance(ground_truth, dict) or ground_truth.get("split_id") != split_id
            or ground_truth.get("run_id") != run_id or ground_truth.get("incident_id") != incident_id):
        raise EvaluationBlocked(f"Source is not a matching {'DEV' if split_id == 'dev' else 'H-G3'} record")
    payload = {"run_id": run_id, "incident_id": incident_id,
               "dossier": dossier, "ground_truth": ground_truth}
    output_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(f"{run_id}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=output_fd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = -1
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        except BaseException:
            os.unlink(f"{run_id}.json", dir_fd=output_fd)
            raise
        finally:
            if fd != -1:
                os.close(fd)
    finally:
        os.close(output_fd)
    return output / f"{run_id}.json"


def join_dev(*, store: Any, audit_events: list[dict[str, Any]], trusted_audit_head: str,
             incident_id: str, run_id: str, dev_source_dir: Path,
             output_dir: Path, runtime_dir: Path) -> Path:
    """Preserve the DEV-only API with the same isolation and closure checks."""
    return join_evaluator(store=store, audit_events=audit_events, trusted_audit_head=trusted_audit_head,
                          incident_id=incident_id, run_id=run_id, split_id="dev",
                          source_dir=dev_source_dir, output_dir=output_dir, runtime_dir=runtime_dir)
