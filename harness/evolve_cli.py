"""Entry point for the auto-fix loop, meant to run against your DEV environment.

Example:
    SYNAPSE_DEV_CONN_STR="Driver=...;Server=...;Database=...;Uid=...;Pwd=..." \\
    ANTHROPIC_API_KEY="sk-..." \\
        python -m harness.evolve_cli \\
            --proc procs/sp_refresh_fact_sales.sql \\
            --exec-statement "EXEC dbo.sp_refresh_fact_sales" \\
            --suite tests/golden_fact_sales.yaml \\
            --allowed-schema dbo \\
            --conn-env SYNAPSE_DEV_CONN_STR \\
            --push

Without --push (the default), this never commits, pushes or opens a PR on its
own: on success it writes the final passing SQL to --output-proc (default:
overwrites --proc) and a full iteration report to --output-dir, for a human
to review and commit. With --push, it commits and pushes that file to the
current branch automatically once the loop converges -- the dev stage of a
dev -> uat -> prd flow where dev is deliberately the automated end and
uat -> prd stays a manual PR (see README).
"""
import argparse
import subprocess
import sys
from pathlib import Path

from harness.config import load_suite
from harness.connector import SynapseConnector
from harness.evolve import evolve
from harness.llm_client import AnthropicLLMClient
from harness.report import write_evolve_report


def _commit_and_push(path: Path, message: str) -> bool:
    """Commits and pushes `path` on the current branch if it actually changed.
    Returns True if a push happened, False if there was nothing to commit."""
    status = subprocess.run(
        ["git", "status", "--porcelain", str(path)], capture_output=True, text=True, check=True,
    )
    if not status.stdout.strip():
        return False
    subprocess.run(["git", "add", str(path)], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push"], check=True)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Deploy-validate-fix loop for a Synapse stored procedure")
    parser.add_argument("--proc", required=True, help="path to the candidate CREATE OR ALTER PROCEDURE .sql file")
    parser.add_argument("--exec-statement", required=True, help="SQL that invokes the procedure, e.g. 'EXEC dbo.sp_refresh_fact_sales'")
    parser.add_argument("--suite", required=True, help="validation suite YAML (golden_rows / row_count / etc.)")
    parser.add_argument("--allowed-schema", required=True, help="schema the candidate procedure must live in")
    parser.add_argument("--conn-env", default="SYNAPSE_DEV_CONN_STR")
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--output-proc", default=None, help="where to write the final passing proc SQL (default: overwrite --proc)")
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--push", action="store_true", help="commit and push the final proc to the current branch once it passes")
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
            f"See {args.output_dir}/evolve_report.md for the full iteration history."
        )
        if args.push:
            message = f"Auto-fix {output_path.name} via evolve loop ({len(history)} iteration(s))"
            if _commit_and_push(output_path, message):
                print(f"Pushed {output_path} to the current branch.")
            else:
                print(f"{output_path} already matches what's committed; nothing to push.")
        else:
            print("Not pushed (pass --push to commit and push automatically).")
        return 0

    print(f"FAIL after {len(history)} attempt(s) -- see {args.output_dir}/evolve_report.md", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
