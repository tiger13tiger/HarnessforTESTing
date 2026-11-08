"""Connections to Azure Synapse SQL, for executing test queries."""
import os

TRANSIENT_SQLSTATES = {"08S01", "HYT00", "40001", "40613"}


class TransientError(Exception):
    """A connection/query error worth retrying (deadlock, timeout, throttling)."""


class SynapseConnector:
    """Runs read-only queries against a Synapse SQL pool / serverless endpoint.

    Connection string comes from an environment variable (never hardcode
    credentials in a suite file). Point ``env_var`` at a per-environment
    variable, e.g. SYNAPSE_UAT_CONN_STR, SYNAPSE_PRD_CONN_STR.
    """

    def __init__(self, env_var: str = "SYNAPSE_CONN_STR", conn_str: str | None = None, query_timeout: int = 60):
        self.conn_str = conn_str or os.environ.get(env_var)
        if not self.conn_str:
            raise RuntimeError(f"connection string not found: set ${env_var}")
        self.query_timeout = query_timeout

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        # imported lazily so the harness (and its unit tests) don't need the
        # unixODBC runtime / driver installed unless a real query actually runs
        import pyodbc

        try:
            with pyodbc.connect(self.conn_str, timeout=self.query_timeout) as conn:
                conn.timeout = self.query_timeout
                cursor = conn.cursor()
                cursor.execute(sql, params or [])
                if cursor.description is None:
                    return []
                columns = [c[0] for c in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except pyodbc.Error as exc:
            sqlstate = exc.args[0] if exc.args else ""
            if sqlstate in TRANSIENT_SQLSTATES:
                raise TransientError(str(exc)) from exc
            raise
