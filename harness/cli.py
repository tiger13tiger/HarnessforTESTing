"""Entry point for the test analyst: run a suite against an environment, get a report.

Example:
    SYNAPSE_UAT_CONN_STR="Driver=...;Server=...;Database=...;Uid=...;Pwd=..." \\
        python -m harness.cli --config tests/uat_suite.example.yaml --conn-env SYNAPSE_UAT_CONN_STR
"""
import argparse
import sys

from harness.config import load_suite
from harness.connector import SynapseConnector
from harness.report import write_reports
from harness.runner import run_suite


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Azure Synapse UAT testing harness")
    parser.add_argument("--config", required=True, help="path to the suite YAML file")
    parser.add_argument("--output-dir", default="reports", help="where report.md/results.csv/summary.json go")
    parser.add_argument(
        "--conn-env", default=None,
        help="env var holding the Synapse connection string (overrides the suite's connection_env)",
    )
    args = parser.parse_args(argv)

    suite = load_suite(args.config)
    conn_env = args.conn_env or suite.get("connection_env", "SYNAPSE_CONN_STR")
    try:
        connector = SynapseConnector(env_var=conn_env)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    results = run_suite(suite, connector)
    summary = write_reports(results, suite["suite"], suite["version"], args.output_dir)

    print(
        f"Gate: {summary['gate'].upper()} — {summary['passed']}/{summary['total']} passed, "
        f"{summary['failed']} failed, {summary['errored']} errored. "
        f"Report: {args.output_dir}/report.md"
    )
    return 1 if summary["gate"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
