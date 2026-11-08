"""Entry point for the dev -> uat promotion step: deploys a finalized stored
procedure to a target environment and validates it there. No LLM call -- the
auto-fix loop (harness/evolve_cli.py) already did that in dev.

Example (what .github/workflows/promote-dev-to-uat.yml runs):
    python -m harness.promote_cli \\
        --proc procs/sp_refresh_fact_sales.example.sql \\
        --exec-statement "EXEC dbo.sp_refresh_fact_sales" \\
        --suite tests/golden_fact_sales.example.yaml \\
        --allowed-schema dbo \\
        --conn-env SYNAPSE_UAT_CONN_STR
"""
import argparse
import sys
from pathlib import Path

from harness.config import load_suite
from harness.connector import SynapseConnector
from harness.guardrails import GuardrailViolation
from harness.promote import promote
from harness.report import write_reports


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Deploy a finalized stored procedure and validate it (no LLM)")
    parser.add_argument("--proc", required=True, help="path to the CREATE OR ALTER PROCEDURE .sql file")
    parser.add_argument("--exec-statement", required=True, help="SQL that invokes the procedure after deploy")
    parser.add_argument("--suite", required=True, help="validation suite YAML to run after invoking the procedure")
    parser.add_argument("--allowed-schema", required=True, help="schema the procedure must live in")
    parser.add_argument("--conn-env", required=True, help="env var holding the target environment's connection string")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args(argv)

    sql = Path(args.proc).read_text(encoding="utf-8")
    suite = load_suite(args.suite)

    try:
        connector = SynapseConnector(env_var=args.conn_env)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        results = promote(sql, args.exec_statement, suite, connector, args.allowed_schema)
    except GuardrailViolation as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = write_reports(results, suite["suite"], suite["version"], args.output_dir)
    print(
        f"Gate: {summary['gate'].upper()} — {summary['passed']}/{summary['total']} passed, "
        f"{summary['failed']} failed, {summary['errored']} errored. Report: {args.output_dir}/report.md"
    )
    return 1 if summary["gate"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
