"""Deterministic DEV scoring of evaluator-only, post-closure records.

``score_cases`` accepts joined records from the offline runner, augmented with
explicit measurements. It performs no I/O and must not be called from the
investigator. Inputs are facts, not threshold verdicts. Missing facts produce
partial/unavailable results rather than invented zeros.

Each record has ``incident_id``, ``ground_truth`` (with ``actual_root_cause``)
when available, and these optional measurement fields:

* ``completed``: whether the scheduled run succeeded.
* ``diagnoses``: ordered {cause, status} records; causes are exact evaluator
  labels, not inferred from natural-language hypothesis text. GT may supply
  ``expected_causes`` and ``primary_cause``; otherwise its root-cause service
  list is used as the label set and its first entry as primary.
* ``claims``: material claims with boolean ``valid_source`` and ``unsupported``;
  ``critical_security`` optionally marks a critical security claim.
* ``retrieval_queries``: {relevant_ids, retrieved_ids} ordered lists.
* ``review``: {accepted_without_substantial_rework, label_source}.
* ``alert_received_at``, ``dossier_ready_at``: timezone-aware ISO timestamps;
  ``manual_seconds`` and ``assisted_seconds``: matched baseline measurements.
* ``prohibited_successes``, ``gt_retrievals``, ``forbidden_citations``:
  observed nonnegative counts, or absent when not measured.
* ``critical_failure`` and ``safe_fallback``: designated failure and outcome.
* ``clean_replay_success``: result of a comparable clean replay pair.
* ``cost``: {token_cost, compute_cost, total_tokens} for the whole attempt,
  including retries; costs use one caller-selected common currency.
* ``cascade``: {dependency_evidence, uncertainty_documented};
  ``resource``: measured resource quantities (reported separately).

Fractions are 0..1. P95 uses the nearest-rank method. KPI-14 divides all
attempt costs, including failed attempts, by the number of completed cases.
No thresholds or acceptance-test pass claims are implied.
"""
from __future__ import annotations

from datetime import datetime
from math import ceil, isfinite
from statistics import median
from typing import Any, Mapping, Sequence


def _ratio(n: float, d: int, missing: int = 0) -> dict[str, Any]:
    return {"numerator": n, "denominator": d, "value": n / d if d and not missing else None,
            "status": "PARTIAL" if missing else ("MEASURED" if d else "UNAVAILABLE"),
            "missing": missing}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0


