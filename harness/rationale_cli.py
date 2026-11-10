"""Prints the LLM's rationale out of an evolve_summary.json, for auto-fix-dev.yml's
commit-message step. Exists as a real module instead of an inline `python3 -c`
in the workflow YAML because that inline version broke: the YAML block's own
indentation became the literal leading whitespace of the Python source, which
is a syntax error at the module's first statement -- caught by running it,
not by reading it. A real module is testable; a string embedded in YAML isn't.
"""
import argparse
import json
import sys
from pathlib import Path


def render_rationale(evolve_summary_path) -> str:
    path = Path(evolve_summary_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return f"({evolve_summary_path} not found)"
    return data.get("rationale") or "(no rationale recorded by evolve_cli.py for this run)"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Print an evolve_summary.json's rationale field")
    parser.add_argument("evolve_summary_path", help="path to evolve_summary.json")
    args = parser.parse_args(argv)
    print(render_rationale(args.evolve_summary_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
