# HarnessforTESTing

A testing harness for data pulled through Azure Synapse SQL / data warehouse.
It follows a `dev` → `uat` → `main` (prd) branch flow:

1. **dev** — you optimize a stored procedure; `harness/evolve_cli.py` can
   deploy it, check the result against business-verified figures, and ask an
   LLM to fix it when it doesn't match, looping until it passes. `--push`
   commits and pushes the final version automatically.
2. **dev → uat** — fully automatic. `.github/workflows/promote-dev-to-uat.yml`
   fires on push to `dev`, deploys the proc to UAT, re-validates it there,
   and — only if that passes — merges `dev` into `uat` and pushes. No human
   review in this step, by design. Then it re-validates again, this time
   the actual merged `uat` state, not just the candidate. If either check
   fails, the failure goes back to an LLM against `dev`; a converged fix
   pushes and re-triggers this whole step. Capped at 3 rounds total (shared
   between both checks) before it stops and waits for a human. Only a clean
   post-merge validation marks `uat` ready for stage 3.
3. **uat → prd** — the one manual gate. A human (the test analyst) opens a
   PR from `uat` into `main`; `.github/workflows/uat-to-prd-gate.yml`
   re-validates against UAT as a required check, but merging stays a human
   decision.

This maps directly onto the existing process: dev and uat are where
iteration happens freely, and prd only ever gets what a person actually
signed off on.

See [`docs/architecture.html`](docs/architecture.html) for a diagrammed walkthrough of this pipeline and of the `evolve()` fix loop's internals, and `PROCESS.md` for what a healthy pipeline state looks like.

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

## Stage 1 — dev: the auto-fix loop (harness/evolve_cli.py)

Your actual dev flow: optimize a stored procedure → push it → refresh the
semantic model's partitions → eyeball the result in a pivot table. This tool
automates the validate/fix part of that: given a candidate
`CREATE OR ALTER PROCEDURE` and the numbers you already verified by hand in
a pivot table, it deploys the candidate to DEV, runs it, checks the result
against those numbers, and — if it doesn't match — asks an LLM to revise the
procedure and tries again, up to a hard iteration cap.

```bash
export SYNAPSE_DEV_CONN_STR="Driver={ODBC Driver 18 for SQL Server};Server=tcp:<dev-workspace>.sql.azuresynapse.net,1433;Database=<db>;Uid=<user>;Pwd=<password>;Encrypt=yes;"
export ANTHROPIC_API_KEY="sk-..."

python -m harness.evolve_cli \
    --proc procs/sp_refresh_fact_sales.example.sql \
    --exec-statement "EXEC dbo.sp_refresh_fact_sales" \
    --suite tests/golden_fact_sales.example.yaml \
    --allowed-schema dbo \
    --conn-env SYNAPSE_DEV_CONN_STR \
    --push
```

**Safety design — read this before running it for real:**

- **Guardrail-checked before every deploy.** `harness/guardrails.py` checks
  each candidate *before* it's deployed: it must be exactly one
  `CREATE OR ALTER PROCEDURE` statement, targeting the schema you pass via
  `--allowed-schema`, with no `DROP DATABASE`/`TRUNCATE TABLE`/
  `xp_cmdshell`/etc. A candidate that fails this is rejected without
  touching the database at all. This is a text-level allow-list, not a full
  security boundary — the real isolation is that `--conn-env` should point
  at your DEV environment, physically separate from UAT/PRD, with
  least-privilege credentials.
