"""Tests harness/manifest.py's loader and TSV output -- no real procedure
files or database needed."""
import pytest
import yaml

from harness.manifest import load_manifest, to_tsv


def _write_manifest(tmp_path, procedures):
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump({"procedures": procedures}), encoding="utf-8")
    return path


def test_loads_a_valid_manifest(tmp_path):
    path = _write_manifest(tmp_path, [
        {"proc": "procs/a.sql", "suite": "tests/a.yaml", "exec_statement": "EXEC dbo.a", "allowed_schema": "dbo"},
        {"proc": "procs/b.sql", "suite": "tests/b.yaml", "exec_statement": "EXEC dbo.b", "allowed_schema": "dbo"},
    ])
    procedures = load_manifest(path)
    assert len(procedures) == 2
    assert procedures[0]["proc"] == "procs/a.sql"
    assert procedures[1]["proc"] == "procs/b.sql"


def test_missing_required_key_raises_naming_it(tmp_path):
    path = _write_manifest(tmp_path, [{"proc": "procs/a.sql", "suite": "tests/a.yaml"}])
    with pytest.raises(ValueError, match="exec_statement"):
        load_manifest(path)


def test_empty_procedures_list_raises(tmp_path):
    path = _write_manifest(tmp_path, [])
    with pytest.raises(ValueError, match="non-empty"):
        load_manifest(path)


def test_missing_procedures_key_raises(tmp_path):
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump({"something_else": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty"):
        load_manifest(path)


def test_to_tsv_one_tab_separated_line_per_entry():
    procedures = [
        {"proc": "procs/a.sql", "suite": "tests/a.yaml", "exec_statement": "EXEC dbo.a", "allowed_schema": "dbo"},
        {"proc": "procs/b.sql", "suite": "tests/b.yaml", "exec_statement": "EXEC dbo.b", "allowed_schema": "dbo"},
    ]
    lines = to_tsv(procedures).splitlines()
    assert lines == [
        "procs/a.sql\ttests/a.yaml\tEXEC dbo.a\tdbo",
        "procs/b.sql\ttests/b.yaml\tEXEC dbo.b\tdbo",
    ]
