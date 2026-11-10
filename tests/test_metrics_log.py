"""Tests harness/metrics_log.py's append/build logic -- no real pipeline
run needed, just the files it reads and writes."""
import json

from harness.metrics_log import append_entry, entry_from_evolve_summary


def test_append_entry_creates_the_file_and_writes_one_json_line(tmp_path):
    log_path = tmp_path / "metrics_log.jsonl"
    append_entry(log_path, {"proc": "a.sql", "success": True})

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"proc": "a.sql", "success": True}


def test_append_entry_appends_without_overwriting(tmp_path):
    log_path = tmp_path / "metrics_log.jsonl"
    append_entry(log_path, {"proc": "a.sql", "success": False})
    append_entry(log_path, {"proc": "a.sql", "success": True})

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["success"] is False
    assert json.loads(lines[1])["success"] is True


def test_append_entry_creates_parent_directories(tmp_path):
    log_path = tmp_path / "reports" / "metrics_log.jsonl"
    append_entry(log_path, {"proc": "a.sql"})
    assert log_path.exists()


def test_entry_from_evolve_summary_pulls_the_expected_fields():
    summary = {
        "success": True,
        "iterations": 2,
        "model": "deepseek-chat",
        "total_tokens": 1500,
        "estimated_cost_usd": 0.0003,
    }
    entry = entry_from_evolve_summary("procs/a.sql", 1, summary)
    assert entry["proc"] == "procs/a.sql"
    assert entry["round"] == 1
    assert entry["success"] is True
    assert entry["iterations"] == 2
    assert entry["model"] == "deepseek-chat"
    assert entry["total_tokens"] == 1500
    assert entry["estimated_cost_usd"] == 0.0003
    assert "timestamp" in entry


def test_entry_from_evolve_summary_handles_an_empty_summary():
    entry = entry_from_evolve_summary("procs/a.sql", 2, {})
    assert entry["success"] is False
    assert entry["iterations"] == 0
    assert entry["model"] == ""
    assert entry["total_tokens"] == 0
    assert entry["estimated_cost_usd"] == 0.0
