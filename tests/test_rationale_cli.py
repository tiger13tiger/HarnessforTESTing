"""Tests harness/rationale_cli.py's render_rationale() -- the function that
replaced a broken inline `python3 -c` in auto-fix-dev.yml's commit-message
step (the YAML block's indentation was being passed through as literal Python
source indentation, an IndentationError on every real run)."""
import json

from harness.rationale_cli import render_rationale


def test_renders_the_rationale_field(tmp_path):
    path = tmp_path / "evolve_summary.json"
    path.write_text(json.dumps({"rationale": "Removed a fan-out join."}), encoding="utf-8")
    assert render_rationale(path) == "Removed a fan-out join."


def test_falls_back_to_a_placeholder_when_rationale_is_missing(tmp_path):
    path = tmp_path / "evolve_summary.json"
    path.write_text(json.dumps({"success": False}), encoding="utf-8")
    assert render_rationale(path) == "(no rationale recorded by evolve_cli.py for this run)"


def test_falls_back_to_a_placeholder_when_rationale_is_empty_string(tmp_path):
    path = tmp_path / "evolve_summary.json"
    path.write_text(json.dumps({"rationale": ""}), encoding="utf-8")
    assert render_rationale(path) == "(no rationale recorded by evolve_cli.py for this run)"


def test_reports_a_missing_file_instead_of_raising(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert render_rationale(missing) == f"({missing} not found)"
