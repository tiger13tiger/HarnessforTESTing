"""Runs every check in a suite against a connector, catching and timing each one
so a single bad query never aborts the whole run."""
import importlib
import time
from dataclasses import dataclass, field

from harness.connector import TransientError

CHECK_MODULES = {
    "row_count": "harness.checks.row_count",
    "null_rate": "harness.checks.null_rate",
    "duplicates": "harness.checks.duplicates",
    "schema": "harness.checks.schema",
    "aggregate": "harness.checks.aggregate",
    "pivot_readiness": "harness.checks.pivot_readiness",
}


@dataclass
class CheckResult:
    id: str
    category: str
    description: str
    severity: str
    status: str  # "pass" | "fail" | "error"
    message: str
    details: dict = field(default_factory=dict)
    duration_ms: float = 0.0


def run_suite(suite: dict, connector, retries: int = 2) -> list[CheckResult]:
    results = []
    for check in suite["checks"]:
        module_path = CHECK_MODULES.get(check["type"])
        if module_path is None:
            results.append(CheckResult(
                check["id"], check["category"], check["description"], check["severity"],
                "error", f"unknown check type: {check['type']}",
            ))
            continue

        module = importlib.import_module(module_path)
        start = time.monotonic()
        attempt = 0
        while True:
            try:
                status, message, details = module.run(connector, check.get("params", {}))
                break
            except TransientError as exc:
                attempt += 1
                if attempt > retries:
                    status, message, details = "error", f"transient error after {retries} retries: {exc}", {}
                    break
                time.sleep(2 ** attempt)
            except Exception as exc:  # noqa: BLE001 - one bad check must not abort the run
                status, message, details = "error", f"{type(exc).__name__}: {exc}", {}
                break
        duration_ms = (time.monotonic() - start) * 1000

        results.append(CheckResult(
            check["id"], check["category"], check["description"], check["severity"],
            status, message, details, duration_ms,
        ))
    return results
