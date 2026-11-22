#!/usr/bin/env python3
"""Freeze a C21 candidate after caller-attested tests, without opening holdout records.

The two restricted files are read as opaque bytes for hashing only. Hash equality
is not proof of access history, isolation, or permission to run a benchmark.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import stat
import json
import pathlib
import re
import sys
from typing import Any, Mapping

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_rollback_restore import (
    G1_EXPECTED_GT_HASH,
    G1_EXPECTED_Q_HASH,
    _sha256_file,
    _sha256_json,
    build_final_release_manifest,
)

C20_MANIFEST = pathlib.Path("evidence/c20-20261120T093645Z/C20/final-release-manifest.json")
C20_SELF_SHA256 = "bc17ccad777b2eae440028557749b201a6c37725a8ca8083ba9af04d42bb7f20"
PROTECTED_DIRS = ("orchestrator", "gateway", "services", "knowledge_base", "observability", "fault_harness", "traffic")
SEAL_HASHES = {
    "restricted/evaluator_queries/holdout_queries.json": G1_EXPECTED_Q_HASH,
    "restricted/gt_registry/ground_truth_records.jsonl": G1_EXPECTED_GT_HASH,
}
VERSION_FIELDS = (
    "prompt_template_sha256", "kb_active_alias", "kb_index_version", "kb_manifest_hash",
    "kb_document_count", "kb_chunk_count",
)


class PreflightError(RuntimeError):
    """The candidate must not be frozen."""


def run_preflight(
    root: pathlib.Path,
    *,
    tests_completed: bool,
    target: pathlib.Path | None = None,
    baseline_self_sha256: str = C20_SELF_SHA256,
    seal_hashes: Mapping[str, str] = SEAL_HASHES,
) -> pathlib.Path:
    """Create candidate evidence; tests_completed is a caller attestation, not proof.

    baseline_self_sha256 and seal_hashes may be overridden for synthetic fixtures;
    production callers must retain the defaults. target, if provided, must be a
    new evidence/c21-preflight-<timestamp>/C21 directory under root.
    """
    if tests_completed is not True:
        raise PreflightError("Tests must be completed before requesting a candidate freeze")
    root = pathlib.Path(root).resolve(strict=True)
    baseline_path = root / C20_MANIFEST
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        if not isinstance(baseline, dict):
            raise PreflightError("Invalid C20 manifest")
        claimed = baseline.get("manifest_self_sha256")
        baseline_body = {key: value for key, value in baseline.items() if key != "manifest_self_sha256"}
        if claimed != baseline_self_sha256 or _sha256_json(baseline_body) != claimed:
            raise PreflightError("C20 manifest integrity mismatch")

        if set(seal_hashes) != set(SEAL_HASHES):
            raise PreflightError("The two required seal files must be specified")
        seals = {}
        for relative, expected in seal_hashes.items():
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise PreflightError("Invalid seal baseline digest")
            digest = _sha256_file(root / relative)
            if digest != expected:
                raise PreflightError("Holdout source hash mismatch")
            seals[relative] = {"baseline_sha256": expected, "sha256": digest, "matches": True}

        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        query_info = (root / "restricted/evaluator_queries/holdout_queries.json").stat()
        query_dir_info = (root / "restricted/evaluator_queries").stat()
        query_private = (
            query_info.st_uid == os.geteuid() and query_dir_info.st_uid == os.geteuid()
            and not (query_info.st_mode & 0o077 or query_dir_info.st_mode & 0o077)
        )
        if target is None:
            target = root / "evidence" / f"c21-preflight-{timestamp}" / "C21"
        else:
            target = pathlib.Path(target)
            if not target.is_absolute():
                target = root / target
        target = target.resolve(strict=False)
        evidence = (root / "evidence").resolve(strict=True)
        if (target.parent.parent != evidence or target.name != "C21" or
                not re.fullmatch(r"c21-preflight-[0-9]{8}T[0-9]{6}(?:[0-9]{1,6})?Z", target.parent.name)):
            raise PreflightError("Target must be a new C21 preflight evidence directory")
        if target.parent.exists():
            raise PreflightError("Preflight target already exists")

        historical = baseline["gates_and_prereqs"]
        candidate = build_final_release_manifest(
            root,
            run_id=target.parent.name,
            seal={"status": "HASH_MATCH_ONLY"},
            rollback_summary={"passed": historical["rollback_drills_passed"], "total_drills": historical["rollback_drills_total"]},
            unit_cost_summary={"actual_cash_spend_usd": historical["actual_cash_spend_usd"]},
        )
        for name in PROTECTED_DIRS:
            old = baseline["source_tree"]["directories"][name]
            new = candidate["source_tree"]["directories"][name]
            if not old["present"] or not new["present"] or old != new:
                raise PreflightError(f"Protected source directory mismatch: {name}")
        if baseline["contracts"] != candidate["contracts"] or not candidate["contracts"]["contract_count"]:
            raise PreflightError("Contract schema mismatch")
        for field in VERSION_FIELDS:
            if baseline["versions"][field] != candidate["versions"][field]:
                raise PreflightError(f"Frozen prompt or KB mismatch: {field}")

        full_match = candidate["source_tree"]["source_tree_sha256"] == baseline["source_tree"]["source_tree_sha256"]
        candidate["status"] = "C21_CANDIDATE_FROZEN_NOT_BENCHMARKED"
        candidate["gates_and_prereqs"] = {
            "c20_historical_prerequisites": historical,
            "h_g4_source_hash_status": "MATCH",
            "tests_completed": "CALLER_ATTESTED_NOT_VERIFIED",
        }
        candidate["lineage"] = {
            "c20_manifest": C20_MANIFEST.as_posix(),
            "c20_manifest_self_sha256": claimed,
            "c20_release_freeze_id": baseline["release_freeze_id"],
            "c20_source_tree_sha256": baseline["source_tree"]["source_tree_sha256"],
            "full_source_tree_matches_c20": full_match,
            "scope": "Evaluator and scripts may differ; a changed full tree is not the C20 freeze.",
        }
        candidate.pop("manifest_self_sha256", None)
        candidate["manifest_self_sha256"] = _sha256_json(candidate)
        holdout = {
            "status": "SOURCE_HASHES_MATCH_ONLY",
            "files": seals,
            "protected_directories": {
                name: {"sha256": candidate["source_tree"]["directories"][name]["dir_sha256"], "matches_c20": True}
                for name in PROTECTED_DIRS
            },
            "contracts_sha256": candidate["contracts"]["contracts_sha256"],
            "kb_manifest_hash": candidate["versions"]["kb_manifest_hash"],
            "prompt_template_sha256": candidate["versions"]["prompt_template_sha256"],
            "c20_source_tree_sha256": baseline["source_tree"]["source_tree_sha256"],
            "candidate_source_tree_sha256": candidate["source_tree"]["source_tree_sha256"],
            "protected_assets_match_c20": True,
            "query_source_permissions": "OWNER_ONLY" if query_private else "NOT_OWNER_ONLY",
            "isolation": "NOT_VERIFIED",
            "authorization": "NOT_VERIFIED",
            "access_history": "NOT_VERIFIED",
            "gt_actual_partition": "NOT_CREATED",
            "gt_partition_rule": "Actual GT partition only after CLOSED for each incident.",
            "benchmark": "NOT_RUN",
            "candidate_manifest_self_sha256": candidate["manifest_self_sha256"],
        }
        markdown = (
            "# C21 holdout preflight\n\n"
            "Source hashes match the C20/G1 baseline. Hashing reads opaque bytes; it does not establish "
            "access history, isolation, or authorization. No holdout payload or label was parsed.\n\n"
            + "".join(f"- `{path}`: `{item['sha256']}`\n" for path, item in seals.items())
            + "\n- Isolation: `NOT_VERIFIED`\n- Authorization: `NOT_VERIFIED`\n"
            "- Access history: `NOT_VERIFIED`\n- Actual GT partition: `NOT_CREATED` "
            "(only after per-incident CLOSED)\n- Benchmark: `NOT_RUN`\n"
            + f"- Query source permissions: `{'OWNER_ONLY' if query_private else 'NOT_OWNER_ONLY'}`\n"
            + f"- Full source tree matches C20: `{str(full_match).lower()}`; evaluator and scripts may differ.\n"
            + "- Tests completed: caller attestation, not independently verified.\n"
        )
        target.parent.mkdir(mode=0o700, exist_ok=False)
        target.mkdir(mode=0o700)
        for name, data in (("final-release-manifest.json", candidate), ("holdout-g4-manifest.json", holdout)):
            (target / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (target / "holdout-g4-manifest.md").write_text(markdown, encoding="utf-8")
        return target
    except PreflightError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise PreflightError("Preflight could not verify required inputs or write evidence") from exc


def partition_closed_incident(
    *, store: Any, audit_events: list[dict[str, Any]], trusted_audit_head: str,
    incident_id: str, run_id: str, source_file: pathlib.Path,
    output_dir: pathlib.Path, runtime_dir: pathlib.Path, offset: int, length: int,
    expected_source_sha256: str = G1_EXPECTED_GT_HASH,
) -> pathlib.Path:
    """Extract one record after authenticated closure using a trusted byte range.

    The caller must independently supply the exact offset and length for this
    incident, the source digest, and an anchored audit head. This function does
    not create or verify an index and never discovers ranges by parsing records.
    """
    from evaluator.runner import EvaluationBlocked, _overlap, _private_directory, _require_closed_dossier

    if (not re.fullmatch(r"inc-[a-z0-9-]+", incident_id)
            or not re.fullmatch(r"run-[a-z0-9-]+", run_id)
            or type(offset) is not int or offset < 0
            or type(length) is not int or length <= 0
            or not isinstance(expected_source_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256)):
        raise EvaluationBlocked("Invalid trusted partition configuration")
    _require_closed_dossier(
        store=store, audit_events=audit_events, trusted_audit_head=trusted_audit_head,
        incident_id=incident_id,
    )
    try:
        source_file = pathlib.Path(source_file).absolute()
        source = _private_directory(source_file.parent)
        output = _private_directory(pathlib.Path(output_dir))
        runtime = pathlib.Path(runtime_dir).resolve(strict=True)
        if _overlap(source, output) or _overlap(source, runtime) or _overlap(output, runtime):
            raise EvaluationBlocked("Partition source, output and runtime must be disjoint")
        source_dir_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(source_file.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_dir_fd)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or info.st_mode & 0o077 or info.st_nlink != 1
                        or offset + length > info.st_size):
                    raise EvaluationBlocked("Invalid partition source or range")
                digest = hashlib.sha256()
                while chunk := os.read(fd, 1024 * 1024):
                    digest.update(chunk)
                if digest.hexdigest() != expected_source_sha256:
                    raise EvaluationBlocked("Partition source hash mismatch")
                raw = os.pread(fd, length, offset)
                after = os.fstat(fd)
                if (len(raw) != length or (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                        != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                    raise EvaluationBlocked("Partition source changed during reading")
            finally:
                os.close(fd)
        finally:
            os.close(source_dir_fd)
        record = json.loads(raw)
        if (not isinstance(record, dict) or record.get("incident_id") != incident_id
                or record.get("run_id") != run_id or record.get("split_id") != "H-G4"):
            raise EvaluationBlocked("Partition record identity mismatch")
        output_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            name = f"{run_id}.json"
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=output_fd)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    fd = -1
                    json.dump(record, stream, sort_keys=True, separators=(",", ":"))
            except BaseException:
                os.unlink(name, dir_fd=output_fd)
                raise
            finally:
                if fd != -1:
                    os.close(fd)
        finally:
            os.close(output_fd)
        return output / name
    except EvaluationBlocked:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise EvaluationBlocked("Unable to create incident partition") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=_REPO_ROOT)
    parser.add_argument("--target", type=pathlib.Path)
    parser.add_argument("--tests-completed", action="store_true", help="Attest that tests finished before freezing")
    args = parser.parse_args()
    try:
        target = run_preflight(args.root, tests_completed=args.tests_completed, target=args.target)
    except PreflightError as exc:
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 1
    print(f"C21 candidate evidence: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
