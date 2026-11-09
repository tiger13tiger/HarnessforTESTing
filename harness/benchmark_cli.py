"""Prints a human-readable report of harness/benchmark.py's scripted-LLM scenarios.

    python -m harness.benchmark_cli

Run this after any change to harness/evolve.py, the same way you'd re-run a MockAgent
against planted bugs before trusting a modified evaluator: every case's actual
outcome should still match what it's designed to prove, or something in the loop's
mechanics broke.
"""
import sys

from harness.benchmark import run_benchmark


def main() -> int:
    report = run_benchmark()

    print(f"{'case':<30} {'expected':<10} {'actual':<10} {'iters':<6} {'final stage':<12} {'ok'}")
    print("-" * 80)
    all_ok = True
    for case in report.cases:
        ok = "✓" if case.matched_expectation else "✗ MISMATCH"
        all_ok = all_ok and case.matched_expectation
        print(
            f"{case.name:<30} {str(case.expected_success):<10} {str(case.actual_success):<10} "
            f"{case.iterations:<6} {case.final_stage:<12} {ok}"
        )

    print("-" * 80)
    print(f"{report.matched_expectation_count}/{report.total} cases matched their expected outcome")
    avg = report.avg_iterations_to_success
    if avg is not None:
        print(f"avg iterations to success (successful cases only): {avg:.1f}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
