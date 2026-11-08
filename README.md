# HarnessforTESTing

A testing harness for data pulled through Azure Synapse SQL / data warehouse,
built for the UAT gate before a release is pushed to PRD. A test analyst runs
it against the UAT environment; it checks the data the way the business will
actually consume it (including via Excel pivot tables) and produces a
pass/fail report.

## Why this shape

This harness borrows a few ideas from an AI-agent evaluation framework
(`build-eval-harness`) that doesn't otherwise fit a SQL data warehouse:

- **Judge by execution, not opinion** — every check runs a real SQL query
  and compares the result (exact match, tolerance, or diff vs. a baseline
  environment), not a free-text judgment.
- **Verify the checks before trusting them** — `tests/test_checks.py` runs
  every check against planted defects (a dropped row, a NULL spike, a
  duplicate key, a silently retyped column, a wrong total, a cardinality
  blow-up) and asserts the check actually fails. A check that can't catch
  its own planted bug can't be trusted on real data.
- **One bad check never aborts the run** — errors are caught and reported
  per check, with retry on transient Synapse errors (deadlock/timeout).
- **report.md + results.csv + summary.json + exit code** — human-readable
  report for the test analyst, full detail for follow-up, and an exit code
  ready to gate a CI pipeline later if you wire this into Azure DevOps.

Dropped entirely: guardrails against prompt injection, LLM-as-judge, prompt
evolution, RAG — none of that applies when there's no AI agent in the loop.

## What it checks

Each check type lives in `harness/checks/`:

| type | category | what it catches |
|---|---|---|
| `schema` | schema | a column renamed, retyped, or dropped between DEV and UAT |
| `row_count` | data_quality | row count out of bounds, or drifted vs. a baseline (e.g. DEV) beyond tolerance |
| `null_rate` | data_quality | a key column filling up with NULLs |
| `duplicates` | data_quality | a key that should be unique isn't |
| `aggregate` | business_logic | a calculated total/metric that doesn't match a reconciled figure (or drifted vs. baseline) |
| `pivot_readiness` | pivot_readiness | missing columns, a measure stored as text, or a dimension's cardinality/NULL rate that would break a pivot table |

A test suite is a YAML file listing checks (see `tests/uat_suite.example.yaml`
for a worked example against a `fact_sales` table). Each check has a
`severity` of `blocker` or `warning` — only a failed `blocker` (or any
`error`) fails the overall gate.

## Running it

```bash
pip install -r requirements.txt
```

Running against a real Synapse environment needs the Microsoft ODBC Driver
for SQL Server installed on the machine (`pyodbc` is just the Python side of
it). Put the connection string in an environment variable — never in the
suite file:

```bash
export SYNAPSE_UAT_CONN_STR="Driver={ODBC Driver 18 for SQL Server};Server=tcp:<workspace>.sql.azuresynapse.net,1433;Database=<db>;Uid=<user>;Pwd=<password>;Encrypt=yes;"

python -m harness.cli --config tests/uat_suite.example.yaml
```

This writes `reports/report.md`, `reports/results.csv`, and
`reports/summary.json`, and exits `1` if the gate failed (so it can later
become a pipeline step).

## Running the test suite (no Synapse connection needed)

```bash
python -m pytest
```

Unit tests run against `harness/mock_connector.py`, a fixed-answer
connector — no real database, no ODBC driver required. Use it to prove a
new check catches the defect it's meant to catch before pointing it at UAT.

## Adding a check

1. Copy an entry in `tests/uat_suite.example.yaml` (or write a new suite
   file) and point it at your table/query.
2. If no existing check type fits, add a module to `harness/checks/`
   exposing `run(connector, params) -> (status, message, details)`, register
   it in `harness/runner.py`'s `CHECK_MODULES`, and add a clean-pass +
   planted-defect test pair in `tests/test_checks.py`.

## Not yet wired up (by design, until needed)

- **CI/CD integration**: the exit code and `summary.json` are ready for an
  Azure DevOps pipeline gate, but nothing triggers this automatically today —
  the test analyst runs it manually in UAT.
- **Per-environment connection management**: `connection_env` in the suite
  file names the env var to read; how those secrets get into the shell
  (Azure Key Vault, pipeline secrets, etc.) is outside this harness's scope.
