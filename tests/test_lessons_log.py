"""Tests harness/lessons_log.py's dedup and append logic -- no real pipeline
run needed, just the files it reads and writes."""
import json

from harness.lessons_log import append_new_lessons, load_lesson_fingerprints, main


def test_append_new_lessons_writes_a_new_entry(tmp_path):
    log_path = tmp_path / "lessons.jsonl"
    new_count = append_new_lessons(
        log_path, "procs/a.sql", 1,
        [{"attempt": 1, "stage": "deploy", "summary": "deploy: syntax error"}],
    )
    assert new_count == 1
    entries = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert entries[0]["proc"] == "procs/a.sql"
    assert entries[0]["stage"] == "deploy"
    assert "timestamp" in entries[0]


def test_append_new_lessons_dedupes_the_same_stage_across_rounds(tmp_path):
    log_path = tmp_path / "lessons.jsonl"
    append_new_lessons(log_path, "procs/a.sql", 1, [{"attempt": 1, "stage": "deploy", "summary": "deploy: syntax error"}])
    new_count = append_new_lessons(log_path, "procs/a.sql", 2, [{"attempt": 1, "stage": "deploy", "summary": "deploy: a different wording of the same syntax error"}])
    assert new_count == 0  # same fingerprint (stage=deploy), wording doesn't matter
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1


def test_append_new_lessons_dedupes_by_failing_check_ids_for_validate_stage(tmp_path):
    log_path = tmp_path / "lessons.jsonl"
    append_new_lessons(log_path, "procs/a.sql", 1, [{"attempt": 1, "stage": "validate", "summary": "validate: revenue_matches (fail): off by 12"}])
    same = append_new_lessons(log_path, "procs/a.sql", 2, [{"attempt": 1, "stage": "validate", "summary": "validate: revenue_matches (fail): off by 4 this time"}])
    different = append_new_lessons(log_path, "procs/a.sql", 3, [{"attempt": 1, "stage": "validate", "summary": "validate: row_count_ok (error): table missing"}])
    assert same == 0  # same failing check id -> same fingerprint
    assert different == 1  # a genuinely different check failing -> a new lesson


def test_load_lesson_fingerprints_returns_empty_set_for_a_missing_file(tmp_path):
    assert load_lesson_fingerprints(tmp_path / "does_not_exist.jsonl") == set()


def test_cli_appends_from_an_evolve_summary(tmp_path):
    log_path = tmp_path / "lessons.jsonl"
    summary_path = tmp_path / "evolve_summary.json"
    summary_path.write_text(json.dumps({
        "success": False,
        "failures": [{"attempt": 1, "stage": "exec", "summary": "exec: divide by zero"}],
    }), encoding="utf-8")

    main(["--log", str(log_path), "--proc", "procs/a.sql", "--round", "1", "--evolve-summary", str(summary_path)])

    entries = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert entries[0]["stage"] == "exec"


def test_cli_handles_a_missing_evolve_summary_gracefully(tmp_path):
    log_path = tmp_path / "lessons.jsonl"
    exit_code = main(["--log", str(log_path), "--proc", "procs/a.sql", "--round", "1",
                      "--evolve-summary", str(tmp_path / "does_not_exist.json")])
    assert exit_code == 0
    assert not log_path.exists()
