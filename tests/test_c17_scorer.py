"""Numeric qualification fixtures for the C17 offline scorer."""
import pytest

from evaluator.scorer import score_cases


def case(**overrides):
    result = {
        "incident_id": "inc-fixture", "completed": True,
        "ground_truth": {"scenario_id": "SC-02", "actual_root_cause": {
            "is_healthy_control": False, "expected_causes": ["a"]}},
        "diagnoses": [{"cause": "a", "status": "SUPPORTED"}],
        "claims": [{"valid_source": True, "unsupported": False}],
        "retrieval_queries": [], "critical_failure": False,
        "prohibited_successes": 0, "gt_retrievals": 0, "forbidden_citations": 0,
        "cost": {"token_cost": 1, "compute_cost": 1, "total_tokens": 100},
    }
    result.update(overrides)
    return result


@pytest.mark.parametrize("kind", ["top1", "top3", "wrong", "unsupported", "obsolete", "outage"])
def test_requested_qualification_cases(kind):
    record = case()
    if kind == "top3":
        record["diagnoses"] = [{"cause": "x", "status": "SUPPORTED"},
                               {"cause": "y", "status": "PARTIAL"},
                               {"cause": "a", "status": "SUPPORTED"}]
    elif kind == "wrong":
        record["diagnoses"] = [{"cause": "x", "status": "SUPPORTED"}]
    elif kind == "unsupported":
        record["claims"] = [{"valid_source": False, "unsupported": True}]
    elif kind == "obsolete":
        record["forbidden_citations"] = 1
    elif kind == "outage":
        record.update(critical_failure=True, safe_fallback=True, claims=[], valid_abstain=True)
    report = score_cases([record])
    m = report["metrics"]
    assert m["KPI-02"]["all_causes"]["value"] == (0 if kind == "wrong" else 1)
    if kind == "unsupported":
        assert m["KPI-03"]["value"] == 0
        assert m["KPI-04"]["value"] == 1
    if kind == "obsolete":
        assert m["KPI-11"]["value"] == 1
    if kind == "outage":
        assert m["KPI-12"]["value"] == 1
        assert m["KPI-03"]["value"] is None
        assert m["KPI-03"]["status"] == "VALID_ABSTAIN"
        assert m["KPI-04"]["status"] == "VALID_ABSTAIN"
        assert m["KPI-04"]["value"] is None
        assert report["separate"]["valid_abstain_zero_claims"] == 1


def test_failed_cost_and_denominators():
    failed = case(completed=False, diagnoses=None, cost={"token_cost": 3, "compute_cost": 2, "total_tokens": 75})
    result = score_cases([case(), failed])["metrics"]
    assert result["KPI-01"]["value"] == .5
    assert result["KPI-02"]["all_causes"]["value"] == .5
    assert result["KPI-14"]["value"] == 7
    assert result["KPI-14"]["denominator"] == 1
    assert result["KPI-14"]["tokens"]["value"] == 175


def test_controls_abstention_multifault():
    healthy = case(ground_truth={"scenario_id": "SC-01", "actual_root_cause": {
        "is_healthy_control": True}}, diagnoses=[])
    multi = case(ground_truth={"scenario_id": "SC-08", "actual_root_cause": {
        "is_healthy_control": False, "expected_causes": ["a", "b"]}})
    abstain = case(ground_truth={"scenario_id": "SC-09", "actual_root_cause": {
        "is_healthy_control": False, "expected_causes": ["a"]}},
        diagnoses=[], claims=[], valid_abstain=True)
    report = score_cases([healthy, multi, abstain])
    assert report["metrics"]["KPI-02"]["primary_cause"]["value"] == .5
    assert report["metrics"]["KPI-02"]["all_causes"]["value"] == 0
    assert report["separate"]["healthy_false_positive_rate"]["value"] == 0
    assert report["separate"]["safety_abstention_accuracy"]["value"] == 1


def test_multifault_two_of_three_counts_as_main_but_not_all():
    multi = case(ground_truth={"scenario_id": "SC-08", "actual_root_cause": {
        "is_healthy_control": False, "expected_causes": ["a", "b", "c"]}},
        diagnoses=[{"cause": "b", "status": "SUPPORTED"},
                   {"cause": "c", "status": "PARTIAL"}])
    score = score_cases([multi])["metrics"]["KPI-02"]
    assert score["value"] == 1
    assert score["primary_cause"]["value"] == 0
    assert score["all_causes"]["value"] == 0


def test_missing_inputs_and_replay():
    report = score_cases([case(cost=None, claims=None, clean_replay_success=True)])
    metrics = report["metrics"]
    assert metrics["KPI-03"]["value"] is None
    assert metrics["KPI-14"]["value"] is None
    assert metrics["KPI-13"]["value"] == 1
    assert metrics["KPI-08"]["value"] is None
    assert report["separate"]["AT-016"]["value"] is None


def test_abstention_does_not_hide_missing_claim_data():
    report = score_cases([case(claims=[], valid_abstain=True), case(claims=None)])
    for key in ("KPI-03", "KPI-04"):
        assert report["metrics"][key]["status"] == "PARTIAL"
        assert report["metrics"][key]["value"] is None


def test_retrieval_latency_review_and_separate_resources():
    a = case(retrieval_queries=[{"relevant_ids": ["a", "b"], "retrieved_ids": ["a", "c"]}],
             review={"accepted_without_substantial_rework": True, "label_source": "self_review_lab_owner"},
             alert_received_at="2026-01-01T00:00:00Z", dossier_ready_at="2026-01-01T00:00:20Z",
             manual_seconds=100, assisted_seconds=50,
             cascade={"dependency_evidence": True, "uncertainty_documented": False}, resource={"peak_rss_bytes": 100})
    report = score_cases([a])
    m = report["metrics"]
    assert m["KPI-05"]["hit_rate_at_5"]["value"] == 1
    assert m["KPI-05"]["classical_recall_at_5"]["value"] == .5
    assert m["KPI-06"]["value"] == 1
    assert m["KPI-07"]["value"] == 20
    assert m["KPI-08"]["value"] == .5
    assert report["separate"]["AT-016"]["value"] == 0
    assert report["separate"]["resource_measurements"][0]["measurement"]["peak_rss_bytes"] == 100