- **Every attempt runs in one transaction, rolled back on failure.**
  Deploy → `EXEC` → validate all happen on the same held-open connection
  (`harness/connector.py`'s `SynapseTransaction`), so the validation
  queries see that attempt's own uncommitted changes. A failing attempt is
  rolled back as a unit before the LLM is asked for a fix — if the
  procedure `TRUNCATE`s and re-`INSERT`s a table, a candidate that doesn't
  pass never leaves that table changed. Only a passing attempt commits.
- **Failures are tagged by stage, not lumped together.** A candidate can
  fail to deploy (bad DDL), fail to `EXEC` (runtime error), or deploy fine
  but produce the wrong data (`stage` is `deploy`/`exec`/`validate` on each
  `Iteration` in `reports/evolve_report.md`). The LLM gets told which one
  happened, instead of one undifferentiated error blob.
- **A flaky LLM call can't crash the loop.** `suggest_fix()` is retried
  with backoff on failure (network blip, rate limit); if it's still
  failing after `--llm-retries` (not just this one call), that's recorded
  as a failed iteration with `stage: llm`, not an unhandled exception.
- **`--push` is opt-in and scoped to dev.** Without it, nothing is
  committed — the final SQL and iteration report are just local files for
  you to review. With it, the loop commits and pushes the final passing
  proc to whatever branch you're on once it converges. This is the one
  place in the pipeline that pushes code automatically; it's deliberately
  limited to dev, where a bad push costs you a re-run, not a UAT/PRD
  incident.
- **Choice of LLM, and data governance.** `--provider anthropic` (default)
  or `--provider deepseek` (`harness/llm_client.py`'s `AnthropicLLMClient` /
  `DeepSeekLLMClient`) — either way, the candidate SQL and your schema are
  sent to that provider's API. DeepSeek is a China-based provider; sending
  it your schema and stored-proc logic is an offshore data transfer, which
  may matter for data-residency or export-control policy even when the SQL
  itself contains no customer data. Confirm with whoever owns data
  governance at your company before pointing this at real procedures, not
  just examples. If policy requires routing through an approved tenant
  instead (e.g. your own Azure OpenAI deployment), swap in a different
  `LLMClient` implementation — `suggest_fix()` is the only method to
  implement.

Each iteration's checks, pass/fail, and the LLM's stated rationale for its
next attempt are recorded in `reports/evolve_report.md`.

### Does the loop actually converge? (harness/benchmark.py)

```bash
python -m harness.benchmark_cli
```

Six scripted-LLM scenarios (fixes immediately, fixes after three tries, never
converges, a deploy→exec→data-bug chain exercising all three failure stages,
an LLM that flakes once then recovers, an LLM that proposes a fix outside the
allowed schema) run through the real `evolve()` loop and report whether each
one converged the way it's designed to, in how many iterations.

**What this does and doesn't prove.** It's loop-mechanics testing, not a
real-world accuracy benchmark: every scenario uses `MockLLMClient` with
scripted responses, so it proves the loop converges, rolls back, tags stages,
enforces the guardrail, and tolerates a flaky LLM call correctly — not that a
real model fixes real bugs at some success rate. That number only comes from
running `evolve_cli.py` against real procedures over time and counting
outcomes; this harness doesn't track that yet. Re-run this (`tests/test_benchmark.py`
runs it in CI) after any change to `harness/evolve.py`, the same way you'd
re-run a MockAgent against planted bugs before trusting a changed evaluator.

## Stage 2 — dev → uat: automatic promotion (harness/promote_cli.py)

`.github/workflows/promote-dev-to-uat.yml` fires on every push to `dev`. It
deploys the already-converged procedure to UAT (via `harness/promote.py` —
no LLM call here, just guardrail-check → deploy → validate), and if that
passes, merges `dev` into `uat` and pushes. No human approves this step; the
guardrail check and the UAT validation are what stand in for review.

Run it by hand the same way the workflow does:

```bash
python -m harness.promote_cli \
    --proc procs/sp_refresh_fact_sales.example.sql \
    --exec-statement "EXEC dbo.sp_refresh_fact_sales" \
    --suite tests/golden_fact_sales.example.yaml \
    --allowed-schema dbo \
    --conn-env SYNAPSE_UAT_CONN_STR
```

Every stage actually loops over `procs/manifest.yaml` (`harness/manifest.py`),
not just the one worked example — add a new procedure by adding an entry
there:

```yaml
procedures:
  - proc: procs/sp_refresh_fact_sales.example.sql
    suite: tests/golden_fact_sales.example.yaml
    exec_statement: "EXEC dbo.sp_refresh_fact_sales"
    allowed_schema: dbo
```

`python -m harness.manifest procs/manifest.yaml --tsv` prints one
tab-separated line per entry; every workflow step that deploys/validates
reads the manifest this way and calls the usual CLI once per entry, each
getting its own `reports/<proc-stem>/` output directory so one procedure's
report can't silently overwrite another's. Nothing in `harness/promote.py`,
`harness/evolve.py`, or their CLIs changed for this — the looping is pure
orchestration at the workflow level around the same single-procedure
interface each already had.

### After the merge: re-validate what actually landed in uat

