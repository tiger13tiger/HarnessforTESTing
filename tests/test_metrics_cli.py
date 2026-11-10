"""Tests harness/metrics_cli.py's aggregation math against a small fixture
log -- no real pipeline history needed."""
import json

from harness.metrics_cli import format_report, load_entries, summarize


def _write_log(tmp_path, entries):
    path = tmp_path / "metrics_log.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


def test_load_entries_returns_empty_list_for_a_missing_file(tmp_path):
    assert load_entries(tmp_path / "does_not_exist.jsonl") == []


def test_load_entries_parses_each_line(tmp_path):
    path = _write_log(tmp_path, [{"success": True}, {"success": False}])
    assert load_entries(path) == [{"success": True}, {"success": False}]


def test_summarize_computes_success_rate_and_totals():
    entries = [
        {"success": True, "total_tokens": 100, "estimated_cost_usd": 0.01, "model": "deepseek-chat"},
        {"success": False, "total_tokens": 200, "estimated_cost_usd": 0.02, "model": "deepseek-chat"},
        {"success": True, "total_tokens": 50, "estimated_cost_usd": 0.005, "model": "deepseek-chat"},
    ]
    summary = summarize(entries)
    assert summary["total_attempts"] == 3
    assert summary["successes"] == 2
    assert summary["success_rate"] == 2 / 3
    assert summary["total_tokens"] == 350
    assert summary["total_estimated_cost_usd"] == 0.035
    assert summary["by_model"]["deepseek-chat"] == {"attempts": 3, "successes": 2}


def test_summarize_splits_by_model_so_a_model_change_is_visible():
    entries = [
        {"success": True, "model": "deepseek-chat"},
        {"success": True, "model": "deepseek-chat"},
        {"success": False, "model": "deepseek-chat-v2"},
    ]
    summary = summarize(entries)
    assert summary["by_model"]["deepseek-chat"] == {"attempts": 2, "successes": 2}
    assert summary["by_model"]["deepseek-chat-v2"] == {"attempts": 1, "successes": 0}


def test_summarize_handles_an_empty_log():
    summary = summarize([])
    assert summary["total_attempts"] == 0
    assert summary["success_rate"] is None
    assert summary["by_model"] == {}


def test_format_report_does_not_crash_on_an_empty_log():
    report = format_report(summarize([]))
    assert "Attempts: 0" in report
    assert "no attempts logged yet" in report


def test_format_report_includes_per_model_breakdown():
    summary = summarize([{"success": True, "model": "deepseek-chat"}])
    report = format_report(summary)
    assert "deepseek-chat: 1/1 (100%)" in report
