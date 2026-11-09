"""Proves promote_cli.main() reports a deploy/exec failure cleanly instead of
letting it crash out as a raw traceback -- caught by a real CI run against a
database whose tables didn't exist yet."""
from harness import promote_cli


def _write_files(tmp_path):
    proc = tmp_path / "proc.sql"
    proc.write_text("CREATE OR ALTER PROCEDURE dbo.sp_x\nAS\nBEGIN\n  SELECT 1;\nEND")
    suite = tmp_path / "suite.yaml"
    suite.write_text(
        "suite: s\n"
        "version: v1\n"
        "checks:\n"
        "  - id: ok\n"
        "    type: aggregate\n"
        "    severity: blocker\n"
        "    params:\n"
        "      sql: \"SELECT 1 AS x\"\n"
        "      expected: {x: 1}\n"
    )
    return proc, suite


class _InvalidObjectNameConnector:
    """Simulates a real pyodbc error (table doesn't exist) on EXEC."""

    def transaction(self):
        return _InvalidObjectNameTransaction()


class _InvalidObjectNameTransaction:
    def execute(self, sql, params=None):
        raise RuntimeError("Invalid object name 'dbo.raw_sales'")

    def rollback(self):
        pass

    def close(self):
        pass


def test_main_reports_a_deploy_exec_failure_cleanly_instead_of_crashing(tmp_path, monkeypatch, capsys):
    proc, suite = _write_files(tmp_path)
    monkeypatch.setattr(promote_cli, "SynapseConnector", lambda env_var: _InvalidObjectNameConnector())

    exit_code = promote_cli.main([
        "--proc", str(proc),
        "--exec-statement", "EXEC dbo.sp_x",
        "--suite", str(suite),
        "--allowed-schema", "dbo",
        "--conn-env", "FAKE_ENV_VAR",
        "--output-dir", str(tmp_path / "reports"),
    ])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "Invalid object name" in err
