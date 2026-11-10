"""Tests the orchestration layer: a bad check must not abort the run, and the
pass/fail gate must only trip on blocker-severity failures or errors."""
from harness.evolve import Iteration
from harness.mock_connector import MockConnector
from harness.report import _estimate_cost, _failure_entries, gate_failed, write_evolve_report
from harness.runner import CheckResult, run_suite


def test_one_broken_check_does_not_abort_the_run():
    conn = MockConnector({"SELECT COUNT(*) AS cnt FROM t": [{"cnt": 10}]})
    suite = {
        "checks": [
            {"id": "ok", "type": "row_count", "category": "c", "description": "", "severity": "blocker",
             "params": {"sql": "SELECT COUNT(*) AS cnt FROM t", "expected": 10}},
            {"id": "broken", "type": "row_count", "category": "c", "description": "", "severity": "blocker",
             "params": {"sql": "SELECT COUNT(*) AS cnt FROM missing_fixture"}},
        ]
    }
    results = run_suite(suite, conn, retries=0)
    assert len(results) == 2
    assert results[0].status == "pass"
    assert results[1].status == "error"


def test_gate_fails_on_blocker_failure_but_not_on_warning_failure():
    conn = MockConnector({})

    def result(status, severity):
        from harness.runner import CheckResult
        return CheckResult("x", "c", "", severity, status, "", {}, 0.0)

    assert gate_failed([result("fail", "blocker")]) is True
    assert gate_failed([result("fail", "warning")]) is False
    assert gate_failed([result("pass", "blocker")]) is False
    assert gate_failed([result("error", "warning")]) is True


def test_evolve_report_surfaces_the_rationale_behind_the_passing_fix(tmp_path):
    # The rationale explaining candidate 2 (the one that passed) is attached to
    # iteration 1 (the one that failed and prompted it) -- evolve.py's own
    # convention, not this function's. A reviewer needs to see this on the commit
    # that actually landed the fix, which is exactly what this is written for.
    history = [
        Iteration(attempt=1, candidate_sql="SELECT 1", stage="validate", gate_failed=True,
                   rationale="De-duplicated store_promotions before the join."),
        Iteration(attempt=2, candidate_sql="SELECT 2", stage="validate", gate_failed=False),
    ]
    summary = write_evolve_report(success=True, history=history, output_dir=tmp_path)
    assert summary["rationale"] == "De-duplicated store_promotions before the join."


def test_evolve_report_has_no_rationale_when_the_first_attempt_already_passes(tmp_path):
    history = [Iteration(attempt=1, candidate_sql="SELECT 1", stage="validate", gate_failed=False)]
    summary = write_evolve_report(success=True, history=history, output_dir=tmp_path)
    assert summary["rationale"] is None


def test_evolve_report_has_no_rationale_when_the_loop_fails_outright(tmp_path):
    history = [Iteration(attempt=1, candidate_sql="SELECT 1", stage="guardrail", error="nope")]
    summary = write_evolve_report(success=False, history=history, output_dir=tmp_path)
    assert summary["rationale"] is None


def test_estimate_cost_for_a_known_model():
    cost = _estimate_cost("deepseek-chat", {"input_tokens": 1000, "output_tokens": 1000})
    assert cost == 0.00014 + 0.00028


def test_estimate_cost_is_zero_without_usage():
    assert _estimate_cost("deepseek-chat", None) == 0.0
    assert _estimate_cost("deepseek-chat", {}) == 0.0


def test_estimate_cost_is_zero_for_an_unknown_model_not_an_error():
    assert _estimate_cost("some-future-model-id", {"input_tokens": 1000, "output_tokens": 1000}) == 0.0


def test_evolve_report_totals_tokens_cost_and_model_across_the_run(tmp_path):
    history = [
        Iteration(attempt=1, candidate_sql="SELECT 1", stage="validate", gate_failed=True,
                   rationale="first fix", usage={"input_tokens": 1000, "output_tokens": 500}, model="deepseek-chat"),
        Iteration(attempt=2, candidate_sql="SELECT 2", stage="validate", gate_failed=False),
    ]
    summary = write_evolve_report(success=True, history=history, output_dir=tmp_path)
    assert summary["model"] == "deepseek-chat"
    assert summary["total_tokens"] == 1500
    assert summary["estimated_cost_usd"] == round(0.00014 + 0.00028 * 0.5, 6)


def test_evolve_report_totals_are_zero_when_no_llm_call_happened(tmp_path):
    history = [Iteration(attempt=1, candidate_sql="SELECT 1", stage="validate", gate_failed=False)]
    summary = write_evolve_report(success=True, history=history, output_dir=tmp_path)
    assert summary["model"] == ""
    assert summary["total_tokens"] == 0
    assert summary["estimated_cost_usd"] == 0.0


def test_failure_entries_covers_a_deploy_stage_failure():
    history = [Iteration(attempt=1, candidate_sql="SELECT 1", stage="deploy", gate_failed=True, error="syntax error near END")]
    entries = _failure_entries(history)
    assert entries == [{"attempt": 1, "stage": "deploy", "summary": "deploy: syntax error near END"}]


def test_failure_entries_covers_a_validate_stage_failure_with_check_ids():
    history = [Iteration(
        attempt=1, candidate_sql="SELECT 1", stage="validate", gate_failed=True,
        results=[
            CheckResult("revenue_matches", "business_logic", "", "blocker", "fail", "off by 12", {}, 1.0),
            CheckResult("row_count_ok", "schema", "", "blocker", "pass", "", {}, 1.0),
        ],
    )]
    entries = _failure_entries(history)
    assert len(entries) == 1
    assert entries[0]["stage"] == "validate"
    assert "revenue_matches" in entries[0]["summary"]
    assert "row_count_ok" not in entries[0]["summary"]  # only the failing check, not the passing one


def test_failure_entries_skips_a_passing_attempt():
    history = [Iteration(attempt=1, candidate_sql="SELECT 1", stage="validate", gate_failed=False, results=[])]
    assert _failure_entries(history) == []


def test_failure_entries_withholds_a_summary_that_looks_like_it_leaked_pii():
    history = [Iteration(
        attempt=1, candidate_sql="SELECT 1", stage="deploy", gate_failed=True,
        error="failed for customer jane.doe@example.com",
    )]
    entries = _failure_entries(history)
    assert "jane.doe@example.com" not in entries[0]["summary"]
    assert "withheld" in entries[0]["summary"]
