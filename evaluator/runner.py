"""Offline DEV-only delayed join. All paths and the audit head are trusted configuration.

C15 hashes are not signatures: a separately protected trusted chain head is required.
C16 currently emits no final-dossier-bound closure event, so its ordinary approval
alone cannot pass this gate. The producer must record the closure payload below
in the C15 chain after persisting the final dossier.
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


def join_dev(*, store: Any, audit_events: list[dict[str, Any]], trusted_audit_head: str,
             incident_id: str, run_id: str, dev_source_dir: Path,
             output_dir: Path, runtime_dir: Path) -> Path:
    """Write a joined JSON artifact in a private evaluator directory, returning its path.

    The dedicated DEV source consists of one JSON object per run named <run_id>.json,
    with split_id='dev', incident_id and run_id. Never pass mixed-split registries.
    Source and output directories must already exist and be mode 0700 (or stricter),
    outside and disjoint from the runtime directory. The caller supplies the complete
    chain and an independently trusted head; neither can be established by hashing alone.
    """
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

    source = _private_directory(Path(dev_source_dir))
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
                raise EvaluationBlocked("DEV source must be an owner-only regular file")
            with os.fdopen(fd, encoding="utf-8") as stream:
                fd = -1
                ground_truth = json.load(stream)
        finally:
            if fd != -1:
                os.close(fd)
    finally:
        os.close(source_fd)
    if (not isinstance(ground_truth, dict) or ground_truth.get("split_id") != "dev"
            or ground_truth.get("run_id") != run_id or ground_truth.get("incident_id") != incident_id):
        raise EvaluationBlocked("Source is not a matching DEV record")
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
