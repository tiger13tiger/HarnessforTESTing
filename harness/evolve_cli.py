"""Entry point for the auto-fix loop.

Example:
    SYNAPSE_SANDBOX_CONN_STR="Driver=...;Server=...;Database=...;Uid=...;Pwd=..." \\
    ANTHROPIC_API_KEY="sk-..." \\
        python -m harness.evolve_cli \\
            --proc procs/sp_refresh_fact_sales.sql \\
            --exec-statement "EXEC sandbox.sp_refresh_fact_sales" \\
            --suite tests/golden_fact_sales.yaml \\
            --allowed-schema sandbox

This never commits, pushes or opens a PR on its own. On success it writes the
final passing SQL to --output-proc (default: overwrites --proc) and a full
iteration report to --output-dir, for a human to review and commit.
"""
import argparse
import sys
from pathlib import Path

from harness.config import load_suite
from harness.connector import SynapseConnector
from harness.evolve import evolve
from harness.llm_client import AnthropicLLMClient
from harness.report import write_evolve_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Deploy-validate-fix loop for a Synapse stored procedure")
    parser.add_argument("--proc", required=True, help="path to the candidate CREATE OR ALTER PROCEDURE .sql file")
    parser.add_argument("--exec-statement", required=True, help="SQL that invokes the procedure, e.g. 'EXEC sandbox.sp_refresh_fact_sales'")
    parser.add_argument("--suite", required=True, help="validation suite YAML (golden_rows / row_count / etc.)")
    parser.add_argument("--allowed-schema", required=True, help="schema the candidate procedure must live in (sandbox isolation)")
    parser.add_argument("--conn-env", default="SYNAPSE_SANDBOX_CONN_STR")
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--output-proc", default=None, help="where to write the final passing proc SQL (default: overwrite --proc)")
    parser.add_argument("--model", default="claude-opus-5-5")
    args = parser.parse_args(argv)

    initial_sql = Path(args.proc).read_text(encoding="utf-8")
    suite = load_suite(args.suite)

    try:
        connector = SynapseConnector(env_var=args.conn_env)
        llm_client = AnthropicLLMClient(model=args.model)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    success, history = evolve(
        initial_sql=initial_sql,
        exec_statement=args.exec_statement,
        validation_suite=suite,
        connector=connector,
        llm_client=llm_client,
        allowed_schema=args.allowed_schema,
        context=f"Candidate procedure file: {args.proc}",
        max_iterations=args.max_iterations,
    )

    write_evolve_report(success, history, args.output_dir)

    if success:
        output_path = Path(args.output_proc or args.proc)
        output_path.write_text(history[-1].candidate_sql, encoding="utf-8")
        print(
            f"PASS after {len(history)} attempt(s). Final proc written to {output_path}. "
            f"Review {args.output_dir}/evolve_report.md, then commit and open a PR yourself -- "
            f"this tool never does that on its own."
        )
        return 0

    print(f"FAIL after {len(history)} attempt(s) -- see {args.output_dir}/evolve_report.md", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
