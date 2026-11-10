"""Tests harness/metrics_log.py's append/build logic -- no real pipeline
run needed, just the files it reads and writes."""
import json

from harness.metrics_log import append_entry, entry_from_evolve_summary, main, next_round_for_proc


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


def test_next_round_is_1_with_no_history(tmp_path):
    log_path = tmp_path / "metrics_log.jsonl"
    assert next_round_for_proc(log_path, "procs/a.sql") == 1


def test_next_round_counts_consecutive_failures_for_this_proc(tmp_path):
    log_path = tmp_path / "metrics_log.jsonl"
    append_entry(log_path, {"proc": "procs/a.sql", "round": 1, "success": False})
    append_entry(log_path, {"proc": "procs/a.sql", "round": 2, "success": False})
    assert next_round_for_proc(log_path, "procs/a.sql") == 3


def test_next_round_resets_after_a_logged_success(tmp_path):
    log_path = tmp_path / "metrics_log.jsonl"
    append_entry(log_path, {"proc": "procs/a.sql", "round": 1, "success": False})
    append_entry(log_path, {"proc": "procs/a.sql", "round": 2, "success": True})
    assert next_round_for_proc(log_path, "procs/a.sql") == 1


def test_next_round_does_not_mix_different_procedures(tmp_path):
    # The exact scaling bug this replaces: a single shared counter (parsed
    # from the last commit on dev) meant one procedure's failing rounds
    # could be attributed to a completely different procedure once the
    # manifest held more than one.
    log_path = tmp_path / "metrics_log.jsonl"
    append_entry(log_path, {"proc": "procs/a.sql", "round": 1, "success": False})
    append_entry(log_path, {"proc": "procs/a.sql", "round": 2, "success": False})
    append_entry(log_path, {"proc": "procs/b.sql", "round": 1, "success": False})
    assert next_round_for_proc(log_path, "procs/a.sql") == 3
    assert next_round_for_proc(log_path, "procs/b.sql") == 2


def test_next_round_ignores_an_unrelated_commit_in_between_by_construction(tmp_path):
    # There's no "commit" concept in the log at all anymore -- this is really
    # testing that interleaved entries from other procedures between two of
    # this procedure's entries don't break the consecutive-failure count.
    log_path = tmp_path / "metrics_log.jsonl"
    append_entry(log_path, {"proc": "procs/a.sql", "round": 1, "success": False})
    append_entry(log_path, {"proc": "procs/c.sql", "round": 1, "success": True})
    append_entry(log_path, {"proc": "procs/a.sql", "round": 2, "success": False})
    assert next_round_for_proc(log_path, "procs/a.sql") == 3


def test_cli_next_round_subcommand_prints_the_number(tmp_path, capsys):
    log_path = tmp_path / "metrics_log.jsonl"
    append_entry(log_path, {"proc": "procs/a.sql", "round": 1, "success": False})
    main(["next-round", "--log", str(log_path), "--proc", "procs/a.sql"])
    assert capsys.readouterr().out.strip() == "2"


def test_cli_append_subcommand_still_works(tmp_path):
    log_path = tmp_path / "metrics_log.jsonl"
    summary_path = tmp_path / "evolve_summary.json"
    summary_path.write_text(json.dumps({"success": True, "model": "deepseek-chat"}), encoding="utf-8")

    main([
        "append", "--log", str(log_path), "--proc", "procs/a.sql",
        "--round", "1", "--evolve-summary", str(summary_path),
    ])

    entries = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert entries["proc"] == "procs/a.sql"
    assert entries["round"] == 1
    assert entries["success"] is True
