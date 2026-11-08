"""A fixed-answer connector for testing check logic without a real Synapse connection."""


class MockConnector:
    def __init__(self, fixtures: dict[str, list[dict]]):
        self.fixtures = fixtures

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        key = " ".join(sql.split())
        if key not in self.fixtures:
            raise KeyError(f"MockConnector has no fixture for query: {key!r}")
        return self.fixtures[key]
