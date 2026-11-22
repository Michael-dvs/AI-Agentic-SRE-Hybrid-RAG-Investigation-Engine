"""Chapter 21 synthetic benchmark harness unit and integration checks.

Strictly synthetic fixtures only: never reads or embeds restricted H-G4 payloads
or ground-truth oracle labels.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from evaluator.scorer import score_cases
from knowledge_base.ingestion.lifecycle import KnowledgeLifecycleManager
from knowledge_base.retrieval import RetrievalEngine, RetrievalService
from scripts.run_c21_benchmark import (
    _extract_service_diagnoses,
    _map_joined_record_to_scorer_case,
    _nearest_rank_percentile,
    discover_h_g4_partition_specs,
    evaluate_retrieval_queries,
    verify_preflight_and_freeze,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_nearest_rank_percentile_and_service_diagnosis_extraction() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _nearest_rank_percentile(vals, 50) == 3.0
    assert _nearest_rank_percentile(vals, 95) == 5.0
    assert _nearest_rank_percentile([], 95) == 0.0

    diagnoses = _extract_service_diagnoses(
        {
            "hypotheses": [
                {
                    "candidate_cause": "auth-service_runtime_error",
                    "statement": "Error rate elevated in auth-service",
                    "support_status": "SUPPORTED",
                },
                {
                    "candidate_cause": "unobserved_transient_failure",
                    "statement": "No additional span anomaly",
                    "support_status": "INCONCLUSIVE",
                },
            ]
        }
    )
    assert diagnoses == [{"cause": "auth-service", "status": "SUPPORTED"}]


def test_evaluate_retrieval_queries_handles_positive_and_negative_synthetic_queries() -> None:
    manager = KnowledgeLifecycleManager()
    manifest, _ = manager.build_manifest_from_corpus(
        _REPO_ROOT / "knowledge_base" / "corpus", "kb-idx-20261111-v1"
    )
    engine = RetrievalEngine(chunks=manifest.chunks, index_version="kb-idx-20261111-v1")
    service = RetrievalService(engine=engine)

    synthetic_queries = [
        {
            "query_id": "SYN-Q-01",
            "target_service_id": "api-gateway",
            "query_text": "Penanganan gateway timeout HTTP 504 pada ingress API",
            "expected_document_ids": ["SOP-GW-ERR-504"],
            "expected_section_paths": [],
        },
        {
            "query_id": "SYN-Q-NEG",
            "target_service_id": "api-gateway",
            "query_text": "Troubleshooting Kubernetes CNI flannel network overlay packet loss",
            "expected_document_ids": [],
            "expected_section_paths": [],
        },
    ]

    result = evaluate_retrieval_queries(service, synthetic_queries)
    rrf = result["modes"]["hybrid_rrf"]
    assert rrf["positive_queries"] == 1
    assert rrf["negative_out_of_scope_queries"] == 1
    assert rrf["document_hit_rate_at_5"] == 1.0
    assert rrf["negative_no_match_safety_rate"] == 1.0
    assert rrf["forbidden_or_cross_service_leaks"] == 0
    assert len(result["scorer_retrieval_queries"]) == 1


def test_discover_h_g4_partition_specs_on_synthetic_jsonl(tmp_path: pathlib.Path) -> None:
    jsonl = tmp_path / "synthetic_records.jsonl"
    rec1 = {"split_id": "DEV", "run_id": "run-syn-1", "incident_id": "inc-syn-1", "target_services": ["api-gateway"]}
    rec2 = {
        "split_id": "H-G4",
        "run_id": "run-syn-2",
        "incident_id": "inc-syn-2",
        "target_services": ["auth-service", "notification-service"],
    }
    raw = (json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n").encode("utf-8")
    jsonl.write_bytes(raw)
    os.chmod(jsonl, 0o600)

    specs = discover_h_g4_partition_specs(jsonl)
    assert len(specs) == 1
    assert specs[0]["line_number"] == 2
    assert specs[0]["run_id"] == "run-syn-2"
    sliced = json.loads(raw[specs[0]["offset"] : specs[0]["offset"] + specs[0]["length"]])
    assert sliced["incident_id"] == "inc-syn-2"


def test_map_joined_record_preserves_sc08_miss_honestly() -> None:
    joined: dict[str, Any] = {
        "incident_id": "inc-syn-sc08",
        "run_id": "run-syn-sc08",
        "dossier": {
            "alert_received_at": "2026-11-22T00:00:00Z",
            "dossier_ready_at": "2026-11-22T00:00:05Z",
            "evidence": [
                {"evidence_id": "ev-1", "source_ref": "loki", "sanitized": True},
            ],
            "hypotheses": [
                {
                    "candidate_cause": "auth-service_runtime_error",
                    "statement": "Error logs detected on auth-service",
                    "support_status": "SUPPORTED",
                    "supporting_evidence_ids": ["ev-1"],
                }
            ],
        },
        "ground_truth": {
            "scenario_id": "SC-08",
            "actual_root_cause": {
                "is_healthy_control": False,
                "expected_root_cause_services": ["auth-service", "notification-service"],
            },
        },
    }

    case = _map_joined_record_to_scorer_case(
        joined,
        retrieval_queries=[{"relevant_ids": ["D1"], "retrieved_ids": ["D1"]}],
        accepted_without_substantial_rework=False,
        cost_profile={"tokens": {"total_tokens": 256}, "shadow_cost": {"estimated_unit_cost_usd": 0.0002}},
        cpu_seconds=0.015,
        peak_rss_mib=120.5,
        forbidden_citations_observed=0,
    )
    scored = score_cases([case])
    assert scored["metrics"]["KPI-02"]["primary_cause"]["value"] == 1.0
    assert scored["metrics"]["KPI-02"]["all_causes"]["value"] == 0.0
    assert scored["metrics"]["KPI-02"]["value"] == 0.0
    assert scored["metrics"]["KPI-03"]["value"] == 1.0
    assert scored["metrics"]["KPI-04"]["value"] == 0.0
    assert scored["metrics"]["KPI-06"]["value"] == 0.0
    assert scored["metrics"]["KPI-08"]["status"] == "UNAVAILABLE"


def test_preflight_freeze_reverification_matches_stage_3a() -> None:
    info = verify_preflight_and_freeze(_REPO_ROOT)
    assert info["manifest_self_sha256"] == "fc7e6a702b73f5185d09aca19c5c55a9fb56ead3864531c6c8d46970d1131b9e"
    assert len(info["protected_dirs_verified"]) == 7
    assert all(p["owner_only"] for p in info["permissions"].values())
