"""A durable, git-native, per-procedure record of distinct failure patterns the
auto-fix loop has hit -- reports/lessons/<proc-stem>.jsonl, one line per NEW
stage+reason combination (not one line per attempt; a procedure that fails
the same way 5 rounds running gets one entry, not 5).

This is a RECORD for a human to read, nothing more. It is never read back
into a prompt automatically -- see README.md's "Lessons log" section for the
full reasoning, but in short: a "lesson" promoted into
harness/llm_client.py's STAGE_GUIDANCE without a human deciding it's a real,
general pattern (not a coincidence, not text influenced by something this
harness didn't author) becomes a standing instruction for every future fix,
on every procedure, with no diff and no reviewer -- exactly the kind of
unreviewed change this project's dev -> uat -> main gate exists to prevent
everywhere else. Promoting a confirmed lesson into the prompt is a normal,
reviewed code change to STAGE_GUIDANCE; this module only writes the record
that makes a real pattern visible to do that from.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _fingerprint(entry: dict) -> str:
    """What makes two failures "the same" for dedup purposes: same stage, and
    the same check id(s) if it's a validate-stage failure (the part of the
    summary that doesn't change run to run), ignoring the free-text message
    (which can vary in wording for the same underlying cause)."""
    stage = entry.get("stage", "")
    summary = entry.get("summary", "")
    if stage == "validate":
        # "validate: check_id (fail): message; check_id2 (error): message2" -> check ids only
        ids = [part.split(" (", 1)[0].strip() for part in summary.split(": ", 1)[-1].split(";")]
        return f"validate:{','.join(sorted(i for i in ids if i))}"
    return stage


def load_lesson_fingerprints(path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    fingerprints = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            fingerprints.add(_fingerprint(json.loads(line)))
    return fingerprints


def append_new_lessons(path, proc: str, round_number: int, failures: list[dict]) -> int:
    """Appends one line per entry in `failures` whose fingerprint hasn't been
    seen before in this log. Returns how many were actually new (0 is a
    normal, expected result -- most rounds re-hit a failure already on
    record, not a fresh one)."""
    path = Path(path)
    seen = load_lesson_fingerprints(path)
    new_count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for entry in failures:
            fp = _fingerprint(entry)
            if fp in seen:
                continue
            seen.add(fp)
            new_count += 1
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "proc": proc,
                "round": round_number,
                "attempt": entry.get("attempt"),
                "stage": entry.get("stage"),
                "summary": entry.get("summary"),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return new_count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Record new failure patterns from an evolve run into a per-procedure lessons log")
    parser.add_argument("--log", required=True, help="path to reports/lessons/<proc-stem>.jsonl")
    parser.add_argument("--proc", required=True, help="path to the procedure file this run was for")
    parser.add_argument("--round", required=True, type=int, help="the auto-fix round number this run was")
    parser.add_argument("--evolve-summary", required=True, help="path to the evolve_summary.json this run wrote")
    args = parser.parse_args(argv)

    try:
        summary = json.loads(Path(args.evolve_summary).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return 0  # evolve_cli.py can fail before writing a summary -- nothing to record

    new_count = append_new_lessons(args.log, args.proc, args.round, summary.get("failures") or [])
    if new_count:
        print(f"{new_count} new failure pattern(s) recorded to {args.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