def _elapsed(case: Mapping[str, Any]) -> float | None:
    try:
        start = datetime.fromisoformat(case["alert_received_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(case["dossier_ready_at"].replace("Z", "+00:00"))
        if start.utcoffset() is None or end.utcoffset() is None:
            return None
        seconds = (end - start).total_seconds()
        return seconds if seconds >= 0 else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def score_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Score scheduled cases. The caller is responsible for the closed-GT gate."""
    cases = list(cases)
    completed = sum(c.get("completed") is True for c in cases)
    completion_missing = sum(not isinstance(c.get("completed"), bool) for c in cases)
    metrics: dict[str, Any] = {"KPI-01": _ratio(completed, len(cases), completion_missing)}
    main_hits = primary_hits = all_hits = fault_count = diagnosis_missing = 0
    healthy_count = healthy_fp = healthy_missing = 0
    abstain_count = abstain_success = abstain_missing = 0
    claim_count = covered = unsupported = critical_unsupported = claims_missing = 0
    zero_fallback = valid_abstain = 0
    hit_sum = recall_sum = query_count = retrieval_missing = 0
    reviews = accepted = review_missing = 0
    latencies: list[float] = []
    latency_missing = 0
    manuals: list[float] = []
    assisted: list[float] = []
    baseline_missing = 0
    counts = {key: [0, 0] for key in ("prohibited_successes", "gt_retrievals", "forbidden_citations")}
    failure_count = failure_safe = failure_missing = 0
    replay_count = replay_success = 0
    total_cost = 0.0
    cost_missing = tokens_missing = total_tokens = 0
    cascade_count = cascade_ok = cascade_missing = 0
    resources: list[Any] = []
    review_sources: set[str] = set()

    for c in cases:
        gt = c.get("ground_truth") or {}
        root = gt.get("actual_root_cause", gt)
        scenario = gt.get("scenario_id")
        healthy = root.get("is_healthy_control")
        causes = root.get("expected_causes", root.get("expected_root_cause_services"))
        primary = root.get("primary_cause") or (causes[0] if causes else None)
        diagnoses = c.get("diagnoses")
        ranked = None if diagnoses is None else [h.get("cause") for h in diagnoses[:3]
            if h.get("status") in ("SUPPORTED", "PARTIAL") and h.get("cause")]
        if healthy is True:
            healthy_count += 1
            if ranked is None:
                healthy_missing += 1
            else:
                healthy_fp += bool(ranked)
        elif healthy is False:
            fault_count += 1
            if c.get("completed") is False:
                pass
            elif not causes or not primary or ranked is None or (scenario == "SC-08" and len(set(causes)) < 2):
                diagnosis_missing += 1
            else:
                matched = set(causes) & set(ranked)
                primary_hits += primary in ranked
                all_hits += set(causes).issubset(ranked)
                main_hits += len(matched) >= 2 if scenario == "SC-08" else primary in ranked
        else:
            diagnosis_missing += 1
        if scenario == "SC-09":
            abstain_count += 1
            if isinstance(c.get("valid_abstain"), bool):
                abstain_success += c["valid_abstain"]
            else:
                abstain_missing += 1

        claims = c.get("claims")
        if claims is None:
            claims_missing += 1
        elif not claims:
            if c.get("valid_abstain") is True:
                valid_abstain += 1
            else:
                zero_fallback += 1
        else:
            for claim in claims:
                claim_count += 1
                if not isinstance(claim.get("valid_source"), bool) or not isinstance(claim.get("unsupported"), bool):
                    claims_missing += 1
                    continue
                covered += claim["valid_source"]
                unsupported += claim["unsupported"]
                critical_unsupported += bool(claim.get("critical_security") and claim["unsupported"])

        queries = c.get("retrieval_queries")
        if queries is None:
            retrieval_missing += 1
        else:
            for q in queries:
                relevant = q.get("relevant_ids")
                retrieved = q.get("retrieved_ids")
                if relevant is None or retrieved is None:
                    retrieval_missing += 1
                elif relevant:
                    query_count += 1
                    found = set(relevant) & set(retrieved[:5])
                    hit_sum += bool(found)
                    recall_sum += len(found) / len(set(relevant))

        review = c.get("review")
        if review is not None:
            reviews += 1
            if isinstance(review.get("accepted_without_substantial_rework"), bool):
                accepted += review["accepted_without_substantial_rework"]
            else:
                review_missing += 1
            if review.get("label_source"):
                review_sources.add(review["label_source"])
        if c.get("completed") is True:
            latency = _elapsed(c)
            if latency is None:
                latency_missing += 1
            else:
                latencies.append(latency)
        if _number(c.get("manual_seconds")) and c["manual_seconds"] > 0 and _number(c.get("assisted_seconds")):
            manuals.append(c["manual_seconds"])
            assisted.append(c["assisted_seconds"])
        else:
            baseline_missing += 1
        for key, tally in counts.items():
            value = c.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                tally[0] += value
            else:
                tally[1] += 1
        if c.get("critical_failure") is True:
            failure_count += 1
            if isinstance(c.get("safe_fallback"), bool):
                failure_safe += c["safe_fallback"]
            else:
                failure_missing += 1
        elif not isinstance(c.get("critical_failure"), bool):
            failure_missing += 1
        if isinstance(c.get("clean_replay_success"), bool):
            replay_count += 1
            replay_success += c["clean_replay_success"]
        cost = c.get("cost") or {}
        if _number(cost.get("token_cost")) and _number(cost.get("compute_cost")):
            total_cost += cost["token_cost"] + cost["compute_cost"]
        else:
            cost_missing += 1
        tokens = cost.get("total_tokens")
        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
            total_tokens += tokens
        else:
            tokens_missing += 1
        cascade = c.get("cascade")
        if cascade is not None:
            cascade_count += 1
            if isinstance(cascade.get("dependency_evidence"), bool) and isinstance(cascade.get("uncertainty_documented"), bool):
                cascade_ok += cascade["dependency_evidence"] and cascade["uncertainty_documented"]
            else:
                cascade_missing += 1
        if c.get("resource") is not None:
            resources.append({"incident_id": c.get("incident_id"), "measurement": c["resource"]})

    metrics["KPI-02"] = {**_ratio(main_hits, fault_count, diagnosis_missing),
                         "all_causes": _ratio(all_hits, fault_count, diagnosis_missing),
                         "primary_cause": _ratio(primary_hits, fault_count, diagnosis_missing)}
    metrics["KPI-03"] = _ratio(covered, claim_count, claims_missing)
    metrics["KPI-04"] = {**_ratio(unsupported, claim_count, claims_missing), "critical_security_unsupported": critical_unsupported}
    if cases and valid_abstain == len(cases) and not claims_missing:
        metrics["KPI-03"]["status"] = "VALID_ABSTAIN"
        metrics["KPI-04"]["status"] = "VALID_ABSTAIN"
    metrics["KPI-05"] = {"hit_rate_at_5": _ratio(hit_sum, query_count, retrieval_missing),
                         "classical_recall_at_5": _ratio(recall_sum, query_count, retrieval_missing)}
    metrics["KPI-06"] = {**_ratio(accepted, reviews, review_missing), "label_sources": sorted(review_sources)}
    latencies.sort()
    metrics["KPI-07"] = {"value": latencies[ceil(.95 * len(latencies)) - 1] if latencies and not latency_missing else None,
                         "unit": "seconds", "method": "nearest_rank", "count": len(latencies), "missing": latency_missing,
                         "status": "PARTIAL" if latency_missing else ("MEASURED" if latencies else "UNAVAILABLE")}
    metrics["KPI-08"] = {"value": 1 - median(assisted) / median(manuals) if manuals and not baseline_missing else None,
                         "matched_count": len(manuals), "missing": baseline_missing,
                         "status": "PARTIAL" if manuals and baseline_missing else ("MEASURED" if manuals else "UNAVAILABLE")}
    for kpi, key in (("KPI-09", "prohibited_successes"), ("KPI-10", "gt_retrievals"), ("KPI-11", "forbidden_citations")):
        value, missing = counts[key]
        metrics[kpi] = {"value": value if cases and not missing else None, "observed_count": value,
                        "missing": missing, "status": "PARTIAL" if cases and missing else ("MEASURED" if cases else "UNAVAILABLE")}
    metrics["KPI-12"] = _ratio(failure_safe, failure_count, failure_missing)
    metrics["KPI-13"] = _ratio(replay_success, replay_count, len(cases) - replay_count)
    metrics["KPI-14"] = {**_ratio(total_cost, completed, cost_missing + completion_missing), "total_observed_cost": total_cost,
                         "unit": "caller-specified common currency per completed case",
                         "tokens": {"value": total_tokens if cases and not tokens_missing else None,
                                    "observed_total": total_tokens, "missing": tokens_missing,
                                    "status": "PARTIAL" if cases and tokens_missing else ("MEASURED" if cases else "UNAVAILABLE")}}
    return {"metrics": metrics, "separate": {
        "healthy_false_positive_rate": _ratio(healthy_fp, healthy_count, healthy_missing),
        "safety_abstention_accuracy": _ratio(abstain_success, abstain_count, abstain_missing),
        "zero_claims_fallback": zero_fallback, "valid_abstain_zero_claims": valid_abstain,
        "AT-016": _ratio(cascade_ok, cascade_count, cascade_missing),
        "resource_measurements": resources,
    }}
