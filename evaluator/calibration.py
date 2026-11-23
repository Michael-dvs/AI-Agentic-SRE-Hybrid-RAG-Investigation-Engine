"""Isolated offline DEV calibration and reliability evaluation for confidence scoring.

CRITICAL ISOLATION INVARIANT:
- Must ONLY consume post-CLOSED dossiers joined through ``evaluator.runner.join_dev``.
- Strictly blocks premature (non-CLOSED) dossiers and strictly blocks H-G3 / H-G4 splits.
- Must NEVER be imported or invoked by runtime investigation modules (``orchestrator/``).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from evaluator.runner import EvaluationBlocked, join_dev


CALIBRATION_CONCLUSIONS: tuple[str, ...] = (
    "EMPIRICALLY SUPPORTED",
    "EXPLORATORY ONLY",
    "NOT ESTABLISHED",
    "NOT EVALUABLE",
)


def _confidence_tier(score: float) -> str:
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def _compute_brier_and_ece(
    probs: Sequence[float],
    outcomes: Sequence[float],
    *,
    num_bins: int = 5,
) -> tuple[float, float, list[dict[str, Any]]]:
    n = len(probs)
    brier = sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / n
    bins: list[dict[str, Any]] = []
    ece = 0.0
    width = 1.0 / num_bins
    for idx in range(num_bins):
        low = round(idx * width, 6)
        high = round((idx + 1) * width, 6)
        members = [
            (p, y)
            for p, y in zip(probs, outcomes)
            if (low <= p < high) or (idx == num_bins - 1 and low <= p <= high)
        ]
        count = len(members)
        if count > 0:
            avg_conf = sum(p for p, _ in members) / count
            emp_acc = sum(y for _, y in members) / count
            gap = abs(emp_acc - avg_conf)
            ece += (count / n) * gap
        else:
            avg_conf = None
            emp_acc = None
            gap = None
        bins.append({
            "bin_index": idx,
            "range": [low, high],
            "count": count,
            "avg_confidence": round(avg_conf, 4) if avg_conf is not None else None,
            "empirical_accuracy": round(emp_acc, 4) if emp_acc is not None else None,
            "abs_calibration_gap": round(gap, 4) if gap is not None else None,
        })
    return round(brier, 6), round(ece, 6), bins


def evaluate_confidence_calibration(
    observations: Sequence[Mapping[str, Any]],
    *,
    num_bins: int = 5,
    min_independent_scenarios: int = 8,
    min_samples: int = 20,
    dev_only_exploratory: bool = True,
) -> dict[str, Any]:
    """Compute post-closure Brier score, ECE, reliability bins, and scenario-clustered metrics.

    Expects evaluator-only records with ``split_id == 'dev'`` and ``closed is not False``.
    """
    if num_bins < 2:
        raise ValueError("num_bins must be >= 2")

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for idx, raw in enumerate(observations):
        rec = dict(raw)
        split_id = rec.get("split_id")
        if split_id != "dev":
            raise EvaluationBlocked(
                f"Calibration restricted to post-closure DEV split only; got split_id={split_id!r}"
            )
        if rec.get("closed") is False:
            raise EvaluationBlocked("PREMATURE_EVALUATION_BLOCKED: unclosed incident passed to calibration")

        inc_id = str(rec.get("incident_id") or f"case-{idx:03d}")
        scenario_id = str(rec.get("scenario_id") or rec.get("fault_scenario_id") or f"unknown-scenario-{idx}")
        if rec.get("excluded_reason"):
            excluded.append({"incident_id": inc_id, "scenario_id": scenario_id, "reason": str(rec["excluded_reason"])})
            continue

        conf = rec.get("predicted_confidence")
        outcome = rec.get("is_correct")
        if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not math.isfinite(conf) or not (0.0 <= float(conf) <= 1.0):
            excluded.append({"incident_id": inc_id, "scenario_id": scenario_id, "reason": "missing_or_invalid_confidence"})
            continue
        if not isinstance(outcome, bool):
            excluded.append({"incident_id": inc_id, "scenario_id": scenario_id, "reason": "missing_binary_ground_truth"})
            continue

        base_conf = rec.get("baseline_confidence")
        valid_base = (
            float(base_conf)
            if isinstance(base_conf, (int, float))
            and not isinstance(base_conf, bool)
            and math.isfinite(base_conf)
            and 0.0 <= float(base_conf) <= 1.0
            else None
        )
        included.append({
            "incident_id": inc_id,
            "scenario_id": scenario_id,
            "split_id": split_id,
            "predicted_confidence": float(conf),
            "baseline_confidence": valid_base,
            "is_correct": outcome,
            "y": 1.0 if outcome else 0.0,
            "hypothesis_status": rec.get("hypothesis_status"),
        })

    if not included:
        return {
            "split_id": "dev",
            "included_count": 0,
            "excluded_count": len(excluded),
            "excluded_cases": excluded,
            "unique_scenarios_count": 0,
            "brier_score": None,
            "ece": None,
            "top1_accuracy": None,
            "reliability_bins": [],
            "tier_summary": {},
            "scenario_clustered": {"unique_scenarios": 0, "clustered_brier": None, "scenarios": []},
            "baseline_comparison": None,
            "conclusion": "NOT EVALUABLE",
            "conclusion_reason": "No eligible post-closure binary calibration observations were available.",
        }

    probs = [item["predicted_confidence"] for item in included]
    ys = [item["y"] for item in included]
    brier, ece, bins = _compute_brier_and_ece(probs, ys, num_bins=num_bins)
    top1_acc = sum(ys) / len(ys)

    correct_confs = [item["predicted_confidence"] for item in included if item["is_correct"]]
    incorrect_confs = [item["predicted_confidence"] for item in included if not item["is_correct"]]
    mean_conf_correct = round(sum(correct_confs) / len(correct_confs), 4) if correct_confs else None
    mean_conf_incorrect = round(sum(incorrect_confs) / len(incorrect_confs), 4) if incorrect_confs else None
    discrimination_gap = (
        round(mean_conf_correct - mean_conf_incorrect, 4)
        if mean_conf_correct is not None and mean_conf_incorrect is not None
        else None
    )

    tier_summary: dict[str, dict[str, Any]] = {}
    for tier in ("LOW", "MEDIUM", "HIGH"):
        members = [item for item in included if _confidence_tier(item["predicted_confidence"]) == tier]
        if members:
            tier_summary[tier] = {
                "count": len(members),
                "avg_confidence": round(sum(m["predicted_confidence"] for m in members) / len(members), 4),
                "empirical_accuracy": round(sum(m["y"] for m in members) / len(members), 4),
            }
        else:
            tier_summary[tier] = {"count": 0, "avg_confidence": None, "empirical_accuracy": None}

    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for item in included:
        by_scenario.setdefault(item["scenario_id"], []).append(item)

    scenario_rows: list[dict[str, Any]] = []
    for sid, group in sorted(by_scenario.items()):
        s_brier = sum((g["predicted_confidence"] - g["y"]) ** 2 for g in group) / len(group)
        scenario_rows.append({
            "scenario_id": sid,
            "n_samples": len(group),
            "avg_confidence": round(sum(g["predicted_confidence"] for g in group) / len(group), 4),
            "accuracy": round(sum(g["y"] for g in group) / len(group), 4),
            "brier_score": round(s_brier, 6),
        })
    clustered_brier = round(sum(row["brier_score"] for row in scenario_rows) / len(scenario_rows), 6)
    unique_scenarios = len(scenario_rows)

    paired = [item for item in included if item["baseline_confidence"] is not None]
    baseline_comparison: dict[str, Any] | None = None
    if paired:
        b_probs = [item["baseline_confidence"] for item in paired]  # type: ignore[misc]
        p_probs = [item["predicted_confidence"] for item in paired]
        p_ys = [item["y"] for item in paired]
        b_brier, b_ece, _ = _compute_brier_and_ece(b_probs, p_ys, num_bins=num_bins)
        m_brier, m_ece, _ = _compute_brier_and_ece(p_probs, p_ys, num_bins=num_bins)
        baseline_comparison = {
            "paired_count": len(paired),
            "baseline_brier": b_brier,
            "candidate_brier": m_brier,
            "brier_delta": round(m_brier - b_brier, 6),
            "baseline_ece": b_ece,
            "candidate_ece": m_ece,
            "ece_delta": round(m_ece - b_ece, 6),
            "caveat": "Comparison limited to closed DEV split pairs; confidence values are uncalibrated heuristics.",
        }

    # Strict statistical validity conclusion (never overclaim)
    non_empty_bins = sum(1 for b in bins if b["count"] > 0)
    if unique_scenarios < min_independent_scenarios or len(included) < min_samples or non_empty_bins < 2:
        conclusion = "NOT ESTABLISHED"
        reason = (
            f"Sample size insufficient for calibration claim "
            f"(included={len(included)}/{min_samples}, unique_scenarios={unique_scenarios}/{min_independent_scenarios}, "
            f"populated_bins={non_empty_bins})."
        )
    elif dev_only_exploratory:
        conclusion = "EXPLORATORY ONLY"
        reason = (
            "Measured solely on isolated DEV synthetic replays with heuristic bounded confidence scores "
            "(is_calibrated_probability=False); out-of-sample holdout calibration not performed."
        )
    elif ece <= 0.12 and brier <= 0.22 and (discrimination_gap is None or discrimination_gap > 0.0):
        conclusion = "EMPIRICALLY SUPPORTED"
        reason = (
            f"Calibrated within DEV bounds across {unique_scenarios} independent scenarios "
            f"(N={len(included)}, ECE={ece:.4f}, Brier={brier:.4f})."
        )
    else:
        conclusion = "NOT ESTABLISHED"
        reason = (
            f"Observed calibration error or discrimination failed target bounds "
            f"(ECE={ece:.4f}, Brier={brier:.4f}, discrimination_gap={discrimination_gap})."
        )

    assert conclusion in CALIBRATION_CONCLUSIONS
    return {
        "split_id": "dev",
        "included_count": len(included),
        "excluded_count": len(excluded),
        "excluded_cases": excluded,
        "unique_scenarios_count": unique_scenarios,
        "brier_score": brier,
        "ece": ece,
        "top1_accuracy": round(top1_acc, 4),
        "mean_confidence_correct": mean_conf_correct,
        "mean_confidence_incorrect": mean_conf_incorrect,
        "discrimination_gap": discrimination_gap,
        "reliability_bins": bins,
        "tier_summary": tier_summary,
        "scenario_clustered": {
            "unique_scenarios": unique_scenarios,
            "clustered_brier": clustered_brier,
            "scenarios": scenario_rows,
        },
        "baseline_comparison": baseline_comparison,
        "conclusion": conclusion,
        "conclusion_reason": reason,
    }


def _match_top_hypothesis_to_gt(dossier: Mapping[str, Any], ground_truth: Mapping[str, Any]) -> tuple[bool | None, str | None]:
    """Deterministically evaluate top dossier hypothesis against isolated DEV ground truth."""
    hyps = dossier.get("hypotheses") or []
    if not hyps or not isinstance(hyps[0], Mapping):
        return None, "no_hypotheses"
    root = ground_truth.get("actual_root_cause", ground_truth)
    if root.get("is_healthy_control") is True:
        return None, "healthy_control_no_fault_target"

    top = hyps[0]
    top_text = f"{top.get('statement', '')} {top.get('reason_summary', '')}".lower()
    expected_causes = root.get("expected_causes") or root.get("expected_root_cause_services") or []
    expected_keywords = root.get("expected_keywords") or []

    # Check explicit keyword + service match when provided by DEV GT
    service_match = True
    if expected_causes:
        service_match = any(
            bool(re.search(rf"\b{re.escape(str(svc).lower())}\b", top_text))
            for svc in expected_causes
            if svc
        )
    keyword_match = True
    if expected_keywords:
        keyword_match = any(str(kw).lower() in top_text for kw in expected_keywords if kw)

    if not expected_causes and not expected_keywords:
        return None, "missing_expected_causes_or_keywords"
    return bool(service_match and keyword_match), None


def run_dev_calibration_from_store(
    *,
    case_specs: Sequence[Mapping[str, Any]],
    store: Any,
    audit_events: list[dict[str, Any]],
    trusted_audit_head: str,
    dev_source_dir: Path,
    output_dir: Path,
    runtime_dir: Path,
    min_independent_scenarios: int = 8,
    min_samples: int = 20,
    dev_only_exploratory: bool = True,
) -> dict[str, Any]:
    """Join post-CLOSED DEV dossiers via ``join_dev`` and run calibration evaluation."""
    observations: list[dict[str, Any]] = []
    for spec in case_specs:
        incident_id = str(spec["incident_id"])
        run_id = str(spec["run_id"])
        joined_path = join_dev(
            store=store,
            audit_events=audit_events,
            trusted_audit_head=trusted_audit_head,
            incident_id=incident_id,
            run_id=run_id,
            dev_source_dir=dev_source_dir,
            output_dir=output_dir,
            runtime_dir=runtime_dir,
        )
        joined = json.loads(joined_path.read_text(encoding="utf-8"))
        dossier = joined["dossier"]
        gt = joined["ground_truth"]
        if gt.get("split_id") != "dev":
            raise EvaluationBlocked(f"Non-DEV split joined unexpectedly: {gt.get('split_id')!r}")

        is_correct = spec.get("is_correct")
        excl_reason = None
        if not isinstance(is_correct, bool):
            is_correct, excl_reason = _match_top_hypothesis_to_gt(dossier, gt)

        pred_conf = spec.get("predicted_confidence")
        if pred_conf is None:
            hyps = dossier.get("hypotheses") or []
            top_hid = hyps[0].get("hypothesis_id") if hyps and isinstance(hyps[0], Mapping) else None
            cp = None
            if hasattr(store, "get_checkpoint"):
                cp = store.get_checkpoint(incident_id)
            elif hasattr(store, "get_latest_checkpoint"):
                cp = store.get_latest_checkpoint(incident_id)
            if isinstance(cp, Mapping):
                ctx_cp = cp.get("context") or {}
                for h_cp in ctx_cp.get("hypotheses", []):
                    if isinstance(h_cp, Mapping) and h_cp.get("hypothesis_id") == top_hid:
                        pred_conf = h_cp.get("confidence_score")
                        break

        observations.append({
            "incident_id": incident_id,
            "scenario_id": gt.get("scenario_id") or gt.get("actual_root_cause", {}).get("scenario_id") or incident_id,
            "split_id": "dev",
            "closed": True,
            "predicted_confidence": pred_conf,
            "baseline_confidence": spec.get("baseline_confidence"),
            "is_correct": is_correct,
            "excluded_reason": excl_reason,
            "hypothesis_status": (dossier.get("hypotheses") or [{}])[0].get("support_status"),
        })

    return evaluate_confidence_calibration(
        observations,
        min_independent_scenarios=min_independent_scenarios,
        min_samples=min_samples,
        dev_only_exploratory=dev_only_exploratory,
    )


__all__ = [
    "CALIBRATION_CONCLUSIONS",
    "evaluate_confidence_calibration",
    "run_dev_calibration_from_store",
]
