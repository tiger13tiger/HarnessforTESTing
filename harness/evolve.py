"""The deploy -> validate -> fix loop.

Takes a candidate stored procedure, deploys it into a sandbox schema, runs it,
checks its output against business-verified golden values (or any other
validation suite), and -- if a check fails -- asks an LLM for a corrected
version of the procedure and tries again, up to a hard iteration cap.

Safety by construction, not by convention:
- every candidate is guardrail-checked (harness/guardrails.py) *before* it is
  deployed, so a candidate that touches the wrong schema or contains a
  destructive statement is rejected without ever running;
- this loop never writes to git, never opens a PR and never deploys outside
  the sandbox schema -- it only returns the final SQL and a report for a
  human to review and commit.
"""
from dataclasses import dataclass, field

from harness.guardrails import GuardrailViolation, check_candidate_sql
from harness.report import gate_failed
from harness.runner import run_suite


@dataclass
class Iteration:
    attempt: int
    candidate_sql: str
    results: list = field(default_factory=list)
    gate_failed: bool = True
    rationale: str = ""
    guardrail_error: str = ""


def evolve(
    initial_sql: str,
    exec_statement: str,
    validation_suite: dict,
    connector,
    llm_client,
    allowed_schema: str,
    context: str = "",
    max_iterations: int = 5,
) -> tuple[bool, list[Iteration]]:
    candidate_sql = initial_sql
    history: list[Iteration] = []

    for attempt in range(1, max_iterations + 1):
        try:
            check_candidate_sql(candidate_sql, allowed_schema)
        except GuardrailViolation as exc:
            history.append(Iteration(attempt, candidate_sql, guardrail_error=str(exc)))
            break  # a guardrail violation means stop, not retry

        connector.execute(candidate_sql)
        connector.execute(exec_statement)
        results = run_suite(validation_suite, connector)
        failed = gate_failed(results)
        history.append(Iteration(attempt, candidate_sql, results, failed))

        if not failed:
            return True, history
        if attempt == max_iterations:
            break

        failing = [
            {"id": r.id, "message": r.message, "details": r.details}
            for r in results if r.status in ("fail", "error")
        ]
        suggestion = llm_client.suggest_fix(candidate_sql, failing, context)
        history[-1].rationale = suggestion.rationale
        candidate_sql = suggestion.sql

    return False, history
