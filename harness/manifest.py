"""Loads and validates procs/manifest.yaml -- the list of procedures the
pipeline validates/promotes/auto-fixes. Mirrors harness/config.py's
load_suite(): read the YAML, check required keys are present, fail loudly
naming what's missing rather than letting a malformed entry surface as a
confusing error three steps later in a workflow.
"""
import argparse
import sys
from pathlib import Path

import yaml

REQUIRED_KEYS = {"proc", "suite", "exec_statement", "allowed_schema"}


def load_manifest(path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    procedures = data.get("procedures") if isinstance(data, dict) else None
    if not isinstance(procedures, list) or not procedures:
        raise ValueError(f"{path}: must have a non-empty top-level 'procedures' list")

    for entry in procedures:
        missing = REQUIRED_KEYS - entry.keys()
        if missing:
            raise ValueError(f"{path}: entry {entry.get('proc', '?')} missing keys: {missing}")

    return procedures


def to_tsv(procedures: list[dict]) -> str:
    """One tab-separated line per entry, in REQUIRED_KEYS' field order -- consumed
    by a workflow's `while IFS=$'\\t' read -r proc suite exec_stmt schema; do ...`
    loop. Tabs/newlines in a field would break this; procedure manifests are
    short, reviewed file paths and SQL statements, not free-form user input, so
    that's an acceptable assumption here."""
    fields = ("proc", "suite", "exec_statement", "allowed_schema")
    return "\n".join("\t".join(entry[f] for f in fields) for entry in procedures)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load and validate procs/manifest.yaml")
    parser.add_argument("manifest", help="path to the manifest YAML file")
    parser.add_argument("--tsv", action="store_true", help="print one tab-separated line per entry")
    args = parser.parse_args(argv)

    try:
        procedures = load_manifest(args.manifest)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.tsv:
        print(to_tsv(procedures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
