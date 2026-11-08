"""A fixed-answer connector for testing check logic without a real Synapse connection.

A fixture value can be a static list of rows, or a callable ``(connector) -> list[dict]``
that inspects ``connector.executed`` -- the DDL/EXEC statements run so far -- so a test
can simulate a deployed candidate changing what a later query returns (needed to test
the evolve loop across iterations without a real database).
"""


class MockConnector:
    def __init__(self, fixtures: dict[str, list[dict]] | None = None):
        self.fixtures = fixtures or {}
        self.executed: list[str] = []

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        key = " ".join(sql.split())
        if key not in self.fixtures:
            raise KeyError(f"MockConnector has no fixture for query: {key!r}")
        value = self.fixtures[key]
        return value(self) if callable(value) else value

    def execute(self, sql: str, params: list | None = None) -> None:
        self.executed.append(sql)
