"""A durable, git-native log of every auto-fix attempt -- one JSON line per
attempt, appended to reports/metrics_log.jsonl and committed to dev alongside
(or instead of, when the round didn't converge) the proc file it tried to fix.
Git-native on purpose: no external database, no API dependency, no artifact
that expires after GitHub's retention window -- just a file this repo already
tracks, that harness/metrics_cli.py reads back to answer "is the auto-fix
success rate drifting" or "did cost jump after a model change."
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def append_entry(path, entry: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def entry_from_evolve_summary(proc: str, round_number: int, summary: dict) -> dict:
    """Builds the log entry from an evolve_summary.json dict (harness/report.py's
    write_evolve_report output) plus the round-tracking info only the calling
    workflow knows."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proc": proc,
        "round": round_number,
        "success": summary.get("success", False),
        "iterations": summary.get("iterations", 0),
        "model": summary.get("model", ""),
        "total_tokens": summary.get("total_tokens", 0),
        "estimated_cost_usd": summary.get("estimated_cost_usd", 0.0),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Append one auto-fix attempt to the metrics log")
    parser.add_argument("--log", required=True, help="path to the metrics_log.jsonl file")
    parser.add_argument("--proc", required=True, help="path to the procedure file this attempt was for")
    parser.add_argument("--round", required=True, type=int, help="the auto-fix round number this attempt was")
    parser.add_argument("--evolve-summary", required=True, help="path to the evolve_summary.json this attempt wrote")
    args = parser.parse_args(argv)

    try:
        summary = json.loads(Path(args.evolve_summary).read_text(encoding="utf-8"))
    except FileNotFoundError:
        # evolve_cli.py can fail before ever writing a summary (e.g. a bad
        # connection string) -- still log the attempt, just with nothing further known.
        summary = {}

    entry = entry_from_evolve_summary(args.proc, args.round, summary)
    append_entry(args.log, entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
