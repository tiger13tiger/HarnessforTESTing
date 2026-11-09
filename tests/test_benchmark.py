"""Runs the scripted-LLM benchmark and asserts every case still matches its expected
outcome -- the loop-mechanics equivalent of re-running a MockAgent against planted
bugs after changing the evaluator, to prove harness/evolve.py didn't quietly get
more lenient (or stop converging) on a change."""
from harness.benchmark import run_benchmark


def test_every_benchmark_case_matches_its_expected_outcome(monkeypatch):
    monkeypatch.setattr("harness.evolve.time.sleep", lambda _seconds: None)  # skip real backoff delays

    report = run_benchmark()

    mismatches = [c for c in report.cases if not c.matched_expectation]
    assert not mismatches, f"benchmark cases that no longer match their expected outcome: {mismatches}"
    assert report.total == 6


def test_the_two_designed_to_fail_actually_fail(monkeypatch):
    monkeypatch.setattr("harness.evolve.time.sleep", lambda _seconds: None)

    report = run_benchmark()
    by_name = {c.name: c for c in report.cases}

    assert by_name["never_converges"].actual_success is False
    assert by_name["never_converges"].iterations == 3  # hit max_iterations, not an early crash

    assert by_name["llm_proposes_wrong_schema"].actual_success is False
    assert by_name["llm_proposes_wrong_schema"].final_stage == "guardrail"


def test_the_multi_stage_case_actually_exercises_all_three_failure_stages(monkeypatch):
    monkeypatch.setattr("harness.evolve.time.sleep", lambda _seconds: None)

    from harness.evolve import evolve
    from harness.benchmark import CHECK_SQL, EXEC_STATEMENT, GOOD_SCHEMA, SUITE, _case_multi_stage_chain

    initial_sql, llm_client, connector, max_iterations, expected_success = _case_multi_stage_chain()
    success, history = evolve(
        initial_sql=initial_sql, exec_statement=EXEC_STATEMENT, validation_suite=SUITE,
        connector=connector, llm_client=llm_client, allowed_schema=GOOD_SCHEMA,
        max_iterations=max_iterations, llm_retries=1,
    )

    assert success is expected_success
    stages_seen = [it.stage for it in history]
    assert stages_seen == ["deploy", "exec", "validate", "validate"]
    assert history[-1].gate_failed is False


def test_avg_iterations_to_success_is_computed_only_over_successes(monkeypatch):
    monkeypatch.setattr("harness.evolve.time.sleep", lambda _seconds: None)

    report = run_benchmark()
    successes = [c.iterations for c in report.cases if c.actual_success]
    assert report.avg_iterations_to_success == sum(successes) / len(successes)
