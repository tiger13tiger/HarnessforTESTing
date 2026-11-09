"""The deploy -> validate -> fix loop.

Takes a candidate stored procedure, deploys it into a sandbox schema, runs it,
checks its output against business-verified golden values (or any other
validation suite), and -- if a check fails -- asks an LLM for a corrected
version of the procedure and tries again, up to a hard iteration cap.

Safety by construction, not by convention:
- every candidate is guardrail-checked (harness/guardrails.py) *before* it is
  ever deployed, so one that touches the wrong schema or contains a
  destructive statement is rejected without ever running;
- deploy -> exec -> validate for one attempt all run inside a single held-open
  transaction (harness/connector.py's SynapseTransaction): validation queries
  see the attempt's own uncommitted changes, and a failing attempt is rolled
  back as a unit -- a candidate that doesn't pass never leaves a mark on the
  sandbox schema, even if it TRUNCATEs and re-INSERTs a table along the way;
- a failure is tagged with the stage it failed at (deploy/exec/validate), so
  the LLM gets a specific signal instead of one undifferentiated error blob;
- the LLM call itself is retried on transient failure and never allowed to
  crash the loop -- an exhausted LLM is a failed iteration, not a stack trace;
- this loop never writes to git, never opens a PR and never deploys outside
  the sandbox schema -- it only returns the final SQL and a report for a
  human to review and commit.
"""
import time
from dataclasses import dataclass, field

from harness.guardrails import GuardrailViolation, check_candidate_sql
from harness.report import gate_failed
from harness.runner import run_suite


@dataclass
class Iteration:
    attempt: int
    candidate_sql: str
    stage: str = "validate"  # "guardrail" | "deploy" | "exec" | "validate" | "llm"
    results: list = field(default_factory=list)
    gate_failed: bool = True
    rationale: str = ""
    error: str = ""  # guardrail/deploy/exec/llm failure text; empty for a plain check failure


def _run_one_attempt(txn, candidate_sql: str, exec_statement: str, validation_suite: dict):
    """Returns (stage, results_or_None, error_or_None) for one deploy+exec+validate pass."""
    try:
        txn.execute(candidate_sql)
    except Exception as exc:  # noqa: BLE001 - a bad candidate must become a failed attempt, not a crash
        return "deploy", None, str(exc)

    try:
        txn.execute(exec_statement)
    except Exception as exc:  # noqa: BLE001
        return "exec", None, str(exc)

    return "validate", run_suite(validation_suite, txn), None


def _suggest_fix_with_retries(llm_client, candidate_sql, failing_checks, context, retries=2):
    """Never lets a flaky LLM call crash the loop: retries with backoff, then
    reports the exhaustion as a (suggestion=None, error) pair instead of raising."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return llm_client.suggest_fix(candidate_sql, failing_checks, context), None
        except Exception as exc:  # noqa: BLE001 - provider SDKs raise their own exception types
            last_exc = exc
            if attempt < retries:
                time.sleep(2 ** (attempt + 1))
    return None, last_exc


def evolve(
    initial_sql: str,
    exec_statement: str,
    validation_suite: dict,
    connector,
    llm_client,
    allowed_schema: str,
    context: str = "",
    max_iterations: int = 5,
    llm_retries: int = 2,
) -> tuple[bool, list[Iteration]]:
    candidate_sql = initial_sql
    history: list[Iteration] = []

    for attempt in range(1, max_iterations + 1):
        try:
            check_candidate_sql(candidate_sql, allowed_schema)
        except GuardrailViolation as exc:
            history.append(Iteration(attempt, candidate_sql, stage="guardrail", error=str(exc)))
            break  # a guardrail violation means stop, not retry -- nothing was deployed

        txn = connector.transaction()
        try:
            stage, results, error = _run_one_attempt(txn, candidate_sql, exec_statement, validation_suite)

            if stage == "validate":
                failed = gate_failed(results)
                txn.commit() if not failed else txn.rollback()
                history.append(Iteration(attempt, candidate_sql, stage=stage, results=results, gate_failed=failed))
                if not failed:
                    return True, history
                failing = [
                    {"id": r.id, "message": r.message, "details": r.details}
                    for r in results if r.status in ("fail", "error")
                ]
            else:
                txn.rollback()  # no-op if nothing was applied (e.g. the deploy itself failed to parse)
                history.append(Iteration(attempt, candidate_sql, stage=stage, error=error))
                failing = [{"id": stage, "message": error, "details": {}}]
        finally:
            txn.close()

        if attempt == max_iterations:
            break

        suggestion, llm_error = _suggest_fix_with_retries(
            llm_client, candidate_sql, failing,
            f"{context}\n\nThe previous attempt failed at the '{stage}' stage.",
            retries=llm_retries,
        )
        if llm_error is not None:
            history.append(Iteration(attempt, candidate_sql, stage="llm", error=f"LLM call failed after retries: {llm_error}"))
            break
        history[-1].rationale = suggestion.rationale
        candidate_sql = suggestion.sql

    return False, history
