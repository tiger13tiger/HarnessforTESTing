"""Reads reports/metrics_log.jsonl (harness/metrics_log.py's output) and prints
a plain console summary: success rate, token/cost totals, and a per-model
breakdown -- the last one surfaces a provider silently changing the model
behind a generic alias (e.g. "deepseek-chat") as a visible before/after split,
not just a hunch.

Run on demand (`python -m harness.metrics_cli --log reports/metrics_log.jsonl`),
not from a scheduled workflow: there's exactly one procedure logging to this
file today, so a live dashboard would be infrastructure for a problem that
doesn't exist yet. This log format is what one would read from, if/when that's
actually warranted.
"""
import argparse
import sys
from collections import defaultdict

from harness.metrics_log import load_entries  # noqa: F401 -- re-exported for backward compatibility


def summarize(entries: list[dict]) -> dict:
    total = len(entries)
    successes = sum(1 for e in entries if e.get("success"))
    total_tokens = sum(e.get("total_tokens", 0) for e in entries)
    total_cost = sum(e.get("estimated_cost_usd", 0.0) for e in entries)

    by_model = defaultdict(lambda: {"attempts": 0, "successes": 0})
    for e in entries:
        model = e.get("model") or "(unknown)"
        by_model[model]["attempts"] += 1
        if e.get("success"):
            by_model[model]["successes"] += 1

    return {
        "total_attempts": total,
        "successes": successes,
        "success_rate": (successes / total) if total else None,
        "total_tokens": total_tokens,
        "total_estimated_cost_usd": round(total_cost, 6),
        "by_model": dict(by_model),
    }


def format_report(summary: dict) -> str:
    lines = [
        f"Attempts: {summary['total_attempts']}",
        f"Successes: {summary['successes']}"
        + (f" ({summary['success_rate']:.0%})" if summary["success_rate"] is not None else ""),
        f"Total tokens: {summary['total_tokens']}",
        f"Total estimated cost: ${summary['total_estimated_cost_usd']:.4f}",
        "",
        "By model:",
    ]
    if not summary["by_model"]:
        lines.append("  (no attempts logged yet)")
    for model, stats in summary["by_model"].items():
        rate = (stats["successes"] / stats["attempts"]) if stats["attempts"] else 0
        lines.append(f"  {model}: {stats['successes']}/{stats['attempts']} ({rate:.0%})")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Summarize the auto-fix metrics log")
    parser.add_argument("--log", default="reports/metrics_log.jsonl", help="path to the metrics_log.jsonl file")
    parser.add_argument("--last", type=int, default=None, help="only consider the last N entries")
    args = parser.parse_args(argv)

    entries = load_entries(args.log)
    if args.last is not None:
        entries = entries[-args.last:]

    print(format_report(summarize(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