Merging doesn't end the workflow. A third job, `validate-after-merge`
(`needs: promote`), checks out `uat` itself — not the `dev` candidate
`promote` already checked a moment ago — and re-runs the same
deploy-and-validate against UAT. This exists because the merge step is the
one place a surprise could sneak in that the pre-merge check couldn't see:
an oddly-resolved conflict, or a UAT database that changed between the two
checks. Only a clean pass here means `uat` is actually ready — that's the
signal to open the Stage 3 pull request, not just a successful `promote`.

### When UAT rejects the candidate: automatic feedback to dev

Two different steps can fail — `promote` (the candidate, before it ever
reaches `uat`) or `validate-after-merge` (the merged state, after). Either
one calls the same reusable workflow, `.github/workflows/auto-fix-dev.yml`,
instead of just leaving things broken:

1. Checks out `dev` and reads the last commit's message for a
   `[auto-fix round N/3]` tag, to work out which round this is — there's no
   shared state across runs, so the commit message is the only memory. Both
   failure points share this one counter: it's one 3-round budget total,
   not three rounds each.
2. Past round 3, it fails loudly (`::error::`) and stops. This is meant to
   be looked at by a person, not retried again.
3. Otherwise it calls `harness/evolve_cli.py --provider deepseek` against
   `SYNAPSE_DEV_CONN_STR` (no `--push`) — the same fix loop described in
   Stage 1 below, just run unattended in CI.
4. If `evolve_cli.py` converges, the job commits the updated proc file with
   the next round's tag and pushes to `dev` — which re-triggers
   `promote-dev-to-uat.yml` from the top, naturally retrying the whole dev
   → uat cycle (including a fresh `validate-after-merge` once it re-merges).
   The commit message carries the LLM's own rationale for the fix, not
   just the round tag — pulled from `reports/evolve_summary.json` — so it
   travels with `git log` into whatever `uat → main` PR eventually picks
   it up, instead of living only in a CI artifact that expires. If
   `evolve_cli.py` doesn't converge (exhausts its own internal
   attempts), that step fails and the job stops there with no commit.
   `uat` is never reverted when this happens — the next successful merge
   simply supersedes it, same as any other `TRUNCATE`/`INSERT` refresh.

This needs three GitHub Actions secrets on the repo: `SYNAPSE_DEV_CONN_STR`,
`DEEPSEEK_API_KEY`, and `GH_PAT`. Secret *values* have to be set by a repo
admin in GitHub's own Settings → Secrets UI — nothing here can set a
secret's value from outside GitHub.

`GH_PAT` needs its own explanation: it's a Personal Access Token (classic,
`repo` scope, or fine-grained with "Contents: Read and write" on this
repo), used only for the final `git push` back to `dev` in
`auto-fix-dev.yml`. GitHub Actions deliberately won't let a push
authenticated with the default `GITHUB_TOKEN` trigger another workflow run
— it's an anti-recursion guard — so without a real PAT there, the push to
`dev` would succeed but silently never re-trigger
`promote-dev-to-uat.yml`, and the retry loop would just stop with no error
and no second attempt.

## Stage 3 — uat → prd: the one manual gate

Promotion to `main` (prd) is a normal pull request from `uat`, opened by a
person. `.github/workflows/uat-to-prd-gate.yml` re-validates against UAT as
a required check on that PR, but merging is a human decision — this
workflow never merges anything. This is where your test analyst's sign-off
actually happens.

That same workflow also scans the PR's commits for an `[auto-fix round`
tag and posts a comment flagging any commit that was LLM-generated rather
than human-written, quoting its full rationale — a reviewer shouldn't have
to dig through `git log` to find out whether a given diff came from a
person or from `evolve_cli.py`. It upserts one comment (keyed by an HTML
marker) instead of spamming a new one on every push to the PR branch.

## Keeping the pipeline's own secrets honest

`.github/workflows/secrets-smoke-test.yml` confirms the four secrets this
pipeline depends on — `SYNAPSE_DEV_CONN_STR`, `SYNAPSE_UAT_CONN_STR`,
`DEEPSEEK_API_KEY`, `GH_PAT` — actually authenticate, not just that
they're set. Each check is read-only (a trivial `SELECT 1`, a `GET`
request); nothing deploys, pushes, or spends a real LLM call. Run it by
hand (Actions tab → this workflow → "Run workflow") right after touching
any of these in Settings → Secrets — a stale password or an empty token
should show up here in under a minute, not mid-pipeline hours later. It
also runs daily on its own, in case something goes stale on its own (e.g.
a certificate or token expiring) without anyone touching Settings at all.

