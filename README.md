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

Dropped: guardrails against *prompt injection*, LLM-as-judge, RAG — none of
that applies when there's no AI agent reading untrusted data. **Prompt
evolution did turn out to apply**, repurposed as the auto-fix loop below:
same idea (mutate a candidate, evaluate, keep only if it passes), but the
thing being evolved is a stored procedure instead of a prompt, and the judge
is a SQL result compared to business-verified numbers instead of an LLM
grading free text.

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
| `golden_rows` | business_logic | query result rows don't match a business-verified reference set (the numbers you already checked by hand in a pivot table), per dimension key and measure tolerance |

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

## The auto-fix loop (harness/evolve_cli.py)

Your actual dev flow: optimize a stored procedure → push it to the warehouse
→ refresh the semantic model's partitions → eyeball the result in a pivot
table. This tool automates the last two steps of validating that: given a
candidate `CREATE OR ALTER PROCEDURE` and the numbers you already verified
by hand in a pivot table, it deploys the candidate, runs it, checks the
result against those numbers, and — if it doesn't match — asks an LLM to
revise the procedure and tries again, up to a hard iteration cap.

```bash
export SYNAPSE_SANDBOX_CONN_STR="Driver={ODBC Driver 18 for SQL Server};Server=tcp:<workspace>.sql.azuresynapse.net,1433;Database=<db>;Uid=<user>;Pwd=<password>;Encrypt=yes;"
export ANTHROPIC_API_KEY="sk-..."

python -m harness.evolve_cli \
    --proc procs/sp_refresh_fact_sales.example.sql \
    --exec-statement "EXEC sandbox.sp_refresh_fact_sales" \
    --suite tests/golden_fact_sales.example.yaml \
    --allowed-schema sandbox
```

**Safety design — read this before running it for real:**

- **Sandbox-only, by construction.** Every candidate is checked by
  `harness/guardrails.py` *before* it's ever deployed: it must be exactly
  one `CREATE OR ALTER PROCEDURE` statement, targeting the schema you pass
  via `--allowed-schema`, with no `DROP DATABASE`/`TRUNCATE TABLE`/
  `xp_cmdshell`/etc. A candidate that fails this is rejected without
  touching the database at all. This is a text-level allow-list, not a
  full security boundary — back it with a least-privilege DB login that
  can only touch the sandbox schema (`SYNAPSE_SANDBOX_CONN_STR` should
  point at credentials scoped that way, never your UAT/PRD admin login).
- **Never auto-commits, never auto-pushes, never opens a PR.** On success
  it writes the final SQL to `--output-proc` (default: overwrites `--proc`)
  and the full iteration history to `reports/evolve_report.md` — you review
  and commit it yourself. The LLM is driving a sandbox, not your git
  history.
- **Where the actual CI gate lives.** `.github/workflows/uat-gate.yml` is
  the gate that runs in GitHub Actions on a pull request — it only
  *validates* (via `harness/cli.py`) against UAT, it never calls the LLM.
  So the flow is: run the evolve loop locally until it passes → commit the
  fixed proc + commit/update the golden suite → open a PR → the Actions
  gate re-validates against UAT → merge after human review. The LLM-driven
  loop stays out of the CI job on purpose, so nothing lands in `main`
  without a human having reviewed the actual diff.
- **Data governance.** The candidate SQL (and your schema) is sent to
  Anthropic's API by default (`harness/llm_client.py`'s
  `AnthropicLLMClient`). If company policy requires routing this through
  an approved tenant (e.g. your own Azure OpenAI deployment) instead,
  swap in a different `LLMClient` implementation — `suggest_fix()` is the
  only method to implement.

Each iteration's checks, pass/fail, and the LLM's stated rationale for its
next attempt are all recorded in `reports/evolve_report.md`, so a human
reviewing the eventual PR can see *why* the procedure changed, not just the
diff.

## Adding a check

1. Copy an entry in `tests/uat_suite.example.yaml` (or write a new suite
   file) and point it at your table/query.
2. If no existing check type fits, add a module to `harness/checks/`
   exposing `run(connector, params) -> (status, message, details)`, register
   it in `harness/runner.py`'s `CHECK_MODULES`, and add a clean-pass +
   planted-defect test pair in `tests/test_checks.py`.

## Not yet wired up (by design, until needed)

- **Actual deployment to UAT/PRD**: nothing here pushes a passing procedure
  into UAT or PRD — that's your existing release process. This harness only
  validates (and, in the sandbox, iterates on) what's about to go there.
- **Per-environment connection management**: `connection_env` in the suite
  file names the env var to read; how those secrets get into the shell
  (Azure Key Vault, GitHub Actions secrets, Azure DevOps variable groups,
  etc.) is outside this harness's scope.