Run it locally too, against your own exported env vars, before ever
pushing a secret to GitHub:

```bash
SYNAPSE_DEV_CONN_STR="..." SYNAPSE_UAT_CONN_STR="..." DEEPSEEK_API_KEY="..." GH_PAT="..." \
    python -m harness.secrets_check
```

## Cost and model-drift observability

Every real `AnthropicLLMClient`/`DeepSeekLLMClient` call now returns its
token usage alongside the fix (`harness/llm_client.py`'s `FixSuggestion.usage`),
which `evolve()` carries through to each `Iteration` and
`write_evolve_report` (`harness/report.py`) totals into
`evolve_summary.json`: `total_tokens`, `estimated_cost_usd` (from a
`PRICING_PER_1K_TOKENS` table — a point-in-time estimate, not an invoice;
an unknown model id contributes `$0` rather than breaking the run), and
`model` (the id actually used, for correlating a fix-rate change with a
provider quietly changing what a generic alias like `deepseek-chat` points
to).

`auto-fix-dev.yml` appends one line per attempt — converged or not, since
a failure is exactly the data point that matters for a success-rate trend
— to `reports/metrics_log.jsonl` (`harness/metrics_log.py`), committed to
`dev` alongside (or instead of, when nothing converged) the fix itself.
It's deliberately a plain git-tracked file, not a dashboard or an
artifact that expires: durable, diffable, and already in a place this
repo commits to anyway.

Read the trend on demand:

```bash
python -m harness.metrics_cli --log reports/metrics_log.jsonl
# success rate, total tokens/cost, and a per-model breakdown
```

There's no scheduled workflow or live dashboard wired up for this yet —
with one procedure logging to this file today, that would be
infrastructure for a problem that doesn't exist. The log format is what a
future dashboard would read from, if/when that's actually warranted.

## Data-governance gate for DeepSeek

DeepSeek is a China-based provider; sending a real procedure's schema and
logic to it is an offshore data transfer that needs sign-off from
whoever owns data governance before it's used on anything beyond this
repo's synthetic demo data. That requirement used to live only in a
comment. It's now a real, enforced gate:
`infra/deepseek_governance_approval.yaml` ships with `approved: false`,
and `auto-fix-dev.yml` runs `python -m harness.governance_check`
(`harness/governance_check.py`) right before it ever calls DeepSeek — a
missing file, `approved: false`, or an `approved: true` with no
`approved_by`/`approved_at` filled in all fail the job loudly instead of
silently sending data.

**This gate being technically enforced does not mean the compliance work
is done.** Getting that sign-off and editing the file (`approved: true`,
who approved it, when) is still entirely a decision for your organization
to make — not something this harness can do on its own. The point is
narrower: that decision can no longer be silently skipped just because
nobody got around to it.

## Adding a check

1. Copy an entry in `tests/uat_suite.example.yaml` (or write a new suite
   file) and point it at your table/query.
2. If no existing check type fits, add a module to `harness/checks/`
   exposing `run(connector, params) -> (status, message, details)`, register
   it in `harness/runner.py`'s `CHECK_MODULES`, and add a clean-pass +
   planted-defect test pair in `tests/test_checks.py`.

## Not yet wired up (by design, until needed)

- **Actual deployment to PRD**: merging the `uat` → `main` PR updates the
  repo, not PRD itself — hooking that merge up to your real PRD deployment
  process (however you currently push to PRD) is outside this harness's
  scope.
- **Per-environment connection management**: `connection_env` in the suite
  file names the env var to read; how those secrets get into the shell
  (Azure Key Vault, GitHub Actions secrets, Azure DevOps variable groups,
  etc.) is outside this harness's scope.
- **Branch protection on `main`**: the one human-reviewed gate
  (`uat-to-prd-gate.yml`) is only as real as GitHub's branch protection
  makes it — without a rule requiring a PR and a passing `validate` check
  on `main`, anyone with write access can bypass it with a direct push.
  This harness can't set that for you (no available tool exposes GitHub's
  branch-protection API); add it yourself under **Settings → Branches**
  on `main` — require a pull request, require the `validate` status
  check, and *don't* require an approval count greater than 0 unless
  there's more than one collaborator, or you'll lock yourself out of
  merging your own PRs.
- **Branch protection on `uat`**: the promotion workflow pushes directly to
  `uat`. If you add a required-review rule there later, exempt the
  workflow's token or switch that step to a PR + auto-merge.
